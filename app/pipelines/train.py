"""
app/pipelines/train.py — First-time model training entrypoint.

Run:
    python -m app.pipelines.train

Generates a synthetic dataset (swap `generate_dataset` for a real historical
RMA loader in production — see pipelines/ingest.py), trains the calibrated
LightGBM model, registers it as champion in model_registry, computes
per-merchant optimal thresholds, and writes everything the API needs to boot.
"""
import json
import logging
from datetime import datetime
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score, brier_score_loss, precision_score, recall_score

from app.config import settings
from app.database import SessionLocal, init_db
from app.models.db_models import Merchant, ModelRegistry
from app.services.ml_core import ReturnAbuseModel, FEATURE_COLS
from app.pipelines.threshold_optimizer import optimize_thresholds, CostProfile

logging.basicConfig(level=settings.LOG_LEVEL, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("train")


def generate_dataset(n=15000, seed=42) -> pd.DataFrame:
    """Synthetic RMA-style dataset with realistic class overlap + 6% label noise.
    REPLACE with pipelines/ingest.py output once real merchant data is available."""
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
        category = rng.choice(["apparel", "electronics", "footwear", "home", "beauty"],
                               p=[0.35, 0.2, 0.15, 0.2, 0.1])
        rows.append(dict(
            order_id=f"ORD{100000+i}", account_age_days=account_age_days, past_orders=past_orders,
            return_rate_hist=round(return_rate_hist, 3), refund_to_keep_count=int(refund_to_keep_count),
            bracketing_score=round(bracketing_score, 3), claim_text_susp=round(claim_text_susp, 3),
            image_ai_artifact_score=round(image_ai_artifact_score, 3),
            weight_mismatch_kg=round(weight_mismatch_kg, 3),
            shared_identifier_flag=int(shared_identifier_flag), carrier_scan_gap=int(carrier_scan_gap),
            days_to_claim=round(days_to_claim, 2), order_value=order_value, category=category,
            is_abuse=int(observed_label),
        ))
    return pd.DataFrame(rows)


def main():
    init_db()
    db = SessionLocal()

    if db.query(Merchant).count() == 0:
        logger.info("Seeding demo merchant M001")
        db.add(Merchant(merchant_id="M001", name="Demo Fashion Co"))
        db.commit()

    logger.info("Generating training dataset...")
    df = generate_dataset()
    df.to_csv("return_abuse_dataset.csv", index=False)

    logger.info("Training calibrated LightGBM model...")
    model = ReturnAbuseModel()
    X_test, y_test = model.train(df)

    probs = model.calibrated.predict_proba(X_test)[:, 1]
    auc = roc_auc_score(y_test, probs)
    brier = brier_score_loss(y_test, probs)
    logger.info(f"Test AUC={auc:.4f}  Brier={brier:.4f}")

    version = "v" + datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    model.save(settings.MODEL_ARTIFACT_PATH, version)
    model.version = version

    db.add(ModelRegistry(
        version=version, created_at=datetime.utcnow(), test_auc=float(auc), test_brier=float(brier),
        is_champion=1, metadata_json=json.dumps({"algo": "LightGBM+isotonic"}),
    ))
    # demote any previous champion
    db.query(ModelRegistry).filter(ModelRegistry.version != version).update({"is_champion": 0})
    db.commit()

    val_df = X_test.copy()
    val_df["y_true"] = y_test.values
    val_df["prob"] = probs

    for merchant in db.query(Merchant).all():
        cost = CostProfile(
            cost_manual_review=merchant.cost_manual_review, cost_inspection=merchant.cost_inspection,
            cost_friction=merchant.cost_friction, fraction_lost_on_miss=merchant.fraction_lost_on_miss,
        )
        result = optimize_thresholds(val_df, cost, min_green_share=settings.MODEL_MIN_GREEN_SHARE)
        merchant.green_threshold = result.green_threshold
        merchant.red_threshold = result.red_threshold
        logger.info(
            f"Merchant {merchant.merchant_id}: green_t={result.green_threshold:.3f} "
            f"red_t={result.red_threshold:.3f} green_share={result.green_share:.1%} "
            f"expected_loss=Rs{result.total_expected_loss:,.0f}"
        )
    db.commit()
    db.close()
    logger.info(f"Training complete. Model version {version} registered as champion.")


if __name__ == "__main__":
    main()
