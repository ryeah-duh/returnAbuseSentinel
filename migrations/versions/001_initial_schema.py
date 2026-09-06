"""
migrations/versions/001_initial_schema.py — Alembic migration: initial schema.

Generated to mirror app/models/db_models.py exactly. Run with:
    alembic upgrade head

revision = '001'
down_revision = None
"""
from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "merchants",
        sa.Column("merchant_id", sa.String, primary_key=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("cost_manual_review", sa.Float, server_default="150"),
        sa.Column("cost_inspection", sa.Float, server_default="40"),
        sa.Column("cost_friction", sa.Float, server_default="5"),
        sa.Column("fraction_lost_on_miss", sa.Float, server_default="0.6"),
        sa.Column("green_threshold", sa.Float, server_default="0.08"),
        sa.Column("red_threshold", sa.Float, server_default="0.47"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "api_keys",
        sa.Column("key_id", sa.String, primary_key=True),
        sa.Column("key_hash", sa.String, nullable=False, unique=True),
        sa.Column("merchant_id", sa.String, sa.ForeignKey("merchants.merchant_id"), nullable=False),
        sa.Column("role", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("revoked", sa.Integer, server_default="0"),
        sa.CheckConstraint("role IN ('ops','admin','auditor')", name="ck_role_valid"),
    )

    op.create_table(
        "returns",
        sa.Column("order_id", sa.String, primary_key=True),
        sa.Column("merchant_id", sa.String, sa.ForeignKey("merchants.merchant_id"), nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="pending"),
        sa.Column("risk_score", sa.Float, nullable=True),
        sa.Column("band", sa.String, nullable=True),
        sa.Column("order_value", sa.Float, nullable=False),
        sa.Column("category", sa.String, nullable=True),
        sa.Column("features_json", sa.Text, nullable=True),
        sa.Column("evidence_json", sa.Text, nullable=True),
        sa.Column("model_version", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("scored_at", sa.DateTime, nullable=True),
        sa.Column("outcome_label", sa.Integer, nullable=True),
        sa.Column("outcome_recorded_at", sa.DateTime, nullable=True),
        sa.CheckConstraint("status IN ('pending','scored','error')", name="ck_status_valid"),
        sa.CheckConstraint("band IN ('Green','Yellow','Red') OR band IS NULL", name="ck_band_valid"),
    )
    op.create_index("ix_returns_merchant_band", "returns", ["merchant_id", "band"])
    op.create_index("ix_returns_created_at", "returns", ["created_at"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("actor", sa.String, nullable=False),
        sa.Column("action", sa.String, nullable=False),
        sa.Column("entity_type", sa.String, nullable=False),
        sa.Column("entity_id", sa.String, nullable=False),
        sa.Column("before_json", sa.Text, nullable=True),
        sa.Column("after_json", sa.Text, nullable=True),
    )
    op.create_index("ix_audit_entity", "audit_log", ["entity_type", "entity_id"])
    op.create_index("ix_audit_timestamp", "audit_log", ["timestamp"])

    op.create_table(
        "model_registry",
        sa.Column("version", sa.String, primary_key=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("test_auc", sa.Float),
        sa.Column("test_brier", sa.Float),
        sa.Column("is_champion", sa.Integer, server_default="0"),
        sa.Column("metadata_json", sa.Text, nullable=True),
    )

    op.create_table(
        "metrics_daily",
        sa.Column("date", sa.String, primary_key=True),
        sa.Column("merchant_id", sa.String, sa.ForeignKey("merchants.merchant_id"), primary_key=True),
        sa.Column("precision_red", sa.Float, nullable=True),
        sa.Column("recall_overall", sa.Float, nullable=True),
        sa.Column("automation_rate", sa.Float, nullable=True),
        sa.Column("loss_prevented", sa.Float, nullable=True),
        sa.Column("psi_score", sa.Float, nullable=True),
    )


def downgrade():
    op.drop_table("metrics_daily")
    op.drop_table("model_registry")
    op.drop_table("audit_log")
    op.drop_table("returns")
    op.drop_table("api_keys")
    op.drop_table("merchants")
