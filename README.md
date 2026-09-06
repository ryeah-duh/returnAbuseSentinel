project: Return-Abuse Sentinel  
track: full-stack + ai-ml + devops  
level: advanced  
started: 2026-09-04  
shipped: 2026-09-05 (local Docker deployment verified)  
repo: Not yet published — local project at `C:\Projects\return-abuse-sentinel`  
live: Local demo — `http://localhost:3000`  
api_docs: `http://localhost:8000/docs`  
status: Locally deployed and verified with a live async Red-band scoring event  
classification: Defense-only merchant risk-management system  
primary user: E-commerce / D2C merchant fraud and return-operations teams  

---

# 1. What this project is

**For a non-technical friend:** Return-Abuse Sentinel is like a safety assistant for an online store. When someone asks to return an item, it checks for warning signs such as an unusually high history of returns, suspicious damage claims, or a parcel-weight mismatch, then tells the store whether the case looks low risk, needs inspection, or needs a human fraud reviewer.

**For an engineer:** Return-Abuse Sentinel is a Dockerized, event-driven return/refund-abuse risk platform. It uses FastAPI for authenticated ingestion, Kafka for asynchronous event delivery, Redis for deduplication and real-time feature support, PostgreSQL for persistent case/evidence/audit storage, calibrated LightGBM for risk scoring, SHAP for per-prediction explanations, and a React operations dashboard for human-in-the-loop review.

**Core promise:** The system is strictly **defense-only**. It scores, routes, explains, and records decisions. It does not auto-deny returns, reverse refunds, block users, message customers, or perform irreversible actions.

# 2. Problem it solves

Return and refund abuse is a post-purchase loss problem that can silently reduce a merchant's margin. Payment fraud tools may detect suspicious payments, but they often do not cover what happens after delivery: serial returns, refund-to-keep behavior, fake or AI-generated damage claims, item swaps, empty-box returns, and coordinated return-abuse rings.

A merchant needs more than a generic binary fraud score. They need an operational decision system that balances fraud loss against customer friction:

- Approving all returns is fast but allows abusive returns to slip through.
- Manually reviewing every return reduces loss but is expensive, slow, and frustrates genuine customers.
- Blocking everyone who returns often is unfair and produces costly false positives.

This project creates three decision lanes:

| Risk lane | Meaning | Action | Business purpose |
|---|---|---|---|
| Green | Low abuse risk | Normal return flow; merchant may auto-approve under its own policy | Preserve customer experience and maximize automation |
| Yellow | Moderate or uncertain risk | Request low-cost verification such as warehouse/photo inspection before refund | Catch ambiguous abuse without treating customers as fraudsters |
| Red | High risk | Generate evidence pack and route to human fraud review; no automatic denial | Protect margin while maintaining human accountability |

The system also models the **cost of mistakes**. A false positive can create review cost and customer friction; a false negative can result in refund, product, logistics, and chargeback loss. Thresholds are optimized against expected merchant-specific ₹ loss rather than a generic accuracy number.

# 3. Architecture

```text
                         ┌──────────────────────────────────────┐
                         │ Merchant OMS / Admin / React UI       │
                         │ submits a return request              │
                         └──────────────────┬───────────────────┘
                                            │ HTTPS / REST
                                            v
┌─────────────────────────────────────────────────────────────────────────────┐
│ FastAPI API Gateway                                                          │
│ - Pydantic validation                                                        │
│ - API key -> JWT authentication                                              │
│ - Role-based access control                                                  │
│ - Merchant isolation                                                        │
│ - Redis request deduplication                                                │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                 ┌─────────────┴─────────────┐
                 │ Rule-based pre-screen     │
                 │ High-value / ring signal? │
                 └─────────────┬─────────────┘
                         sync   │   async
             ┌──────────────────┘   └────────────────────┐
             v                                           v
┌───────────────────────────────┐            ┌───────────────────────────────┐
│ Immediate model scoring       │            │ Kafka: returns.incoming         │
│ API returns score/evidence    │            │ Durable asynchronous event queue│
└──────────────┬────────────────┘            └──────────────┬────────────────┘
               │                                            │
               └──────────────────────┬─────────────────────┘
                                      v
                 ┌──────────────────────────────────────┐
                 │ Scorer Worker replicas                │
                 │ - consume Kafka events                │
                 │ - enrich live features via Redis      │
                 │ - calibrated LightGBM risk scoring    │
                 │ - SHAP attribution / evidence pack    │
                 └──────────────────┬───────────────────┘
                                    │
                   ┌────────────────┴─────────────────┐n                   v                                  v
┌──────────────────────────────────────┐  ┌──────────────────────────────────┐
│ PostgreSQL                            │  │ Kafka: returns.scored             │
│ - returns and scores                  │  │ - downstream event notification   │
│ - evidence JSON                       │  └────────────────┬─────────────────┘
│ - merchant cost profiles              │                   │
│ - audit log                           │                   v
│ - model registry                      │  ┌──────────────────────────────────┐
│ - reviewer outcome labels             │  │ Webhook dispatcher / live updates │
└──────────────────┬───────────────────┘  └──────────────────────────────────┘
                   │
                   v
┌─────────────────────────────────────────────────────────────────────────────┐
│ React Operations Dashboard                                                    │
│ - Green / Yellow / Red queues                                                 │
│ - Evidence drawer with SHAP contributions                                     │
│ - Human reviewer outcome buttons                                              │
│ - Threshold simulator                                                         │
│ - Metrics and drift visibility                                                │
└─────────────────────────────────────────────────────────────────────────────┘

Supporting services:
  Redis       -> deduplication + rolling velocity feature store
  Prometheus  -> scrape API service metrics
  Grafana     -> observability dashboard
  Retraining  -> champion/challenger model pipeline
```

