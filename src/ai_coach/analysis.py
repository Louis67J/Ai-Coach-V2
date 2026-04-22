"""
Calcul de métriques d'entraînement à partir du cache d'activités.

Fonctions principales :
- build_daily_tss(activities) : série temporelle TSS quotidien
- compute_fitness(daily_tss) : CTL/ATL/TSB
- compute_weekly_load(daily_tss) : charge hebdomadaire
- compute_power_bests(activities) : meilleurs efforts par durée (stub)
- build_report(activities) : assemble tout en un dict prêt pour JSON / LLM
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd


# --- Filtrage ---

def is_usable(act: dict) -> bool:
    """Une activité est exploitable si elle a au moins une métrique utile."""
    return bool(
        (act.get("distance") or 0) > 0
        or (act.get("moving_time") or 0) > 0
        or (act.get("icu_training_load") or 0) > 0
    )


def filter_usable(activities: list[dict]) -> list[dict]:
    return [a for a in activities if is_usable(a)]


# --- Séries temporelles ---

def build_daily_tss(activities: list[dict]) -> pd.Series:
    """
    Construit une série pandas indexée par date avec le TSS quotidien.
    Les jours sans activité sont à 0 (nécessaire pour CTL/ATL).
    """
    rows = []
    for a in activities:
        start = a.get("start_date_local") or a.get("start_date")
        tss = a.get("icu_training_load") or a.get("tss") or 0
        if start and tss:
            rows.append((start[:10], float(tss)))

    if not rows:
        return pd.Series(dtype=float)

    df = pd.DataFrame(rows, columns=["date", "tss"])
    df["date"] = pd.to_datetime(df["date"])
    daily = df.groupby(df["date"].dt.date)["tss"].sum()
    daily.index = pd.to_datetime(daily.index)

    # Remplit les jours sans entraînement avec 0 (important pour CTL/ATL)
    full_index = pd.date_range(start=daily.index.min(), end=daily.index.max(), freq="D")
    daily = daily.reindex(full_index, fill_value=0)
    return daily


# --- Métriques de forme ---

def compute_fitness(daily_tss: pd.Series) -> pd.DataFrame:
    """
    Calcule CTL (charge long terme, 42j), ATL (charge court terme, 7j),
    TSB (forme = CTL - ATL).

    Utilise un lissage exponentiel, convention standard TrainingPeaks.
    """
    if daily_tss.empty:
        return pd.DataFrame(columns=["tss", "ctl", "atl", "tsb"])

    ctl = daily_tss.ewm(span=42, adjust=False).mean()
    atl = daily_tss.ewm(span=7, adjust=False).mean()
    tsb = ctl - atl

    return pd.DataFrame({
        "tss": daily_tss,
        "ctl": ctl,
        "atl": atl,
        "tsb": tsb,
    })


def compute_weekly_load(daily_tss: pd.Series) -> pd.Series:
    """Somme hebdomadaire de TSS."""
    if daily_tss.empty:
        return pd.Series(dtype=float)
    return daily_tss.resample("W").sum()


# --- Agrégats globaux ---

def compute_totals(activities: list[dict]) -> dict[str, Any]:
    """Totaux sur la période : heures, distance, nombre de séances."""
    total_s = sum((a.get("moving_time") or 0) for a in activities)
    total_m = sum((a.get("distance") or 0) for a in activities)
    return {
        "count": len(activities),
        "total_hours": round(total_s / 3600, 1),
        "total_km": round(total_m / 1000, 1),
    }


def compute_sport_breakdown(activities: list[dict]) -> dict[str, dict]:
    """Répartition par type d'activité."""
    by_sport: dict[str, dict] = {}
    for a in activities:
        sport = a.get("type") or "Unknown"
        entry = by_sport.setdefault(
            sport, {"count": 0, "hours": 0.0, "tss": 0.0}
        )
        entry["count"] += 1
        entry["hours"] += (a.get("moving_time") or 0) / 3600
        entry["tss"] += a.get("icu_training_load") or 0

    # Arrondis pour lisibilité
    for sport, data in by_sport.items():
        data["hours"] = round(data["hours"], 1)
        data["tss"] = round(data["tss"], 0)
    return by_sport


# --- Rapport complet ---

