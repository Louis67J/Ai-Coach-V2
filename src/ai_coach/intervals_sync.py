"""
Envoi des séances planifiées vers le calendrier Intervals.icu.

C'est le seul endroit du projet qui écrit chez un tiers. Deux garde-fous en
conséquence : le mode simulation est le défaut, et une date qui porte déjà
une séance planifiée n'est jamais écrasée.
"""
from __future__ import annotations

import logging
from typing import Any

import requests

from ai_coach.intervals import IntervalsClient
from ai_coach.workout import Workout, workout_from_plan_day

logger = logging.getLogger(__name__)

# Type d'activité Intervals.icu selon le type de séance du plan
_DEFAULT_ACTIVITY_TYPE = "Ride"


def to_workout_description(workout: Workout, ftp: int) -> str:
    """
    Traduit les segments en syntaxe d'entraînement Intervals.icu.

    Format repris de la bibliothèque existante de l'athlète : une ligne par
    bloc, `- <durée> <puissance>w`. Les watts sont figés à partir de la FTP
    du moment — un plan porte sur les jours qui viennent, pas sur l'année.
    """
    lines = []
    for seg in workout.segments:
        watts = round(ftp * seg.pct_ftp / 100)
        lines.append(f"- {_format_duration(seg.minutes)} {watts}w")
    return "\n".join(lines)


def _format_duration(minutes: float) -> str:
    """
    Durée en syntaxe Intervals.icu : minutes entières, secondes en dessous.

    On arrondit à la minute au-delà d'une minute : "1224s" pour un
    échauffement est exact mais illisible, et la demi-minute d'écart n'a
    aucune portée sur un échauffement ou un retour au calme.
    """
    if minutes < 1:
        return f"{max(round(minutes * 60), 1)}s"
    return f"{max(round(minutes), 1)}m"


def build_event_payload(day: dict[str, Any], ftp: int) -> dict[str, Any] | None:
    """
    Prépare l'événement calendrier correspondant à une journée de plan.

    Renvoie None pour ce qui n'a pas sa place au calendrier vélo : jours de
    repos et séances hors vélo, qu'on n'a pas à transformer en sortie.
    """
    workout = workout_from_plan_day(day)
    if not workout.segments:
        return None

    date_str = day.get("date")
    if not date_str:
        return None

    name = day.get("type") or "Séance"
    description = to_workout_description(workout, ftp)

    return {
        "start_date_local": f"{date_str}T00:00:00",
        "category": "WORKOUT",
        "type": _DEFAULT_ACTIVITY_TYPE,
        "name": name,
        "description": description,
        "moving_time": int(round(workout.total_minutes * 60)),
        "icu_training_load": int(day.get("target_tss") or 0),
    }


def existing_planned_dates(start_date: str, end_date: str) -> set[str]:
    """Dates portant déjà une séance planifiée, pour ne rien écraser."""
    client = IntervalsClient()
    url = f"{client.base_url}/athlete/{client.athlete_id}/events"
    try:
        response = requests.get(
            url,
            params={"oldest": start_date, "newest": end_date},
            auth=client.auth,
            timeout=30,
        )
        response.raise_for_status()
        events = response.json()
    except Exception as e:
        logger.warning("Lecture du calendrier impossible: %s", e)
        raise

    return {
        (event.get("start_date_local") or "")[:10]
        for event in events
        if event.get("category") == "WORKOUT"
    }


def push_plan_to_calendar(
    plan: dict[str, Any],
    ftp: int,
    dry_run: bool = True,
    overwrite: bool = False,
) -> dict[str, Any]:
    """
    Envoie les séances d'un plan vers le calendrier Intervals.icu.

    dry_run=True (défaut) ne fait aucun appel d'écriture : il renvoie
    exactement ce qui serait créé, pour relecture avant validation.

    Les dates déjà occupées par une séance planifiée sont ignorées, sauf
    overwrite explicite — ajouter un doublon en silence sur un calendrier
    réel serait pire que de ne rien faire.
    """
    days = (plan.get("structured") or {}).get("days") or []
    payloads = [p for p in (build_event_payload(d, ftp) for d in days) if p]

    result: dict[str, Any] = {
        "to_create": payloads,
        "skipped_rest_or_off_bike": len(days) - len(payloads),
        "created": [],
        "skipped_existing": [],
        "errors": [],
        "dry_run": dry_run,
    }
    if not payloads:
        return result

    dates = sorted(p["start_date_local"][:10] for p in payloads)
    occupied = existing_planned_dates(dates[0], dates[-1]) if not overwrite else set()

    pending = []
    for payload in payloads:
        if payload["start_date_local"][:10] in occupied:
            result["skipped_existing"].append(payload["start_date_local"][:10])
        else:
            pending.append(payload)
    result["to_create"] = pending

    if dry_run:
        return result

    client = IntervalsClient()
    url = f"{client.base_url}/athlete/{client.athlete_id}/events"
    for payload in pending:
        try:
            response = requests.post(url, json=payload, auth=client.auth, timeout=30)
            response.raise_for_status()
            result["created"].append(payload["start_date_local"][:10])
            logger.info("Séance créée sur Intervals.icu : %s", payload["start_date_local"][:10])
        except Exception as e:
            logger.warning("Échec création %s: %s", payload["start_date_local"][:10], e)
            result["errors"].append({"date": payload["start_date_local"][:10], "error": str(e)})

    return result
