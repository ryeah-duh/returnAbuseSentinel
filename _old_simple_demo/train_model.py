"""
Return-Abuse Sentinel — Model Training Script
================================================
Trains a two-class risk model (legit vs. abusive/fraudulent return) on
historical RMA data, then calibrates a 3-band decision policy
(Green / Yellow / Red) using an explicit false-positive/false-negative
cost model instead of a single arbitrary threshold.

DEFENSE-ONLY: This script only produces a *score* + *routing recommendation*.
It never auto-refunds, auto-denies, auto-messages a customer, or takes any
irreversible action. All Red-band cases go to a human review queue.

Run:
    python train_model.py
Outputs:
    return_abuse_model.pkl   -> trained sklearn pipeline
    metrics_report.json      -> honest precision/recall + cost report
"""

import json
import numpy as np
import pandas as pd
import joblib

from sklearn.model_selection import train_test_split
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.metrics import roc_auc_score, precision_score, recall_score
from sklearn.inspection import permutation_importance

RANDOM_STATE = 42
np.random.seed(RANDOM_STATE)

FEATURE_COLS = [
    'account_age_days', 'past_orders', 'return_rate_hist', 'refund_to_keep_count',
    'bracketing_score', 'claim_text_susp', 'image_ai_artifact_score', 'weight_mismatch_kg',
    'shared_identifier_flag', 'carrier_scan_gap', 'days_to_claim', 'order_value', 'category'
]
TARGET_COL = 'is_abuse'

# ---------------------------------------------------------------------------
# 1. Synthetic dataset generator
# ---------------------------------------------------------------------------
# In production this is replaced by real historical RMA + chargeback-linked
# return data pulled from the merchant's order management system. The
# generator below intentionally overlaps the two classes and injects 6%
# label noise (real-world label noise: appealed chargebacks, reversed
# fraud flags, mislabeled inspections) so the resulting model faces a
# realistic, non-trivial classification problem instead of a toy dataset
# that trivially separates.

def generate_dataset(n=15000, seed=RANDOM_STATE):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        is_abuse = rng.random() < 0.12
        account_age_days = max(1, int(rng.exponential(400)))
        past_orders = max(1, int(rng.poisson(8)))

        if is_abuse:
            return_rate_hist = np.clip(rng.beta(3, 3), 0, 1)
            refund_to_keep_count = rng.poisson(0.9)
            bracketing_score = rng.beta(2.5, 2.5)
            claim_text_susp = rng.beta(2.5, 3)
            image_ai_artifact_score = rng.beta(2.5, 3)
            weight_mismatch_kg = rng.exponential(0.15)
            shared_identifier_flag = rng.random() < 0.18
            carrier_scan_gap = rng.random() < 0.15
            days_to_claim = rng.exponential(3.5)
        else:
            return_rate_hist = np.clip(rng.beta(2.2, 5), 0, 1)
            refund_to_keep_count = rng.poisson(0.35)
            bracketing_score = rng.beta(2, 4.5)
            claim_text_susp = rng.beta(2, 5.5)
            image_ai_artifact_score = rng.beta(2, 6)
            weight_mismatch_kg = rng.exponential(0.07)
            shared_identifier_flag = rng.random() < 0.05
            carrier_scan_gap = rng.random() < 0.06
            days_to_claim = rng.exponential(5.5)

        observed_label = is_abuse
        if rng.random() < 0.06:
            observed_label = not is_abuse

        order_value = round(float(rng.lognormal(7.2, 0.8)), 2)
        category = rng.choice(['apparel', 'electronics', 'footwear', 'home', 'beauty'],
                               p=[0.35, 0.2, 0.15, 0.2, 0.1])

        rows.append(dict(
            order_id=f"ORD{100000+i}",
            account_age_days=account_age_days,
            past_orders=past_orders,
            return_rate_hist=round(return_rate_hist, 3),
            refund_to_keep_count=int(refund_to_keep_count),
            bracketing_score=round(bracketing_score, 3),
            claim_text_susp=round(claim_text_susp, 3),
            image_ai_artifact_score=round(image_ai_artifact_score, 3),
            weight_mismatch_kg=round(weight_mismatch_kg, 3),
            shared_identifier_flag=int(shared_identifier_flag),
            carrier_scan_gap=int(carrier_scan_gap),
            days_to_claim=round(days_to_claim, 2),
            order_value=order_value,
            category=category,
            is_abuse=int(observed_label)
        ))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 2. Cost model (INR, illustrative — replace with real merchant P&L numbers)
# ---------------------------------------------------------------------------
COST_MANUAL_REVIEW = 150     # cost of full human fraud-review of one Red case
COST_INSPECTION = 40         # cost of warehouse/photo inspection for one Yellow case
COST_FRIVOLOUS_FRICTION = 5  # small CSAT cost when a genuine customer sits in Yellow
FRACTION_LOST_ON_MISS = 0.6  # fraction of order value lost when abuse slips through as approved


def band_of(prob, low_t, high_t):
    return np.select([prob < low_t, prob < high_t], ['Green', 'Yellow'], default='Red')


