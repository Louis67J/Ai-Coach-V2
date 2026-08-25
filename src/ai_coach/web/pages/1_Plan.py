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

        # La journée en cours est volontairement hors des totaux (sinon un plan
        # généré le matin afficherait 0 % avant qu'on ait roulé), mais sans la
        # montrer on croit que la séance du jour n'a pas été prise en compte.
        today_row = next((d for d in adherence.get("days", []) if d.get("is_today")), None)
        if today_row and (today_row["planned_tss"] or today_row["actual_tss"]):
            st.caption(
                f"**Aujourd'hui (journée en cours)** : {today_row['actual_tss']:.0f} TSS réalisés "
                f"sur {today_row['planned_tss']:.0f} prescrits — pas encore comptés "
                "dans l'adhérence ci-dessus, la journée n'est pas terminée."
            )

        verdict = adherence.get("verdict")
        if verdict:
            if pct is None:
                st.info(verdict)
            else:
                (st.success if pct >= 70 else st.warning)(verdict)

        days = adherence.get("days", [])
        if days:
            # Le prescrit s'estompe sur les jours à venir : sans ça, une colonne
            # grise sans bleue à côté se lit comme une séance manquée alors
            # qu'elle n'a simplement pas encore eu lieu.
            planned_colors = [
                "rgba(148,163,184,0.55)" if d["completed"] or d["is_today"]
                else "rgba(148,163,184,0.22)"
                for d in days
            ]
            actual_colors = ["#f2a154" if d["is_today"] else "#4c9be8" for d in days]

            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=[d["date"] for d in days], y=[d["planned_tss"] for d in days],
                    name="Prescrit", marker_color=planned_colors,
                    hovertemplate="%{x}<br>Prescrit %{y:.0f} TSS<extra></extra>",
                )
            )
            fig.add_trace(
                go.Bar(
                    x=[d["date"] for d in days], y=[d["actual_tss"] for d in days],
                    name="Réalisé", marker_color=actual_colors,
                    hovertemplate="%{x}<br>Réalisé %{y:.0f} TSS<extra></extra>",
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
            st.caption(
                "Gris plein = jours révolus ou en cours, gris pâle = à venir. "
                "La barre orange est la journée d'aujourd'hui."
            )

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
