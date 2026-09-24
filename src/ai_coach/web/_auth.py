"""
Connexion et accueil d'un athlète dans l'app web multi-utilisateur.

Chaque page appelle `require_athlete()` juste après `st.set_page_config` :
elle positionne l'athlète courant pour ce visiteur, ou affiche à sa place ce
qui manque encore (connexion, clés API, profil) et arrête le rendu.

Sans MULTI_USER=1, rien ne change : l'app sert l'athlète par défaut avec les
clés de .env, comme une installation personnelle.
"""
from __future__ import annotations

import streamlit as st

from ai_coach.accounts import (
    MIN_PASSWORD_LENGTH,
    AccountError,
    authenticate,
    create_account,
    has_credentials,
    load_credentials,
    mask_secret,
    save_credentials,
)
from ai_coach.config import DEFAULT_ATHLETE, multi_user_enabled, set_current_athlete
from ai_coach.profile import ProfileNotFoundError, load_profile, new_profile, save_profile
from ai_coach.weather import geocode

SESSION_KEY = "athlete_slug"


def require_athlete() -> str:
    """Athlète de ce visiteur, une fois connecté, ses clés et son profil en place."""
    if not multi_user_enabled():
        set_current_athlete(DEFAULT_ATHLETE)
        return DEFAULT_ATHLETE

    slug = st.session_state.get(SESSION_KEY)
    if not slug:
        _render_login()
        st.stop()

    set_current_athlete(slug)
    _render_sidebar(slug)

    if not has_credentials(slug):
        _render_onboarding_header(step=1)
        render_credentials_form(slug)
        st.stop()

    try:
        load_profile()
    except ProfileNotFoundError:
        _render_onboarding_header(step=2)
        _render_profile_form()
        st.stop()

    return slug


def _render_sidebar(slug: str) -> None:
    with st.sidebar:
        st.caption(f"Connecté : **{slug}**")
        if st.button("Se déconnecter"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()


def _render_login() -> None:
    st.title("🚴 AI Coach")
    st.caption("Ton coach cyclisme IA, branché sur tes données Intervals.icu.")

    login_tab, signup_tab = st.tabs(["Se connecter", "Créer un compte"])

    with login_tab:
        with st.form("login"):
            username = st.text_input("Identifiant")
            password = st.text_input("Mot de passe", type="password")
            submitted = st.form_submit_button("Se connecter", type="primary")
        if submitted:
            slug = authenticate(username, password)
            if slug:
                st.session_state[SESSION_KEY] = slug
                st.rerun()
            else:
                st.error("Identifiant ou mot de passe incorrect.")

    with signup_tab:
        with st.form("signup"):
            username = st.text_input(
                "Identifiant",
                help="Lettres minuscules, chiffres, « - » ou « _ ».",
            )
            password = st.text_input(
                "Mot de passe",
                type="password",
                help=f"Au moins {MIN_PASSWORD_LENGTH} caractères.",
            )
            confirm = st.text_input("Confirme le mot de passe", type="password")
            submitted = st.form_submit_button("Créer mon compte", type="primary")
        if submitted:
            if password != confirm:
                st.error("Les deux mots de passe ne correspondent pas.")
            else:
                try:
                    slug = create_account(username, password)
                except AccountError as e:
                    st.error(str(e))
                else:
                    st.session_state[SESSION_KEY] = slug
                    st.rerun()


def _render_onboarding_header(step: int) -> None:
    st.title("🚴 Bienvenue")
    st.progress(step / 3, text=f"Étape {step} sur 3")
    st.caption(
        "1. Tes clés API · 2. Ton profil · 3. L'import de tes séances "
        "(page **Données**, une fois ces deux étapes faites)."
    )


def render_credentials_form(slug: str) -> None:
    """Saisie ou remplacement des clés API de l'athlète (aussi utilisé par la page Profil)."""
    current = {}
    try:
        current = load_credentials(slug) or {}
    except RuntimeError as e:
        st.warning(str(e))

    st.subheader("🔑 Tes clés API")
    st.caption(
        "Elles sont chiffrées sur le serveur et ne servent qu'à ton compte : "
        "ta consommation Claude est facturée directement sur ton compte Anthropic."
    )
    if current:
        st.caption(
            f"Enregistrées : Claude {mask_secret(current.get('anthropic_api_key', ''))} · "
            f"Intervals.icu {mask_secret(current.get('intervals_api_key', ''))} · "
            f"athlète {current.get('intervals_athlete_id', '')}"
        )

    with st.form("credentials"):
        anthropic_key = st.text_input(
            "Clé API Claude",
            type="password",
            help="Crée-la sur console.anthropic.com → API Keys.",
        )
        intervals_key = st.text_input(
            "Clé API Intervals.icu",
            type="password",
            help="Intervals.icu → Settings → Developer Settings.",
        )
        intervals_id = st.text_input(
            "ID athlète Intervals.icu",
            value=current.get("intervals_athlete_id", ""),
            placeholder="i123456",
            help="Le numéro après le « i » dans l'URL de ton profil Intervals.icu.",
        )
        submitted = st.form_submit_button("Enregistrer mes clés", type="primary")

    if submitted:
        credentials = {
            # Champ laissé vide = on garde la clé déjà enregistrée.
            "anthropic_api_key": anthropic_key or current.get("anthropic_api_key", ""),
            "intervals_api_key": intervals_key or current.get("intervals_api_key", ""),
            "intervals_athlete_id": intervals_id,
        }
        try:
            save_credentials(slug, credentials)
        except AccountError as e:
            st.error(str(e))
        except RuntimeError as e:
            st.error(str(e))
        else:
            st.success("Clés enregistrées.")
            st.rerun()


def _render_profile_form() -> None:
    st.subheader("🧑 Ton profil")
    st.caption(
        "Le minimum pour que le coach te connaisse. Objectifs et contraintes "
        "se complètent ensuite dans la page **Profil**."
    )
    with st.form("new_profile"):
        name = st.text_input("Prénom")
        c1, c2, c3 = st.columns(3)
        ftp = c1.number_input("FTP (W)", min_value=50, max_value=600, value=250, step=5)
        weight = c2.number_input("Poids (kg)", min_value=30.0, max_value=150.0, value=70.0, step=0.5)
        fc_max = c3.number_input("FC max (optionnel)", min_value=0, max_value=230, value=0, step=1)
        city = st.text_input(
            "Ville où tu t'entraînes",
            help="La météo et le terrain du coach suivent ce lieu.",
        )
        submitted = st.form_submit_button("Créer mon profil", type="primary")

    if submitted:
        if not name.strip() or not city.strip():
            st.error("Le prénom et la ville sont nécessaires.")
            return
        matches = geocode(city.strip(), count=1)
        if not matches:
            st.error("Ville introuvable : essaie avec un autre nom ou une ville proche.")
            return
        place = matches[0]
        profile = new_profile(
            name=name.strip(),
            ftp_watts=int(ftp),
            weight_kg=float(weight),
            fc_max=int(fc_max) or None,
            base_location={
                "name": place["name"],
                "latitude": place["latitude"],
                "longitude": place["longitude"],
            },
        )
        save_profile(profile)
        st.rerun()
