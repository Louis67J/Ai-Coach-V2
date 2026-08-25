"""
Tests de la boucle plan ↔ réalisé.

Le plan structuré est ce qui rend l'adhérence mesurable ; s'il est mal
extrait ou mal compté, le coach recalibre le bloc suivant sur des chiffres
faux — un mode d'échec invisible depuis l'interface.
"""
from __future__ import annotations

from datetime import date, timedelta

from ai_coach.coach import _extract_structured_plan
from ai_coach.plan_tracker import compute_plan_adherence


def _day(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


# --- Extraction du plan structuré ---

def test_extraction_du_bloc_json():
    texte = (
        "Voici ton plan.\n\nLundi: repos.\n\n"
        '```json\n{"days": [{"date": "2026-08-25", "type": "Repos", "target_tss": 0}]}\n```\n'
    )
    prose, structured = _extract_structured_plan(texte)

    assert len(structured["days"]) == 1
    assert structured["days"][0]["type"] == "Repos"
    # Le JSON ne doit pas rester visible dans le plan affiché à l'athlète
    assert "```json" not in prose
    assert "Lundi: repos." in prose


def test_extraction_sans_bloc_json():
    """Sans bloc structuré on garde le texte tel quel plutôt que de perdre le plan."""
    prose, structured = _extract_structured_plan("Plan libre sans JSON.")
    assert prose == "Plan libre sans JSON."
    assert structured == {}


def test_extraction_json_malforme():
    texte = 'Plan.\n```json\n{"days": [ceci n\'est pas du json}\n```'
    prose, structured = _extract_structured_plan(texte)
    assert structured == {}
    assert prose == texte  # on ne mutile pas la réponse


def test_extraction_rejette_un_json_sans_days():
    prose, structured = _extract_structured_plan('Plan.\n```json\n{"autre": 1}\n```')
    assert structured == {}


# --- Adhérence ---

def _activity(day_offset: int, tss: int) -> dict:
    return {
        "start_date_local": _day(day_offset),
        "icu_training_load": tss,
        "moving_time": 3600,
    }


def test_adherence_ne_compte_pas_le_jour_en_cours():
    """
    Le bug d'origine : un plan généré le matin était noté "très peu suivi"
    avant même que la journée ait eu lieu.
    """
    plan = {
        "start_date": _day(0),
        "structured": {"days": [{"date": _day(0), "type": "Seuil", "target_tss": 95}]},
    }
    result = compute_plan_adherence(plan, [])

    assert result["days_completed"] == 0
    assert result["sessions_missed"] == 0
    assert result.get("adherence_pct") is None
    assert "démarré" in result["verdict"]


def test_adherence_plan_suivi():
    plan = {
        "start_date": _day(-3),
        "structured": {
            "days": [
                {"date": _day(-3), "type": "Endurance", "target_tss": 80},
                {"date": _day(-2), "type": "Seuil", "target_tss": 100},
            ]
        },
    }
    activities = [_activity(-3, 80), _activity(-2, 100)]
    result = compute_plan_adherence(plan, activities)

    assert result["adherence_pct"] == 100
    assert result["sessions_done"] == 2
    assert result["sessions_missed"] == 0
    assert "suivi" in result["verdict"]


def test_adherence_seance_manquee():
    plan = {
        "start_date": _day(-2),
        "structured": {
            "days": [
                {"date": _day(-2), "type": "Endurance", "target_tss": 100},
                {"date": _day(-1), "type": "Seuil", "target_tss": 100},
            ]
        },
    }
    result = compute_plan_adherence(plan, [_activity(-2, 100)])  # rien fait hier

    assert result["sessions_done"] == 1
    assert result["sessions_missed"] == 1
    assert result["adherence_pct"] == 50


def test_adherence_jour_de_repos_non_compte_comme_manque():
    """Un repos prescrit et respecté n'est ni "fait" ni "manqué"."""
    plan = {
        "start_date": _day(-1),
        "structured": {"days": [{"date": _day(-1), "type": "Repos", "target_tss": 0}]},
    }
    result = compute_plan_adherence(plan, [])
    assert result["sessions_missed"] == 0
    assert result["sessions_done"] == 0


def test_adherence_sans_plan_structure():
    """Les plans d'avant le suivi structuré doivent être signalés, pas plantés."""
    result = compute_plan_adherence({"start_date": _day(-5), "plan_text": "..."}, [])
    assert result["status"] == "no_structured_plan"
