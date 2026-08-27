"""
Tests de la lecture du profil de coureur.

Le barème Coggan classait l'athlète "Excellent" sur quatre durées sur cinq
et ne listait aucune faiblesse : flatteur, mais rigoureusement inexploitable
pour décider quoi travailler. Ce qui compte est l'écart d'une durée au niveau
propre de l'athlète.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from ai_coach.analysis import coggan_score, compute_rider_shape


def _profile(**durations: float) -> dict:
    """Construit un power_profile minimal {durée: W/kg}."""
    return {
        "profile": {
            d: {"w_kg": wkg, "watts": int(wkg * 63), "level": "?"}
            for d, wkg in durations.items()
        }
    }


# --- Score continu ---

def test_score_aux_paliers_nommes():
    assert coggan_score("5min", 5.5) == 70.0    # seuil "Excellent"
    assert coggan_score("5min", 6.5) == 85.0    # seuil "Exceptionnel"


def test_score_interpole_entre_paliers():
    score = coggan_score("5min", 6.0)  # à mi-chemin entre 5.5 et 6.5
    assert 76 < score < 79


def test_score_plafonne_au_sommet():
    assert coggan_score("5s", 30.0) == 100.0


def test_score_sous_le_dernier_palier():
    score = coggan_score("5min", 1.75)  # moitié du seuil "Moyen" (3.5)
    assert 0 <= score <= 15


def test_score_durees_comparables_entre_elles():
    """
    Même niveau nommé sur deux durées ⇒ même score, alors que les W/kg
    diffèrent du simple au triple. C'est tout l'intérêt de l'échelle.
    """
    assert coggan_score("5s", 17.0) == coggan_score("60min", 4.6)


def test_score_duree_inconnue():
    assert coggan_score("42min", 5.0) is None


# --- Forme du coureur ---

def test_profil_explosif():
    shape = compute_rider_shape(_profile(**{"5s": 20.0, "1min": 9.5, "5min": 5.5, "20min": 4.3, "60min": 3.4}))
    assert "explosif" in shape["archetype"]
    assert shape["orientation_delta"] > 0


def test_profil_rouleur():
    shape = compute_rider_shape(_profile(**{"5s": 11.0, "1min": 5.5, "5min": 5.5, "20min": 5.6, "60min": 5.2}))
    assert shape["archetype"] == "rouleur / grimpeur"
    assert shape["orientation_delta"] < 0


def test_profil_polyvalent():
    """Même niveau relatif partout : aucune orientation à annoncer."""
    shape = compute_rider_shape(_profile(**{"5s": 17.0, "1min": 8.0, "5min": 5.5, "20min": 5.0, "60min": 4.6}))
    assert shape["archetype"] == "polyvalent"
    assert shape["relative_strengths"] == []
    assert shape["relative_weaknesses"] == []


def test_faiblesse_relative_malgre_un_bon_niveau_absolu():
    """
    Le cas qui motivait tout ça : "Excellent" partout, et pourtant un creux
    net sur une durée. L'ancien affichage ne le voyait pas.
    """
    shape = compute_rider_shape(_profile(**{"5s": 17.02, "1min": 8.74, "5min": 5.79, "20min": 5.07, "60min": 4.19}))
    assert shape["relative_weaknesses"] == ["60min"]
    assert shape["deltas"]["60min"] < -6


def test_donnees_insuffisantes():
    assert compute_rider_shape(_profile(**{"5s": 17.0}))["status"] == "insufficient_data"
    assert compute_rider_shape({})["status"] == "insufficient_data"


# --- Fraîcheur des records ---

def _profile_with_dates(dates: dict[str, str]) -> dict:
    base = _profile(**{"5s": 17.02, "1min": 8.74, "5min": 5.79, "20min": 5.07, "60min": 4.19})
    for duration, day in dates.items():
        base["profile"][duration]["date"] = day
    return base


def test_creux_sur_record_ancien_est_signale():
    """Une durée jamais testée paraît faible sans l'être : à dire, pas à corriger."""
    old = (date.today() - timedelta(days=300)).isoformat()
    shape = compute_rider_shape(_profile_with_dates({"60min": old}))
    assert shape["relative_weaknesses"] == ["60min"]
    assert any("60min" in c for c in shape["caveats"])


