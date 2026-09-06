"""
app/api/main.py — FastAPI application entrypoint.

Endpoints (all except /health and /auth/token require a Bearer JWT):
  POST /auth/token                  — exchange API key for JWT
  POST /returns/score                — score one return (sync or async per rule-prescreen)
  POST /returns/batch                 — score up to 500 returns in one call
  GET  /returns/{order_id}            — fetch one return + evidence pack
  GET  /returns                       — list/filter/paginate returns
  GET  /metrics                       — precision/recall/loss/drift for a merchant
  POST /config/thresholds             — update Green/Yellow/Red cutoffs (admin only)
  POST /config/cost                   — update per-merchant cost profile (admin only)
  POST /returns/{order_id}/outcome    — record ground-truth label (admin/ops)
  GET  /simulate/threshold-curve      — projected impact curve for the frontend slider
  WS   /ws/returns                    — live stream of newly-scored returns
  GET  /metrics/prometheus            — Prometheus scrape endpoint
"""
import json
import time
from datetime import datetime, date
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query, status
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.config import settings
from app.database import get_db, init_db
from app.models.db_models import ReturnCase, Merchant, AuditLog
from app.api import schemas
from app.api.auth import (
    authenticate_api_key, issue_api_key, get_current_user, require_role, CurrentUser,
)
from app.services.ml_core import ReturnAbuseModel, rule_prescreen
from app.services.feature_store import check_and_set_dedup, cache_response, get_cached_response
from app.services.kafka_client import publish_return_event
from app.monitoring.drift_monitor import check_score_drift, compute_daily_metrics
from app.pipelines.threshold_optimizer import CostProfile, projected_impact_curve

REQUEST_COUNT = Counter("sentinel_requests_total", "Total API requests", ["endpoint", "status"])
SCORING_LATENCY = Histogram("sentinel_scoring_latency_seconds", "Sync scoring latency")

app = FastAPI(
    title="Return-Abuse Sentinel API",
    description="Defense-only AI Risk Manager for return/refund abuse. "
                "Scores, routes, and explains — never auto-refunds or auto-denies.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_model: Optional[ReturnAbuseModel] = None
_ws_connections: List[WebSocket] = []


@app.on_event("startup")
def on_startup():
    global _model
    init_db()
    try:
        _model = ReturnAbuseModel.load(settings.MODEL_ARTIFACT_PATH)
    except FileNotFoundError:
        _model = None  # allow API to boot for /health even before first training run


def get_model() -> ReturnAbuseModel:
    if _model is None:
        raise HTTPException(status_code=503, detail="Model not loaded yet — run training pipeline first.")
    return _model


def write_audit(db: Session, actor: str, action: str, entity_type: str, entity_id: str,
                 before: Optional[dict] = None, after: Optional[dict] = None):
    db.add(AuditLog(
        timestamp=datetime.utcnow(), actor=actor, action=action,
        entity_type=entity_type, entity_id=entity_id,
        before_json=json.dumps(before) if before else None,
        after_json=json.dumps(after) if after else None,
    ))
    db.commit()


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": _model is not None}


@app.get("/metrics/prometheus")
def prometheus_metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/auth/token", response_model=schemas.TokenResponseOut)
def get_token(payload: schemas.TokenRequestIn, db: Session = Depends(get_db)):
    token = authenticate_api_key(db, payload.api_key)
    if not token:
        REQUEST_COUNT.labels(endpoint="/auth/token", status="401").inc()
        raise HTTPException(status_code=401, detail="Invalid API key")
    REQUEST_COUNT.labels(endpoint="/auth/token", status="200").inc()
    return schemas.TokenResponseOut(access_token=token, expires_in=settings.JWT_EXPIRE_SECONDS)


@app.post("/admin/api-keys", response_model=schemas.ApiKeyIssueOut)
def create_api_key(
    payload: schemas.ApiKeyIssueIn, db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("admin")),
):
    raw_key = issue_api_key(db, payload.merchant_id, payload.role)
    write_audit(db, f"user:{user.key_id}", "issue_api_key", "api_key", payload.merchant_id,
                after={"role": payload.role})
    return schemas.ApiKeyIssueOut(key_id=f"issued-for-{payload.merchant_id}", raw_key=raw_key,
                                    role=payload.role, merchant_id=payload.merchant_id)


