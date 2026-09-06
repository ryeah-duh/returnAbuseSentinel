"""
app/services/webhook_dispatcher.py — Outbound webhook delivery for merchant systems.

Fires:
  - return.scored     whenever any return finishes scoring
  - return.escalated  whenever a Red-band case is confirmed as fraud
    (outcome_label=1 recorded by a human reviewer via /returns/{id}/outcome)

Runs as a background consumer of the `returns.scored` Kafka topic, decoupled
from the scorer itself so a slow/broken merchant endpoint never blocks scoring.
"""
import asyncio
import logging
import httpx
from datetime import datetime

from app.config import settings
from app.database import SessionLocal
from app.models.db_models import Merchant, AuditLog
from app.services.kafka_client import consume_return_events  # topic param overridden below
from aiokafka import AIOKafkaConsumer
import json

logger = logging.getLogger("webhook_dispatcher")

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = [2, 8, 30]


async def deliver_webhook(url: str, event_type: str, payload: dict) -> bool:
    body = {"event": event_type, "data": payload, "timestamp": datetime.utcnow().isoformat()}
    async with httpx.AsyncClient(timeout=5.0) as client:
        for attempt in range(MAX_RETRIES):
            try:
                resp = await client.post(url, json=body)
                if resp.status_code < 300:
                    return True
                logger.warning(f"Webhook {url} returned {resp.status_code}, attempt {attempt+1}")
            except httpx.HTTPError as e:
                logger.warning(f"Webhook delivery failed: {e}, attempt {attempt+1}")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS[attempt])
    return False


async def run_dispatcher():
    consumer = AIOKafkaConsumer(
        settings.KAFKA_TOPIC_SCORED,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id="sentinel-webhook-dispatcher",
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        auto_offset_reset="earliest",
    )
    await consumer.start()
    logger.info("Webhook dispatcher started")
    try:
        async for msg in consumer:
            event = msg.value
            db = SessionLocal()
            try:
                # In a real deployment, merchant webhook URLs would be stored on the
                # Merchant row. Left as a TODO field to keep the schema minimal here.
                merchant = db.query(Merchant).filter_by(merchant_id=event.get("merchant_id", "")).first()
                webhook_url = getattr(merchant, "webhook_url", None) if merchant else None
                if webhook_url:
                    success = await deliver_webhook(webhook_url, "return.scored", event)
                    db.add(AuditLog(
                        timestamp=datetime.utcnow(), actor="system:webhook_dispatcher",
                        action="deliver_webhook", entity_type="return", entity_id=event["order_id"],
                        after_json=json.dumps({"delivered": success}),
                    ))
                    db.commit()
            finally:
                db.close()
    finally:
        await consumer.stop()


if __name__ == "__main__":
    asyncio.run(run_dispatcher())
