"""
Tests de la couture multi-athlète.

Tout est mono-athlète aujourd'hui ; ce qui compte, c'est que les chemins de
données soient résolus à l'appel et non figés à l'import — sinon ouvrir
l'app à quelqu'un d'autre imposerait de reprendre chaque module.
"""
from __future__ import annotations

import pytest

from ai_coach import intervals, journal, memory, plan_tracker, profile, token_tracker, wellness
from ai_coach.config import (
    DATA_DIR,
    DEFAULT_ATHLETE,
    athlete_data_dir,
    athlete_path,
    current_athlete,
    set_current_athlete,
)


@pytest.fixture(autouse=True)
def _restore_athlete():
    """Aucun test ne doit laisser l'athlète courant modifié."""
    original = current_athlete()
    yield
    set_current_athlete(original)


def test_athlete_par_defaut_garde_la_racine_data():
    """Les fichiers existants ne doivent pas bouger pour l'installation actuelle."""
    assert athlete_data_dir(DEFAULT_ATHLETE) == DATA_DIR
    assert athlete_path("profile.json", DEFAULT_ATHLETE) == DATA_DIR / "profile.json"


def test_autre_athlete_est_isole():
    assert athlete_data_dir("bob") == DATA_DIR / "athletes" / "bob"
    assert athlete_path("profile.json", "bob") != athlete_path("profile.json", DEFAULT_ATHLETE)


# Tous les chemins de données du projet, pour vérifier qu'aucun n'a été oublié
PATH_FUNCS = [
    intervals.activities_cache_path,
    intervals.sessions_cache_path,
    profile.profile_path,
    memory.conversations_path,
    memory.summary_path,
    plan_tracker.plans_path,
    journal.journal_path,
    wellness.wellness_cache_path,
    token_tracker.tracker_path,
]


@pytest.mark.parametrize("path_func", PATH_FUNCS, ids=lambda f: f.__name__)
def test_chaque_chemin_suit_l_athlete_courant(path_func):
    """
    Un chemin figé à l'import ne bougerait pas en changeant d'athlète : c'est
    exactement ce que cette couture doit empêcher.
    """
    default_path = path_func()

    set_current_athlete("bob")
    bob_path = path_func()

    assert bob_path != default_path, f"{path_func.__name__} ignore l'athlète courant"
    assert bob_path.name == default_path.name  # même fichier, dossier différent
    assert "bob" in str(bob_path)


def test_rag_suit_aussi_l_athlete_courant():
    from ai_coach.rag import rag_dir

    default_dir = rag_dir()
    set_current_athlete("bob")
    assert rag_dir() != default_dir


def test_set_current_athlete_vide_revient_au_defaut():
    set_current_athlete("")
    assert current_athlete() == DEFAULT_ATHLETE