## Components

| Component | Responsibility | Why this technology | Why not the simpler alternative |
|---|---|---|---|
| FastAPI API gateway | Accept return-risk requests, validate them, authenticate callers, route sync/async requests, provide OpenAPI docs | FastAPI gives type-driven validation, async support, and Swagger docs automatically | A plain Flask app would work for a small demo, but would require more manual validation and API documentation work |
| Pydantic v2 | Reject malformed inputs before they reach ML or database logic | Strong field bounds and typed contracts prevent invalid values such as negative order amount or invalid risk score | Manual `if` checks become inconsistent and hard to maintain |
| PostgreSQL | Persist returns, scores, evidence packs, labels, audit logs, models, and merchant configuration | Transactional, queryable relational storage is appropriate for operations and audit requirements | CSV and in-memory objects disappear on restart and cannot safely support multiple workers |
| SQLAlchemy + Alembic | Database models and schema migrations | Makes schema change/versioning explicit and repeatable | Raw SQL-only development is harder to maintain as entities grow |
| Kafka + Zookeeper | Async event queue between API and scorer workers | API responds quickly while workers independently scale and process scores | A synchronous model call blocks request latency; a Python-only queue does not survive process/container restarts |
| Redis | Request deduplication and rolling velocity features | Fast TTL-based reads/writes suit recent order-id dedup and counters | Querying PostgreSQL for every recent event is slower and more expensive |
| LightGBM | Main gradient-boosted decision-tree risk model | Strong baseline for tabular fraud/risk features, handles non-linear interactions efficiently | Deep learning is unnecessary for this initial tabular dataset and harder to explain under time constraints |
| Isotonic calibration | Converts model outputs into more reliable probabilities | Cost-aware thresholds need calibrated probabilities, not just rankings | Raw classifier probabilities can be overconfident or underconfident |
| SHAP TreeExplainer | Explain individual model predictions | Produces per-feature contributions for reviewers and judges | A generic rules list cannot explain why this specific prediction received this score |
| React + TypeScript + Vite | Interactive operations dashboard | Modern component model, compile-time type checks, browser dashboard delivery | Streamlit was retained as an old fallback demo but is more static and less suitable for role-based operations UI |
| TanStack Query + Axios | Fetch and cache API data with automatic polling | Keeps live queue state manageable and separates data-fetching from UI logic | Manually calling `fetch` everywhere makes cache/error handling harder |
| Prometheus + Grafana | Observe API request count/latency and operate the stack | Standard metrics pipeline that judges recognize | Console logging alone does not provide time-series visibility |
| Docker Compose | Run the full multi-service platform locally | One command starts the same services together with networking/volumes | Installing Postgres, Redis, Kafka, frontend, and API manually is error-prone |

# 4. Key decisions and trade-offs

