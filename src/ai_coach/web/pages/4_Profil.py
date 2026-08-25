"""Lecture et édition rapide du profil athlète (FTP, poids, objectifs)."""
from __future__ import annotations

from datetime import date

import streamlit as st

from ai_coach.profile import (
    ProfileNotFoundError,
    load_profile,
    resolve_location,
    update_field,
)
from ai_coach.weather import geocode

st.set_page_config(page_title="AI Coach — Profil", page_icon="🧑", layout="wide")
st.title("🧑 Profil athlète")

try:
    profile = load_profile()
except ProfileNotFoundError:
    st.warning(
        "Aucun profil trouvé (`data/profile.json`). Crée-le manuellement une première fois "
        "— c'est un simple fichier JSON, voir le format attendu dans `ai_coach/profile.py`."
    )
    st.stop()

athlete = profile.get("athlete", {})
context = profile.get("context", {})
objectives = profile.get("season_2026_objectives", [])

st.subheader("Athlète")
c1, c2, c3, c4 = st.columns(4)
c1.metric("FTP", f"{athlete.get('ftp_watts', '?')}W")
c2.metric("Poids", f"{athlete.get('weight_kg', '?')}kg")
c3.metric("Catégorie", athlete.get("category", "?"))
c4.metric("PMA", f"{athlete.get('pma_watts', '?')}W" if athlete.get("pma_watts") else "?")

st.caption(
    f"Profession : {context.get('profession', '?')} "
    f"({context.get('weekly_work_hours', '?')}h/sem) — "
    f"volume cible {context.get('weekly_training_hours_target', '?')}/sem"
)

st.divider()
st.subheader("Où je suis")

location = resolve_location(profile)
if location["is_away"]:
    msg = f"En déplacement à **{location['name']}**"
    if location.get("until"):
        msg += f" jusqu'au {location['until']}"
    st.info(f"{msg} — météo et terrain raisonnés sur ce lieu.")
else:
    st.caption(f"À la base : **{location['name']}**")

search = st.text_input(
    "Changer de lieu",
    placeholder="Nom de ville (ex: Sagunto, Grenoble, Girona)",
    help="La météo du coach suit ce lieu. Laisse la base pour revenir chez toi.",
)
if search:
    matches = geocode(search)
    if not matches:
        st.warning("Aucun lieu trouvé pour cette recherche.")
    else:
        labels = [
            f"{m['name']} — {m.get('region') or '?'}, {m.get('country') or '?'}"
            for m in matches
        ]
        choice = st.selectbox("Résultats", options=range(len(matches)), format_func=lambda i: labels[i])
        picked = matches[choice]
        until = st.date_input(
            "Jusqu'au (optionnel)",
            value=None,
            help="Laisse vide si tu ne sais pas encore quand tu rentres.",
        )
        if st.button("📍 Définir comme lieu actuel"):
            update_field(
                ["context", "current_location"],
                {
                    "name": labels[choice],
                    "latitude": picked["latitude"],
                    "longitude": picked["longitude"],
                    "timezone": picked.get("timezone"),
                    "since": date.today().isoformat(),
                    **({"until": until.isoformat()} if until else {}),
                },
            )
            st.success(f"Lieu actuel : {labels[choice]}")
            st.rerun()

if location["is_away"] and st.button("🏠 Revenir à la base"):
    update_field(["context", "current_location"], None)
    st.success("Retour à la base.")
    st.rerun()

st.divider()
st.subheader("Mise à jour rapide")
col_ftp, col_weight = st.columns(2)
with col_ftp:
    new_ftp = st.number_input(
        "Nouvelle FTP (W)", min_value=0, value=int(athlete.get("ftp_watts") or 0), step=1
    )
    if st.button("Mettre à jour la FTP"):
        update_field(["athlete", "ftp_watts"], new_ftp)
        update_field(["athlete", "ftp_updated"], date.today().isoformat())
        st.success(f"FTP mise à jour : {new_ftp}W")
        st.rerun()

with col_weight:
    new_weight = st.number_input(
        "Nouveau poids (kg)",
        min_value=0.0,
        value=float(athlete.get("weight_kg") or 0),
        step=0.1,
        format="%.1f",
    )
    if st.button("Mettre à jour le poids"):
        update_field(["athlete", "weight_kg"], new_weight)
        st.success(f"Poids mis à jour : {new_weight}kg")
        st.rerun()

if objectives:
    st.divider()
    st.subheader("Objectifs de la saison")
    for obj in objectives:
        priority = obj.get("priority", "?")
        icon = {"A": "🏆", "B": "🎯", "C": "🔹"}.get(priority, "•")
        st.write(
            f"{icon} **[{priority}] {obj.get('name', '?')}** — "
            f"{obj.get('date', '?')} ({obj.get('type', '?')})"
        )
        if obj.get("notes"):
            st.caption(obj["notes"])
