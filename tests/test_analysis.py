"""
Tests des fonctions de calcul.

Ces fonctions produisent des chiffres qu'on lit sans les recouper : une
erreur y est silencieuse et oriente les décisions d'entraînement. Trois
d'entre elles étaient effectivement fausses (comparaison FTP biaisée,
période de durabilité inversée, jour en cours compté comme raté) et n'ont
été repérées qu'à l'œil — d'où ces tests.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from ai_coach.analysis import (
    _parse_hours_target,
    _session_zone_secs,
    compute_durability_index,
    compute_fitness_projection_from_plan,
    compute_ftp_trend,
    compute_volume_vs_target,
    compute_zone_distribution,
)


def _days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


# --- Objectif de volume hebdomadaire ---

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("8-14h", (8.0, 14.0)),   # le format réellement présent dans le profil
        ("10h", (10.0, 10.0)),
        ("8 - 14", (8.0, 14.0)),
        (12, (12.0, 12.0)),
        (10.5, (10.5, 10.5)),
        (None, None),
        ("", None),
        ("beaucoup", None),
    ],
)
def test_parse_hours_target(raw, expected):
    assert _parse_hours_target(raw) == expected


def test_volume_vs_target_exclut_la_semaine_en_cours():
    """La semaine en cours est incomplète : la compter tirerait la moyenne vers le bas."""
    activities = [
        {"start_date_local": _days_ago(n), "moving_time": 3600, "icu_training_load": 50}
        for n in range(0, 40)
    ]
    result = compute_volume_vs_target(activities, "8-14h", weeks=4)

    today = date.today()
    for row in result["weekly"]:
        assert date.fromisoformat(row["week_ending"]) < today


def test_volume_vs_target_verdict_sous_objectif():
    # 1h par semaine, très en dessous d'une cible 8-14h
    activities = [
        {"start_date_local": _days_ago(7 * n + 3), "moving_time": 3600, "icu_training_load": 40}
        for n in range(1, 6)
    ]
    result = compute_volume_vs_target(activities, "8-14h", weeks=4)
    assert result["target_min_hours"] == 8.0
    assert result["avg_weekly_hours"] < 8
    assert "sous l'objectif" in result["verdict"]
    assert result["weeks_in_target"] == 0


def test_volume_vs_target_sans_objectif_defini():
    activities = [{"start_date_local": _days_ago(10), "moving_time": 7200, "icu_training_load": 80}]
    result = compute_volume_vs_target(activities, None, weeks=4)
    assert "verdict" not in result
    assert result["avg_weekly_hours"] > 0


# --- Durabilité ---

def test_durability_periode_dans_lordre_chronologique():
    """La période s'affichait à l'envers (fin → début)."""
    sessions = [
        {
            "type": "Ride", "moving_time_s": 9000, "np_watts": 250, "avg_watts": 230,
            "date": d, "decoupling_pct": 5.0, "variability_index": 1.05,
        }
        for d in ("2024-02-03", "2025-06-15", "2026-08-21")
    ]
    result = compute_durability_index(sessions)
    start, end = result["period"].split(" → ")
    assert start == "2024-02-03"
    assert end == "2026-08-21"
    assert start < end


def test_durability_pas_assez_de_sorties_longues():
    sessions = [{"type": "Ride", "moving_time_s": 9000, "np_watts": 250, "avg_watts": 230, "date": "2026-01-01"}]
    assert compute_durability_index(sessions)["status"] == "insufficient_data"


# --- Tendance FTP ---

def _ftp_session(days_ago: int, ftp: int) -> dict:
    return {"type": "Ride", "date": _days_ago(days_ago), "rolling_ftp": ftp, "name": "x"}


def test_ftp_trend_ne_compare_pas_a_tout_lhistorique():
    """
    Le bug d'origine : les 90 derniers jours (peu de séances) étaient comparés
    à TOUT l'historique antérieur (beaucoup), donc le meilleur du gros
    échantillon gagnait mécaniquement et le verdict annonçait une régression
    imaginaire.

    Ici le niveau réel est identique sur les deux fenêtres de 90 jours ; seul
    un passé plus ancien et plus fourni contient des pics plus hauts. Comparer
    à ce passé produirait un faux "en régression".
    """
    recent = [_ftp_session(d, w) for d, w in [(10, 300), (30, 295), (50, 290), (70, 285)]]
    previous = [_ftp_session(d, w) for d, w in [(95, 300), (120, 295), (150, 290), (170, 285)]]
    # Passé plus ancien, hors des deux fenêtres et hors de la fenêtre "l'an
    # dernier" (365-455j) : beaucoup de points, avec des pics nettement plus hauts
    vieux = [_ftp_session(d, 330 if d % 20 == 0 else 280) for d in range(185, 355, 5)]

    result = compute_ftp_trend(recent + previous + vieux)

    assert result["previous"]["count"] == len(previous)  # fenêtre bornée, pas tout le passé
    assert result["delta_vs_previous"] == 0  # même niveau réel ⇒ aucun écart
    assert result["trend"] == "stable →"


def test_ftp_trend_egalise_la_taille_des_echantillons():
    """Top-N identique des deux côtés, sinon la fenêtre la plus fournie gagne."""
    recent = [_ftp_session(d, 300) for d in (10, 30, 50)]
    previous = [_ftp_session(d, 300) for d in range(95, 175, 3)]
    result = compute_ftp_trend(recent + previous)
    assert result["top_n_used"] == len(recent)


def test_ftp_trend_detecte_une_vraie_progression():
    recent = [_ftp_session(d, 320) for d in (10, 20, 30, 40)]
    previous = [_ftp_session(d, 280) for d in (100, 110, 120, 130)]
    result = compute_ftp_trend(recent + previous)
    assert result["delta_vs_previous"] == 40
    assert "progression" in result["trend"]


def test_ftp_trend_sans_fenetre_comparable():
    """Sans période antérieure comparable, on ne prononce pas de verdict."""
    recent = [_ftp_session(d, 300) for d in (5, 15, 25, 35, 45)]
    result = compute_ftp_trend(recent)
    assert result.get("delta_vs_previous") is None
    assert result["trend"] == "pas de fenêtre comparable de même durée"


def test_ftp_trend_donnees_insuffisantes():
    assert compute_ftp_trend([])["status"] == "insufficient_data"


# --- Répartition des intensités ---

def test_session_zone_secs_reconstruit_depuis_le_resume_texte():
    """Les séances enrichies avant l'ajout de zone_secs doivent rester exploitables."""
    session = {"zones": "Z1:50% | Z2:50%", "moving_time_s": 3600}
    assert _session_zone_secs(session) == {"Z1": 1800.0, "Z2": 1800.0}


