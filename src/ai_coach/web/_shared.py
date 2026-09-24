"""
Helpers communs aux pages du dashboard Streamlit.

Toute la logique métier vit déjà dans ai_coach.* (analysis, coach, intervals,
profile, plan_tracker, memory) — ce module ne fait qu'appeler ces fonctions
et les mettre en cache pour l'UI, comme bot.py le fait pour Discord.
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from ai_coach.analysis import build_daily_tss, build_report, compute_fitness, filter_usable
from ai_coach.config import configure_logging, current_athlete
from ai_coach.intervals import load_cached_activities
from ai_coach.profile import ProfileNotFoundError, load_profile

# Point d'entrée web : les logs des modules métier sortent dans la console du serveur.
configure_logging()


# Les fonctions en cache prennent l'athlète en argument : st.cache_data est
# partagé entre tous les visiteurs, et sans cette clé le premier rapport
# calculé serait servi à tout le monde.


@st.cache_data(ttl=300, show_spinner=False)
def _report_for(athlete: str) -> dict[str, Any]:
    activities = load_cached_activities()
    if not activities:
        return {}
    return build_report(activities)


def get_report() -> dict[str, Any]:
    """Charge le cache d'activités et construit le rapport d'analyse (mis en cache 5 min)."""
    return _report_for(current_athlete())


@st.cache_data(ttl=300, show_spinner=False)
def _fitness_df_for(athlete: str) -> pd.DataFrame:
    activities = load_cached_activities()
    usable = filter_usable(activities)
    daily_tss = build_daily_tss(usable)
    return compute_fitness(daily_tss)


def get_fitness_df() -> pd.DataFrame:
    """
    Série temporelle CTL/ATL/TSB, nécessaire aux graphes (le report JSON ne
    garde que le point courant). Même pipeline que bot.py: filter_usable →
    build_daily_tss → compute_fitness — centralisé ici au lieu d'être
    recalculé dans chaque commande/page.
    """
    return _fitness_df_for(current_athlete())


def get_report_or_stop() -> dict[str, Any]:
    """Comme get_report(), mais arrête le rendu de la page avec un message si le cache est vide."""
    report = get_report()
    if not report:
        st.warning(
            "Aucune donnée en cache. Va dans la page **Données** pour lancer un premier "
            "rafraîchissement depuis Intervals.icu."
        )
        st.stop()
    return report


@st.cache_data(ttl=300, show_spinner=False)
def _plan_projection_for(athlete: str, current_ctl: float, current_atl: float) -> list[dict]:
    from ai_coach.analysis import compute_fitness_projection_from_plan
    from ai_coach.plan_tracker import load_recent_plans

    plans = load_recent_plans(limit=1)
    if not plans:
        return []
    days = (plans[0].get("structured") or {}).get("days") or []
    return compute_fitness_projection_from_plan(current_ctl, current_atl, days)


def get_plan_projection(current_ctl: float, current_atl: float) -> list[dict]:
    """
    Trajectoire de forme si le dernier plan est suivi à la lettre.
    Vide si aucun plan structuré n'existe encore.
    """
    return _plan_projection_for(current_athlete(), current_ctl, current_atl)


def get_profile_safe() -> dict[str, Any]:
    """Charge le profil, ou {} s'il n'existe pas encore."""
    try:
        return load_profile()
    except ProfileNotFoundError:
        return {}


def invalidate_report_cache() -> None:
    """À appeler après un refresh/enrich pour forcer le recalcul du rapport."""
    _report_for.clear()
    _fitness_df_for.clear()
    _plan_projection_for.clear()
