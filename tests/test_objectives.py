"""
Tests de la gestion des objectifs.

Les objectifs pilotent tout le raisonnement du coach : sans eux il n'a rien
vers quoi construire, et s'il croit qu'une course passée est encore à venir
il planifie un affûtage pour un événement déjà couru.
"""
from __future__ import annotations

from datetime import date

from ai_coach.profile import (
    OBJECTIVES_KEY,
    format_profile_for_llm,
    get_objectives,
    set_objectives,
    split_objectives,
)


def _obj(name: str, day: str, priority: str = "A") -> dict:
    return {"name": name, "date": day, "priority": priority, "type": "cyclosportive"}


def test_lecture_de_la_cle_neutre():
    profile = {OBJECTIVES_KEY: [_obj("GFNY", "2027-05-25")]}
    assert get_objectives(profile)[0]["name"] == "GFNY"


def test_lecture_des_anciennes_cles_de_saison():
    """L'ancien format ne doit pas être perdu au passage à la clé neutre."""
    profile = {"season_2026_objectives": [_obj("GFNY", "2026-05-25")]}
    assert get_objectives(profile)[0]["name"] == "GFNY"


def test_fusion_de_plusieurs_saisons():
    profile = {
        "season_2025_objectives": [_obj("Ancienne", "2025-06-01")],
        "season_2026_objectives": [_obj("Récente", "2026-05-25")],
    }
    names = [o["name"] for o in get_objectives(profile)]
    assert names == ["Ancienne", "Récente"]  # triés par date


def test_objectifs_tries_par_date():
    profile = {OBJECTIVES_KEY: [_obj("Tardif", "2027-09-01"), _obj("Tôt", "2027-03-01")]}
    assert [o["name"] for o in get_objectives(profile)] == ["Tôt", "Tardif"]


def test_ecriture_supprime_les_anciennes_cles():
    """Sans ça, les deux formats coexisteraient et se contrediraient."""
    profile = {"season_2026_objectives": [_obj("Vieux", "2026-05-25")]}
    set_objectives(profile, [_obj("Neuf", "2027-05-25")])
    assert "season_2026_objectives" not in profile
    assert profile[OBJECTIVES_KEY][0]["name"] == "Neuf"


def test_separation_passe_futur():
    objectives = [_obj("Passé", "2026-05-01"), _obj("Futur", "2026-12-01")]
    upcoming, past = split_objectives(objectives, today=date(2026, 8, 25))
    assert [o["name"] for o in upcoming] == ["Futur"]
    assert [o["name"] for o in past] == ["Passé"]


def test_objectif_du_jour_compte_comme_a_venir():
    """Le jour J, la course n'est pas derrière soi."""
    upcoming, past = split_objectives([_obj("Aujourd'hui", "2026-08-25")], today=date(2026, 8, 25))
    assert len(upcoming) == 1
    assert past == []


def test_prompt_distingue_passe_et_futur():
    """
    Le coach recevait les objectifs sans marque temporelle et préparait
    encore une course écoulée depuis trois mois.
    """
    profile = {
        OBJECTIVES_KEY: [
            _obj("Course passée", (date.today().replace(year=date.today().year - 1)).isoformat()),
            _obj("Course future", (date.today().replace(year=date.today().year + 1)).isoformat()),
        ]
    }
    text = format_profile_for_llm(profile)
    assert "Objectifs À VENIR" in text
    assert "Objectifs PASSÉS" in text
    assert text.index("Course future") < text.index("Course passée")


def test_prompt_signale_absence_dobjectif_futur():
    profile = {OBJECTIVES_KEY: [_obj("Vieux", "2020-01-01")]}
    assert "Aucun objectif futur" in format_profile_for_llm(profile)


def test_profil_sans_objectif():
    assert get_objectives({}) == []
