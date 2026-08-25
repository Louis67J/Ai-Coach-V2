"""Rafraîchissement des données Intervals.icu + résumé du cache local."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from ai_coach.analysis import is_usable
from ai_coach.intervals import enrich_sessions, load_cached_activities, refresh_cache
from ai_coach.web._shared import invalidate_report_cache

st.set_page_config(page_title="AI Coach — Données", page_icon="🔄", layout="wide")
st.title("🔄 Données")

st.subheader("Rafraîchir depuis Intervals.icu")
st.caption(
    "Récupère les activités des N derniers jours (pas de plage de dates arbitraire "
    "pour l'instant — ajout possible plus tard si besoin d'une plage fixe précise)."
)

days = st.slider("Jours d'historique à récupérer", min_value=7, max_value=730, value=90, step=7)
max_new = st.slider("Nouvelles séances max à enrichir", min_value=5, max_value=100, value=20, step=5)

if st.button("🔄 Rafraîchir + enrichir", type="primary"):
    with st.spinner(f"Fetch des {days} derniers jours..."):
        try:
            activities = refresh_cache(days=days)
        except Exception as e:
            st.error(f"Erreur pendant le fetch : {e}")
            activities = None

    if activities is not None:
        st.success(f"{len(activities)} activités récupérées.")
        with st.spinner(f"Enrichissement (max {max_new} nouvelles séances)..."):
            try:
                enrich_sessions(activities, max_new=max_new)
            except Exception as e:
                st.error(f"Erreur pendant l'enrichissement : {e}")
        invalidate_report_cache()
        st.success("Cache mis à jour. Va sur le Dashboard pour voir les nouvelles données.")

st.divider()
st.subheader("Résumé du cache local")

all_activities = load_cached_activities()
if not all_activities:
    st.info("Aucun cache trouvé. Lance un premier rafraîchissement ci-dessus.")
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
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
