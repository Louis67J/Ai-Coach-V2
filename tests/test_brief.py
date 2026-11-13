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


# --- Rattrapage au démarrage ---

def test_rattrapage_si_heure_passee_et_aucun_brief():
    """Démarrer le bot à 10h ne doit pas faire attendre le lendemain."""
    from datetime import datetime

    assert brief.missed_today(7, 0, now=datetime(2026, 8, 28, 10, 30)) is True


def test_pas_de_rattrapage_avant_l_heure():
    """Avant l'heure prévue, c'est à la boucle planifiée de s'en charger."""
    from datetime import datetime

    assert brief.missed_today(7, 0, now=datetime(2026, 8, 28, 6, 59)) is False


def test_pas_de_rattrapage_si_deja_envoye():
    """Un redémarrage en milieu de journée ne doit pas renvoyer le brief."""
    from datetime import datetime

    brief.mark_brief_sent("daily", day="2026-08-28")
    assert brief.missed_today(7, 0, now=datetime(2026, 8, 28, 10, 30)) is False


def test_rattrapage_a_l_heure_pile():
    from datetime import datetime

    assert brief.missed_today(7, 0, now=datetime(2026, 8, 28, 7, 0)) is True


def test_heure_du_brief_suit_tz(monkeypatch):
    """
    discord.py lit une heure sans fuseau comme de l'UTC : sur un serveur en
    UTC, le brief de 7 h partirait à 8 h ou 9 h à Paris.
    """
    from datetime import datetime

    monkeypatch.setenv("TZ", "Europe/Paris")
    t = brief.brief_time(7, 30)
    assert (t.hour, t.minute) == (7, 30)
    assert t.tzinfo is not None
    # Le fuseau nommé suit l'heure d'été, contrairement à un décalage fixe
    assert t.tzinfo.utcoffset(datetime(2026, 1, 15)).total_seconds() == 3600
    assert t.tzinfo.utcoffset(datetime(2026, 7, 15)).total_seconds() == 7200


def test_heure_du_brief_sans_tz_garde_un_fuseau(monkeypatch):
    monkeypatch.delenv("TZ", raising=False)
    assert brief.brief_time(7).tzinfo is not None


def test_tz_inconnu_ne_casse_pas_le_bot(monkeypatch):
    monkeypatch.setenv("TZ", "Pas/UnFuseau")
    assert brief.brief_time(7).tzinfo is not None
