"""Lecture et édition rapide du profil athlète (FTP, poids, objectifs)."""
from __future__ import annotations

from datetime import date

import streamlit as st

from ai_coach.profile import (
    PRIORITIES,
    ProfileNotFoundError,
    get_objectives,
    load_profile,
    resolve_location,
    save_profile,
    set_objectives,
    split_objectives,
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
objectives = get_objectives(profile)

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

st.divider()
st.subheader("Objectifs")
st.caption(
    "A = objectif majeur (on construit la saison autour) · "
    "B = important (on s'y prépare sans tout sacrifier) · "
    "C = bonus (on y va en forme, sans affûtage). "
    "Le coach ne planifie que pour les objectifs à venir."
)

PRIORITY_ICONS = {"A": "🏆", "B": "🎯", "C": "🔹"}
OBJECTIVE_TYPES = ["cyclosportive", "course", "performance metric", "stage", "autre"]

upcoming, past = split_objectives(objectives)


def _save(new_list: list[dict]) -> None:
    current = load_profile()
    set_objectives(current, new_list)
    save_profile(current)


def _render_objective(obj: dict, index: int) -> None:
    priority = obj.get("priority", "?")
    icon = PRIORITY_ICONS.get(priority, "•")
    label = f"{icon} [{priority}] {obj.get('name', '?')} — {obj.get('date', '?')}"

    with st.expander(label, expanded=False):
        with st.form(f"obj_form_{index}"):
            name = st.text_input("Nom", value=obj.get("name", ""))
            c1, c2 = st.columns(2)
            prio = c1.selectbox(
                "Priorité", PRIORITIES,
                index=PRIORITIES.index(priority) if priority in PRIORITIES else 2,
            )
            try:
                obj_date = date.fromisoformat(obj.get("date", ""))
            except ValueError:
                obj_date = date.today()
            new_date = c2.date_input("Date", value=obj_date)

            obj_type = obj.get("type", "autre")
            type_choice = st.selectbox(
                "Type", OBJECTIVE_TYPES,
                index=OBJECTIVE_TYPES.index(obj_type) if obj_type in OBJECTIVE_TYPES else len(OBJECTIVE_TYPES) - 1,
            )
            notes = st.text_area("Notes", value=obj.get("notes", ""))

            col_save, col_del = st.columns(2)
            saved = col_save.form_submit_button("💾 Enregistrer", type="primary")
            deleted = col_del.form_submit_button("🗑️ Supprimer")

        if saved:
            updated = list(objectives)
            # Repérage par identité : deux objectifs au contenu identique
            # feraient sinon modifier le mauvais.
            position = next(k for k, o in enumerate(objectives) if o is obj)
            updated[position] = {
                "priority": prio,
                "name": name,
                "date": new_date.isoformat(),
                "type": type_choice,
                "notes": notes,
            }
            _save(updated)
            st.success("Objectif mis à jour.")
            st.rerun()

        if deleted:
            updated = [o for o in objectives if o is not obj]
            _save(updated)
            st.success("Objectif supprimé.")
            st.rerun()


st.markdown("**À venir**")
if upcoming:
    for i, obj in enumerate(upcoming):
        _render_objective(obj, i)
else:
    st.info("Aucun objectif à venir — le coach n'a rien vers quoi construire.")

if past:
    with st.expander(f"Objectifs passés ({len(past)})"):
        st.caption(
            "Conservés comme historique : le coach les voit comme écoulés "
            "et ne planifie plus pour eux."
        )
        for i, obj in enumerate(past):
            _render_objective(obj, 1000 + i)

with st.expander("➕ Ajouter un objectif"):
    with st.form("new_objective"):
        new_name = st.text_input("Nom", placeholder="ex: GFNY Villard de Lans")
        c1, c2 = st.columns(2)
        new_prio = c1.selectbox("Priorité", PRIORITIES, index=1)
        new_date = c2.date_input("Date", value=date.today())
        new_type = st.selectbox("Type", OBJECTIVE_TYPES)
        new_notes = st.text_area("Notes", placeholder="Contexte, parcours, ambition…")
        added = st.form_submit_button("Ajouter", type="primary")

    if added:
        if not new_name.strip():
            st.error("Un objectif a besoin d'un nom.")
        else:
            _save(objectives + [{
                "priority": new_prio,
                "name": new_name.strip(),
                "date": new_date.isoformat(),
                "type": new_type,
                "notes": new_notes.strip(),
            }])
            st.success(f"Objectif ajouté : {new_name}")
            st.rerun()