def expected_loss_for_bands(d, low_t, high_t):
    """d must have columns: prob, y_true, order_value"""
    band = band_of(d['prob'].values, low_t, high_t)
    d = d.assign(band=band)

    green_fn = d[(d.band == 'Green') & (d.y_true == 1)]
    green_loss = (green_fn.order_value * FRACTION_LOST_ON_MISS).sum()

    yellow = d[d.band == 'Yellow']
    yellow_abuse = yellow[yellow.y_true == 1]
    yellow_genuine = yellow[yellow.y_true == 0]
    yellow_inspection_cost = len(yellow) * COST_INSPECTION
    # assume warehouse inspection catches 80% of abuse routed to Yellow
    yellow_missed_loss = (yellow_abuse.order_value * FRACTION_LOST_ON_MISS * 0.20).sum()
    yellow_friction_cost = len(yellow_genuine) * COST_FRIVOLOUS_FRICTION

    red = d[d.band == 'Red']
    red_review_cost = len(red) * COST_MANUAL_REVIEW
    # assume human review catches 95% of abuse routed to Red
    red_missed_loss = (red[red.y_true == 1].order_value * FRACTION_LOST_ON_MISS * 0.05).sum()

    total = (green_loss + yellow_inspection_cost + yellow_missed_loss +
             yellow_friction_cost + red_review_cost + red_missed_loss)
    return total, d


def calibrate_bands(val_df, min_green_share=0.55):
    """Grid-search low/high thresholds to minimize expected business loss,
    subject to a minimum automation-rate constraint (Green band must cover
    at least `min_green_share` of volume, otherwise the system creates too
    much manual-review load to be operationally useful)."""
    n_total = len(val_df)
    best = None
    for low_t in np.linspace(0.02, 0.5, 25):
        for high_t in np.linspace(low_t + 0.03, 0.9, 25):
            total, d = expected_loss_for_bands(val_df, low_t, high_t)
            green_share = (d.band == 'Green').mean()
            if green_share < min_green_share:
                continue
            if best is None or total < best[0]:
                best = (total, low_t, high_t, green_share)
    return best  # (total_loss, low_t, high_t, green_share)


# ---------------------------------------------------------------------------
# 3. Train + evaluate + calibrate + save
# ---------------------------------------------------------------------------
def main():
    df = generate_dataset()
    df.to_csv('return_abuse_dataset.csv', index=False)

    X = df[FEATURE_COLS]
    y = df[TARGET_COL]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, stratify=y, random_state=RANDOM_STATE)

    preprocess = ColumnTransformer([
        ('cat', OneHotEncoder(handle_unknown='ignore'), ['category'])
    ], remainder='passthrough')

    model = Pipeline([
        ('prep', preprocess),
        ('clf', GradientBoostingClassifier(
            n_estimators=200, max_depth=3, learning_rate=0.08,
            random_state=RANDOM_STATE))
    ])
    model.fit(X_train, y_train)

    probs_test = model.predict_proba(X_test)[:, 1]
    auc = roc_auc_score(y_test, probs_test)

    val_df = X_test.copy()
    val_df['y_true'] = y_test.values
    val_df['prob'] = probs_test

    total_loss, low_t, high_t, green_share = calibrate_bands(val_df)
    _, banded = expected_loss_for_bands(val_df, low_t, high_t)

    pred_red = (banded.band == 'Red').astype(int)
    pred_any_flag = banded.band.isin(['Yellow', 'Red']).astype(int)

    naive_loss = (val_df[val_df.y_true == 1].order_value * FRACTION_LOST_ON_MISS).sum()
    loss_prevented = naive_loss - total_loss

    perm = permutation_importance(model, X_test, y_test, n_repeats=8,
                                   random_state=RANDOM_STATE, scoring='average_precision')
    importances = pd.Series(perm.importances_mean, index=X_test.columns).sort_values(ascending=False)

    summary = banded.groupby('band').agg(
        count=('y_true', 'size'),
        abuse_rate=('y_true', 'mean'),
        avg_order_value=('order_value', 'mean')
    ).reindex(['Green', 'Yellow', 'Red']).reset_index()

    report = {
        "model": "GradientBoostingClassifier (sklearn)",
        "test_set_size": int(len(y_test)),
        "test_auc": round(float(auc), 4),
        "thresholds": {"green_yellow": round(float(low_t), 3),
                       "yellow_red": round(float(high_t), 3)},
        "band_distribution": summary.to_dict(orient='records'),
        "red_only_hard_flag": {
            "precision": round(float(precision_score(banded.y_true, pred_red)), 3),
            "recall": round(float(recall_score(banded.y_true, pred_red)), 3)
        },
        "yellow_plus_red_any_flag": {
            "precision": round(float(precision_score(banded.y_true, pred_any_flag)), 3),
            "recall": round(float(recall_score(banded.y_true, pred_any_flag)), 3)
        },
        "cost_model_inr": {
            "cost_manual_review_red": COST_MANUAL_REVIEW,
            "cost_inspection_yellow": COST_INSPECTION,
            "cost_friction_yellow_genuine": COST_FRIVOLOUS_FRICTION,
            "fraction_of_order_value_lost_on_miss": FRACTION_LOST_ON_MISS
        },
        "business_impact": {
            "naive_approve_all_loss_inr": round(float(naive_loss), 0),
            "sentinel_system_loss_inr": round(float(total_loss), 0),
            "loss_prevented_inr": round(float(loss_prevented), 0),
            "loss_reduction_pct": round(float(loss_prevented / naive_loss * 100), 1),
            "automation_rate_green_pct": round(float(green_share * 100), 1)
        },
        "top_feature_importances": importances.round(4).to_dict()
    }

    joblib.dump({"model": model, "low_t": low_t, "high_t": high_t}, 'return_abuse_model.pkl')
    with open('metrics_report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print(json.dumps(report, indent=2))
    print("\nSaved: return_abuse_model.pkl, metrics_report.json, return_abuse_dataset.csv")


if __name__ == '__main__':
    main()
