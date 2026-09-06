"""
app/api/auth.py — Authentication & role-based authorization.

Flow:
  1. Merchant is issued a raw API key out-of-band (shown once, stored only as
     a sha256 hash in the DB).
  2. Client calls POST /auth/token with the raw API key -> gets back a
     short-lived signed JWT carrying {merchant_id, role, exp}.
  3. All other endpoints require `Authorization: Bearer <jwt>` and are
     protected by role via `require_role(...)`.

Roles:
  - ops:     can view queue + evidence packs, add case notes, escalate.
  - admin:   everything ops can do, plus change thresholds/cost config,
             trigger retraining.
  - auditor: read-only access to audit logs and decision history; cannot
             view raw evidence packs' PII fields or change any config.
"""
import hashlib
import secrets
import time
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.db_models import ApiKey

bearer_scheme = HTTPBearer(auto_error=True)

VALID_ROLES = {"ops", "admin", "auditor"}


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def generate_api_key() -> str:
    """Generates a new random API key. Call this once when onboarding a merchant
    user; show the raw key to them exactly once, then only store the hash."""
    return secrets.token_urlsafe(32)


def issue_api_key(db: Session, merchant_id: str, role: str) -> str:
    if role not in VALID_ROLES:
        raise ValueError(f"invalid role {role}")
    raw_key = generate_api_key()
    key_id = f"key_{role}_{secrets.token_hex(6)}"
    db.add(ApiKey(key_id=key_id, key_hash=hash_key(raw_key), merchant_id=merchant_id, role=role))
    db.commit()
    return raw_key  # caller must surface this to the user ONCE; it is never retrievable again


def create_access_token(merchant_id: str, role: str, key_id: str) -> str:
    payload = {
        "merchant_id": merchant_id,
        "role": role,
        "key_id": key_id,
        "exp": int(time.time()) + settings.JWT_EXPIRE_SECONDS,
        "iat": int(time.time()),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def authenticate_api_key(db: Session, raw_key: str) -> Optional[str]:
    """Exchanges a raw API key for a signed JWT. Returns None if invalid/revoked."""
    key_hash = hash_key(raw_key)
    record = db.query(ApiKey).filter(ApiKey.key_hash == key_hash, ApiKey.revoked == 0).first()
    if not record:
        return None
    return create_access_token(record.merchant_id, record.role, record.key_id)


class CurrentUser:
    def __init__(self, merchant_id: str, role: str, key_id: str):
        self.merchant_id = merchant_id
        self.role = role
        self.key_id = key_id


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> CurrentUser:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    merchant_id = payload.get("merchant_id")
    role = payload.get("role")
    key_id = payload.get("key_id")
    if not merchant_id or role not in VALID_ROLES:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token claims")
    return CurrentUser(merchant_id=merchant_id, role=role, key_id=key_id)


def require_role(*allowed_roles: str):
    """Dependency factory: require_role('admin') or require_role('admin','ops')."""
    def _checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role}' is not permitted; requires one of {allowed_roles}",
            )
        return user
    return _checker
