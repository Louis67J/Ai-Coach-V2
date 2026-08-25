"""
Dashboard principal — forme actuelle, projection, métriques avancées.

Lancement: streamlit run src/ai_coach/web/app.py
(depuis le venv du projet, ai_coach doit être installé en mode editable
— `pip install -e .` — comme documenté dans le README).
"""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from ai_coach.charts import plot_sport_breakdown
from ai_coach.charts_interactive import build_fitness_fig
from ai_coach.config import load_config
from ai_coach.profile import get_objectives
from ai_coach.web._shared import (
    get_fitness_df,
    get_plan_projection,
    get_profile_safe,
    get_report_or_stop,
)

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
objectives = get_objectives(profile)
forecast = report.get("ctl_forecast", [])
plan_projection = get_plan_projection(cf.get("ctl", 0), cf.get("atl", 0)) if cf else []
fig = build_fitness_fig(
    fitness_df,
    objectives=objectives,
    forecast=forecast,
    plan_projection=plan_projection,
)
if fig is not None:
    st.plotly_chart(fig, width="stretch")
    if plan_projection:
        end = plan_projection[-1]
        st.caption(
            f"En violet : ta forme si tu suis le plan en cours jusqu'au "
            f"{end['date']} → CTL {end['ctl']}, TSB {end['tsb']}."
        )
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

# --- Méthode d'entraînement ---
zones = report.get("zone_distribution", {})
volume = report.get("volume_vs_target", {})