def build_recent_daily_log(activities: list[dict], days: int = 14) -> list[dict]:
    """
    Construit une liste jour par jour des N derniers jours, avec les séances
    de chaque jour (ou un marqueur 'repos' si rien).

    Format de sortie:
        [
            {"date": "2026-04-15", "weekday": "mercredi", "sessions": [...]},
            {"date": "2026-04-14", "weekday": "mardi", "sessions": []},
            ...
        ]
    """
    weekday_fr = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

    today = date.today()
    start = today - timedelta(days=days - 1)

    # Indexe les activités par jour
    by_day: dict[str, list[dict]] = {}
    for a in activities:
        if not is_usable(a):
            continue
        start_local = a.get("start_date_local") or ""
        if not start_local:
            continue
        day_str = start_local[:10]
        try:
            day_date = date.fromisoformat(day_str)
        except ValueError:
            continue
        if day_date < start or day_date > today:
            continue
        by_day.setdefault(day_str, []).append({
            "name": a.get("name") or "(sans nom)",
            "type": a.get("type") or "?",
            "duration_h": round((a.get("moving_time") or 0) / 3600, 2),
            "distance_km": round((a.get("distance") or 0) / 1000, 1),
            "tss": int(a.get("icu_training_load") or 0),
        })

    # Construit la timeline complète, jour par jour, du plus récent au plus ancien
    log = []
    cursor = today
    while cursor >= start:
        day_str = cursor.isoformat()
        log.append({
            "date": day_str,
            "weekday": weekday_fr[cursor.weekday()],
            "sessions": by_day.get(day_str, []),
        })
        cursor -= timedelta(days=1)

    return log

def build_report(activities: list[dict]) -> dict[str, Any]:
    """
    Construit un rapport d'analyse complet à partir des activités brutes.
    Ce dict est sauvegardé en JSON et sera passé au LLM coach.
    """
    usable = filter_usable(activities)

    daily_tss = build_daily_tss(usable)
    fitness = compute_fitness(daily_tss)
    weekly = compute_weekly_load(daily_tss)

    # Valeurs de forme actuelles
    current_fitness: dict[str, float] = {}
    if not fitness.empty:
        latest = fitness.iloc[-1]
        current_fitness = {
            "ctl": round(float(latest["ctl"]), 1),
            "atl": round(float(latest["atl"]), 1),
            "tsb": round(float(latest["tsb"]), 1),
            "as_of": fitness.index[-1].strftime("%Y-%m-%d"),
        }

    # Charge des dernières semaines, avec annotation pour la semaine en cours
    recent_weekly = []
    if not weekly.empty:
        today = date.today()
        for week_end, tss in weekly.tail(5).items():
            week_end_date = week_end.date() if hasattr(week_end, "date") else week_end
            entry = {
                "week_ending": week_end_date.strftime("%Y-%m-%d"),
                "tss": round(float(tss), 0),
            }
            # Si on est avant la fin de cette semaine, c'est la semaine en cours
            if week_end_date >= today:
                # Compte les jours écoulés dans cette semaine (lundi=jour 1)
                week_start = week_end_date - timedelta(days=6)
                days_done = (today - week_start).days + 1
                entry["status"] = f"en cours, {days_done}/7 jours"
            else:
                entry["status"] = "complète"
            recent_weekly.append(entry)

    # Log jour par jour des 14 derniers jours
    recent_daily = build_recent_daily_log(activities, days=14)

    report = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "today": date.today().isoformat(),
        "today_weekday": ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"][date.today().weekday()],
        "period": {
            "activities_total": len(activities),
            "activities_usable": len(usable),
            "activities_stubs": len(activities) - len(usable),
            "stub_pct": round(100 * (len(activities) - len(usable)) / max(len(activities), 1), 0),
        },
        "totals_usable": compute_totals(usable),
        "sport_breakdown": compute_sport_breakdown(usable),
        "current_fitness": current_fitness,
        "recent_weekly_load": recent_weekly,
        "recent_daily_log": recent_daily,
    }
    # Fiches de séances enrichies (si disponibles)
    from ai_coach.intervals import load_enriched_sessions
    enriched = load_enriched_sessions()
    if enriched:
        # Trie par date, garde les 14 plus récentes
        enriched_sorted = sorted(
            enriched,
            key=lambda s: s.get("date", ""),
            reverse=True,
        )[:14]
        report["recent_sessions"] = enriched_sorted
    return report