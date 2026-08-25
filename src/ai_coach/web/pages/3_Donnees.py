"""Rafraîchissement des données Intervals.icu + résumé du cache local."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from ai_coach.analysis import is_usable
from ai_coach.intervals import (
    count_pending_enrichment,
    enrich_sessions,
    load_cached_activities,
    refresh_cache,
)
from ai_coach.web._shared import invalidate_report_cache

st.set_page_config(page_title="AI Coach — Données", page_icon="🔄", layout="wide")
st.title("🔄 Données")

st.subheader("1. Récupérer les activités")

mode = st.radio(
    "Période",
    ["Dernières années", "Plage de dates précise"],
    horizontal=True,
)

start_date = end_date = None
if mode == "Dernières années":
    years = st.slider("Années d'historique", min_value=1, max_value=10, value=3)
    end_date = date.today()
    start_date = end_date - timedelta(days=round(years * 365.25))
else:
    c1, c2 = st.columns(2)
    start_date = c1.date_input("Du", value=date.today() - timedelta(days=365 * 3))
    end_date = c2.date_input("Au", value=date.today())

st.caption(f"Fenêtre : {start_date} → {end_date}")

if st.button("📡 Récupérer les activités", type="primary"):
    if start_date > end_date:
        st.error("La date de début est après la date de fin.")
    else:
        with st.spinner("Fetch Intervals.icu..."):
            try:
                activities = refresh_cache(start=start_date, end=end_date)
            except Exception as e:
                st.error(f"Erreur pendant le fetch : {e}")
            else:
                invalidate_report_cache()
                st.success(f"{len(activities)} activités récupérées.")

st.divider()
st.subheader("2. Enrichir les séances")
st.caption(
    "L'enrichissement récupère le détail de chaque séance (intervalles, zones, "
    "et le flux de puissance quand la classification est douteuse). "
    "Compte ~2 à 3 requêtes par séance : un gros rattrapage prend du temps."
)

all_activities = load_cached_activities()
pending = count_pending_enrichment(all_activities) if all_activities else 0

if not all_activities:
    st.info("Aucune activité en cache — commence par l'étape 1.")
elif pending == 0:
    st.success("Toutes les séances exploitables sont déjà enrichies et vérifiées. ✨")
else:
    st.metric("Séances à traiter", pending)
    max_new = st.number_input(
        "Nombre à traiter maintenant",
        min_value=1,
        max_value=max(pending, 1),
        value=min(50, pending),
        step=10,
        help="Le cache est sauvegardé régulièrement : tu peux interrompre sans rien perdre.",
    )

    if st.button("🔬 Lancer l'enrichissement"):
        progress = st.progress(0.0)
        status = st.empty()

        def on_progress(done: int, total: int, name: str) -> None:
            progress.progress(min(done / total, 1.0) if total else 1.0)
            status.caption(f"{done}/{total} — {name}")

        try:
            enrich_sessions(all_activities, max_new=int(max_new), progress_cb=on_progress)
        except Exception as e:
            st.error(f"Erreur pendant l'enrichissement : {e}")
        else:
            invalidate_report_cache()
            remaining = count_pending_enrichment(all_activities)
            if remaining:
                st.success(f"Terminé. Il reste {remaining} séance(s) à traiter.")
            else:
                st.success("Terminé — tout l'historique est traité. ✨")

st.divider()
st.subheader("Résumé du cache local")

if not all_activities:
    st.info("Aucun cache trouvé.")
else:
    usable = [a for a in all_activities if is_usable(a)]
    stubs = len(all_activities) - len(usable)

    c1, c2, c3 = st.columns(3)
    c1.metric("Activités au total", len(all_activities))
    c2.metric("Exploitables", len(usable))
    c3.metric("Stubs (Strava bloqué)", stubs)

    if usable:
        rows = []
        for act in sorted(usable, key=lambda a: a.get("start_date_local", ""), reverse=True)[:30]:
            rows.append(
                {
                    "Date": (act.get("start_date_local") or "")[:10],
                    "Sport": act.get("type") or "?",
                    "Distance (km)": round((act.get("distance") or 0) / 1000, 1),
                    "Durée (h)": round((act.get("moving_time") or 0) / 3600, 1),
                    "TSS": act.get("icu_training_load") or 0,
                    "Nom": act.get("name") or "(sans nom)",
                }
            )
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
