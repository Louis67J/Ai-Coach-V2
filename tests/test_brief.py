"""
Tests du brief proactif.

Le brief part tout seul : personne ne le relit avant envoi. Les deux modes
d'échec qui comptent sont donc l'absence de brief et, surtout, le brief
envoyé plusieurs fois — le bot peut redémarrer plusieurs fois par jour.
"""
from __future__ import annotations

import pytest

from ai_coach import brief
from ai_coach.config import current_athlete, set_current_athlete


@pytest.fixture(autouse=True)
def _isolated_athlete():
    """
    Chaque test écrit son propre état de brief : on bascule sur un athlète
    jetable pour ne jamais toucher le fichier réel.
    """
    original = current_athlete()
    set_current_athlete("test-brief")
    path = brief.brief_state_path()
    if path.exists():
        path.unlink()
    yield
    if path.exists():
        path.unlink()
    set_current_athlete(original)


def test_premier_brief_de_la_journee_est_autorise():
    assert brief.should_send("daily") is True


def test_pas_deux_briefs_le_meme_jour():
    """Un redémarrage du bot après l'heure prévue ne doit pas en renvoyer un."""
    brief.mark_brief_sent("daily")
    assert brief.should_send("daily") is False


def test_nouveau_jour_reautorise_le_brief():
    brief.mark_brief_sent("daily", day="2026-08-24")
    assert brief.should_send("daily", today="2026-08-25") is True


def test_les_types_de_brief_sont_independants():
    brief.mark_brief_sent("daily")
    assert brief.should_send("weekly") is True


def test_etat_corrompu_ne_bloque_pas_le_brief():
    """Mieux vaut un brief en trop qu'un silence dû à un fichier illisible."""
    brief.brief_state_path().write_text("{ pas du json", encoding="utf-8")
    assert brief.should_send("daily") is True


def test_last_brief_date_sans_etat():
    assert brief.last_brief_date("daily") is None
