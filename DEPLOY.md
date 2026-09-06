# Return-Abuse Sentinel v2 — Local Deployment Guide

Full production-grade stack: FastAPI + PostgreSQL + Redis + Kafka + async scorer
workers + React dashboard + Prometheus/Grafana. Everything runs via Docker Compose.

## 0. Prerequisites

Install these once:

- **Docker Desktop** (includes Docker Compose v2) — [docker.com/get-started](https://www.docker.com/get-started/)
- **Git** (optional, if you want version control)
- At least **6GB free RAM** for Docker (Postgres + Redis + Kafka + Zookeeper + API + 2 scorer replicas + frontend + Prometheus + Grafana is a lot of containers)

Verify Docker works:
```bash
docker --version
docker compose version
```

## 1. Assemble the project folder

Create a folder and download every file from the chat's file panel into it (flat, all in one folder), plus `setup_structure.py`. Then run:

```bash
mkdir return-abuse-sentinel
cd return-abuse-sentinel
# download all files from chat into this folder
python setup_structure.py
```

This moves every file into its correct path (`app/api/main.py`, `frontend/src/App.tsx`, etc.), renames the three `Dockerfile.*.txt` files correctly, and creates the empty `__init__.py` package markers Python needs.

Verify the structure looks like this afterward:

```
return-abuse-sentinel/
├── app/
│   ├── api/ (auth.py, schemas.py, main.py, __init__.py)
│   ├── services/ (ml_core.py, feature_store.py, kafka_client.py, scorer_worker.py, webhook_dispatcher.py, pdf_export.py, __init__.py)
│   ├── models/ (db_models.py, __init__.py)
│   ├── monitoring/ (drift_monitor.py, __init__.py)
│   ├── pipelines/ (train.py, retrain.py, ingest.py, threshold_optimizer.py, __init__.py)
│   ├── config.py, database.py, __init__.py
├── migrations/ (env.py, versions/001_initial_schema.py)
├── frontend/ (package.json, src/, Dockerfile, ...)
├── monitoring/prometheus.yml
├── scripts/bootstrap.py
├── docker-compose.yml
├── Dockerfile.api / Dockerfile.scorer / Dockerfile.webhook
├── requirements.txt
├── alembic.ini
└── .env.example
```

## 2. Configure environment variables

```bash
cp .env.example .env
```

Generate a real JWT secret and paste it into `.env`:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```
Open `.env` and replace `JWT_SECRET_KEY=CHANGE_ME_GENERATE_A_REAL_SECRET` with the generated value.

## 3. Build and start the full stack

```bash
docker compose up -d --build
```

This pulls/builds 10 containers: `postgres`, `redis`, `zookeeper`, `kafka`, `api`, `scorer` (x2 replicas), `webhook_dispatcher`, `frontend`, `prometheus`, `grafana`. First build takes 3–6 minutes depending on your connection (LightGBM/SHAP wheels are sizeable).

Watch it come up:
```bash
docker compose ps
docker compose logs -f api
```

Wait until `postgres`, `redis`, and `kafka` show `healthy` in `docker compose ps` before proceeding — the API container will retry-connect but starting too early can cause confusing errors in the logs.

## 4. Bootstrap the database, train the first model, get your API keys

```bash
docker compose exec api python -m scripts.bootstrap
```

This runs migrations, generates the synthetic training dataset, trains the calibrated LightGBM model, registers it as champion, computes optimal per-merchant thresholds, and **prints three API keys to your terminal** — admin, ops, and auditor. **Copy them immediately**, they're never shown again (only their hash is stored in Postgres).

## 5. Open the dashboard

Go to **[http://localhost:3000](http://localhost:3000)** in your browser. Paste the **admin** or **ops** key into the login screen — it exchanges the key for a JWT automatically and stores it in your browser's local storage.

You should see:
- The metrics strip (will say "not enough labeled outcomes yet" until you label a few cases — see step 7)
- Green/Yellow/Red tabs with live returns
- Click any row to open the evidence drawer with the SHAP waterfall chart

## 6. Send test return events

The dashboard alone won't have data until you POST some returns. Use the interactive API docs at **[http://localhost:8000/docs](http://localhost:8000/docs)**:

1. Click `POST /auth/token`, "Try it out", paste your ops API key, execute — copy the `access_token`.
2. Click the padlock icon (Authorize) at the top of the Swagger page, paste `Bearer <token>`.
3. Try `POST /returns/score` with a sample body:
```json
{
  "order_id": "ORD900001",
  "merchant_id": "M001",
  "account_age_days": 40,
  "past_orders": 12,
  "return_rate_hist": 0.65,
  "refund_to_keep_count": 2,
  "bracketing_score": 0.7,
  "claim_text_susp": 0.6,
  "image_ai_artifact_score": 0.65,
  "weight_mismatch_kg": 0.3,
  "shared_identifier_flag": 0,
  "carrier_scan_gap": 0,
  "days_to_claim": 0.8,
  "order_value": 1200,
  "category": "electronics"
}
```
This should route to `sync` (or `async` if it doesn't hit a pre-screen rule) and come back scored — refresh the dashboard to see it appear in its band.

Or script a batch of test traffic:
```bash
curl -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"api_key":"<your ops key>"}'
```

## 7. Label a few outcomes to unlock live metrics

In the dashboard, open the evidence drawer for a few scored returns and click **"Mark: Legitimate"** or **"Mark: Confirmed abuse"**. Once ~20+ cases per merchant are labeled, the `/metrics` endpoint and dashboard metrics strip populate with real precision/recall/loss numbers, and the threshold simulator unlocks after 30+ labels.

## 8. Observability

- **Prometheus**: [http://localhost:9090](http://localhost:9090) — query `sentinel_requests_total` or `sentinel_scoring_latency_seconds`
- **Grafana**: [http://localhost:3001](http://localhost:3001) — login `admin` / `admin` (set in docker-compose.yml), add Prometheus (`http://prometheus:9090`) as a data source if not auto-provisioned
- **API docs**: [http://localhost:8000/docs](http://localhost:8000/docs) — full interactive Swagger UI

## 9. Common issues

| Problem | Fix |
|---|---|
| `api` container keeps restarting | Run `docker compose logs api` — usually means Postgres wasn't healthy yet. Run `docker compose up -d` again after a few seconds. |
| `ModuleNotFoundError: app` inside container | You edited files outside the mapped volumes — rebuild with `docker compose up -d --build api` |
| Bootstrap script errors "model not found" | It trains inline, so this shouldn't happen — check `docker compose logs api` for a training exception (usually a pandas/lightgbm version mismatch; confirm `requirements.txt` installed cleanly) |
| Frontend shows blank page | Open browser dev console; check `VITE_API_BASE_URL` matches where the API is actually reachable (`http://localhost:8000` by default) |
| Kafka container unhealthy forever | Give it more time (30-60s) on first boot — Zookeeper + Kafka startup ordering is slow on first run. `docker compose restart kafka` if it's stuck after 2 minutes. |
| Port already in use (5432, 6379, 8000, 3000, 9092...) | Something else on your machine is using that port — stop it, or edit the port mappings in `docker-compose.yml` |

## 10. Stopping / resetting

```bash
docker compose down            # stop everything, keep data
docker compose down -v         # stop everything AND wipe Postgres/Redis volumes (full reset)
```

## 11. Retraining with real data later

Once you have real merchant RMA data with confirmed outcomes:
```bash
docker compose exec api python -m app.pipelines.ingest --file merchant_returns.csv --merchant-id M001
docker compose exec api python -m app.pipelines.retrain
```
`retrain.py` only promotes the new model if it genuinely beats the current champion on AUC and Brier score — otherwise it logs why it kept the old one.

## What to demo at the buildathon

1. Show `docker compose up -d` bringing up the whole stack in one command — judges notice this.
2. Walk through Swagger docs at `/docs`, score a live case, show it land in the dashboard via WebSocket in real time.
3. Open the evidence drawer, show the SHAP waterfall — not generic rules, real per-prediction attribution.
4. Label a few outcomes live, refresh metrics strip, show precision/recall/loss-prevented populate from real data.
5. Open the threshold simulator, show the automation-rate vs. loss-reduction curve, apply a different threshold live.
6. Mention the champion-challenger retrain pipeline and PSI drift monitor — most teams won't have thought about model staleness at all.