| Decision | Options I considered | What I chose | Why | What I gave up |
|---|---|---|---|---|
| Loss class | Generic payment fraud, chargeback responder, COD RTO risk, return abuse | Return/refund abuse | It is a focused, under-addressed post-purchase merchant loss category and allows a strong human-review workflow | The project does not cover every payment-fraud pattern |
| Risk outcome | Binary approve/block | Green/Yellow/Red triage | A middle verification lane captures uncertainty without forcing a harmful automatic decision | More operational complexity than a single binary threshold |
| Enforcement posture | Auto-deny/block, score-only, human-in-the-loop | Defense-only human-in-the-loop | Meets track rules and reduces harm from false positives | Cannot claim fully automatic fraud prevention |
| API behavior | All synchronous scoring, all asynchronous scoring, hybrid | Hybrid rule pre-screen + async Kafka path | High-risk signals can receive immediate scoring; normal requests remain low-latency and scalable | More services and debugging complexity |
| Model choice | Logistic regression, sklearn Gradient Boosting, LightGBM, neural model | LightGBM + isotonic calibration | Strong tabular baseline with efficient inference and explainability | Requires external dependency and model artifact lifecycle |
| Explainability | Static hand-coded reasons, global feature importance, SHAP | SHAP-style per-case explanation | Reviewer sees why a particular case is high risk | SHAP adds dependency/version sensitivity and inference overhead |
| Storage | CSV/pickle, SQLite, PostgreSQL | PostgreSQL | Supports durable multi-worker operations, auditability, queries, and configuration | Higher local deployment overhead |
| Real-time feature data | Recompute from DB, Redis, dedicated feature store | Redis-backed lightweight feature-store pattern | Fast rolling counters plus TTL-based deduplication | Not a full enterprise feature-store implementation such as Feast |
| Authentication | No auth, hardcoded password, API key only, API key -> JWT | Hashed API keys exchanged for signed JWT + RBAC | API keys are not stored in raw form; JWT scopes requests by merchant/role | Frontend session handling needs improvement for stale tokens |
| Local deployment | Python scripts only, cloud-only deployment, Docker Compose | Docker Compose | Repeatable local demo with Postgres/Redis/Kafka/React/API stack | Uses significant laptop RAM and has first-run setup complexity |
| Model retraining | Always replace model, manual retraining only, champion/challenger | Champion/challenger | Prevents a worse new model from automatically replacing the current model | Needs enough delayed labels before it becomes useful |
| Test data | Public dataset, real merchant data, synthetic RMA data | Synthetic RMA-style data with overlap and label noise | Enables a safe Buildathon demo without private customer data | Metrics are illustrative, not real merchant performance |

# 5. Skills demonstrated

- [x] Full-stack API design  
  evidence: `app/api/main.py` provides `/auth/token`, `/returns/score`, `/returns/batch`, `/returns/{order_id}`, `/returns`, `/metrics`, `/config/thresholds`, `/config/cost`, and WebSocket route `/ws/returns`.

- [x] Data validation and API contracts  
  evidence: `app/api/schemas.py` uses Pydantic v2 field bounds, category literals, batch limits, and threshold validation.

- [x] Authentication and role-based access control  
  evidence: `app/api/auth.py` hashes raw API keys, issues JWTs, verifies JWT claims, and enforces `ops`, `admin`, and `auditor` roles.

- [x] Multi-tenant data isolation  
  evidence: `app/api/main.py` verifies `case.merchant_id == user.merchant_id` and filters list results by authenticated merchant identity.

- [x] Event-driven backend architecture  
  evidence: `app/services/kafka_client.py`, `app/services/scorer_worker.py`, and Docker service `kafka` in `docker-compose.yml`.

- [x] Async worker processing  
  evidence: `app/services/scorer_worker.py` consumes `returns.incoming`, scores cases, persists output, writes audit records, and publishes a scored event.

- [x] Machine learning for tabular risk classification  
  evidence: `app/services/ml_core.py` and `app/pipelines/train.py` train a LightGBM-based model on return-risk features.

- [x] Probability calibration  
  evidence: `CalibratedClassifierCV(..., method="isotonic")` in `app/services/ml_core.py`.

- [x] Model explainability  
  evidence: `shap.TreeExplainer` and the `EvidencePack` object in `app/services/ml_core.py`; SHAP contributions appear in `frontend/src/App.tsx`.

- [x] Cost-sensitive decision optimization  
  evidence: `app/pipelines/threshold_optimizer.py` calculates per-merchant Green/Red thresholds from cost configuration and validation scores.

- [x] Database design and migrations  
  evidence: `app/models/db_models.py`, `migrations/versions/001_initial_schema.py`, `migrations/env.py`.

- [x] Auditability and governance design  
  evidence: `AuditLog` model and `write_audit()` in `app/api/main.py`.

- [x] Redis caching and idempotency/deduplication  
  evidence: `app/services/feature_store.py` uses TTL dedup keys and response caching.

- [x] Monitoring and ML drift awareness  
  evidence: `app/monitoring/drift_monitor.py`, `monitoring/prometheus.yml`, and the `/metrics/prometheus` endpoint.

- [x] React + TypeScript frontend development  
  evidence: `frontend/src/App.tsx`, `frontend/src/api/client.ts`, and `frontend/src/main.tsx`.

- [x] Containerization and local DevOps deployment  
  evidence: `docker-compose.yml`, `Dockerfile.api`, `Dockerfile.scorer`, `Dockerfile.webhook`, and `frontend/Dockerfile`.

- [x] Practical debugging of distributed local systems  
  evidence: verified Docker logs, service health, Kafka worker output, PostgreSQL persistence query, and documented fixes in Section 7.

# 6. Numbers I measured

