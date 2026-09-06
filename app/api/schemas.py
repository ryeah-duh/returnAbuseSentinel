"""
app/api/schemas.py — Pydantic v2 request/response contracts.
Every external input is validated here before it touches business logic.
"""
from datetime import datetime
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field, field_validator

Category = Literal["apparel", "electronics", "footwear", "home", "beauty"]
Band = Literal["Green", "Yellow", "Red"]
Role = Literal["ops", "admin", "auditor"]


class ReturnCaseIn(BaseModel):
    """Inbound payload for scoring one return. Mirrors FEATURE_COLS exactly."""
    order_id: str = Field(..., min_length=3, max_length=64)
    merchant_id: str = Field(..., min_length=1, max_length=32)
    account_age_days: int = Field(..., ge=0, le=20000)
    past_orders: int = Field(..., ge=0, le=100000)
    return_rate_hist: float = Field(..., ge=0, le=1)
    refund_to_keep_count: int = Field(..., ge=0, le=1000)
    bracketing_score: float = Field(..., ge=0, le=1)
    claim_text_susp: float = Field(..., ge=0, le=1)
    image_ai_artifact_score: float = Field(..., ge=0, le=1)
    weight_mismatch_kg: float = Field(..., ge=0, le=100)
    shared_identifier_flag: int = Field(..., ge=0, le=1)
    carrier_scan_gap: int = Field(..., ge=0, le=1)
    days_to_claim: float = Field(..., ge=0, le=3650)
    order_value: float = Field(..., gt=0, le=10_000_000)
    category: Category

    @field_validator("order_id")
    @classmethod
    def sanitize_order_id(cls, v: str) -> str:
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError("order_id must be alphanumeric (with - or _ only)")
        return v


class ReturnBatchIn(BaseModel):
    cases: List[ReturnCaseIn] = Field(..., min_length=1, max_length=500)


class EvidencePackOut(BaseModel):
    base_value: float
    predicted_value: float
    contributions: Dict[str, float]
    reasons: List[str]


class ReturnScoreOut(BaseModel):
    order_id: str
    mode: Literal["sync", "async"]
    status: str
    risk_score: Optional[float] = None
    band: Optional[Band] = None
    recommended_action: Optional[str] = None
    evidence: Optional[EvidencePackOut] = None


class ReturnListItemOut(BaseModel):
    order_id: str
    merchant_id: str
    status: str
    risk_score: Optional[float]
    band: Optional[Band]
    order_value: float
    category: Optional[str]
    created_at: datetime
    scored_at: Optional[datetime]

    model_config = {"from_attributes": True}


class ReturnListOut(BaseModel):
    items: List[ReturnListItemOut]
    total: int
    page: int
    page_size: int


class ThresholdUpdateIn(BaseModel):
    green_threshold: float = Field(..., gt=0, lt=1)
    red_threshold: float = Field(..., gt=0, lt=1)

    @field_validator("red_threshold")
    @classmethod
    def red_above_green(cls, v, info):
        green = info.data.get("green_threshold")
        if green is not None and v <= green:
            raise ValueError("red_threshold must be greater than green_threshold")
        return v


class CostConfigUpdateIn(BaseModel):
    cost_manual_review: float = Field(..., ge=0)
    cost_inspection: float = Field(..., ge=0)
    cost_friction: float = Field(..., ge=0)
    fraction_lost_on_miss: float = Field(..., ge=0, le=1)


class MetricsOut(BaseModel):
    merchant_id: str
    date_range: str
    precision_red: float
    recall_overall: float
    automation_rate_pct: float
    loss_prevented_inr: float
    psi_score: float
    psi_alert: bool


class TokenRequestIn(BaseModel):
    api_key: str = Field(..., min_length=20)


class TokenResponseOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class ApiKeyIssueIn(BaseModel):
    merchant_id: str
    role: Role


class ApiKeyIssueOut(BaseModel):
    key_id: str
    raw_key: str = Field(..., description="Shown only once. Store it securely now.")
    role: Role
    merchant_id: str


class OutcomeLabelIn(BaseModel):
    order_id: str
    outcome_label: Literal[0, 1]
