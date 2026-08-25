"""Parcours des séances enrichies : tags, patterns détectés, graphe détaillé.

C'est l'outil pour vérifier concrètement ce que la classification automatique
(_classify_session / _detect_interval_pattern, intervals.py) est capable de
détecter — et repérer les cas où elle se trompe encore.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from ai_coach.charts_interactive import build_session_fig
from ai_coach.intervals import fetch_activity_streams, load_enriched_sessions

st.set_page_config(page_title="AI Coach — Séances", page_icon="🚵", layout="wide")
st.title("🚵 Séances")

sessions = load_enriched_sessions()
if not sessions:
    st.info("Aucune séance enrichie. Va dans **Données** pour lancer un enrichissement.")
    st.stop()

sessions = sorted(sessions, key=lambda s: s.get("date", ""), reverse=True)

tags = sorted({s.get("tag", "?") for s in sessions})
selected_tags = st.multiselect("Filtrer par tag", options=tags, default=[])

filtered = [s for s in sessions if not selected_tags or s.get("tag") in selected_tags]
sessions_by_id = {s.get("id"): s for s in filtered}

_BASIS_LABEL = {"power": "⚡ puissance", "hr": "❤️ FC", "none": "—"}

df = pd.DataFrame(
    [
        {
            "id": s.get("id"),
            "Date": s.get("date"),
            "Nom": s.get("name"),
            "Tag": s.get("tag"),
            "Base": _BASIS_LABEL.get(s.get("classification_basis"), "—"),
            "TSS": s.get("tss"),
            "NP (W)": s.get("np_watts"),
            "Pattern détecté": s.get("interval_pattern") or "—",
        }
        for s in filtered
    ]
)

st.caption(
    f"{len(filtered)} séance(s) — clique une ligne pour voir le détail. "
    "La colonne **Base** indique si le tag vient de la puissance ou, à défaut, "
    "de la fréquence cardiaque (lecture valable mais moins précise sur les efforts courts)."
)
event = st.dataframe(
    df,
    column_order=["Date", "Nom", "Tag", "Base", "TSS", "NP (W)", "Pattern détecté"],
    width="stretch",
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
)

selected_positions = event.selection.rows if event and event.selection else []
if not selected_positions:
    st.caption("Sélectionne une séance dans le tableau ci-dessus.")
    st.stop()

selected_id = df.iloc[selected_positions[0]]["id"]
target = sessions_by_id[selected_id]

st.divider()
st.subheader(f"{target.get('date')} — {target.get('name')}")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Tag", target.get("tag"))
c2.metric("TSS", target.get("tss"))
c3.metric("NP", f"{target.get('np_watts', '?')}W")
c4.metric("IF", target.get("intensity_factor"))

basis = target.get("classification_basis")
if basis == "hr":
    st.info(
        "Séance sans capteur de puissance : le tag est déduit du temps passé "
        f"en zones de FC (LTHR {target.get('lthr', '?')}). La FC étant inerte, "
        "les efforts très courts y sont sous-représentés."
    )
elif basis == "none":
    st.warning("Ni puissance ni FC exploitable : cette séance n'a pas pu être classifiée.")

if target.get("interval_pattern"):
    st.success(f"Pattern détecté : {target['interval_pattern']}")
else:
    st.caption("Aucun pattern d'intervalle détecté pour cette séance.")

power_bests = target.get("power_bests") or {}
if power_bests:
    st.caption("Meilleures puissances glissantes (depuis le stream) :")
    st.write(
        " | ".join(
            f"**{label}** {b['watts']}W ({b['pct_ftp']}% FTP)"
            for label, b in power_bests.items()
        )
    )

if st.button("📈 Charger le graphe détaillé"):
    with st.spinner("Chargement du stream..."):
        streams = fetch_activity_streams(target["id"])
    if not streams:
        st.error("Impossible de charger les streams pour cette séance.")
    else:
        fig = build_session_fig(streams, session_summary=target)
        if fig is not None:
            st.plotly_chart(fig, width="stretch")
        else:
            st.warning("Pas de données de puissance pour tracer le graphe.")
