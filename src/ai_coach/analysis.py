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

# --- Métriques avancées ---

import numpy as np


def compute_monotony_strain(daily_tss: pd.Series, window: int = 7) -> dict[str, Any]:
    """
    Monotonie et Strain (Foster, 1998).

    Monotonie = mean(TSS 7j) / std(TSS 7j)
    Strain = sum(TSS 7j) × Monotonie

    Monotonie haute (>2.0) + Strain élevé = risque de surentraînement.
    Monotonie basse = bonne variété dans la charge.
    """
    if daily_tss.empty or len(daily_tss) < window:
        return {}

    # Derniers 7 jours
    recent = daily_tss.tail(window)
    mean_tss = recent.mean()
    std_tss = recent.std()

    if std_tss == 0 or pd.isna(std_tss):
        monotony = 0.0
    else:
        monotony = float(mean_tss / std_tss)

    strain = float(recent.sum() * monotony)

    # Interprétation
    if monotony > 2.0:
        mono_status = "ÉLEVÉE — manque de variété, risque surentraînement"
    elif monotony > 1.5:
        mono_status = "modérée — acceptable"
    else:
        mono_status = "bonne — charge variée"

    if strain > 3000:
        strain_status = "TRÈS ÉLEVÉ — risque imminent"
    elif strain > 2000:
        strain_status = "élevé — surveiller"
    elif strain > 1000:
        strain_status = "modéré"
    else:
        strain_status = "bas"

    return {
        "monotony": round(monotony, 2),
        "monotony_status": mono_status,
        "strain": round(strain, 0),
        "strain_status": strain_status,
        "period_days": window,
        "daily_mean_tss": round(float(mean_tss), 1),
        "daily_std_tss": round(float(std_tss), 1),
    }


def compute_ctl_forecast(
    daily_tss: pd.Series,
    current_ctl: float,
    forecast_days: list[int] | None = None,
) -> list[dict]:
    """
    Projette le CTL futur en supposant que la charge moyenne récente (14j) continue.

    Retourne une liste de projections à différents horizons.
    """
    if daily_tss.empty:
        return []

    if forecast_days is None:
        forecast_days = [14, 28, 42]

    # Charge quotidienne moyenne des 14 derniers jours comme hypothèse
    recent_avg = float(daily_tss.tail(14).mean())
    today = daily_tss.index[-1]

    projections = []
    ctl = current_ctl
    decay = 2 / (42 + 1)  # facteur EWM pour CTL (span=42)

    for target_days in forecast_days:
        # Simule jour par jour
        projected_ctl = current_ctl
        for d in range(1, target_days + 1):
            projected_ctl = projected_ctl * (1 - decay) + recent_avg * decay

        target_date = today + timedelta(days=target_days)
        projections.append({
            "horizon_days": target_days,
            "target_date": target_date.strftime("%Y-%m-%d"),
            "projected_ctl": round(projected_ctl, 1),
            "assumption_daily_tss": round(recent_avg, 0),
            "delta_vs_now": round(projected_ctl - current_ctl, 1),
        })

    return projections