| Metric | Before | After | How I measured it |
|---|---:|---:|---|
| Synthetic dataset size | No dataset | 15,000 return records | Generated in training pipeline for safe demo data |
| Synthetic observed abuse rate | No baseline | Approximately 12–16%, depending on label-noise realization | Dataset generator assigns base abuse and 6% label noise |
| Held-out ROC-AUC, reference validated implementation | No model | Approximately 0.806–0.812 | `roc_auc_score` on held-out test split in sandbox reference implementation |
| Brier score, uncalibrated reference model | N/A | 0.0908 | `brier_score_loss` before isotonic calibration |
| Brier score, calibrated reference model | 0.0908 | 0.0902 | `brier_score_loss` after isotonic calibration; lower is better |
| Reference Red-only precision | No triage | Approximately 0.75–0.80 across validation runs | Red band interpreted as hard human-review alert on held-out set |
| Reference Yellow+Red recall | No triage | Approximately 0.75–0.80 across validation runs | Fraction of labeled abusive cases sent to Yellow or Red |
| Reference expected-loss reduction | Approve-all baseline | Approximately 50–55% lower modeled loss | Cost model compared approve-all with Green/Yellow/Red policy |
| Reference automation rate | Manual/everything reviewed baseline | Approximately 55–65% Green cases | Minimum-Green-share threshold optimization constraint |
| No-drift PSI sanity check | N/A | 0.0000 | Compared baseline score distribution to itself |
| Simulated fraud-pattern-shift PSI | N/A | 0.4265 | Increased suspicious-text and AI-artifact signals; exceeds 0.2 alert threshold |
| Live deployment result | No live event | `ORD900001` scored Red at 92.8/100 | Scorer log: `Scored ORD900001: band=Red score=92.8` |
| Live persistence | No durable event proof | One PostgreSQL row persisted as `M001 / scored / Red / 0.928` | Manual `psql SELECT` query inside Docker Compose Postgres service |
| Scorer replicas | Single static script | 2 worker replicas | `docker-compose.yml` scorer service configured with `replicas: 2` |

## Important interpretation of the metrics

- The metrics above are from synthetic/demo data. They are useful for showing that the evaluation workflow exists, but they are not a claim of real production fraud-detection performance.
- Accuracy is intentionally not the headline metric because fraud/abuse classes are imbalanced. Precision, recall, calibration, expected cost, automation rate, and false-positive impact matter more.
- The live score of 92.8 is not a real-world fraud verdict. It is a demonstration of the deployed model and workflow on constructed test features.

# 7. Things that broke and how I fixed them

1. **Symptom:** Docker command failed before containers started.

   **What I saw:**
   ```text
   failed to connect to the docker API at npipe:////./pipe/docker_engine
   ```

   **Cause:** Docker Desktop engine was not running, even though WSL2 itself was configured.

   **Fix:** Started Docker Desktop and verified the engine with:
   ```cmd
   docker ps
   ```

   **Lesson:** Before debugging Compose files, first verify the Docker daemon itself can respond.

2. **Symptom:** Docker Compose emitted an obsolete `version` warning.

   **What I saw:**
   ```text
   the attribute `version` is obsolete, it will be ignored
   ```

   **Cause:** Compose v2 ignores the old `version: "3.9"` property.

   **Fix:** Removed the top-level `version: "3.9"` line from `docker-compose.yml`.

   **Lesson:** Treat warnings separately from blocking errors; this warning did not stop deployment.

3. **Symptom:** React frontend image failed during `npm run build`.

   **What I saw:**
   ```text
   src/App.tsx(...): error TS2339: Property 'env' does not exist on type 'ImportMeta'.
   src/api/client.ts(...): error TS2339: Property 'env' does not exist on type 'ImportMeta'.
   ```

   **Cause:** TypeScript did not have Vite definitions for `import.meta.env`.

   **Fix:** Created `frontend/src/vite-env.d.ts` with:
   ```ts
   /// <reference types="vite/client" />
   ```
   Then rebuilt the frontend:
   ```cmd
   docker compose build frontend --progress=plain
   docker compose up -d --build frontend
   ```

   **Lesson:** Vite environment variables require Vite client types in strict TypeScript projects.

4. **Symptom:** API and both scorer workers crash-looped.

   **What I saw:**
   ```text
   ModuleNotFoundError: No module named 'sklearn.frozen'
   ```

   **Cause:** `app/services/ml_core.py` imported `FrozenEstimator` from `sklearn.frozen`, but this module did not exist in the installed scikit-learn environment.

   **Fix:** Removed:
   ```python
   from sklearn.frozen import FrozenEstimator
   ```
   Replaced:
   ```python
   self.calibrated = CalibratedClassifierCV(FrozenEstimator(self.pipeline), method="isotonic")
   self.calibrated.fit(X_calib, y_calib)
   ```
   with:
   ```python
   self.calibrated = CalibratedClassifierCV(
       self.pipeline,
       method="isotonic",
       cv="prefit",
   )
   self.calibrated.fit(X_calib, y_calib)
   ```
   Then rebuilt only affected services:
   ```cmd
   docker compose up -d --build api scorer
   ```

   **Lesson:** Pinning a package version is not enough; confirm APIs used by the code actually exist in that installed version. Shared-library import errors can crash multiple services at once.

