"""
app/services/scorer_worker.py — Standalone async scoring microservice.

Run as a SEPARATE process/container from the API (see Dockerfile.scorer +
docker-compose.yml). Consumes return events from Kafka, scores them using
the shared ML model + Redis feature cache, writes results to Postgres, logs
to the immutable audit table, and republishes a `return.scored` event for
downstream consumers (e.g. webhook dispatcher).

This is what decouples scoring latency from API response time: the API
publishes-and-forgets for low-risk-routed cases, and this worker does the
(relatively) expensive model + SHAP call on its own schedule, scaled
independently (run N replicas of this container under load).
"""
import asyncio
import json
import logging
from datetime import datetime

from app.config import settings
from app.database import SessionLocal
from app.models.db_models import ReturnCase, AuditLog, Merchant
from app.services.kafka_client import consume_return_events, publish_scored_event
from app.services.feature_store import get_velocity_features, record_return_event
from app.services.ml_core import ReturnAbuseModel

logging.basicConfig(level=settings.LOG_LEVEL, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("scorer_worker")

_model: ReturnAbuseModel | None = None


def get_model() -> ReturnAbuseModel:
    global _model
    if _model is None:
        logger.info(f"Loading model artifact from {settings.MODEL_ARTIFACT_PATH}")
        _model = ReturnAbuseModel.load(settings.MODEL_ARTIFACT_PATH)
    return _model


async def process_case(case: dict, model: ReturnAbuseModel):
    db = SessionLocal()
    try:
        merchant = db.query(Merchant).filter_by(merchant_id=case["merchant_id"]).first()
        green_t = merchant.green_threshold if merchant else 0.08
        red_t = merchant.red_threshold if merchant else 0.47

        # enrich with real-time velocity features before scoring (train/serve parity)
        velocity = get_velocity_features(case.get("account_id", case["order_id"]))
        record_return_event(case.get("account_id", case["order_id"]))
        case = {**case, **velocity}

        evidence = model.score(case, green_t, red_t)

        row = db.query(ReturnCase).filter_by(order_id=case["order_id"]).first()
        if row is None:
            row = ReturnCase(order_id=case["order_id"], merchant_id=case["merchant_id"],
                              order_value=case["order_value"], category=case["category"],
                              features_json=json.dumps(case), created_at=datetime.utcnow())
            db.add(row)

        row.status = "scored"
        row.risk_score = evidence.risk_score / 100.0
        row.band = evidence.band
        row.evidence_json = json.dumps(evidence.to_dict())
        row.model_version = model.version
        row.scored_at = datetime.utcnow()
        db.commit()

        db.add(AuditLog(
            timestamp=datetime.utcnow(), actor="system:scorer", action="score_return",
            entity_type="return", entity_id=case["order_id"],
            before_json=None, after_json=json.dumps({"score": evidence.risk_score, "band": evidence.band}),
        ))
        db.commit()

        await publish_scored_event({"order_id": case["order_id"], "band": evidence.band,
                                     "risk_score": evidence.risk_score})
        logger.info(f"Scored {case['order_id']}: band={evidence.band} score={evidence.risk_score}")

    except Exception:
        logger.exception(f"Failed to score {case.get('order_id')}")
        row = db.query(ReturnCase).filter_by(order_id=case["order_id"]).first()
        if row:
            row.status = "error"
            db.commit()
    finally:
        db.close()


async def run_worker():
    model = get_model()
    logger.info("Scorer worker started, consuming from Kafka topic: %s", settings.KAFKA_TOPIC_RETURNS)
    async for case in consume_return_events():
        await process_case(case, model)


if __name__ == "__main__":
    asyncio.run(run_worker())
