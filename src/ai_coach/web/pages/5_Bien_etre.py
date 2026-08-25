"""Bien-être : HRV, sommeil, readiness (données déjà fetchées par wellness.py,
utilisées par le coach mais jamais affichées jusqu'ici)."""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from ai_coach.wellness import build_wellness_summary, fetch_wellness, load_cached_wellness

st.set_page_config(page_title="AI Coach — Bien-être", page_icon="🛌", layout="wide")
st.title("🛌 Bien-être")

col_days, col_btn = st.columns([3, 1])
with col_days:
    days = st.slider("Jours à récupérer lors du rafraîchissement", min_value=7, max_value=90, value=30)
with col_btn:
    st.write("")
    if st.button("🔄 Rafraîchir", type="primary"):
        with st.spinner("Fetch wellness..."):
            fetch_wellness(days=days)
        st.rerun()

wellness_data = load_cached_wellness()
if not wellness_data:
    st.info("Aucune donnée en cache. Clique sur Rafraîchir pour fetcher depuis Intervals.icu.")
    st.stop()

summary = build_wellness_summary(wellness_data)
if not summary:
    st.warning("Données présentes mais aucun jour exploitable (HRV/RHR/sommeil/readiness tous vides).")
    st.stop()

c1, c2, c3, c4 = st.columns(4)
if "hrv_latest" in summary:
    c1.metric("HRV", f"{summary['hrv_latest']} ms", summary.get("hrv_trend"))
if "rhr_latest" in summary:
    c2.metric("FC repos", f"{summary['rhr_latest']} bpm", summary.get("rhr_trend"))
if "sleep_hours_avg" in summary:
    c3.metric("Sommeil (moy. 7j)", f"{summary['sleep_hours_avg']}h")
if "readiness_latest" in summary:
    c4.metric("Readiness", f"{summary['readiness_latest']}%")

alerts = summary.get("alerts", [])
for alert in alerts:
    st.warning(f"🚨 {alert}")

st.subheader("Tendance")
dates = [d["id"] for d in wellness_data if d.get("id")]
hrv = [d.get("hrv") for d in wellness_data]
rhr = [d.get("restingHR") for d in wellness_data]
readiness = [d.get("readiness") for d in wellness_data]

fig = go.Figure()
if any(v is not None for v in hrv):
    fig.add_trace(go.Scatter(x=dates, y=hrv, name="HRV (ms)", line=dict(color="#1f77b4")))
if any(v is not None for v in readiness):
    fig.add_trace(go.Scatter(x=dates, y=readiness, name="Readiness (%)", line=dict(color="#2ca02c"), yaxis="y2"))
fig.update_layout(
    height=420,
    template="plotly_white",
    hovermode="x unified",
    yaxis=dict(title="HRV (ms)"),
    yaxis2=dict(title="Readiness (%)", overlaying="y", side="right"),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
)
st.plotly_chart(fig, use_container_width=True)

if any(v is not None for v in rhr):
    fig_rhr = go.Figure()
    fig_rhr.add_trace(go.Scatter(x=dates, y=rhr, name="FC repos (bpm)", line=dict(color="#d62728")))
    fig_rhr.update_layout(height=300, template="plotly_white", hovermode="x unified")
    st.plotly_chart(fig_rhr, use_container_width=True)

st.subheader("Détail 7 derniers jours")
daily = summary.get("daily", [])
if daily:
    st.dataframe(
        [
            {
                "Date": d["date"],
                "Jour": d["weekday"],
                "HRV": d.get("hrv"),
                "FC repos": d.get("rhr"),
                "Sommeil (h)": d.get("sleep_hours"),
                "Score sommeil": d.get("sleep_score"),
                "Readiness (%)": d.get("readiness"),
            }
            for d in daily
        ],
        use_container_width=True,
        hide_index=True,
    )
