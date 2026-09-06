"""
app/pipelines/retrain.py — Scheduled retraining with champion-challenger promotion.

Run manually or via cron/Airflow:
    python -m app.pipelines.retrain

Pulls returns with a known outcome_label from Postgres, retrains a challenger
model, evaluates it against the current champion on the same held-out split,
and only promotes it if it's genuinely better (AUC + Brier both improve, or
AUC improves without Brier regressing beyond a small tolerance).
"""
import json
import logging
from datetime import datetime
import pandas as pd
from sklearn.metrics import roc_auc_score, brier_score_loss

from app.config import settings
from app.database import SessionLocal
from app.models.db_models import ReturnCase, ModelRegistry, Merchant
from app.services.ml_core import ReturnAbuseModel, FEATURE_COLS
from app.pipelines.threshold_optimizer import optimize_thresholds, CostProfile

logging.basicConfig(level=settings.LOG_LEVEL, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("retrain")

MIN_LABELED_ROWS = 500
BRIER_REGRESSION_TOLERANCE = 0.005


def load_labeled_data(db) -> pd.DataFrame:
    rows = db.query(ReturnCase).filter(ReturnCase.outcome_label.isnot(None)).all()
    records = []
    for r in rows:
        if not r.features_json:
            continue
        features = json.loads(r.features_json)
        record = {col: features.get(col) for col in FEATURE_COLS}
        record["is_abuse"] = r.outcome_label
        records.append(record)
    return pd.DataFrame(records)


def main():
    db = SessionLocal()
    df = load_labeled_data(db)

    if len(df) < MIN_LABELED_ROWS:
        logger.warning(
            f"Only {len(df)} labeled rows available (need {MIN_LABELED_ROWS}+). "
            "Skipping retrain — label pipeline needs more confirmed outcomes first."
        )
        db.close()
        return

    logger.info(f"Retraining challenger on {len(df)} labeled returns...")
    challenger = ReturnAbuseModel()
    X_test, y_test = challenger.train(df)
    probs_challenger = challenger.calibrated.predict_proba(X_test)[:, 1]
    auc_challenger = roc_auc_score(y_test, probs_challenger)
    brier_challenger = brier_score_loss(y_test, probs_challenger)

    champion_row = db.query(ModelRegistry).filter_by(is_champion=1).first()
    promote = True
    if champion_row:
        logger.info(
            f"Current champion {champion_row.version}: AUC={champion_row.test_auc:.4f} "
            f"Brier={champion_row.test_brier:.4f}"
        )
        logger.info(f"Challenger: AUC={auc_challenger:.4f} Brier={brier_challenger:.4f}")
        auc_improved = auc_challenger > champion_row.test_auc
        brier_ok = brier_challenger <= champion_row.test_brier + BRIER_REGRESSION_TOLERANCE
        promote = auc_improved and brier_ok
        if not promote:
            logger.info("Challenger did NOT beat champion. Keeping current champion.")

    if promote:
        version = "v" + datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        challenger.save(settings.MODEL_ARTIFACT_PATH, version)
        db.add(ModelRegistry(
            version=version, created_at=datetime.utcnow(),
            test_auc=float(auc_challenger), test_brier=float(brier_challenger),
            is_champion=1, metadata_json=json.dumps({"algo": "LightGBM+isotonic", "retrained": True}),
        ))
        db.query(ModelRegistry).filter(ModelRegistry.version != version).update({"is_champion": 0})
        db.commit()
        logger.info(f"Promoted new champion: {version}")

        val_df = X_test.copy()
        val_df["y_true"] = y_test.values
        val_df["prob"] = probs_challenger
        for merchant in db.query(Merchant).all():
            cost = CostProfile(
                cost_manual_review=merchant.cost_manual_review, cost_inspection=merchant.cost_inspection,
                cost_friction=merchant.cost_friction, fraction_lost_on_miss=merchant.fraction_lost_on_miss,
            )
            result = optimize_thresholds(val_df, cost, min_green_share=settings.MODEL_MIN_GREEN_SHARE)
            merchant.green_threshold = result.green_threshold
            merchant.red_threshold = result.red_threshold
        db.commit()

    db.close()


if __name__ == "__main__":
    main()