@app.post("/returns/score", response_model=schemas.ReturnScoreOut)
async def score_return(
    case: schemas.ReturnCaseIn, db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("ops", "admin")),
    model: ReturnAbuseModel = Depends(get_model),
):
    if case.merchant_id != user.merchant_id:
        raise HTTPException(status_code=403, detail="Cannot score returns for another merchant")

    if not check_and_set_dedup(case.order_id):
        cached = get_cached_response(case.order_id)
        if cached:
            return schemas.ReturnScoreOut(**cached)

    case_dict = case.model_dump()
    merchant = db.query(Merchant).filter_by(merchant_id=case.merchant_id).first()
    green_t = merchant.green_threshold if merchant else 0.08
    red_t = merchant.red_threshold if merchant else 0.47

    route = rule_prescreen(case_dict)

    existing = db.query(ReturnCase).filter_by(order_id=case.order_id).first()
    if existing is None:
        db.add(ReturnCase(
            order_id=case.order_id, merchant_id=case.merchant_id, status="pending",
            order_value=case.order_value, category=case.category,
            features_json=json.dumps(case_dict), created_at=datetime.utcnow(),
        ))
        db.commit()

    if route == "sync":
        with SCORING_LATENCY.time():
            evidence = model.score(case_dict, green_t, red_t)
        row = db.query(ReturnCase).filter_by(order_id=case.order_id).first()
        row.status = "scored"
        row.risk_score = evidence.risk_score / 100.0
        row.band = evidence.band
        row.evidence_json = json.dumps(evidence.to_dict())
        row.model_version = model.version
        row.scored_at = datetime.utcnow()
        db.commit()
        write_audit(db, f"user:{user.key_id}", "score_return_sync", "return", case.order_id,
                    after={"score": evidence.risk_score, "band": evidence.band})

        response = schemas.ReturnScoreOut(
            order_id=case.order_id, mode="sync", status="scored",
            risk_score=evidence.risk_score, band=evidence.band,
            recommended_action=evidence.recommended_action,
            evidence=schemas.EvidencePackOut(
                base_value=evidence.base_value, predicted_value=evidence.risk_score / 100.0,
                contributions=evidence.contributions, reasons=evidence.reasons,
            ),
        )
        cache_response(case.order_id, response.model_dump())
        REQUEST_COUNT.labels(endpoint="/returns/score", status="200_sync").inc()
        return response
    else:
        await publish_return_event(case_dict)
        response = schemas.ReturnScoreOut(order_id=case.order_id, mode="async", status="pending")
        cache_response(case.order_id, response.model_dump())
        REQUEST_COUNT.labels(endpoint="/returns/score", status="200_async").inc()
        return response


@app.post("/returns/batch", response_model=List[schemas.ReturnScoreOut])
async def score_batch(
    payload: schemas.ReturnBatchIn, db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("ops", "admin")),
    model: ReturnAbuseModel = Depends(get_model),
):
    results = []
    for case in payload.cases:
        result = await score_return(case, db, user, model)
        results.append(result)
    return results


@app.get("/returns/{order_id}", response_model=schemas.ReturnScoreOut)
def get_return(
    order_id: str, db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("ops", "admin", "auditor")),
):
    row = db.query(ReturnCase).filter_by(order_id=order_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Return not found")
    if row.merchant_id != user.merchant_id:
        raise HTTPException(status_code=403, detail="Not your merchant's data")

    evidence = None
    if row.evidence_json:
        ev = json.loads(row.evidence_json)
        evidence = schemas.EvidencePackOut(
            base_value=ev["base_value"], predicted_value=(row.risk_score or 0),
            contributions=ev["contributions"], reasons=ev["reasons"],
        )
    return schemas.ReturnScoreOut(
        order_id=row.order_id, mode="sync" if row.scored_at else "async",
        status=row.status, risk_score=row.risk_score * 100 if row.risk_score else None,
        band=row.band, evidence=evidence,
    )


@app.get("/returns", response_model=schemas.ReturnListOut)
def list_returns(
    band: Optional[str] = None, category: Optional[str] = None,
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("ops", "admin", "auditor")),
):
    q = db.query(ReturnCase).filter_by(merchant_id=user.merchant_id)
    if band:
        q = q.filter(ReturnCase.band == band)
    if category:
        q = q.filter(ReturnCase.category == category)
    total = q.count()
    items = (
        q.order_by(desc(ReturnCase.created_at))
        .offset((page - 1) * page_size).limit(page_size).all()
    )
    return schemas.ReturnListOut(
        items=[schemas.ReturnListItemOut.model_validate(i) for i in items],
        total=total, page=page, page_size=page_size,
    )