def compute_durability_index(sessions: list[dict]) -> dict[str, Any]:
    """
    Indice de durabilité : compare la puissance en 1re vs 2e moitié
    des sorties longues (>2h).

    Un bon score = tu maintiens ta puissance. Un mauvais score = tu fades.

    Utilise les groupes d'intervalles détaillés pour comparer début vs fin.
    """
    long_rides = [
        s for s in sessions
        if s.get("type") in ("Ride", "VirtualRide")
        and (s.get("moving_time_s") or 0) >= 7200  # >2h
        and s.get("np_watts")
        and s.get("avg_watts")
    ]

    if len(long_rides) < 3:
        return {"status": "insufficient_data", "count": len(long_rides)}

    # Méthode simple : ratio NP/avg_watts comme proxy de fatigue
    # Plus le VI est élevé en fin de sortie, plus tu "fades" (efforts irréguliers)
    # On utilise aussi le découplage comme signal direct
    decouplings = []
    vi_values = []

    for ride in long_rides:
        dec = ride.get("decoupling_pct")
        vi = ride.get("variability_index")
        if dec is not None:
            decouplings.append(float(dec))
        if vi is not None:
            vi_values.append(float(vi))

    result: dict[str, Any] = {
        "count": len(long_rides),
        "period": f"{long_rides[-1].get('date', '?')} → {long_rides[0].get('date', '?')}",
    }

    if decouplings:
        avg_dec = np.mean(decouplings)
        result["avg_decoupling_pct"] = round(float(avg_dec), 1)
        if avg_dec < 5:
            result["durability_rating"] = "excellente"
        elif avg_dec < 10:
            result["durability_rating"] = "bonne"
        elif avg_dec < 15:
            result["durability_rating"] = "moyenne — à travailler"
        else:
            result["durability_rating"] = "faible — priorité d'entraînement"

        # Tendance : les dernières sorties s'améliorent ou empirent ?
        if len(decouplings) >= 4:
            first_half = np.mean(decouplings[:len(decouplings)//2])
            second_half = np.mean(decouplings[len(decouplings)//2:])
            delta = float(second_half - first_half)
            result["trend_decoupling"] = round(delta, 1)
            if delta < -2:
                result["trend"] = "en amélioration ↗️"
            elif delta > 2:
                result["trend"] = "en dégradation ↘️"
            else:
                result["trend"] = "stable →"

    return result


def compute_ftp_trend(sessions: list[dict]) -> dict[str, Any]:
    """
    Analyse la tendance FTP en regardant l'évolution des meilleurs
    efforts 20min (icu_pm_ftp_watts ou NP des séances seuil/VO2).

    Utilise les sessions enrichies qui ont des données de puissance.
    """
    # Cherche les séances avec des efforts significatifs au seuil
    data_points = []

    for s in sessions:
        if s.get("type") not in ("Ride", "VirtualRide"):
            continue
        date_str = s.get("date", "")
        if not date_str:
            continue

        # Utilise le NP des séances intenses (IF > 0.75) comme proxy
        if_val = s.get("intensity_factor") or 0
        np_w = s.get("np_watts")
        tss = s.get("tss") or 0

        # On ne garde que les séances assez intenses et longues
        duration_h = (s.get("moving_time_s") or 0) / 3600
        if np_w and if_val >= 0.75 and duration_h >= 0.5 and tss >= 40:
            data_points.append({
                "date": date_str,
                "np": np_w,
                "if": if_val,
                "name": s.get("name", "?")[:30],
            })

    if len(data_points) < 5:
        return {"status": "insufficient_data", "count": len(data_points)}

    # Trie par date
    data_points.sort(key=lambda x: x["date"])

    # NP moyen des 5 meilleures séances récentes (3 derniers mois) vs anciennes
    recent_cutoff = (date.today() - timedelta(days=90)).isoformat()
    recent = [d for d in data_points if d["date"] >= recent_cutoff]
    older = [d for d in data_points if d["date"] < recent_cutoff]

    result: dict[str, Any] = {
        "total_quality_sessions": len(data_points),
        "recent_3_months": len(recent),
        "older": len(older),
    }

    if recent:
        recent_top = sorted(recent, key=lambda x: x["np"], reverse=True)[:5]
        result["recent_best_np"] = [
            {"date": d["date"], "np": d["np"], "name": d["name"]}
            for d in recent_top
        ]
        result["recent_avg_top5_np"] = round(np.mean([d["np"] for d in recent_top]), 0)

    if older:
        older_top = sorted(older, key=lambda x: x["np"], reverse=True)[:5]
        result["older_avg_top5_np"] = round(np.mean([d["np"] for d in older_top]), 0)

    if recent and older and "recent_avg_top5_np" in result and "older_avg_top5_np" in result:
        delta = result["recent_avg_top5_np"] - result["older_avg_top5_np"]
        result["np_delta"] = round(float(delta), 0)
        if delta > 5:
            result["trend"] = "en progression ↗️"
        elif delta < -5:
            result["trend"] = "en régression ↘️"
        else:
            result["trend"] = "stable → (stagnation confirmée)"
    elif recent:
        result["trend"] = "pas assez d'historique ancien pour comparer"

    return result


def compute_power_profile(sessions: list[dict], weight_kg: float = 63.0) -> dict[str, Any]:
    """
    Profil de puissance depuis l'API Intervals.icu (power curves réelles).
    Fallback sur les sessions enrichies si l'API échoue.
    """
    from ai_coach.intervals import fetch_power_curves

    coggan_levels = {
        "5s": [(23.0, "World Class"), (20.0, "Exceptionnel"), (17.0, "Excellent"),
               (14.0, "Très bon"), (11.0, "Bon"), (8.0, "Moyen")],
        "1min": [(11.0, "World Class"), (9.5, "Exceptionnel"), (8.0, "Excellent"),
                 (6.5, "Très bon"), (5.5, "Bon"), (4.5, "Moyen")],
        "5min": [(7.5, "World Class"), (6.5, "Exceptionnel"), (5.5, "Excellent"),
                 (4.8, "Très bon"), (4.0, "Bon"), (3.5, "Moyen")],
        "20min": [(6.4, "World Class"), (5.6, "Exceptionnel"), (5.0, "Excellent"),
                  (4.3, "Très bon"), (3.7, "Bon"), (3.2, "Moyen")],
        "60min": [(6.0, "World Class"), (5.2, "Exceptionnel"), (4.6, "Excellent"),
                  (4.0, "Très bon"), (3.4, "Bon"), (2.9, "Moyen")],
    }

    # Durées cibles en secondes
    targets = {
        "5s": 5,
        "1min": 60,
        "5min": 300,
        "20min": 1200,
        "60min": 3600,
    }

    # Essaie d'utiliser l'API power curves
    curve = fetch_power_curves()

    if curve and "secs" in curve and "values" in curve:
        secs_list = curve["secs"]
        values_list = curve["values"]
        wkg_list = curve.get("watts_per_kg", [])
        activity_ids = curve.get("activity_id", [])
        weight_used = curve.get("weight", weight_kg)

        # Construit un mapping secs -> (watts, wkg, activity_id)
        secs_map = {}
        for i, s in enumerate(secs_list):
            secs_map[s] = {
                "watts": values_list[i] if i < len(values_list) else 0,
                "wkg": wkg_list[i] if i < len(wkg_list) else 0,
                "activity_id": activity_ids[i] if i < len(activity_ids) else None,
            }

        profile = {}
        for label, target_secs in targets.items():
            # Cherche la durée la plus proche dans la courbe
            best_match = min(secs_list, key=lambda s: abs(s - target_secs))
            data = secs_map[best_match]
            watts = data["watts"]
            wkg = round(data["wkg"], 2) if data["wkg"] else round(watts / weight_used, 2) if weight_used else 0

            # Classification Coggan
            level = "Débutant"
            for threshold, lvl in coggan_levels.get(label, []):
                if wkg >= threshold:
                    level = lvl
                    break

            profile[label] = {
                "watts": watts,
                "w_kg": wkg,
                "level": level,
                "actual_duration_s": best_match,
                "activity_id": data.get("activity_id"),
            }

        # Power models d'Intervals
        power_models = {}
        for pm in curve.get("powerModels", []):
            pm_type = pm.get("type", "?")
            power_models[pm_type] = {
                "cp": pm.get("criticalPower"),
                "w_prime": pm.get("wPrime"),
                "ftp": pm.get("ftp"),
                "p_max": pm.get("pMax"),
            }

        # VO2max estimée
        vo2max = curve.get("vo2max_5m")

        # Forces et faiblesses
        strengths = []
        weaknesses = []
        for dur, data in profile.items():
            if data["level"] in ("World Class", "Exceptionnel", "Excellent"):
                strengths.append(f"{dur} ({data['watts']}W = {data['w_kg']} W/kg, {data['level']})")
            elif data["level"] in ("Moyen", "Débutant"):
                weaknesses.append(f"{dur} ({data['watts']}W = {data['w_kg']} W/kg, {data['level']})")

        return {
            "source": "intervals_api",
            "profile": profile,
            "power_models": power_models,
            "vo2max_estimated": vo2max,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "weight_kg_used": weight_used,
            "period": f"{curve.get('start_date_local', '?')[:10]} → {curve.get('end_date_local', '?')[:10]}",
        }

    # Fallback : méthode précédente basée sur les sessions
    return _compute_power_profile_from_sessions(sessions, weight_kg)


def _compute_power_profile_from_sessions(sessions: list[dict], weight_kg: float = 63.0) -> dict[str, Any]:
    """Fallback : calcul du profil depuis les sessions enrichies (méthode d'avant)."""
    coggan_levels = {
        "5s": [(23.0, "World Class"), (20.0, "Exceptionnel"), (17.0, "Excellent"),
               (14.0, "Très bon"), (11.0, "Bon"), (8.0, "Moyen")],
        "1min": [(11.0, "World Class"), (9.5, "Exceptionnel"), (8.0, "Excellent"),
                 (6.5, "Très bon"), (5.5, "Bon"), (4.5, "Moyen")],
        "5min": [(7.5, "World Class"), (6.5, "Exceptionnel"), (5.5, "Excellent"),
                 (4.8, "Très bon"), (4.0, "Bon"), (3.5, "Moyen")],
        "20min": [(6.4, "World Class"), (5.6, "Exceptionnel"), (5.0, "Excellent"),
                  (4.3, "Très bon"), (3.7, "Bon"), (3.2, "Moyen")],
        "60min": [(6.0, "World Class"), (5.2, "Exceptionnel"), (4.6, "Excellent"),
                  (4.0, "Très bon"), (3.4, "Bon"), (2.9, "Moyen")],
    }

    best = {"5s": 0, "1min": 0, "5min": 0, "20min": 0, "60min": 0}

    for s in sessions:
        if s.get("type") not in ("Ride", "VirtualRide"):
            continue
        p_max = s.get("p_max") or 0
        if p_max > best["5s"]:
            best["5s"] = p_max
        groups = s.get("detailed_groups") or []
        for g in groups:
            watts = g.get("avg_watts") or 0
            dur_s = g.get("duration_s") or 0
            if 50 <= dur_s <= 75 and watts > best["1min"]:
                best["1min"] = watts
            elif 240 <= dur_s <= 360 and watts > best["5min"]:
                best["5min"] = watts
            elif 1080 <= dur_s <= 1500 and watts > best["20min"]:
                best["20min"] = watts
            elif 3000 <= dur_s <= 4200 and watts > best["60min"]:
                best["60min"] = watts
        moving_s = s.get("moving_time_s") or 0
        np_w = s.get("np_watts") or 0
        if moving_s >= 3600 and np_w > best["60min"]:
            best["60min"] = np_w

    def _classify(label, watts):
        wkg = round(watts / weight_kg, 2) if weight_kg else 0
        level = "Débutant"
        for threshold, lvl in coggan_levels.get(label, []):
            if wkg >= threshold:
                level = lvl
                break
        return {"watts": watts, "w_kg": wkg, "level": level}

    profile = {d: _classify(d, w) for d, w in best.items() if w > 0}
    strengths = [f"{d} ({v['watts']}W = {v['w_kg']} W/kg, {v['level']})" for d, v in profile.items() if
                 v["level"] in ("World Class", "Exceptionnel", "Excellent")]
    weaknesses = [f"{d} ({v['watts']}W = {v['w_kg']} W/kg, {v['level']})" for d, v in profile.items() if
                  v["level"] in ("Moyen", "Débutant")]

    return {"source": "sessions_fallback", "profile": profile, "strengths": strengths, "weaknesses": weaknesses,
            "weight_kg_used": weight_kg}


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
        # --- Métriques avancées ---

        # 1. Monotonie & Strain
        report["monotony_strain"] = compute_monotony_strain(daily_tss)

        # 2. Projection CTL
        if current_fitness:
            # Projections aux dates clés (objectifs de saison)
            report["ctl_forecast"] = compute_ctl_forecast(
                daily_tss,
                current_ctl=current_fitness["ctl"],
                forecast_days=[14, 28, 42],
            )

        # 3-5. Métriques basées sur les sessions enrichies
        if enriched:
            # Trie chronologiquement pour les tendances
            enriched_chrono = sorted(enriched, key=lambda s: s.get("date", ""))

            # Récupère le poids depuis le profil si disponible
            try:
                from ai_coach.profile import load_profile
                profile_data = load_profile()
                weight = profile_data.get("athlete", {}).get("weight_kg", 63.0)
            except Exception:
                weight = 63.0

            # 3. Durabilité
            report["durability"] = compute_durability_index(enriched_chrono)

            # 4. Tendance FTP
            report["ftp_trend"] = compute_ftp_trend(enriched_chrono)

            # 5. Profil de puissance
            report["power_profile"] = compute_power_profile(enriched_chrono, weight_kg=weight)
    return report