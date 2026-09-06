"""
app/services/feature_store.py — Redis-backed real-time feature cache.

Ensures identical feature definitions are used at training time and at
inference time (avoids train/serve skew). Two responsibilities:
  1. Compute/cache rolling velocity features (returns in last 1h/24h per
     account, rolling return rate) that are too expensive to recompute
     from a full table scan on every request.
  2. Deduplicate return submissions: if the same order_id is POSTed twice
     within a short window (retry, double-click, replay), return the
     cached result instead of double-scoring / double-counting.
"""
import json
import time
from typing import Optional, Dict, Any
import redis

from app.config import settings

_redis_client: Optional[redis.Redis] = None


def get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def dedup_key(order_id: str) -> str:
    return f"dedup:return:{order_id}"


def check_and_set_dedup(order_id: str, ttl_seconds: int = 300) -> bool:
    """Returns True if this is a NEW submission (should proceed), False if it's
    a duplicate within the TTL window (should short-circuit and return the
    cached response)."""
    r = get_redis()
    key = dedup_key(order_id)
    was_set = r.set(key, "1", nx=True, ex=ttl_seconds)
    return bool(was_set)


def cache_response(order_id: str, response: Dict[str, Any], ttl_seconds: int = 300):
    r = get_redis()
    r.set(f"resp:{order_id}", json.dumps(response), ex=ttl_seconds)


def get_cached_response(order_id: str) -> Optional[Dict[str, Any]]:
    r = get_redis()
    raw = r.get(f"resp:{order_id}")
    return json.loads(raw) if raw else None


def record_return_event(account_id: str, timestamp: Optional[float] = None):
    """Push a return event into a per-account sorted set (score = timestamp)
    so velocity features can be computed as a range query instead of a
    full-table scan."""
    r = get_redis()
    ts = timestamp or time.time()
    key = f"velocity:{account_id}"
    r.zadd(key, {str(ts): ts})
    r.expire(key, 60 * 60 * 24 * 30)  # keep 30 days of history


def get_velocity_features(account_id: str) -> Dict[str, int]:
    """Returns count of return events in the last 1h and 24h for this account.
    Same function is called during training-data feature engineering and
    during live inference, so definitions never drift apart."""
    r = get_redis()
    key = f"velocity:{account_id}"
    now = time.time()
    count_1h = r.zcount(key, now - 3600, now)
    count_24h = r.zcount(key, now - 86400, now)
    return {"returns_last_1h": int(count_1h), "returns_last_24h": int(count_24h)}