@app.post("/returns/{order_id}/outcome")
def record_outcome(
    order_id: str, payload: schemas.OutcomeLabelIn, db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("ops", "admin")),
):
    row = db.query(ReturnCase).filter_by(order_id=order_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Return not found")
    before = {"outcome_label": row.outcome_label}
    row.outcome_label = payload.outcome_label
    row.outcome_recorded_at = datetime.utcnow()
    db.commit()
    write_audit(db, f"user:{user.key_id}", "record_outcome", "return", order_id,
                before=before, after={"outcome_label": payload.outcome_label})
    return {"status": "ok"}


@app.post("/config/thresholds")
def update_thresholds(
    payload: schemas.ThresholdUpdateIn, db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("admin")),
):
    merchant = db.query(Merchant).filter_by(merchant_id=user.merchant_id).first()
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    before = {"green": merchant.green_threshold, "red": merchant.red_threshold}
    merchant.green_threshold = payload.green_threshold
    merchant.red_threshold = payload.red_threshold
    db.commit()
    write_audit(db, f"user:{user.key_id}", "update_thresholds", "merchant_config", user.merchant_id,
                before=before, after=payload.model_dump())
    return {"status": "ok", "green_threshold": merchant.green_threshold, "red_threshold": merchant.red_threshold}


@app.post("/config/cost")
def update_cost_profile(
    payload: schemas.CostConfigUpdateIn, db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("admin")),
):
    merchant = db.query(Merchant).filter_by(merchant_id=user.merchant_id).first()
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    before = {
        "cost_manual_review": merchant.cost_manual_review, "cost_inspection": merchant.cost_inspection,
        "cost_friction": merchant.cost_friction, "fraction_lost_on_miss": merchant.fraction_lost_on_miss,
    }
    merchant.cost_manual_review = payload.cost_manual_review
    merchant.cost_inspection = payload.cost_inspection
    merchant.cost_friction = payload.cost_friction
    merchant.fraction_lost_on_miss = payload.fraction_lost_on_miss
    db.commit()
    write_audit(db, f"user:{user.key_id}", "update_cost_profile", "merchant_config", user.merchant_id,
                before=before, after=payload.model_dump())
    return {"status": "ok"}


@app.get("/metrics", response_model=schemas.MetricsOut)
def get_metrics(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("ops", "admin", "auditor")),
):
    metrics = compute_daily_metrics(db, user.merchant_id, date.today())
    if metrics is None:
        raise HTTPException(status_code=404, detail="Not enough labeled outcomes yet for this merchant")

    scored = db.query(ReturnCase).filter_by(merchant_id=user.merchant_id, status="scored").all()
    scores = [r.risk_score for r in scored if r.risk_score is not None]
    naive_loss_total = sum(r.order_value for r in scored if r.outcome_label == 1)
    loss_prevented = naive_loss_total * metrics["recall_overall"] * 0.6  # illustrative estimate

    drift = check_score_drift(
        baseline_scores=__import__("numpy").array(scores[: len(scores) // 2] or [0.0]),
        current_scores=__import__("numpy").array(scores[len(scores) // 2 :] or [0.0]),
        merchant_id=user.merchant_id,
    )

    return schemas.MetricsOut(
        merchant_id=user.merchant_id, date_range="today",
        precision_red=round(metrics["precision_red"], 3),
        recall_overall=round(metrics["recall_overall"], 3),
        automation_rate_pct=round(metrics["automation_rate"] * 100, 1),
        loss_prevented_inr=round(loss_prevented, 0),
        psi_score=round(drift.psi_score, 3), psi_alert=drift.is_alert,
    )


@app.get("/simulate/threshold-curve")
def simulate_threshold_curve(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("ops", "admin")),
):
    """Powers the frontend threshold slider: shows loss-reduction tradeoff
    across a range of automation-rate targets."""
    import pandas as pd
    rows = db.query(ReturnCase).filter_by(merchant_id=user.merchant_id).filter(
        ReturnCase.outcome_label.isnot(None), ReturnCase.risk_score.isnot(None)
    ).all()
    if len(rows) < 30:
        raise HTTPException(status_code=404, detail="Not enough labeled data to simulate yet")

    val_df = pd.DataFrame([{
        "prob": r.risk_score, "y_true": r.outcome_label, "order_value": r.order_value,
    } for r in rows])

    merchant = db.query(Merchant).filter_by(merchant_id=user.merchant_id).first()
    cost = CostProfile(
        cost_manual_review=merchant.cost_manual_review, cost_inspection=merchant.cost_inspection,
        cost_friction=merchant.cost_friction, fraction_lost_on_miss=merchant.fraction_lost_on_miss,
    )
    curve = projected_impact_curve(val_df, cost)
    return curve.to_dict(orient="records")


@app.websocket("/ws/returns")
async def ws_returns(websocket: WebSocket):
    await websocket.accept()
    _ws_connections.append(websocket)
    try:
        while True:
            await websocket.receive_text()  # keep-alive ping from client
    except WebSocketDisconnect:
        _ws_connections.remove(websocket)


async def broadcast_scored_return(payload: dict):
    """Called by the scored-event consumer (see services/webhook_dispatcher.py)
    to push live updates to any connected dashboard clients."""
    dead = []
    for ws in _ws_connections:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_connections.remove(ws)