5. **Symptom:** Bootstrap command failed with a module-not-found error.

   **What I saw:**
   ```text
   ModuleNotFoundError: No module named 'scripts'
   ```

   **Cause:** `scripts/bootstrap.py` existed on Windows, but `Dockerfile.api` copied `app/` and `migrations/` only. It did not copy `scripts/` into `/app/scripts` inside the API image.

   **Fix:** Added this to `Dockerfile.api`:
   ```dockerfile
   COPY scripts/ ./scripts/
   ```
   Then rebuilt API:
   ```cmd
   docker compose up -d --build api
   ```

   **Lesson:** A file existing on the host does not mean it exists in a container. Verify Dockerfile `COPY` instructions for every runtime module.

6. **Symptom:** Scorer workers initially reported a missing model artifact.

   **What I saw:**
   ```text
   FileNotFoundError: /app/artifacts/model_current.pkl
   ```

   **Cause:** Scorer containers started before the first model had been trained. The model artifact is created by bootstrap/training, not committed as a static file.

   **Fix:** Ran:
   ```cmd
   docker compose exec api python -m scripts.bootstrap
   docker compose restart api scorer
   ```

   **Lesson:** In a multi-service ML system, distinguish expected first-boot ordering errors from persistent runtime failures. Model-dependent workers should ideally wait/retry gracefully in a later improvement.

7. **Symptom:** Old errors appeared even after services started successfully.

   **What I saw:** `docker compose logs --tail=20 scorer` still included prior `FileNotFoundError` entries.

   **Cause:** Docker logs are historical. The `--tail` output mixed old failed startup attempts with newer successful worker startup messages.

   **Fix:** Used recent logs instead:
   ```cmd
   docker compose logs --since=2m scorer
   ```
   Successful state included:
   ```text
   Loading model artifact from /app/artifacts/model_current.pkl
   Scorer worker started, consuming from Kafka topic: returns.incoming
   Successfully synced group sentinel-scorer
   ```

   **Lesson:** Use `docker compose ps` for current process state and `--since` for fresh logs; do not diagnose solely from historical tail output.

8. **Symptom:** Kafka emitted topic-not-found/auto-create initialization messages.

   **What I saw:**
   ```text
   Topic returns.incoming is not available during auto-create initialization
   ```

   **Cause:** Kafka broker and consumers were starting concurrently; topic metadata was not ready during initial subscription.

   **Fix:** Allowed Kafka initialization/consumer-group rebalance to complete. Workers eventually joined successfully and received partition assignments.

   **Lesson:** Kafka startup timing is normal in local Compose environments. Production should provision topics explicitly and use readiness checks/retry logic.

9. **Symptom:** Swagger returned `403 Not authenticated` for `POST /returns/score`.

   **What I saw:**
   ```json
   { "detail": "Not authenticated" }
   ```

   **Cause:** Protected FastAPI endpoint was called without a valid `Authorization` header.

   **Fix:** Used `POST /auth/token` with raw ops/admin API key, copied the returned JWT, clicked Swagger **Authorize**, and authenticated the docs session.

   **Lesson:** API key and JWT are different credentials. The raw API key exchanges for a short-lived JWT; protected endpoints require the JWT.

10. **Symptom:** Swagger said invalid token after a token was pasted.

    **Cause:** Swagger's HTTP Bearer authorization UI prepended the `Bearer` scheme automatically. Pasting `Bearer <token>` manually could create `Authorization: Bearer Bearer <token>`.

    **Fix:** Logged out in Swagger, obtained a fresh JWT, and pasted only the raw long JWT string (`eyJ...`) into Swagger's authorization input.

    **Lesson:** Read generated curl/header output to confirm how the API documentation client formats authorization.

11. **Symptom:** `GET /returns` returned an empty list when filtering by `red`.

    **What I saw:**
    ```json
    { "items": [], "total": 0, "page": 1, "page_size": 50 }
    ```
    Yet PostgreSQL contained:
    ```text
    ORD900001 | M001 | scored | Red | 0.928
    ```

    **Cause:** Stored band values use title case (`Red`, `Yellow`, `Green`) and PostgreSQL string comparison is case-sensitive. Query parameter `band=red` did not match `Red`.

    **Fix:** Used exact values `Red`, `Yellow`, or `Green`, or left the band field empty to fetch all cases.

    **Lesson:** Normalize user filters at API boundaries. Future fix: validate/normalize band inputs with `band.strip().capitalize()` or use a case-insensitive DB filter.

