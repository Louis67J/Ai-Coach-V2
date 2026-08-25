"""Plan d'entraînement en cours, génération, comparaison plan vs réalisé."""
from __future__ import annotations

import streamlit as st

from ai_coach.coach import generate_plan
from ai_coach.intervals import load_enriched_sessions
from ai_coach.plan_tracker import build_plan_vs_actual, load_recent_plans
from ai_coach.web._shared import get_report_or_stop

st.set_page_config(page_title="AI Coach — Plan", page_icon="📋", layout="wide")
st.title("📋 Plan d'entraînement")

report = get_report_or_stop()

recent_plans = load_recent_plans(limit=1)
latest_plan = recent_plans[0] if recent_plans else None

st.subheader("Dernier plan généré")
if latest_plan:
    st.caption(
        f"Généré le {latest_plan['timestamp'][:10]} — "
        f"{latest_plan['days']} jours à partir du {latest_plan['start_date']}"
    )
    st.markdown(latest_plan["plan_text"])

    st.subheader("Plan vs réalisé")
    sessions = load_enriched_sessions()
    comparison = build_plan_vs_actual(latest_plan, sessions)
    st.text(comparison)
else:
    st.info("Aucun plan généré pour l'instant.")

st.divider()
st.subheader("Générer un nouveau plan")
horizon = st.slider("Horizon (jours)", min_value=3, max_value=21, value=7)
if st.button("🧠 Générer le plan", type="primary"):
    with st.spinner("Le coach réfléchit..."):
        try:
            plan_text = generate_plan(report, horizon_days=horizon, source="web")
        except Exception as e:
            st.error(f"Erreur : {e}")
        else:
            st.success("Plan généré et enregistré. Recharge la page pour le voir en haut.")
            st.markdown(plan_text)