def test_session_zone_secs_prefere_les_secondes_brutes():
    session = {"zone_secs": {"Z1": 600, "Z2": 1200}, "zones": "Z1:50% | Z2:50%", "moving_time_s": 3600}
    assert _session_zone_secs(session) == {"Z1": 600.0, "Z2": 1200.0}


def test_zone_distribution_polarise():
    """Beaucoup de facile, très peu de milieu, une vraie part de haut."""
    sessions = [{
        "date": _days_ago(5), "moving_time_s": 10000,
        "zone_secs": {"Z1": 4000, "Z2": 4000, "Z3": 300, "Z5": 1700},
    }]
    result = compute_zone_distribution(sessions, days=90)
    assert result["model"] == "polarisé"
    assert result["high_pct"] > result["mid_pct"]


def test_zone_distribution_pyramidal():
    sessions = [{
        "date": _days_ago(5), "moving_time_s": 10000,
        "zone_secs": {"Z1": 4000, "Z2": 4000, "Z3": 1800, "Z5": 200},
    }]
    assert compute_zone_distribution(sessions, days=90)["model"] == "pyramidal"


def test_zone_distribution_ignore_les_seances_hors_periode():
    sessions = [{
        "date": _days_ago(200), "moving_time_s": 10000,
        "zone_secs": {"Z1": 10000},
    }]
    assert compute_zone_distribution(sessions, days=90)["status"] == "insufficient_data"


# --- Projection de forme depuis le plan ---

def test_projection_ignore_les_jours_deja_passes():
    plan_days = [
        {"date": _days_ago(3), "target_tss": 500},   # passé : relève du réalisé
        {"date": _days_ago(-1), "target_tss": 100},  # demain
    ]
    projection = compute_fitness_projection_from_plan(30.0, 40.0, plan_days)
    assert len(projection) == 1
    assert projection[0]["date"] == _days_ago(-1)


def test_projection_ctl_monte_avec_la_charge():
    plan_days = [
        {"date": (date.today() + timedelta(days=i)).isoformat(), "target_tss": 120}
        for i in range(1, 15)
    ]
    projection = compute_fitness_projection_from_plan(30.0, 30.0, plan_days)
    assert projection[-1]["ctl"] > 30.0
    # TSB = CTL - ATL, et l'ATL (7j) réagit plus vite que le CTL (42j)
    assert projection[-1]["tsb"] == pytest.approx(
        projection[-1]["ctl"] - projection[-1]["atl"], abs=0.1
    )


def test_projection_vide_sans_plan():
    assert compute_fitness_projection_from_plan(30.0, 40.0, []) == []
