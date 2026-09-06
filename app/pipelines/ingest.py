"""
app/pipelines/ingest.py — Batch loader for real historical RMA/chargeback data.

Run:
    python -m app.pipelines.ingest --file merchant_returns.csv --merchant-id M001

Expected CSV columns (rename your merchant's export to match, or edit
COLUMN_MAP below): the same FEATURE_COLS used everywhere else, plus
order_id, merchant_id, and outcome_label (0/1) if known.

This keeps a single source of truth for feature definitions across
training, retraining, and live inference (imported from app.services.ml_core).
"""
import argparse
import logging
import pandas as pd
from datetime import datetime

from app.config import settings
from app.database import SessionLocal, init_db
from app.models.db_models import ReturnCase, Merchant
from app.services.ml_core import FEATURE_COLS

logging.basicConfig(level=settings.LOG_LEVEL, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("ingest")

REQUIRED_COLS = ["order_id"] + FEATURE_COLS


def validate_columns(df: pd.DataFrame):
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"Input file is missing required columns: {missing}")


def main(file_path: str, merchant_id: str):
    init_db()
    db = SessionLocal()

    if not db.query(Merchant).filter_by(merchant_id=merchant_id).first():
        logger.info(f"Creating merchant record for {merchant_id}")
        db.add(Merchant(merchant_id=merchant_id, name=merchant_id))
        db.commit()

    df = pd.read_csv(file_path)
    validate_columns(df)
    logger.info(f"Loaded {len(df)} rows from {file_path}")

    inserted, skipped = 0, 0
    for _, row in df.iterrows():
        existing = db.query(ReturnCase).filter_by(order_id=row["order_id"]).first()
        if existing:
            skipped += 1
            continue
        outcome = int(row["outcome_label"]) if "outcome_label" in df.columns and pd.notna(row.get("outcome_label")) else None
        db.add(ReturnCase(
            order_id=row["order_id"], merchant_id=merchant_id, status="pending",
            order_value=float(row["order_value"]), category=row.get("category"),
            features_json=row[FEATURE_COLS].to_json(),
            created_at=datetime.utcnow(),
            outcome_label=outcome,
            outcome_recorded_at=datetime.utcnow() if outcome is not None else None,
        ))
        inserted += 1
        if inserted % 500 == 0:
            db.commit()
    db.commit()
    db.close()
    logger.info(f"Ingest complete: {inserted} inserted, {skipped} skipped (already existed).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, help="Path to CSV export from merchant OMS/ERP")
    parser.add_argument("--merchant-id", required=True)
    args = parser.parse_args()
    main(args.file, args.merchant_id)
