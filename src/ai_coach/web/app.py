"""
Dashboard principal — forme actuelle, projection, métriques avancées.

Lancement: streamlit run src/ai_coach/web/app.py
(depuis le venv du projet, ai_coach doit être installé en mode editable
— `pip install -e .` — comme documenté dans le README).
"""
from __future__ import annotations

import streamlit as st

from ai_coach.charts import plot_sport_breakdown
from ai_coach.charts_interactive import build_fitness_fig
from ai_coach.config import load_config
from ai_coach.web._shared import get_fitness_df, get_profile_safe, get_report_or_stop

st.set_page_config(page_title="AI Coach — Dashboard", page_icon="🚴", layout="wide")

try:
    load_config()
except RuntimeError as e:
    st.error(str(e))
    st.stop()

st.title("🚴 AI Coach — Dashboard")

report = get_report_or_stop()
profile = get_profile_safe()

# --- Forme actuelle ---
cf = report.get("current_fitness", {})
col1, col2, col3 = st.columns(3)
col1.metric("CTL (forme)", cf.get("ctl", "?"))
col2.metric("ATL (fatigue)", cf.get("atl", "?"))
col3.metric("TSB (fraîcheur)", cf.get("tsb", "?"))
if cf.get("as_of"):
    st.caption(f"Au {cf['as_of']}")

# --- Graphe forme + projection + objectifs ---
st.subheader("Forme & projection")
fitness_df = get_fitness_df()
objectives = profile.get("season_2026_objectives", [])
forecast = report.get("ctl_forecast", [])
fig = build_fitness_fig(fitness_df, objectives=objectives, forecast=forecast)
if fig is not None:
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Pas encore assez de données pour tracer la courbe de forme.")

# --- Charge hebdomadaire récente ---
recent_weekly = report.get("recent_weekly_load", [])
if recent_weekly:
    st.subheader("Charge des dernières semaines")
    weekly_cols = st.columns(len(recent_weekly))
    for col, week in zip(weekly_cols, recent_weekly):
        col.metric(
            week["week_ending"],
            f"{week['tss']:.0f} TSS",
            help=week.get("status"),
        )

# --- Répartition par sport ---
sport_breakdown = report.get("sport_breakdown", {})
if sport_breakdown:
    st.subheader("Répartition par sport")
    path = plot_sport_breakdown(sport_breakdown)
    if path:
        st.image(str(path))

# --- Métriques avancées ---
st.subheader("Métriques avancées")

mono = report.get("monotony_strain", {})
dur = report.get("durability", {})
ftp_trend = report.get("ftp_trend", {})
pp = report.get("power_profile", {})

if not any([mono, dur, ftp_trend, pp]):
    st.caption(
        "Pas encore de métriques avancées — elles apparaissent une fois des séances "
        "enrichies disponibles (page Données → Enrichir)."
    )
else:
    tab_mono, tab_dur, tab_ftp, tab_power = st.tabs(
        ["Monotonie & Strain", "Durabilité", "Tendance FTP", "Profil de puissance"]
    )

    with tab_mono:
        if mono:
            c1, c2, c3 = st.columns(3)
            c1.metric("Monotonie", mono.get("monotony", "?"), mono.get("monotony_status"))
            c2.metric("Strain", mono.get("strain", "?"), mono.get("strain_status"))
            c3.metric(
                "TSS/jour (7j)",
                mono.get("daily_mean_tss", "?"),
                f"± {mono.get('daily_std_tss', '?')}",
            )
        else:
            st.caption("Pas assez de données récentes.")

    with tab_dur:
        if dur and dur.get("status") != "insufficient_data":
            c1, c2 = st.columns(2)
            c1.metric("Note de durabilité", dur.get("durability_rating", "?"))
            c2.metric("Découplage moyen", f"{dur.get('avg_decoupling_pct', '?')}%")
            if "trend" in dur:
                st.caption(f"Tendance : {dur['trend']}")
            st.caption(f"{dur.get('count', '?')} sorties de plus de 2h analysées")
        else:
            st.caption("Pas assez de sorties longues pour calculer la durabilité.")

    with tab_ftp:
        if ftp_trend and ftp_trend.get("status") != "insufficient_data":
            if "trend" in ftp_trend:
                st.write(f"**Tendance :** {ftp_trend['trend']}")
            c1, c2, c3 = st.columns(3)
            c1.metric("Top 5 NP récent", f"{ftp_trend.get('recent_avg_top5_np', '?')}W")
            c2.metric("Top 5 NP ancien", f"{ftp_trend.get('older_avg_top5_np', '?')}W")
            delta = ftp_trend.get("np_delta")
            c3.metric("Delta", f"{delta:+d}W" if isinstance(delta, int) else "?")
        else:
            st.caption("Pas assez de séances pour estimer une tendance FTP.")

    with tab_power:
        if pp and pp.get("profile"):
            st.caption(f"Poids utilisé : {pp.get('weight_kg_used', '?')}kg")
            for duration, data in pp["profile"].items():
                st.write(
                    f"**{duration}** : {data['watts']}W = {data['w_kg']:.1f} W/kg "
                    f"({data['level']})"
                )
            if pp.get("strengths"):
                st.success(f"💪 Forces : {', '.join(pp['strengths'])}")
            if pp.get("weaknesses"):
                st.warning(f"⚠️ Faiblesses : {', '.join(pp['weaknesses'])}")
            vo2 = pp.get("vo2max_estimated")
            if vo2:
                st.metric("VO2max estimée", f"{vo2:.1f} ml/kg/min")
        else:
            st.caption("Profil de puissance pas encore disponible.")