if (zones and zones.get("status") != "insufficient_data") or (
    volume and volume.get("status") != "insufficient_data"
):
    st.subheader("Méthode d'entraînement")
    col_zones, col_volume = st.columns(2)

    with col_zones:
        if zones and zones.get("status") != "insufficient_data":
            st.markdown(f"**Répartition des intensités — modèle {zones['model']}**")
            st.caption(
                f"{zones['sessions']} séances / {zones['total_hours']}h "
                f"sur les {zones['period_days']} derniers jours"
            )

            bands = [
                ("Facile (Z1-Z2)", zones["low_pct"], "#4c9be8"),
                ("Tempo/Seuil (Z3-Z4)", zones["mid_pct"], "#f2a154"),
                ("Haute intensité (Z5+)", zones["high_pct"], "#e05c5c"),
            ]
            fig_zones = go.Figure()
            for label, pct, color in bands:
                fig_zones.add_trace(
                    go.Bar(
                        x=[pct], y=["Répartition"], name=f"{label} — {pct}%",
                        orientation="h", marker_color=color,
                        hovertemplate=f"{label}: {pct}%<extra></extra>",
                    )
                )
            fig_zones.update_layout(
                barmode="stack", height=170, template="plotly_white",
                margin=dict(l=0, r=0, t=10, b=10),
                xaxis=dict(range=[0, 100], ticksuffix="%", showgrid=False),
                yaxis=dict(showticklabels=False),
                legend=dict(orientation="h", yanchor="top", y=-0.2),
            )
            st.plotly_chart(fig_zones, width="stretch")
            st.caption(zones["comment"])
        else:
            st.caption("Pas assez de séances enrichies pour lire la répartition des intensités.")

    with col_volume:
        if volume and volume.get("status") != "insufficient_data":
            st.markdown("**Volume hebdomadaire vs objectif**")
            target_label = volume.get("target_label")
            st.caption(
                f"Objectif du profil : {target_label}/sem"
                if target_label
                else "Aucun objectif de volume défini dans le profil."
            )

            weekly = volume.get("weekly", [])
            fig_vol = go.Figure()
            fig_vol.add_trace(
                go.Bar(
                    x=[w["week_ending"] for w in weekly],
                    y=[w["hours"] for w in weekly],
                    marker_color="#4c9be8", name="Heures",
                    hovertemplate="%{x}<br>%{y}h<extra></extra>",
                )
            )
            lo, hi = volume.get("target_min_hours"), volume.get("target_max_hours")
            if lo is not None and hi is not None:
                fig_vol.add_hrect(
                    y0=lo, y1=hi, fillcolor="rgba(46,160,67,0.10)",
                    line_width=0, annotation_text="cible", annotation_position="top left",
                    annotation_font_size=10,
                )
            fig_vol.update_layout(
                height=250, template="plotly_white", showlegend=False,
                margin=dict(l=0, r=0, t=10, b=10),
                yaxis=dict(title="heures", gridcolor="rgba(0,0,0,0.06)"),
                xaxis=dict(showgrid=False),
            )
            st.plotly_chart(fig_vol, width="stretch")

            verdict = volume.get("verdict")
            if verdict:
                in_target = volume.get("weeks_in_target", 0)
                total_weeks = volume.get("weeks_analyzed", 0)
                (st.success if in_target >= total_weeks / 2 else st.warning)(
                    f"{verdict} {in_target}/{total_weeks} semaines dans la cible."
                )
        else:
            st.caption("Pas assez d'historique pour comparer le volume à l'objectif.")

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
            window = ftp_trend.get("window_days", 90)
            top_n = ftp_trend.get("top_n_used")
            st.write(f"**Tendance :** {ftp_trend.get('trend', '?')}")
            st.caption(
                f"Comparaison sur des fenêtres de {window} jours de même durée"
                + (f", moyenne des {top_n} meilleures estimations de chaque fenêtre." if top_n else ".")
            )

            cols = st.columns(3)
            labels = [
                ("recent", f"{window} derniers jours"),
                ("previous", f"{window} jours précédents"),
                ("year_ago", "Même période l'an dernier"),
            ]
            for col, (key, title) in zip(cols, labels):
                win = ftp_trend.get(key)
                if not win:
                    col.metric(title, "—", help="Pas assez de données sur cette fenêtre")
                    continue
                # Le delta ne s'affiche que sur la fenêtre récente : c'est elle
                # qu'on compare aux deux autres, pas l'inverse.
                delta = ftp_trend.get("delta_vs_previous") if key == "recent" else None
                col.metric(
                    title,
                    f"{win['avg_top']:.0f}W",
                    f"{delta:+.0f}W vs période précédente" if delta is not None else None,
                    help=f"{win['count']} séance(s) — {win['period']}",
                )

            delta_year = ftp_trend.get("delta_vs_year_ago")
            if delta_year is not None:
                st.caption(
                    f"À la même période l'an dernier tu étais à "
                    f"{ftp_trend['year_ago']['avg_top']:.0f}W, soit {delta_year:+.0f}W. "
                    "La forme d'un cycliste étant saisonnière, c'est la comparaison "
                    "la plus parlante des deux."
                )

            best = (ftp_trend.get("recent") or {}).get("best") or []
            if best:
                st.caption("Meilleures estimations récentes :")
                st.dataframe(
                    [
                        {"Date": b["date"], "FTP est. (W)": b["ftp"], "Séance": b["name"], "Source": b["source"]}
                        for b in best
                    ],
                    width="stretch",
                    hide_index=True,
                )
        else:
            note = (ftp_trend or {}).get("note")
            st.caption(note or "Pas assez de séances pour estimer une tendance FTP.")

    with tab_power:
        if pp and pp.get("profile"):
            st.caption(
                f"Poids utilisé : {pp.get('weight_kg_used', '?')}kg — "
                f"période {pp.get('period', '?')} (fenêtre glissante Intervals.icu)"
            )
            rows = []
            for duration, data in pp["profile"].items():
                act_id = data.get("activity_id")
                rows.append(
                    {
                        "Durée": duration,
                        "Puissance": f"{data['watts']}W",
                        "W/kg": data["w_kg"],
                        "Niveau": data["level"],
                        "Date": data.get("date") or "—",
                        "Séance": data.get("activity_name") or "—",
                        "Lien": f"https://intervals.icu/activities/{act_id}" if act_id else None,
                    }
                )
            st.dataframe(
                rows,
                width="stretch",
                hide_index=True,
                column_config={"Lien": st.column_config.LinkColumn("Vérifier", display_text="Intervals.icu")},
            )
            st.caption(
                "Chaque record renvoie à la séance qui l'a produit — un chiffre qui "
                "paraît faux vient souvent d'une perf hors de la fenêtre glissante."
            )
            vo2 = pp.get("vo2max_estimated")
            if vo2:
                st.metric("VO2max estimée", f"{vo2:.1f} ml/kg/min")
        else:
            st.caption("Profil de puissance pas encore disponible.")
