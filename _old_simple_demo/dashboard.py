"""
Return-Abuse Sentinel — Demo Dashboard (Streamlit)
======================================================
Judge-facing demo UI. Shows the Green/Yellow/Red lanes live, lets you
click into any flagged case to see its evidence pack, and displays the
honest metrics (precision/recall/false-positive cost) up front.

Run:
    streamlit run dashboard.py

Requires: return_abuse_model.pkl, return_abuse_dataset.csv,
          metrics_report.json  (produced by train_model.py)
"""

import json
import pandas as pd
import streamlit as st
from evidence_engine import ReturnAbuseSentinel

st.set_page_config(page_title="Return-Abuse Sentinel", layout="wide")

@st.cache_resource
def load_sentinel():
    return ReturnAbuseSentinel('return_abuse_model.pkl')

@st.cache_data
def load_data():
    return pd.read_csv('return_abuse_dataset.csv')

@st.cache_data
def load_metrics():
    with open('metrics_report.json') as f:
        return json.load(f)

sentinel = load_sentinel()
df = load_data()
metrics = load_metrics()

st.title("🛡️ Return-Abuse Sentinel")
st.caption("Defense-only risk router for return/refund abuse — scores, routes, and explains. "
           "Never auto-refunds, auto-denies, or contacts customers.")

# ---------------------------------------------------------------------------
# Top metrics strip
# ---------------------------------------------------------------------------
biz = metrics['business_impact']
c1, c2, c3, c4 = st.columns(4)
c1.metric("Loss prevented (test set)", f"₹{biz['loss_prevented_inr']:,.0f}",
          f"{biz['loss_reduction_pct']}% vs approve-all")
c2.metric("Automation rate (Green)", f"{biz['automation_rate_green_pct']}%")
c3.metric("Red-band precision", f"{metrics['red_only_hard_flag']['precision']*100:.1f}%")
c4.metric("Overall recall (Yellow+Red)", f"{metrics['yellow_plus_red_any_flag']['recall']*100:.1f}%")

with st.expander("📊 Full honest metrics report (held-out test set)"):
    st.json(metrics)

st.divider()

# ---------------------------------------------------------------------------
# Live scoring lanes
# ---------------------------------------------------------------------------
st.subheader("Live Return Queue")

sample = df.sample(60, random_state=42)
packs = sentinel.score_batch(sample)
pack_df = pd.DataFrame([p.to_dict() for p in packs])

tab_green, tab_yellow, tab_red = st.tabs([
    f"🟢 Green ({ (pack_df.band=='Green').sum() })",
    f"🟡 Yellow ({ (pack_df.band=='Yellow').sum() })",
    f"🔴 Red ({ (pack_df.band=='Red').sum() })",
])

def render_lane(tab, band_name):
    with tab:
        lane_df = pack_df[pack_df.band == band_name].sort_values('risk_score', ascending=False)
        st.dataframe(
            lane_df[['order_id', 'risk_score', 'order_value', 'category', 'recommended_action']],
            use_container_width=True, hide_index=True
        )
        if len(lane_df) > 0:
            chosen = st.selectbox(f"Inspect a {band_name} case", lane_df['order_id'], key=band_name)
            row = lane_df[lane_df.order_id == chosen].iloc[0]
            st.markdown(f"**Risk score:** {row.risk_score}/100")
            st.markdown("**Why flagged:**")
            for r in row['reasons']:
                st.markdown(f"- {r}")
            st.info(row['recommended_action'])

render_lane(tab_green, 'Green')
render_lane(tab_yellow, 'Yellow')
render_lane(tab_red, 'Red')

st.divider()
st.caption("Built for the Razorpay AI Risk Manager buildathon track — strictly defense-only. "
           "All Red-band routing requires human sign-off; no autonomous refund reversal or "
           "account action is ever taken by this system.")
