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
from ai_coach.charts_interactive import build_workout_fig
from ai_coach.intervals_sync import push_plan_to_calendar
from ai_coach.web._shared import (
    get_profile_safe,
    get_report_or_stop,
    invalidate_report_cache,
)
from ai_coach.workout import workout_from_plan_day

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

    # --- Profil des séances prescrites ---
    plan_days = (latest_plan.get("structured") or {}).get("days") or []
    if plan_days:
        st.divider()
        st.subheader("Forme des séances")
        st.caption(
            "Dessin déduit du texte du plan par un interpréteur — aucune "
            "génération par le coach, donc rien d'inventé. Purement illustratif."
        )

        ftp = (get_profile_safe().get("athlete") or {}).get("ftp_watts")
        for day in plan_days:
            workout = workout_from_plan_day(day)
            header = (
                f"**{day.get('date')}** — {day.get('type', '?')} · "
                f"{day.get('duration_min', 0)}min · {day.get('target_tss', 0)} TSS"
            )
            st.markdown(header)
            st.caption(day.get("intensity") or "")

            fig_workout = build_workout_fig(workout, ftp=ftp)
            if fig_workout is not None:
                st.plotly_chart(fig_workout, width="stretch")
            for note in workout.notes:
                st.caption(f"— {note}")

        # --- Export vers Intervals.icu ---
        st.divider()
        st.subheader("Envoyer vers Intervals.icu")
        st.caption(
            "Crée les séances dans ton calendrier Intervals.icu. "
            "Les jours de repos et les séances hors vélo ne sont pas envoyés, "
            "et une date qui porte déjà une séance planifiée n'est jamais écrasée."
        )

        if not ftp:
            st.warning("FTP absente du profil : impossible de convertir les intensités en watts.")
        elif st.button("👁️ Prévisualiser l'envoi"):
            with st.spinner("Lecture de ton calendrier..."):
                try:
                    st.session_state.push_preview = push_plan_to_calendar(
                        latest_plan, ftp=ftp, dry_run=True
                    )
                except Exception as e:
                    st.error(f"Impossible de lire le calendrier Intervals.icu : {e}")

        preview = st.session_state.get("push_preview")
        if preview:
            to_create = preview["to_create"]
            if preview["skipped_existing"]:
                st.info(
                    "Déjà planifié sur Intervals.icu, laissé intact : "
                    + ", ".join(preview["skipped_existing"])
                )
            if preview["skipped_rest_or_off_bike"]:
                st.caption(
                    f"{preview['skipped_rest_or_off_bike']} jour(s) non envoyé(s) "
                    "(repos ou séance hors vélo)."
                )

            if not to_create:
                st.success("Rien à créer : tout est déjà en place.")
            else:
                st.write(f"**{len(to_create)} séance(s) seraient créées :**")
                for payload in to_create:
                    with st.expander(
                        f"{payload['start_date_local'][:10]} — {payload['name']} "
                        f"({payload['moving_time'] // 60}min, TSS {payload['icu_training_load']})"
                    ):
                        st.code(payload["description"], language="text")

                st.warning(
                    "Cette action écrit dans ton calendrier Intervals.icu. "
                    "Relis la liste ci-dessus avant de confirmer."
                )
                if st.button("✅ Confirmer l'envoi", type="primary"):
                    with st.spinner("Envoi..."):
                        result = push_plan_to_calendar(latest_plan, ftp=ftp, dry_run=False)
                    if result["created"]:
                        st.success(f"{len(result['created'])} séance(s) créées : "
                                   + ", ".join(result["created"]))
                    for err in result["errors"]:
                        st.error(f"{err['date']} : {err['error']}")
                    st.session_state.pop("push_preview", None)

    st.divider()
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
instructions = st.text_area(
    "Tes consignes pour ce bloc (optionnel)",
    placeholder=(
        "ex : je suis à Sagunto sans routine encore, "
        "je veux tester mon 20min, pas dispo jeudi…"
    ),
    help=(
        "C'est ici qu'il faut demander une adaptation. Un plan demandé dans "
        "l'onglet Coach n'est pas enregistré et n'apparaîtra pas sur cette page."
    ),
)
if st.button("🧠 Générer le plan", type="primary"):
    with st.spinner("Le coach réfléchit..."):
        try:
            plan_text = generate_plan(
                report, horizon_days=horizon, source="web", instructions=instructions,
            )
        except Exception as e:
            st.error(f"Erreur : {e}")
        else:
            invalidate_report_cache()
            st.success("Plan généré et enregistré. Recharge la page pour voir le suivi.")
            st.markdown(plan_text)
