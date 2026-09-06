"""
app/models/db_models.py — SQLAlchemy ORM models.

Mirrors the schema validated in the reference SQLite prototype:
merchants, api_keys, returns, audit_log, model_registry, metrics_daily.
Run `alembic upgrade head` (see migrations/) to create these in Postgres.
"""
from datetime import datetime
from sqlalchemy import (
    Column, String, Float, Integer, Text, ForeignKey, DateTime,
    CheckConstraint, UniqueConstraint, Index
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Merchant(Base):
    __tablename__ = "merchants"

    merchant_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)

    # Per-merchant cost model (Concrete change #9 — merchant-specific P&L)
    cost_manual_review = Column(Float, default=150.0)
    cost_inspection = Column(Float, default=40.0)
    cost_friction = Column(Float, default=5.0)
    fraction_lost_on_miss = Column(Float, default=0.6)

    # Calibrated, per-merchant thresholds (set by threshold_optimizer.py)
    green_threshold = Column(Float, default=0.08)
    red_threshold = Column(Float, default=0.47)

    created_at = Column(DateTime, default=datetime.utcnow)

    api_keys = relationship("ApiKey", back_populates="merchant")
    returns = relationship("ReturnCase", back_populates="merchant")


class ApiKey(Base):
    __tablename__ = "api_keys"

    key_id = Column(String, primary_key=True)
    key_hash = Column(String, nullable=False, unique=True)  # sha256 of raw key, never store raw
    merchant_id = Column(String, ForeignKey("merchants.merchant_id"), nullable=False)
    role = Column(String, nullable=False)  # 'ops' | 'admin' | 'auditor'
    created_at = Column(DateTime, default=datetime.utcnow)
    revoked = Column(Integer, default=0)  # soft-delete flag for key rotation/revocation

    __table_args__ = (
        CheckConstraint("role IN ('ops','admin','auditor')", name="ck_role_valid"),
    )

    merchant = relationship("Merchant", back_populates="api_keys")


class ReturnCase(Base):
    __tablename__ = "returns"

    order_id = Column(String, primary_key=True)
    merchant_id = Column(String, ForeignKey("merchants.merchant_id"), nullable=False)
    status = Column(String, nullable=False, default="pending")  # pending | scored | error
    risk_score = Column(Float, nullable=True)
    band = Column(String, nullable=True)  # Green | Yellow | Red
    order_value = Column(Float, nullable=False)
    category = Column(String, nullable=True)

    features_json = Column(Text, nullable=True)     # raw input snapshot (immutable audit trail)
    evidence_json = Column(Text, nullable=True)      # SHAP-style contributions + plain-English reasons
    model_version = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    scored_at = Column(DateTime, nullable=True)

    # Label pipeline (Concrete change #7) — filled in later when ground truth is known
    outcome_label = Column(Integer, nullable=True)   # 1 = confirmed abuse, 0 = confirmed legit, NULL = pending
    outcome_recorded_at = Column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('pending','scored','error')", name="ck_status_valid"),
        CheckConstraint("band IN ('Green','Yellow','Red') OR band IS NULL", name="ck_band_valid"),
        Index("ix_returns_merchant_band", "merchant_id", "band"),
        Index("ix_returns_created_at", "created_at"),
    )

    merchant = relationship("Merchant", back_populates="returns")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    actor = Column(String, nullable=False)          # e.g. "user:abhinav" or "system:scorer"
    action = Column(String, nullable=False)         # e.g. "score_return", "update_thresholds"
    entity_type = Column(String, nullable=False)    # e.g. "return", "merchant_config"
    entity_id = Column(String, nullable=False)
    before_json = Column(Text, nullable=True)
    after_json = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_audit_entity", "entity_type", "entity_id"),
        Index("ix_audit_timestamp", "timestamp"),
    )


class ModelRegistry(Base):
    __tablename__ = "model_registry"

    version = Column(String, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    test_auc = Column(Float)
    test_brier = Column(Float)
    is_champion = Column(Integer, default=0)  # only one row should be 1 at a time
    metadata_json = Column(Text, nullable=True)


class MetricsDaily(Base):
    __tablename__ = "metrics_daily"

    date = Column(String, primary_key=True)
    merchant_id = Column(String, ForeignKey("merchants.merchant_id"), primary_key=True)
    precision_red = Column(Float, nullable=True)
    recall_overall = Column(Float, nullable=True)
    automation_rate = Column(Float, nullable=True)
    loss_prevented = Column(Float, nullable=True)
    psi_score = Column(Float, nullable=True)

    __table_args__ = (
        UniqueConstraint("date", "merchant_id", name="uq_metrics_date_merchant"),
    )
