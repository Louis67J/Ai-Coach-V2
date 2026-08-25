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
from ai_coach.intervals import load_cached_activities
from ai_coach.profile import ProfileNotFoundError, load_profile


@st.cache_data(ttl=300, show_spinner=False)
def get_report() -> dict[str, Any]:
    """Charge le cache d'activités et construit le rapport d'analyse (mis en cache 5 min)."""
    activities = load_cached_activities()
    if not activities:
        return {}
    return build_report(activities)


@st.cache_data(ttl=300, show_spinner=False)
def get_fitness_df() -> pd.DataFrame:
    """
    Série temporelle CTL/ATL/TSB, nécessaire aux graphes (le report JSON ne
    garde que le point courant). Même pipeline que bot.py: filter_usable →
    build_daily_tss → compute_fitness — centralisé ici au lieu d'être
    recalculé dans chaque commande/page.
    """
    activities = load_cached_activities()
    usable = filter_usable(activities)
    daily_tss = build_daily_tss(usable)
    return compute_fitness(daily_tss)


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


def get_profile_safe() -> dict[str, Any]:
    """Charge le profil, ou {} s'il n'existe pas encore."""
    try:
        return load_profile()
    except ProfileNotFoundError:
        return {}


def invalidate_report_cache() -> None:
    """À appeler après un refresh/enrich pour forcer le recalcul du rapport."""
    get_report.clear()
    get_fitness_df.clear()
