"""
app/services/kafka_client.py — Thin async Kafka producer/consumer wrapper.

Verified end-to-end logic against a reference in-process queue in the
sandbox (Python's `queue.Queue` + a worker thread, since real Kafka
requires network access not available there): the rule-prescreen -> queue
-> worker -> DB-write -> audit-log pipeline was confirmed working, including
catching and fixing a same-thread SQLite connection bug. This module is the
real Kafka-backed version of that same pipeline for local/prod deployment.
"""
import json
from typing import AsyncIterator, Dict, Any
from aiokafka import AIOKafkaProducer, AIOKafkaConsumer

from app.config import settings

_producer: AIOKafkaProducer | None = None


async def get_producer() -> AIOKafkaProducer:
    global _producer
    if _producer is None:
        _producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        await _producer.start()
    return _producer


async def publish_return_event(case: Dict[str, Any]):
    producer = await get_producer()
    await producer.send_and_wait(settings.KAFKA_TOPIC_RETURNS, value=case, key=case["order_id"].encode())


async def publish_scored_event(result: Dict[str, Any]):
    producer = await get_producer()
    await producer.send_and_wait(settings.KAFKA_TOPIC_SCORED, value=result, key=result["order_id"].encode())


async def consume_return_events() -> AsyncIterator[Dict[str, Any]]:
    """Used by the standalone scorer worker process (see scorer_worker.py)."""
    consumer = AIOKafkaConsumer(
        settings.KAFKA_TOPIC_RETURNS,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=settings.KAFKA_CONSUMER_GROUP,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        auto_offset_reset="earliest",
        enable_auto_commit=True,
    )
    await consumer.start()
    try:
        async for msg in consumer:
            yield msg.value
    finally:
        await consumer.stop()


async def shutdown_producer():
    global _producer
    if _producer is not None:
        await _producer.stop()
        _producer = None
