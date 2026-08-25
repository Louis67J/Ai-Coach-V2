"""
Tests de la classification des séances.

La classification alimente tout le reste (recherche du coach, répartition
des intensités, lecture de la méthode d'entraînement), et se trompe
silencieusement : une séance mal taguée reste plausible à l'œil.
"""
from __future__ import annotations

import pytest

from ai_coach.intervals import (
    _classify_by_hr_zones,
    _compute_stream_analysis,
    _needs_processing,
    _should_fetch_streams,
    _stream_effort_override,
    _zone_from_pct_ftp,
    CLASSIFICATION_VERSION,
    hr_zone_secs,
)


# --- Zones de puissance ---

@pytest.mark.parametrize(
    "pct_ftp, zone",
    [
        (40, "Z1"), (55, "Z1"), (56, "Z2"), (75, "Z2"), (76, "Z3"),
        (90, "Z3"), (91, "Z4"), (105, "Z4"), (106, "Z5"), (119, "Z5"),
        (120, "Z6"), (149, "Z6"), (150, "Z7"), (300, "Z7"),
    ],
)
def test_zone_from_pct_ftp_aux_bornes(pct_ftp, zone):
    assert _zone_from_pct_ftp(pct_ftp) == zone


# --- Analyse du flux de puissance ---

def test_stream_analysis_trouve_le_meilleur_effort_glissant():
    """Un effort de 5min noyé dans une sortie facile doit ressortir."""
    ftp = 300
    watts = [150] * 3600
    watts[1200:1500] = [400] * 300  # 5 minutes à 400W

    result = _compute_stream_analysis({"watts": watts}, ftp)

    best5 = result["power_bests"]["5min"]
    assert best5["watts"] == 400
    assert best5["start_s"] == 1200
    assert best5["zone"] == "Z6"


def test_stream_analysis_estime_les_zones():
    """Sert de repli quand icu_zone_times est absent."""
    result = _compute_stream_analysis({"watts": [150] * 1800 + [300] * 1800}, 300)
    assert result["zone_pct"]["Z1"] == 50  # 150W = 50% FTP → Z1
    assert result["zone_pct"]["Z4"] == 50  # 300W = 100% FTP → Z4


def test_stream_analysis_sans_donnees():
    assert _compute_stream_analysis({"watts": []}, 300) == {"power_bests": {}, "zone_pct": {}}


def test_stream_effort_override_detecte_un_test_5min():
    """Le cas réel : un test max de 5min qu'Intervals.icu n'isole pas en lap."""
    analysis = _compute_stream_analysis({"watts": [150] * 1200 + [400] * 300 + [150] * 1200}, 300)
    tag, desc = _stream_effort_override(analysis)
    assert tag == "VO2_PMA"
    assert "5min" in desc


def test_stream_effort_override_ignore_une_sortie_facile():
    """Une sortie tranquille ne doit pas être promue en séance d'intensité."""
    analysis = _compute_stream_analysis({"watts": [150] * 3600}, 300)
    assert _stream_effort_override(analysis) == (None, None)


# --- Zones de fréquence cardiaque ---

def test_hr_zone_secs_depuis_la_liste_api():
    """L'API renvoie une liste ordonnée Z1→Z7, pas des dicts comme pour la puissance."""
    detail = {"icu_hr_zone_times": [1834, 3041, 649, 310, 10, 0, 0]}
    assert hr_zone_secs(detail) == {"Z1": 1834.0, "Z2": 3041.0, "Z3": 649.0, "Z4": 310.0, "Z5": 10.0}


def test_hr_zone_secs_respecte_icu_ignore_hr():
    """Si l'athlète a invalidé la FC de la séance, on ne s'en sert pas."""
    detail = {"icu_hr_zone_times": [1000, 2000], "icu_ignore_hr": True}
    assert hr_zone_secs(detail) == {}


@pytest.mark.parametrize(
    "pct, expected",
    [
        ({"Z1": 31, "Z2": 52, "Z3": 11, "Z4": 5, "Z5": 1}, "ENDURANCE"),
        ({"Z1": 95, "Z2": 5}, "RECUP"),
        ({"Z1": 40, "Z2": 55, "Z3": 5}, "Z2_STRICT"),
        ({"Z1": 20, "Z2": 30, "Z3": 30, "Z4": 20}, "SEUIL"),
        ({"Z1": 20, "Z2": 30, "Z3": 40, "Z4": 10}, "TEMPO"),
        ({"Z1": 20, "Z2": 30, "Z3": 20, "Z4": 20, "Z5": 10}, "VO2_PMA"),
    ],
)
def test_classify_by_hr_zones(pct, expected):
    assert _classify_by_hr_zones(pct) == expected


def test_seuils_fc_plus_bas_que_puissance():
    """
    La FC est inerte : les efforts courts y laissent peu de trace. 8% de Z5
    cardiaque suffit donc à qualifier une séance de VO2max, là où il faut
    15% en puissance.
    """
    assert _classify_by_hr_zones({"Z1": 50, "Z2": 42, "Z5": 8}) == "VO2_PMA"
    assert _classify_by_hr_zones({"Z1": 50, "Z2": 43, "Z5": 7}) != "VO2_PMA"


# --- Décision de fetch et de retraitement ---

def test_pas_de_fetch_de_stream_sans_puissance():
    """Sans capteur de puissance, le stream n'apprend rien : requête économisée."""
    detail = {"type": "Ride", "icu_hr_zone_times": [1000, 2000]}
    assert _should_fetch_streams(detail) is False


def test_fetch_de_stream_si_zones_de_puissance_absentes():
    detail = {"type": "Ride", "icu_average_watts": 200, "icu_zone_times": []}
    assert _should_fetch_streams(detail) is True


def test_needs_processing_nouvelle_seance():
    assert _needs_processing(None) is True


def test_needs_processing_ignore_les_seances_bien_classifiees():
    assert _needs_processing({"tag": "SEUIL", "stream_checked": False}) is False


def test_needs_processing_reprend_apres_evolution_de_la_logique():
    """
    Sans ce garde-fou, les séances déjà traitées resteraient bloquées sur
    l'ancienne logique de classification.
    """
    ancienne = {"tag": "RIDE", "stream_checked": True, "classification_version": CLASSIFICATION_VERSION - 1}
    a_jour = {"tag": "RIDE", "stream_checked": True, "classification_version": CLASSIFICATION_VERSION}
    assert _needs_processing(ancienne) is True
    assert _needs_processing(a_jour) is False
