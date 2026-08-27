"""
Tests de l'interpréteur de séances.

Le dessin du profil est déduit du texte, pas produit par le LLM : il doit
donc être stable et ne rien inventer. Une mauvaise lecture donnerait une
forme plausible mais fausse — le pire cas, puisque rien ne la contredit
à l'écran.
"""
from __future__ import annotations

import pytest

from ai_coach.workout import ZONE_PCT, parse_workout, workout_from_plan_day


def _kinds(workout) -> list[str]:
    return [s.kind for s in workout.segments]


def _work_segments(workout):
    return [s for s in workout.segments if s.kind == "work"]


# --- Cas dégénérés ---

def test_jour_de_repos():
    w = parse_workout("Repos complet", duration_min=0, session_type="Repos")
    assert w.segments == []
    assert "repos" in w.notes[0].lower()


def test_duree_nulle():
    assert parse_workout("Z2", duration_min=0).segments == []


def test_seance_hors_velo_nest_pas_dessinee():
    """Une séance de PPG tracée en %FTP tromperait sur sa nature."""
    w = parse_workout(
        "PPG prévention (foam roller, étirements TFL/hanche)",
        duration_min=30, session_type="Récupération",
    )
    assert w.segments == []
    assert "hors vélo" in w.notes[0]


# --- Séances continues ---

def test_seance_continue_encadree():
    w = parse_workout("Z2 (65-75% FTP)", duration_min=90, session_type="Endurance")
    assert _kinds(w) == ["warmup", "steady", "cooldown"]
    assert w.total_minutes == pytest.approx(90, abs=0.2)


def test_seance_courte_sans_encadrement():
    w = parse_workout("Z1", duration_min=20, session_type="Récupération")
    assert _kinds(w) == ["steady"]


def test_zone_traduite_en_pourcentage():
    w = parse_workout("Z4", duration_min=20)
    assert w.segments[0].pct_ftp == ZONE_PCT["Z4"]


def test_fourchette_de_pourcentage_prend_le_milieu():
    w = parse_workout("75-85% FTP", duration_min=20)
    assert w.segments[0].pct_ftp == 80.0


def test_intensite_absente_est_signalee():
    """Mieux vaut dire qu'on a supposé que de laisser croire à une lecture."""
    w = parse_workout("sortie libre", duration_min=60, session_type="Sortie")
    assert w.understood is False
    assert w.notes


# --- Séances à intervalles ---

def test_repetitions_simples():
    w = parse_workout("4x8min @ 100% FTP", duration_min=75, session_type="Seuil")
    work = _work_segments(w)
    assert len(work) == 4
    assert all(s.minutes == 8 for s in work)
    assert all(s.pct_ftp == 100 for s in work)
    # Une récupération entre chaque effort, pas après le dernier
    assert len([s for s in w.segments if s.kind == "recovery"]) == 3


def test_deux_blocs_de_repetitions():
    w = parse_workout("2x8min tempo + 3x1min @ 90% FTP", duration_min=60, session_type="Activation")
    work = _work_segments(w)
    assert len(work) == 5
    assert sum(1 for s in work if s.minutes == 8) == 2
    assert sum(1 for s in work if s.minutes == 1) == 3


def test_repetitions_en_secondes():
    w = parse_workout("10x30s @ 150% FTP", duration_min=60, session_type="Sprint")
    work = _work_segments(w)
    assert len(work) == 10
    assert work[0].minutes == pytest.approx(0.5)


def test_duree_totale_respectee():
    """Le dessin ne doit pas déborder de la durée annoncée."""
    w = parse_workout("4x8min @ 100% FTP", duration_min=75)
    assert w.total_minutes == pytest.approx(75, abs=0.5)


def test_intervalles_plus_longs_que_la_seance_signales():
    w = parse_workout("10x10min @ 100% FTP", duration_min=30)
    assert w.notes


# --- Effort chronométré unique ---

def test_test_ftp_reste_un_bloc_borne():
    """
    Le cas qui clochait : "20min à fond" dans une séance d'une heure était
    étalé sur toute la séance, affichant une heure à 105% FTP.
    """
    w = parse_workout(
        "20min à fond maximum (objectif 315-325W)", duration_min=60, session_type="Test FTP"
    )
    work = _work_segments(w)
    assert len(work) == 1
    assert work[0].minutes == 20
    assert work[0].pct_ftp >= 100
    assert w.total_minutes == pytest.approx(60, abs=0.5)


def test_effort_couvrant_toute_la_seance_reste_continu():
    """"60min Z3" dans une séance d'1h est une séance continue, pas un intervalle."""
    w = parse_workout("60min Z3", duration_min=60)
    assert _kinds(w) == ["warmup", "steady", "cooldown"]


def test_bloc_facile_nest_pas_isole():
    """Un bloc peu intense ne justifie pas d'être détaché comme un effort."""
    w = parse_workout("30min Z2 tranquille", duration_min=90)
    assert _kinds(w) == ["warmup", "steady", "cooldown"]


# --- Entrée depuis un plan ---

def test_depuis_une_journee_de_plan():
    day = {
        "date": "2026-08-30", "type": "Test FTP",
        "duration_min": 60, "target_tss": 105,
        "intensity": "20min à fond maximum (objectif 315-325W)",
    }
    w = workout_from_plan_day(day)
    assert len(_work_segments(w)) == 1


def test_journee_de_plan_incomplete():
    assert workout_from_plan_day({}).segments == []
