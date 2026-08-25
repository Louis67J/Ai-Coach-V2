"""Plan d'entraînement en cours, adhérence mesurée, génération du suivant."""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from ai_coach.coach import generate_plan
from ai_coach.intervals import load_cached_activities, load_enriched_sessions
from ai_coach.plan_tracker import (
    build_plan_vs_actual,
    compute_plan_adherence,
    load_recent_plans,
)
from ai_coach.web._shared import get_report_or_stop, invalidate_report_cache

st.set_page_config(page_title="AI Coach — Plan", page_icon="📋", layout="wide")
st.title("📋 Plan d'entraînement")

report = get_report_or_stop()

recent_plans = load_recent_plans(limit=1)
latest_plan = recent_plans[0] if recent_plans else None

if not latest_plan:
    st.info("Aucun plan généré pour l'instant.")
else:
    st.subheader("Dernier plan généré")
    st.caption(
        f"Généré le {latest_plan['timestamp'][:10]} — "
        f"{latest_plan['days']} jours à partir du {latest_plan['start_date']}"
    )

    adherence = compute_plan_adherence(latest_plan, load_cached_activities())

    if adherence.get("status") == "no_structured_plan":
        st.caption(
            "Ce plan date d'avant le suivi structuré : l'adhérence ne peut pas être "
            "mesurée automatiquement. Le prochain plan généré le sera."
        )
    else:
        pct = adherence.get("adherence_pct")
        completed = adherence.get("days_completed", 0)

        c1, c2, c3 = st.columns(3)
        c1.metric(
            "Adhérence",
            f"{pct:.0f}%" if pct is not None else "—",
            help=f"Sur les {completed} journée(s) déjà terminée(s) — le jour en cours n'est pas compté.",
        )
        c2.metric(
            "Charge réalisée / prescrite",
            f"{adherence['actual_tss_to_date']:.0f} / {adherence['planned_tss_to_date']:.0f} TSS",
        )
        c3.metric(
            "Séances faites / manquées",
            f"{adherence['sessions_done']} / {adherence['sessions_missed']}",
        )

        verdict = adherence.get("verdict")
        if verdict:
            if pct is None:
                st.info(verdict)
            else:
                (st.success if pct >= 70 else st.warning)(verdict)

        days = adherence.get("days", [])
        if days:
            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=[d["date"] for d in days], y=[d["planned_tss"] for d in days],
                    name="Prescrit", marker_color="rgba(148,163,184,0.55)",
                )
            )
            fig.add_trace(
                go.Bar(
                    x=[d["date"] for d in days], y=[d["actual_tss"] for d in days],
                    name="Réalisé", marker_color="#4c9be8",
                )
            )
            fig.update_layout(
                barmode="group", height=300, template="plotly_white",
                margin=dict(l=0, r=0, t=10, b=10),
                yaxis=dict(title="TSS", gridcolor="rgba(0,0,0,0.06)"),
                xaxis=dict(showgrid=False),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            st.plotly_chart(fig, width="stretch")

    st.markdown(latest_plan["plan_text"])

    with st.expander("Détail séances réalisées sur la période"):
        st.text(build_plan_vs_actual(latest_plan, load_enriched_sessions()))

st.divider()
st.subheader("Générer un nouveau plan")
st.caption(
    "Le coach consulte d'abord ce que tu as réellement fait du plan précédent "
    "et calibre le nouveau en conséquence."
)
horizon = st.slider("Horizon (jours)", min_value=3, max_value=21, value=7)
if st.button("🧠 Générer le plan", type="primary"):
    with st.spinner("Le coach réfléchit..."):
        try:
            plan_text = generate_plan(report, horizon_days=horizon, source="web")
        except Exception as e:
            st.error(f"Erreur : {e}")
        else:
            invalidate_report_cache()
            st.success("Plan généré et enregistré. Recharge la page pour voir le suivi.")
            st.markdown(plan_text)