12. **Symptom:** Case did not appear on dashboard after refreshing a browser page.

    **Cause:** The React app stores a JWT in browser local storage as `sentinel_token`. A refresh preserves it. A stale/malformed/expired token can prevent the dashboard from fetching data, while the UI did not yet automatically clear it and return to the login page.

    **Workaround:** Open an Incognito/private browser window, visit `http://localhost:3000`, and log in again using the raw ops/admin API key.

    **Permanent fix planned:** Add an Axios response interceptor in `frontend/src/api/client.ts`:
    ```ts
    apiClient.interceptors.response.use(
      (response) => response,
      (error) => {
        if (error.response?.status === 401 || error.response?.status === 403) {
          clearToken();
          window.location.reload();
        }
        return Promise.reject(error);
      }
    );
    ```
    Then rebuild frontend:
    ```cmd
    docker compose up -d --build frontend
    ```

    **Lesson:** Persisting a token is not enough. Frontends must explicitly handle expired/invalid sessions and show useful recovery behavior.

13. **Symptom:** Confusion about using `http://api:8000` versus `http://localhost:8000` for frontend API calls.

    **Cause:** Docker internal service DNS (`api`) works from containers, but browser JavaScript executes on the Windows host and cannot generally resolve the internal Docker hostname `api`.

    **Fix:** Browser-facing Vite configuration should use:
    ```yaml
    VITE_API_BASE_URL: http://localhost:8000
    VITE_WS_URL: ws://localhost:8000/ws/returns
    ```

    **Lesson:** Distinguish container-to-container network names from host-browser URLs.

# 8. What I would do differently at 100x scale

- **Replace single-broker local Kafka and ad hoc worker scaling with managed, partitioned infrastructure.** Use a managed Kafka service or equivalent durable streaming platform; partition by merchant/account key; configure consumer lag alerts, dead-letter topics, replay tooling, idempotent producers, schema registry, and exactly-once/idempotency safeguards. Separate high-priority synchronous review events from ordinary background events.

- **Build a real online/offline feature platform and data-quality layer.** Use a feature store with versioned feature definitions, point-in-time-correct offline joins, online Redis/KeyDB serving, feature freshness SLAs, lineage, null-rate monitoring, and backfills. Current prototype Redis velocity features are a lightweight pattern, not a full feature governance system.

- **Strengthen security, privacy, governance, and model operations.** Move secrets to a cloud secrets manager; use HTTPS/mTLS, KMS-backed field encryption, short-lived key rotation, SSO/OIDC, fine-grained data access, PII tokenization, retention/deletion policies, immutable external audit storage, fairness monitoring, delayed-label evaluation, shadow/canary deployment, automated rollback, and an explicit human-review policy with reviewer QA.

# 9. Interview answers I have rehearsed

## Q: What problem does Return-Abuse Sentinel solve?

**A:**

Return-Abuse Sentinel helps e-commerce merchants manage post-purchase losses caused by return and refund abuse. Payment fraud systems can stop suspicious payment attempts, but a merchant can still lose money after delivery through serial returns, refund-to-keep abuse, fake damage claims, item swaps, empty-box returns, or coordinated customer accounts.

The project scores a return request using behavioral, claim, logistics, and network-risk features. Instead of simply blocking customers, it routes cases into Green, Yellow, and Red bands. Green is low risk and supports a normal automated flow. Yellow means the merchant should use lower-cost verification, like warehouse inspection. Red means high risk, but the system still does not auto-deny—it generates an evidence pack and sends the case to a human reviewer.

The important design choice is that we optimize for expected merchant loss, including false-positive customer friction and review cost, not just model accuracy. That makes it both safer and more useful operationally.

## Q: Why did you choose Kafka instead of scoring every request synchronously?

**A:**

The ML model and especially per-case SHAP explanation add work that should not delay every return request. If the API waits for scoring for all traffic, latency rises and one slow dependency can degrade the merchant experience.

So the platform uses a hybrid strategy. A transparent pre-screen identifies certain higher-risk cases that may need immediate scoring. Most requests are saved as pending and published to Kafka. Independent scorer workers consume those events, perform model inference and explanation, then persist the result in PostgreSQL.

This decouples API availability from scoring capacity. If traffic increases, we can scale scorer replicas without changing the API. It also gives us retries and durable event processing. In local deployment, I verified the path by submitting `ORD900001`, receiving an async pending response, and then seeing the worker log a Red score of 92.8 and the persisted Postgres record.

## Q: How do you prevent false positives from harming genuine customers?

**A:**

First, I do not use a binary block/allow model. I use Green, Yellow, and Red bands. Yellow is specifically there for uncertainty: a customer can receive a low-cost inspection rather than an automatic refusal. Red is human review only, not automatic denial.

Second, threshold selection is cost-aware. The optimizer includes review cost, inspection cost, customer-friction cost, and loss from missed abuse. It also enforces a minimum automation rate so the system cannot cheat by sending every case to manual review.

Third, the model has explanation evidence through SHAP, so reviewers can see which signals influenced a decision instead of blindly trusting a score. Finally, reviewer outcomes become labels for monitoring precision/recall and retraining. That creates a feedback loop to catch when the system is over-flagging legitimate returns.

## Q: Why calibrate the model instead of using raw LightGBM probabilities?

