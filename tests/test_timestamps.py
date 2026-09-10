"""
Horodatage : on écrit en UTC, on affiche en heure locale.

Le défaut d'origine : un échange enregistré à 12h08 à Sagunto s'affichait
« 10:08 » dans !history, parce que le timestamp UTC était tronqué et montré
tel quel. Ces tests figent les deux moitiés du contrat.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from ai_coach.config import to_local_display, utc_now_iso


def test_utc_now_iso_est_bien_en_utc():
    ts = utc_now_iso()
    assert ts.endswith("Z")
    parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    # Le datetime porte réellement son fuseau : c'est ce que utcnow() ne
    # faisait pas (il renvoyait un naïf qu'on suffixait « Z » à la main).
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0
    ecart = abs((datetime.now(timezone.utc) - parsed).total_seconds())
    assert ecart < 60


def test_affichage_decale_du_bon_nombre_d_heures():
    """La conversion doit décaler de l'offset réel de la machine, pas de zéro.

    Formulé sans coder un fuseau en dur : la même assertion tient sur le
    portable de Louis (CEST) et sur une CI en UTC, où le décalage vaut 0.
    """
    instant = datetime(2026, 9, 10, 10, 8, 31, tzinfo=timezone.utc)
    offset = instant.astimezone().utcoffset()

    affiche = datetime.strptime(to_local_display("2026-09-10T10:08:31Z"), "%Y-%m-%d %H:%M")
    brut = datetime(2026, 9, 10, 10, 8)

    assert affiche - brut == timedelta(seconds=int(offset.total_seconds()))


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="tzset absent sous Windows")
def test_affichage_en_heure_de_madrid():
    """Le cas concret : 10h08 UTC en septembre se lit 12h08 à Sagunto."""
    ancien_tz = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "Europe/Madrid"
        time.tzset()
        assert to_local_display("2026-09-10T10:08:31.123456Z") == "2026-09-10 12:08"
    finally:
        if ancien_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = ancien_tz
        time.tzset()


def test_horodatage_sans_fuseau_est_suppose_utc():
    """L'historique déjà sur disque n'a pas toujours de suffixe explicite."""
    avec = to_local_display("2026-09-10T10:08:31Z")
    sans = to_local_display("2026-09-10T10:08:31")
    assert avec == sans


def test_ligne_abimee_ne_fait_pas_planter_l_affichage():
    # !history doit rester lisible même si une ligne du journal est corrompue.
    assert to_local_display("pas une date") == "pas une date"
    assert to_local_display("?") == "?"
    assert to_local_display(None) == "None"


def test_format_sur_disque_inchange(tmp_path, monkeypatch):
    """Le passage à utc_now_iso ne doit pas changer ce qu'on écrit."""
    monkeypatch.setattr("ai_coach.config._current_athlete", "test_ts", raising=False)
    from ai_coach import memory

    monkeypatch.setattr(memory, "conversations_path", lambda: tmp_path / "conv.jsonl")
    memory.append_exchange("q", "a", source="test")

    entry = json.loads((tmp_path / "conv.jsonl").read_text(encoding="utf-8"))
    ts = entry["timestamp"]
    assert ts.endswith("Z")
    assert ts[10] == "T"
    # Les lecteurs existants tronquent à [:10] et [:19] : ces découpes doivent
    # rester valides.
    assert datetime.fromisoformat(ts[:19])
