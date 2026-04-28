"""
Données wellness (récupération, sommeil, HRV) depuis Intervals.icu.
Sources possibles : Whoop, Garmin, saisie manuelle.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import requests

from ai_coach.config import DATA_DIR
from ai_coach.intervals import IntervalsClient


WELLNESS_CACHE = DATA_DIR / "wellness.json"


def fetch_wellness(days: int = 14) -> list[dict]:
    """Fetch les données wellness des N derniers jours."""
    client = IntervalsClient()
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=days - 1)).isoformat()

    url = f"{client.base_url}/athlete/{client.athlete_id}/wellness?oldest={start}&newest={end}"
    try:
        response = requests.get(url, auth=client.auth, timeout=30)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            return []

        # Sauvegarde en cache
        WELLNESS_CACHE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return data
    except Exception as e:
        print(f"  ⚠️ Wellness fetch failed: {e}")
        return []


def load_cached_wellness() -> list[dict]:
    """Charge le wellness depuis le cache local."""
    if not WELLNESS_CACHE.exists():
        return []
    return json.loads(WELLNESS_CACHE.read_text(encoding="utf-8"))


def build_wellness_summary(wellness_data: list[dict]) -> dict[str, Any]:
    """
    Construit un résumé wellness pour le coach.
    """
    if not wellness_data:
        return {}

    # Filtre les jours qui ont au moins une donnée utile
    valid_days = []
    for day in wellness_data:
        if any(day.get(k) is not None for k in ("hrv", "restingHR", "sleepScore", "readiness")):
            valid_days.append(day)

    if not valid_days:
        return {}

    # Derniers 7 jours pour les moyennes
    recent_7 = valid_days[-7:]

    # HRV
    hrv_values = [d["hrv"] for d in recent_7 if d.get("hrv") is not None]
    # Resting HR
    rhr_values = [d["restingHR"] for d in recent_7 if d.get("restingHR") is not None]
    # Sleep
    sleep_scores = [d["sleepScore"] for d in recent_7 if d.get("sleepScore") is not None]
    sleep_durations = [d["sleepSecs"] / 3600 for d in recent_7 if d.get("sleepSecs") is not None]
    # Readiness
    readiness_values = [d["readiness"] for d in recent_7 if d.get("readiness") is not None]

    import numpy as np

    summary: dict[str, Any] = {
        "days_with_data": len(valid_days),
    }

    if hrv_values:
        summary["hrv_avg_7d"] = round(float(np.mean(hrv_values)), 1)
        summary["hrv_trend"] = _compute_trend(hrv_values)
        summary["hrv_latest"] = round(hrv_values[-1], 1)

    if rhr_values:
        summary["rhr_avg_7d"] = round(float(np.mean(rhr_values)), 0)
        summary["rhr_trend"] = _compute_trend(rhr_values, invert=True)
        summary["rhr_latest"] = int(rhr_values[-1])

    if sleep_scores:
        summary["sleep_score_avg"] = round(float(np.mean(sleep_scores)), 0)

    if sleep_durations:
        summary["sleep_hours_avg"] = round(float(np.mean(sleep_durations)), 1)

    if readiness_values:
        summary["readiness_avg"] = round(float(np.mean(readiness_values)), 0)
        summary["readiness_latest"] = round(readiness_values[-1], 0)

    # Détail jour par jour (7 derniers)
    daily_detail = []
    weekdays_fr = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    for day in recent_7:
        day_date = date.fromisoformat(day["id"])
        daily_detail.append({
            "date": day["id"],
            "weekday": weekdays_fr[day_date.weekday()],
            "hrv": round(day["hrv"], 1) if day.get("hrv") is not None else None,
            "rhr": day.get("restingHR"),
            "sleep_score": day.get("sleepScore"),
            "sleep_hours": round(day["sleepSecs"] / 3600, 1) if day.get("sleepSecs") else None,
            "readiness": day.get("readiness"),
            "spo2": day.get("spO2"),
        })
    summary["daily"] = daily_detail

    # Alertes
    alerts = []
    if hrv_values and hrv_values[-1] < np.mean(hrv_values) * 0.80:
        alerts.append("HRV en forte baisse (-20% vs moyenne) → fatigue ou stress")
    if rhr_values and rhr_values[-1] > np.mean(rhr_values) + 5:
        alerts.append("FC repos élevée (+5bpm vs moyenne) → récupération insuffisante")
    if sleep_durations and sleep_durations[-1] < 6:
        alerts.append("Nuit courte (<6h) → dette de sommeil")
    if readiness_values and readiness_values[-1] < 33:
        alerts.append("Readiness très basse → journée de récupération recommandée")
    summary["alerts"] = alerts

    return summary


def _compute_trend(values: list[float], invert: bool = False) -> str:
    """Calcule une tendance simple sur une liste de valeurs."""
    if len(values) < 3:
        return "données insuffisantes"

    first_half = sum(values[:len(values)//2]) / (len(values)//2)
    second_half = sum(values[len(values)//2:]) / (len(values) - len(values)//2)

    delta_pct = (second_half - first_half) / first_half * 100 if first_half else 0

    if invert:
        delta_pct = -delta_pct

    if delta_pct > 5:
        return "en amélioration ↗️"
    elif delta_pct < -5:
        return "en dégradation ↘️"
    else:
        return "stable →"


def format_wellness_for_llm(summary: dict[str, Any]) -> str:
    """Formate le wellness pour le contexte du coach."""
    if not summary:
        return ""

    lines = ["\n=== DONNÉES DE RÉCUPÉRATION (Whoop / Wellness) ==="]

    if "hrv_avg_7d" in summary:
        lines.append(f"\n  HRV (variabilité cardiaque) :")
        lines.append(f"    Moyenne 7j : {summary['hrv_avg_7d']} ms")
        lines.append(f"    Aujourd'hui : {summary.get('hrv_latest', '?')} ms")
        lines.append(f"    Tendance : {summary.get('hrv_trend', '?')}")

    if "rhr_avg_7d" in summary:
        lines.append(f"  FC repos :")
        lines.append(f"    Moyenne 7j : {summary['rhr_avg_7d']} bpm")
        lines.append(f"    Aujourd'hui : {summary.get('rhr_latest', '?')} bpm")
        lines.append(f"    Tendance : {summary.get('rhr_trend', '?')}")

    if "sleep_score_avg" in summary:
        lines.append(f"  Sommeil :")
        lines.append(f"    Score moyen : {summary['sleep_score_avg']}/100")
        lines.append(f"    Durée moyenne : {summary.get('sleep_hours_avg', '?')}h")

    if "readiness_avg" in summary:
        lines.append(f"  Readiness (Whoop) :")
        lines.append(f"    Moyenne : {summary['readiness_avg']}%")
        lines.append(f"    Aujourd'hui : {summary.get('readiness_latest', '?')}%")

    # Détail jour par jour
    daily = summary.get("daily", [])
    if daily:
        lines.append(f"\n  Détail 7 derniers jours :")
        for d in daily:
            parts = [f"{d['weekday']:9s} {d['date']}"]
            if d.get("hrv") is not None:
                parts.append(f"HRV={d['hrv']}")
            if d.get("rhr") is not None:
                parts.append(f"RHR={d['rhr']}")
            if d.get("sleep_hours") is not None:
                parts.append(f"sommeil={d['sleep_hours']}h")
            if d.get("readiness") is not None:
                parts.append(f"readiness={d['readiness']}%")
            lines.append(f"    {' | '.join(parts)}")

    # Alertes
    alerts = summary.get("alerts", [])
    if alerts:
        lines.append(f"\n  🚨 ALERTES RÉCUPÉRATION :")
        for a in alerts:
            lines.append(f"    • {a}")

    return "\n".join(lines)