**A:**

The raw score from a classifier is useful for ranking risk, but it is not always a reliable probability. A raw 0.8 does not necessarily mean that 80% of similar cases are abusive. That matters because thresholds in this project are chosen using costs in ₹.

I use isotonic calibration on a separate calibration split. It learns a mapping between model outputs and observed outcome rates. In the reference evaluation, calibration improved Brier score from about 0.0908 to 0.0902 while preserving roughly the same AUC, around 0.81. That means the ranking stayed useful while the scores became slightly more trustworthy for cost-based routing.

## Q: How do you explain a Red decision to a merchant reviewer?

**A:**

Each scored case gets an evidence pack. It contains the final risk score, its Green/Yellow/Red band, the recommended human action, and a SHAP contribution list showing which features pushed risk up or down.

For example, a case may be Red because the return rate is unusually high, there are prior refund-to-keep incidents, bracketing behavior is present, claim text looks suspicious, an image artifact signal is high, and parcel weight differs from expected. The reviewer sees these as plain-language reasons plus a contribution chart.

I deliberately frame the evidence as decision support, not proof of fraud. The system tells the human what deserves attention; it does not make the final irreversible decision.

## Q: What happens when fraud patterns change?

**A:**

The project includes a PSI-based drift monitor. It compares current score distributions with a baseline distribution. In the reference test, a stable comparison produced PSI 0.0, while a simulated change in suspicious-text and AI-image signals produced PSI 0.4265, which exceeds the 0.2 alert threshold.

A drift alert does not automatically retrain or change thresholds. It tells the risk team to investigate whether data quality broke, customer behavior changed, or attackers adapted. Once confirmed outcomes are available, the retraining pipeline trains a challenger model and only promotes it if it improves against the champion on AUC without materially worsening calibration.

## Q: What was the hardest deployment/debugging issue?

**A:**

The most instructive issue was a shared dependency error: both the API and scorer workers crash-looped because `ml_core.py` imported `FrozenEstimator` from a scikit-learn module that was unavailable in the deployed environment. Because both services depended on that module, it looked like multiple failures, but it was actually one root cause.

I replaced that dependency with a compatible `CalibratedClassifierCV` prefit calibration flow and rebuilt only the affected API/scorer services. That taught me to read the earliest shared traceback, identify common dependencies, and avoid treating every repeated container restart as an independent bug.

# 10. Honest limitations

- The training data is synthetic. It is realistic enough to demonstrate architecture and evaluation flow, but it is not actual merchant outcome data. Therefore, the measured metrics are illustrative and must not be presented as real merchant fraud-loss reduction.

- `claim_text_susp` and `image_ai_artifact_score` are currently numeric input features supplied to the model. The prototype does not yet contain a real NLP model for claim-text analysis or a computer-vision model that inspects uploaded photos.

- `shared_identifier_flag` is represented as a prepared feature. The prototype does not yet implement an actual device/address/payment graph engine for detecting abuse rings.

- The default local Kafka setup has one broker and simple auto-created topics. It is useful for development but is not highly available or production hardened.

- The WebSocket endpoint exists, but the complete `returns.scored` Kafka-to-WebSocket bridge is not fully wired as a robust production notification pipeline. The frontend also polls via TanStack Query.

- The webhook dispatcher is scaffolded, but merchant webhook URLs and signed webhook verification are not fully implemented in the database schema.

- The API has JWT/RBAC and API-key hashing, but local deployment defaults are not enough for internet exposure. Public deployment needs HTTPS, secret rotation, strict CORS, rate limiting, field-level PII encryption, network controls, and external identity management.

- Dashboard token handling needs improvement. A stale JWT can cause empty queues after refresh until the Axios 401/403 auto-logout interceptor is added and frontend rebuilt.

- The project does not automatically deny/approve money movement decisions. That is intentional due to the defense-only requirement, but it means the merchant needs an operations workflow for Yellow and Red cases.

- Model fairness, disparate impact, customer appeals, reviewer quality assurance, and privacy/legal policy evaluation are not completed. These would be mandatory before using the system with real customers.

# 11. How to run it

## Prerequisites

- Docker Desktop running on Windows
- WSL2 backend enabled for Docker Desktop
- At least roughly 6 GB free RAM available for Docker services
- Project directory:

```text
C:\Projects\return-abuse-sentinel
```

## First-time setup

```bash
# Windows Command Prompt or PowerShell
cd C:\Projects\return-abuse-sentinel

# If files are still flat downloads, organize them once
python setup_structure.py

# Create local environment file
copy .env.example .env

# Generate a JWT secret; paste the result into JWT_SECRET_KEY in .env
python -c "import secrets; print(secrets.token_hex(32))"

# Build and start the local multi-service stack
docker compose up -d --build

# Confirm current container state
docker compose ps

# Bootstrap schema, demo merchant, first model, thresholds, and API keys
docker compose exec api python -m scripts.bootstrap

# Restart services so API/scorers load the new model artifact
docker compose restart api scorer

# Verify model/API health
curl http://localhost:8000/health
```