def test_creux_sur_record_recent_nest_pas_signale():
    recent = (date.today() - timedelta(days=20)).isoformat()
    shape = compute_rider_shape(_profile_with_dates({"60min": recent}))
    assert shape["relative_weaknesses"] == ["60min"]
    assert shape["caveats"] == []


def test_absence_de_date_ne_plante_pas():
    shape = compute_rider_shape(_profile(**{"5s": 17.0, "1min": 8.0, "5min": 5.5, "20min": 5.0, "60min": 4.6}))
    assert shape["caveats"] == []


# --- Durées non testées (modèle de puissance critique) ---

_MODELS = {"MS_2P": {"cp": 296.0, "w_prime": 16200.0}}


def _profile_with_models(watts: dict[str, int]) -> dict:
    """power_profile avec watts explicites et modèles CP/W'."""
    return {
        "profile": {
            d: {"watts": w, "w_kg": w / 63, "level": "?"} for d, w in watts.items()
        },
        "power_models": _MODELS,
    }


def test_effort_60min_non_maximal_est_detecte():
    """
    Cas réel : les sorties all-out de l'athlète durent moins d'une heure,
    donc aucune fenêtre de 60min n'existe à pleine intensité. Le "meilleur
    60min" décrit une sortie tranquille, pas une capacité.
    """
    from ai_coach.analysis import detect_untested_durations

    profile = _profile_with_models({"5min": 359, "20min": 309, "60min": 260})["profile"]
    untested = detect_untested_durations(profile, _MODELS)
    assert "60min" in untested
    assert untested["60min"]["gap_pct"] < -10


def test_effort_20min_maximal_nest_pas_ecarte():
    """Le 20min colle à la prédiction du modèle : c'est un vrai test."""
    from ai_coach.analysis import detect_untested_durations

    profile = _profile_with_models({"5min": 359, "20min": 309, "60min": 260})["profile"]
    assert "20min" not in detect_untested_durations(profile, _MODELS)


def test_durees_courtes_jamais_ecartees():
    """Sous 5min l'anaérobie domine : le modèle CP n'y est pas une référence."""
    from ai_coach.analysis import detect_untested_durations

    profile = _profile_with_models({"5s": 100, "1min": 100, "20min": 309})["profile"]
    untested = detect_untested_durations(profile, _MODELS)
    assert "5s" not in untested and "1min" not in untested


def test_sans_modele_aucune_duree_ecartee():
    from ai_coach.analysis import detect_untested_durations

    profile = _profile_with_models({"60min": 100})["profile"]
    assert detect_untested_durations(profile, None) == {}


def test_duree_non_testee_exclue_de_la_forme():
    """
    Sans exclusion, un 60min non testé faisait conclure à tort à un profil
    explosif avec l'endurance comme point faible.
    """
    shape = compute_rider_shape(_profile_with_models(
        {"5s": 1055, "1min": 542, "5min": 359, "20min": 309, "60min": 260}
    ))
    assert "60min" not in shape["scores"]
    assert "60min" in shape["untested"]
    assert "60min" not in shape["relative_weaknesses"]


def test_lecture_partielle_est_annoncee():
    """Annoncer un profil équilibré sans avoir mesuré la longue durée serait faux."""
    shape = compute_rider_shape(_profile_with_models(
        {"5s": 1055, "1min": 542, "5min": 359, "20min": 309, "60min": 260}
    ))
    assert "lecture partielle" in shape["archetype"]
    assert "60min" in shape["comment"]
