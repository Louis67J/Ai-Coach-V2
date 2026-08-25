"""
Brief proactif : ce que le coach a à dire sans qu'on le lui demande.

Le reste de l'application est en « pull » — il faut ouvrir le dashboard ou
poser une question. Un coach utile devance : il dit le matin ce qu'il y a à
faire aujourd'hui compte tenu de la forme, du plan, de la météo et de la nuit.

Ce module ne connaît aucun canal : il produit le texte, et c'est à Discord
(ou à un autre canal) de le distribuer.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

from ai_coach.config import athlete_path

logger = logging.getLogger(__name__)


def brief_state_path() -> Path:
    """Trace des briefs déjà envoyés, pour ne pas en renvoyer deux le même jour."""
    return athlete_path("brief_state.json")


def _load_state() -> dict[str, Any]:
    path = brief_state_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def last_brief_date(kind: str = "daily") -> str | None:
    return _load_state().get(kind)


def mark_brief_sent(kind: str = "daily", day: str | None = None) -> None:
    state = _load_state()
    state[kind] = day or date.today().isoformat()
    brief_state_path().write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def should_send(kind: str = "daily", today: str | None = None) -> bool:
    """
    Un brief par jour au maximum.

    Le bot peut redémarrer plusieurs fois dans la journée ; sans cette
    vérification, chaque redémarrage après l'heure prévue en renverrait un.
    """
    today = today or date.today().isoformat()
    return last_brief_date(kind) != today


DAILY_QUESTION = (
    "Fais-moi le brief du jour, en 6 lignes maximum. "
    "Commence par la séance que tu me recommandes aujourd'hui (type, durée, intensité), "
    "puis la raison en une phrase (forme, fatigue, plan en cours, météo). "
    "Appelle get_plan_followup pour voir où j'en suis du plan, get_wellness pour ma nuit "
    "et get_weather_forecast pour la météo du jour. "
    "Si quelque chose mérite mon attention (fatigue anormale, plan décroché, "
    "objectif qui approche), dis-le en une ligne. Sinon n'inflige pas de remplissage."
)


def build_daily_brief(report: dict[str, Any] | None = None) -> str:
    """
    Génère le texte du brief quotidien.

    Passe par le même `ask_coach` que le reste : le brief hérite ainsi du
    profil, de la mémoire et des outils, au lieu d'être un second cerveau
    à maintenir en parallèle.
    """
    from ai_coach.analysis import build_report
    from ai_coach.coach import ask_coach
    from ai_coach.intervals import load_cached_activities

    if report is None:
        activities = load_cached_activities()
        if not activities:
            raise RuntimeError("Aucune activité en cache : impossible de faire un brief.")
        report = build_report(activities)

    return ask_coach(DAILY_QUESTION, report, max_tokens=1200, source="brief")