Expected health output:

```json
{"status":"ok","model_loaded":true}
```

## Open the application

```text
Dashboard:    http://localhost:3000
Swagger docs: http://localhost:8000/docs
Prometheus:   http://localhost:9090
Grafana:      http://localhost:3001
```

Log into the React dashboard using the **raw ops API key** generated by `scripts.bootstrap`. Do not paste a JWT into the dashboard login screen; the dashboard exchanges the raw API key for a JWT itself.

## Score a test return using Swagger

1. Open `http://localhost:8000/docs`.
2. Run `POST /auth/token` with raw ops API key.
3. Copy only the returned `access_token` value.
4. Click Swagger **Authorize**.
5. Paste the raw JWT only if Swagger supplies the Bearer prefix automatically.
6. Run `POST /returns/score` with a new `order_id` each time.

Example high-risk request:

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

Typical immediate async response:

```json
{
  "order_id": "ORD900001",
  "mode": "async",
  "status": "pending"
}
```

Wait 5–15 seconds, then inspect:

```bash
docker compose logs --since=5m scorer
```

Or retrieve the case at Swagger endpoint:

```text
GET /returns/{order_id}
```

## Required environment variables

Copy `.env.example` to `.env`. At minimum configure:

| Variable | Purpose | Local default / guidance |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection URL | `postgresql://sentinel:sentinel_pw@postgres:5432/sentinel_db` inside Compose |
| `REDIS_URL` | Redis feature/dedup connection | `redis://redis:6379/0` inside Compose |
| `KAFKA_BOOTSTRAP_SERVERS` | Kafka broker address | `kafka:9092` inside Compose |
| `KAFKA_TOPIC_RETURNS` | Incoming return-event topic | `returns.incoming` |
| `KAFKA_TOPIC_SCORED` | Scored-event topic | `returns.scored` |
| `JWT_SECRET_KEY` | JWT signing secret | Must be replaced with a randomly generated value |
| `JWT_ALGORITHM` | JWT algorithm | `HS256` for demo |
| `JWT_EXPIRE_SECONDS` | JWT lifetime | `3600` seconds by default |
| `MODEL_ARTIFACT_PATH` | Path to trained model | `/app/artifacts/model_current.pkl` inside containers |
| `MODEL_MIN_GREEN_SHARE` | Minimum automation requirement for threshold optimization | `0.55` |
| `DEFAULT_COST_MANUAL_REVIEW` | Default ₹ review cost | `150` |
| `DEFAULT_COST_INSPECTION` | Default ₹ inspection cost | `40` |
| `DEFAULT_COST_FRICTION` | Default ₹ customer friction cost | `5` |
| `DEFAULT_FRACTION_LOST_ON_MISS` | Loss fraction for missed abusive return | `0.6` |
| `PSI_ALERT_THRESHOLD` | Drift alert threshold | `0.2` |
| `APP_ENV` | Environment name | `development` locally |

## Useful operating commands

```bash
# Current container status
docker compose ps

# Recent scorer events only
docker compose logs --since=5m scorer

# API/scorer/frontend errors
docker compose logs --tail=100 api scorer frontend

# Stop platform, preserve database volume
docker compose down

# Stop platform and wipe all local Docker volumes/data
docker compose down -v

# Rebuild one changed service
docker compose up -d --build frontend
docker compose up -d --build api scorer

# Inspect persisted returns directly in Postgres
docker compose exec postgres psql -U sentinel -d sentinel_db -c "SELECT order_id, merchant_id, status, band, risk_score, outcome_label FROM returns ORDER BY created_at DESC;"
```

# 12. Credits

## Tools and frameworks used

- FastAPI — API and automatic OpenAPI/Swagger documentation
- Pydantic — typed input validation
- SQLAlchemy and Alembic — database models and migrations
- PostgreSQL — persistent relational storage
- Redis — low-latency deduplication and feature-cache pattern
- Apache Kafka / Confluent Platform image — event-driven queue
- LightGBM — gradient-boosted tabular ML model
- scikit-learn — calibration, train/test utilities, evaluation
- SHAP — local model explanation framework
- React, TypeScript, Vite — frontend platform
- TanStack Query, Axios, Recharts — frontend data flow and visualization
- Docker Desktop and Docker Compose — local container orchestration
- Prometheus and Grafana — observability stack
- ReportLab — evidence-pack PDF export scaffold

## Sources and learning references

- Docker Compose documentation for `up`, `ps`, `logs`, and `exec` workflows.
- FastAPI security documentation for HTTP Bearer token patterns and Swagger authorization behavior.
- Standard ML practices for held-out evaluation, probability calibration, class imbalance awareness, and monitoring data/model drift.
- SHAP documentation/concepts for per-prediction feature attribution.

