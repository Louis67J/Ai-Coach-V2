"""
Tests de la résolution de lieu.

La météo pilote les recommandations du coach (indoor ou dehors, chaleur,
vent). Un lieu faux ne se voit pas : les prévisions restent plausibles,
elles décrivent juste une autre ville.
"""
from __future__ import annotations

from ai_coach.profile import resolve_location


def test_lieu_par_defaut_est_la_base():
    profile = {"context": {"base_location": "Grenoble", "latitude": 45.19, "longitude": 5.72}}
    location = resolve_location(profile)
    assert location["name"] == "Grenoble"
    assert location["is_away"] is False


def test_deplacement_prend_le_pas_sur_la_base():
    profile = {
        "context": {
            "base_location": "Grenoble",
            "latitude": 45.19,
            "longitude": 5.72,
            "current_location": {"name": "Sagunto", "latitude": 39.68, "longitude": -0.27},
        }
    }
    location = resolve_location(profile)
    assert location["name"] == "Sagunto"
    assert location["latitude"] == 39.68
    assert location["is_away"] is True


def test_deplacement_incomplet_retombe_sur_la_base():
    """Un lieu sans coordonnées ne doit pas produire une météo au large de l'Afrique."""
    profile = {
        "context": {
            "base_location": "Grenoble",
            "latitude": 45.19,
            "longitude": 5.72,
            "current_location": {"name": "Quelque part"},
        }
    }
    location = resolve_location(profile)
    assert location["name"] == "Grenoble"
    assert location["is_away"] is False


def test_longitude_negative_est_conservee():
    """L'ouest de Greenwich est négatif : un abs() malencontreux enverrait en Asie."""
    profile = {"context": {"current_location": {"name": "Sagunto", "latitude": 39.68, "longitude": -0.27}}}
    assert resolve_location(profile)["longitude"] == -0.27


def test_retour_a_la_base_apres_effacement():
    profile = {
        "context": {
            "base_location": "Grenoble",
            "latitude": 45.19,
            "longitude": 5.72,
            "current_location": None,
        }
    }
    assert resolve_location(profile)["is_away"] is False


def test_profil_vide_ne_plante_pas():
    location = resolve_location({})
    assert location["latitude"] and location["longitude"]
