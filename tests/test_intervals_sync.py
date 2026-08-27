"""
Tests de l'export vers le calendrier Intervals.icu.

C'est le seul code du projet qui écrit chez un tiers, sur le vrai calendrier
de l'athlète. Les tests portent donc autant sur ce qui doit être envoyé que
sur ce qui ne doit jamais l'être : aucune écriture en simulation, aucun
écrasement d'une séance déjà planifiée.
"""
from __future__ import annotations

import pytest

from ai_coach import intervals_sync
from ai_coach.intervals_sync import (
    build_event_payload,
    push_plan_to_calendar,
    to_workout_description,
)
from ai_coach.workout import parse_workout

FTP = 310


def _day(**kwargs) -> dict:
    base = {
        "date": "2026-08-30", "type": "Seuil",
        "duration_min": 60, "target_tss": 80,
        "intensity": "2x20min @ 95% FTP",
    }
    base.update(kwargs)
    return base


def _plan(days: list[dict]) -> dict:
    return {"start_date": days[0]["date"], "structured": {"days": days}}


# --- Traduction en syntaxe Intervals.icu ---

def test_description_en_watts():
    workout = parse_workout("20min @ 100% FTP", duration_min=20)
    assert "310w" in to_workout_description(workout, FTP)


def test_durees_lisibles_en_minutes():
    """"1224s" est exact mais illisible pour un échauffement."""
    workout = parse_workout("2x8min @ 83% FTP", duration_min=60)
    description = to_workout_description(workout, FTP)
    assert "s " not in description  # aucune durée en secondes au-delà de la minute
    assert "m " in description


def test_intervalles_courts_restent_en_secondes():
    workout = parse_workout("6x30s @ 150% FTP", duration_min=45)
    assert "30s" in to_workout_description(workout, FTP)


def test_une_ligne_par_bloc():
    workout = parse_workout("3x5min @ 100% FTP", duration_min=60)
    lines = to_workout_description(workout, FTP).splitlines()
    assert len(lines) == len(workout.segments)
    assert all(line.startswith("- ") for line in lines)


# --- Construction de l'événement ---

def test_payload_complet():
    payload = build_event_payload(_day(), FTP)
    assert payload["category"] == "WORKOUT"
    assert payload["start_date_local"] == "2026-08-30T00:00:00"
    assert payload["icu_training_load"] == 80
    assert payload["moving_time"] > 0


def test_jour_de_repos_non_envoye():
    """Un jour de repos n'a rien à faire au calendrier comme séance."""
    assert build_event_payload(_day(type="Repos", intensity="Repos complet", duration_min=0), FTP) is None


def test_seance_hors_velo_non_envoyee():
    payload = build_event_payload(
        _day(type="Récupération", intensity="PPG étirements foam roller", duration_min=30), FTP
    )
    assert payload is None


def test_journee_sans_date_ignoree():
    assert build_event_payload(_day(date=None), FTP) is None


# --- Garde-fous d'écriture ---

def test_simulation_n_ecrit_rien(monkeypatch):
    """Le mode par défaut ne doit émettre aucune requête d'écriture."""
    monkeypatch.setattr(intervals_sync, "existing_planned_dates", lambda *a, **k: set())

    def _fail(*args, **kwargs):
        raise AssertionError("aucune écriture ne doit partir en simulation")

    monkeypatch.setattr(intervals_sync.requests, "post", _fail)

    result = push_plan_to_calendar(_plan([_day()]), ftp=FTP, dry_run=True)
    assert result["dry_run"] is True
    assert result["created"] == []
    assert len(result["to_create"]) == 1


def test_date_deja_occupee_est_ignoree(monkeypatch):
    """Ajouter un doublon en silence sur un vrai calendrier serait pire que rien."""
    monkeypatch.setattr(intervals_sync, "existing_planned_dates", lambda *a, **k: {"2026-08-30"})

    result = push_plan_to_calendar(_plan([_day(date="2026-08-30")]), ftp=FTP, dry_run=True)
    assert result["skipped_existing"] == ["2026-08-30"]
    assert result["to_create"] == []


def test_overwrite_ne_consulte_pas_le_calendrier(monkeypatch):
    def _fail(*args, **kwargs):
        raise AssertionError("overwrite ne doit pas dépendre du calendrier existant")

    monkeypatch.setattr(intervals_sync, "existing_planned_dates", _fail)
    result = push_plan_to_calendar(_plan([_day()]), ftp=FTP, dry_run=True, overwrite=True)
    assert len(result["to_create"]) == 1


def test_comptage_des_jours_non_envoyes(monkeypatch):
    monkeypatch.setattr(intervals_sync, "existing_planned_dates", lambda *a, **k: set())
    plan = _plan([
        _day(date="2026-08-30"),
        _day(date="2026-08-31", type="Repos", intensity="Repos complet", duration_min=0),
    ])
    result = push_plan_to_calendar(plan, ftp=FTP, dry_run=True)
    assert result["skipped_rest_or_off_bike"] == 1
    assert len(result["to_create"]) == 1


def test_plan_sans_structure():
    result = push_plan_to_calendar({"structured": {}}, ftp=FTP, dry_run=True)
    assert result["to_create"] == []
    assert result["created"] == []
