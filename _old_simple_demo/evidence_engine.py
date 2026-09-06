"""
Return-Abuse Sentinel — Evidence Pack Engine
================================================
Turns a raw risk score into a plain-English evidence pack that a merchant
ops / fraud-review agent can act on in under a minute.

DEFENSE-ONLY GUARANTEE
-----------------------
This module NEVER:
  - auto-refunds or auto-denies a return
  - contacts / messages the customer
  - blocks an account or payment instrument
  - takes any action beyond scoring, routing, and explaining

It ONLY produces a risk score, a routing band (Green/Yellow/Red), and a
human-readable evidence pack for a person to review. All Red-band cases
are required to pass through a human review queue before any action is
taken on the account.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any
import joblib
import pandas as pd

FEATURE_COLS = [
    'account_age_days', 'past_orders', 'return_rate_hist', 'refund_to_keep_count',
    'bracketing_score', 'claim_text_susp', 'image_ai_artifact_score', 'weight_mismatch_kg',
    'shared_identifier_flag', 'carrier_scan_gap', 'days_to_claim', 'order_value', 'category'
]

ACTION_MAP = {
    'Green': "Auto-approve. Instant refund on carrier scan confirmation. No human touch needed.",
    'Yellow': "Hold for low-cost warehouse/photo inspection before refunding. Offer exchange or "
              "store credit as a faster alternative for the customer.",
    'Red': "Do NOT auto-refund or auto-deny. Route to human fraud-review queue with this "
           "evidence pack attached. A human reviewer makes the final call."
}


@dataclass
class EvidencePack:
    order_id: str
    risk_score: float
    band: str
    order_value: float
    category: str
    reasons: List[str] = field(default_factory=list)
    recommended_action: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "order_id": self.order_id,
            "risk_score": self.risk_score,
            "band": self.band,
            "order_value": self.order_value,
            "category": self.category,
            "reasons": self.reasons,
            "recommended_action": self.recommended_action,
        }

    def to_markdown(self) -> str:
        lines = [
            f"### Evidence Pack — {self.order_id}",
            f"**Risk score:** {self.risk_score}/100  **Band:** {self.band}",
            f"**Order value:** ₹{self.order_value:,.2f}  **Category:** {self.category}",
            "",
            "**Why this was flagged:**",
        ]
        lines += [f"- {r}" for r in self.reasons]
        lines += ["", f"**Recommended action:** {self.recommended_action}"]
        return "\n".join(lines)


def _reasons_for(row: pd.Series) -> List[str]:
    reasons = []

    if row['return_rate_hist'] > 0.5:
        reasons.append(
            f"Customer's historical return rate is {row['return_rate_hist']*100:.0f}%, "
            f"well above the ~20% category norm."
        )
    if row['refund_to_keep_count'] > 1:
        reasons.append(
            f"{int(row['refund_to_keep_count'])} prior refund-but-keep incidents on this account."
        )
    if row['bracketing_score'] > 0.55:
        reasons.append(
            f"Order pattern shows bracketing behavior (score {row['bracketing_score']:.2f}) — "
            f"multiple sizes/variants ordered together, most returned."
        )
    if row['claim_text_susp'] > 0.55:
        reasons.append(
            f"Return claim text flagged as suspicious (score {row['claim_text_susp']:.2f}) — "
            f"inconsistent or templated damage description."
        )
    if row['image_ai_artifact_score'] > 0.55:
        reasons.append(
            f"Uploaded damage photo shows AI-generation artifacts "
            f"(score {row['image_ai_artifact_score']:.2f})."
        )
    if row['weight_mismatch_kg'] > 0.2:
        reasons.append(
            f"Returned parcel weight differs from expected by {row['weight_mismatch_kg']:.2f} kg — "
            f"possible empty-box or item-swap claim."
        )
    if row['shared_identifier_flag'] == 1:
        reasons.append(
            "Account shares a device/address/payment fingerprint with other flagged accounts "
            "— possible coordinated abuse ring."
        )
    if row['carrier_scan_gap'] == 1:
        reasons.append(
            "Gap detected in carrier scan trail for the returned parcel — chain-of-custody incomplete."
        )
    if row['days_to_claim'] < 1.5:
        reasons.append(
            f"Claim filed unusually fast ({row['days_to_claim']:.1f} days) after delivery."
        )

    if not reasons:
        reasons.append(
            "No single dominant signal; risk is driven by a combination of weaker signals "
            "near the model's decision boundary."
        )
    return reasons


class ReturnAbuseSentinel:
    """Loads the trained model + calibrated thresholds and scores new cases."""

    def __init__(self, model_path: str = 'return_abuse_model.pkl'):
        artifact = joblib.load(model_path)
        self.model = artifact['model']
        self.low_t = artifact['low_t']
        self.high_t = artifact['high_t']

    def _band(self, prob: float) -> str:
        if prob < self.low_t:
            return 'Green'
        elif prob < self.high_t:
            return 'Yellow'
        return 'Red'

    def score_case(self, case: Dict[str, Any]) -> EvidencePack:
        """case: dict with keys matching FEATURE_COLS + 'order_id'"""
        row = pd.Series(case)
        X = pd.DataFrame([{k: case[k] for k in FEATURE_COLS}])
        prob = float(self.model.predict_proba(X)[0, 1])
        band = self._band(prob)

        pack = EvidencePack(
            order_id=case.get('order_id', 'N/A'),
            risk_score=round(prob * 100, 1),
            band=band,
            order_value=case['order_value'],
            category=case['category'],
            reasons=_reasons_for(row),
            recommended_action=ACTION_MAP[band],
        )
        return pack

    def score_batch(self, df: pd.DataFrame) -> List[EvidencePack]:
        X = df[FEATURE_COLS]
        probs = self.model.predict_proba(X)[:, 1]
        packs = []
        for i, (_, row) in enumerate(df.iterrows()):
            prob = float(probs[i])
            band = self._band(prob)
            packs.append(EvidencePack(
                order_id=row.get('order_id', f'ROW{i}'),
                risk_score=round(prob * 100, 1),
                band=band,
                order_value=row['order_value'],
                category=row['category'],
                reasons=_reasons_for(row),
                recommended_action=ACTION_MAP[band],
            ))
        return packs


if __name__ == '__main__':
    # Quick smoke test using a few rows from the generated dataset
    df = pd.read_csv('return_abuse_dataset.csv')
    sentinel = ReturnAbuseSentinel('return_abuse_model.pkl')

    sample = df.sample(5, random_state=1)
    for pack in sentinel.score_batch(sample):
        print(pack.to_markdown())
        print()
