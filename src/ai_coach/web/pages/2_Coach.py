"""Chat libre avec le coach (même fonction que la CLI `ask` et le bot `!ask`)."""
from __future__ import annotations

import streamlit as st

from ai_coach.coach import ask_coach
from ai_coach.memory import load_recent_exchanges
from ai_coach.web._shared import get_report_or_stop

st.set_page_config(page_title="AI Coach — Coach", page_icon="💬", layout="wide")
st.title("💬 Coach")

report = get_report_or_stop()

st.caption(
    "Discussion libre : les réponses sont mémorisées, mais **un plan demandé ici "
    "n'est pas enregistré** et n'apparaîtra pas dans l'onglet Plan. Pour un plan "
    "suivi (adhérence, projection de forme), passe par **Plan → Générer le plan**, "
    "où tu peux saisir tes consignes."
)

if "chat_history" not in st.session_state:
    # Amorce l'affichage avec les derniers échanges déjà en mémoire
    st.session_state.chat_history = [
        {"question": ex["question"], "answer": ex["answer"]}
        for ex in load_recent_exchanges(limit=10)
    ]

for exchange in st.session_state.chat_history:
    with st.chat_message("user"):
        st.write(exchange["question"])
    with st.chat_message("assistant"):
        st.write(exchange["answer"])

question = st.chat_input("Pose ta question au coach...")
if question:
    with st.chat_message("user"):
        st.write(question)
    with st.chat_message("assistant"):
        with st.spinner("Réflexion en cours..."):
            try:
                answer = ask_coach(question, report, source="web")
            except Exception as e:
                answer = f"❌ Erreur : {e}"
        st.write(answer)
    st.session_state.chat_history.append({"question": question, "answer": answer})
