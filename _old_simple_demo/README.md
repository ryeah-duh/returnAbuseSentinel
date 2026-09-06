# Return-Abuse Sentinel

A defense-only AI Risk Manager for **return/refund abuse** — built for the Razorpay AI Risk Manager buildathon track.

Scores every return request, routes it into a Green/Yellow/Red lane, and generates a plain-English evidence pack for every flagged case. It never auto-refunds, auto-denies, contacts a customer, or takes any irreversible action — it only scores, routes, and explains, leaving the final call to a human for anything above Green.

## Why this problem

Returns and chargeback abuse quietly eat merchant margin: serial "wardrobers," empty-box claims, AI-faked damage photos, bracketing, and refund-to-keep patterns. Most fraud systems focus on payment fraud and miss this class of loss entirely.

## Architecture

```
return_abuse_dataset.csv   -> historical RMA-style training data (synthetic, realistic overlap + 6% label noise)
train_model.py             -> trains GradientBoostingClassifier, calibrates Green/Yellow/Red thresholds
                               via an explicit cost model (not an arbitrary 0.5 cutoff)
return_abuse_model.pkl     -> saved model + calibrated thresholds
metrics_report.json        -> honest precision/recall + false-positive cost + business impact
evidence_engine.py         -> ReturnAbuseSentinel class: scores a case, generates plain-English
                               evidence pack + recommended action
dashboard.py               -> Streamlit demo UI: live Green/Yellow/Red queue, click into any case
```

## How the risk bands work

| Band | Meaning | Action |
|---|---|---|
| 🟢 Green | Low risk | Auto-approve, instant refund on carrier scan |
| 🟡 Yellow | Uncertain | Hold for cheap warehouse/photo inspection before refund |
| 🔴 Red | High risk | Route to human fraud-review queue with evidence pack — no auto-refund or auto-deny |

Thresholds are **not** picked arbitrarily. `train_model.py` grid-searches the Green/Yellow and Yellow/Red cutoffs to minimize total expected business loss, using:

- Cost of a false positive (wrongly holding a genuine return): ₹150 human review / ₹40 cheap inspection
- Cost of a false negative (abuse slipping through as approved): 60% of order value
- A minimum automation-rate constraint (Green must cover ≥55% of volume) so the system stays operationally useful instead of just routing everything to manual review

## Measured results (held-out test set, one run)

- **Red-band precision:** ~0.75-0.80 — when the system fully commits, it's right about 3 in 4 times
- **Yellow+Red recall:** ~0.75-0.80 — catches roughly 4 in 5 abuse cases across both flagged lanes
- **Loss reduction:** ~50-55% vs. an approve-everything baseline, on the same held-out set
- **Automation rate:** ~55-65% of returns auto-approved with zero human touch

Exact numbers are in `metrics_report.json` after each training run (there's natural run-to-run variance from the threshold grid search and synthetic data seed).

## Defense-only guarantees

- No auto-refund reversal, no auto-deny, no customer messaging, no account blocking.
- Red-band cases are **required** to pass through a human reviewer before any action.
- The system's only outputs are: a risk score, a routing band, and a human-readable evidence pack.

## Running it

```bash
pip install scikit-learn pandas numpy joblib streamlit
python train_model.py        # generates data, trains model, calibrates thresholds, writes metrics_report.json
python evidence_engine.py    # smoke test: prints 5 sample evidence packs
streamlit run dashboard.py   # judge-facing live demo
```

## What to say in the pitch

1. Open with the metrics strip: loss prevented, automation rate, Red-band precision, overall recall.
2. Click into 2-3 Red cases and read the evidence pack aloud — this is the differentiator over a bare risk score.
3. Show the cost model explicitly: "we didn't pick 0.5 as a threshold, we minimized ₹ expected loss."
4. Name one failure mode honestly (e.g., a coordinated ring with no shared identifiers) and how you'd extend the system to catch it — judges reward teams who know their model's limits.
5. Reiterate defense-only: the system recommends, a human decides on anything above Green.

## Extending this

- Swap the synthetic dataset for real RMA + chargeback-linked return history.
- Add a graph-based network signal (shared device/address/payment clusters) for the abuse-ring case.
- Add an LLM pass over claim text and photo metadata for the Yellow/Red forensics step.
- Replace the single train/test split with time-based validation (train on older returns, test on newer) to catch concept drift.
