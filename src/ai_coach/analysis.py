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


def compute_fitness_projection_from_plan(
    current_ctl: float,
    current_atl: float,
    plan_days: list[dict],
    start_from: date | None = None,
) -> list[dict]:
    """
    Projette la forme jour par jour **en supposant le plan suivi à la lettre**.

    Contrairement à compute_ctl_forecast, qui extrapole la charge moyenne
    récente, on utilise ici le TSS prescrit de chaque journée du plan : c'est
    la trajectoire "si je m'y tiens".
    """
    if not plan_days:
        return []

    ctl_decay = 2 / (42 + 1)
    atl_decay = 2 / (7 + 1)

    ctl, atl = float(current_ctl), float(current_atl)
    today = start_from or date.today()

    projection = []
    for day in sorted(plan_days, key=lambda d: d.get("date") or ""):
        day_date = day.get("date")
        if not day_date:
            continue
        try:
            parsed = date.fromisoformat(day_date)
        except ValueError:
            continue
        if parsed < today:
            continue  # journée déjà passée : elle relève du réalisé, pas de la projection

        tss = float(day.get("target_tss") or 0)
        ctl = ctl * (1 - ctl_decay) + tss * ctl_decay
        atl = atl * (1 - atl_decay) + tss * atl_decay
        projection.append({
            "date": day_date,
            "planned_tss": round(tss, 0),
            "ctl": round(ctl, 1),
            "atl": round(atl, 1),
            "tsb": round(ctl - atl, 1),
        })

    return projection


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

    # long_rides suit l'ordre de `sessions` (chronologique croissant côté
    # build_report) : [0] = la plus ancienne, [-1] = la plus récente.
    dates = sorted(r.get("date", "") for r in long_rides if r.get("date"))
    result: dict[str, Any] = {
        "count": len(long_rides),
        "period": f"{dates[0]} → {dates[-1]}" if dates else "?",
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
    Analyse la tendance FTP en utilisant le icu_rolling_ftp calculé
    par Intervals.icu (plus fiable que le NP brut des séances).
    Fallback sur NP des séances intenses si rolling_ftp absent.
    """
    data_points = []

    for s in sessions:
        if s.get("type") not in ("Ride", "VirtualRide"):
            continue
        date_str = s.get("date", "")
        if not date_str:
            continue

        # Priorité : icu_rolling_ftp (calculé par Intervals)
        rolling_ftp = s.get("rolling_ftp")
        if rolling_ftp and rolling_ftp > 100:
            data_points.append({
                "date": date_str,
                "ftp_estimate": rolling_ftp,
                "source": "rolling_ftp",
                "name": s.get("name", "?")[:30],
            })
            continue

        # Fallback : NP des séances intenses longues (>1h, IF>0.80)
        if_val = s.get("intensity_factor") or 0
        np_w = s.get("np_watts")
        duration_h = (s.get("moving_time_s") or 0) / 3600
        if np_w and if_val >= 0.80 and duration_h >= 1.0:
            data_points.append({
                "date": date_str,
                "ftp_estimate": np_w,
                "source": "np_intense",
                "name": s.get("name", "?")[:30],
            })

    if len(data_points) < 5:
        return {"status": "insufficient_data", "count": len(data_points)}

    data_points.sort(key=lambda x: x["date"])

    # Comparaisons sur des fenêtres de MÊME durée. Comparer les 3 derniers
    # mois à "tout le reste de l'historique" biaise mécaniquement le verdict :
    # le meilleur de 400 séances bat toujours le meilleur de 20, ce qui
    # faisait conclure à tort à une régression.
    window = 90
    today = date.today()

    def _slice(days_ago_start: int, days_ago_end: int) -> list[dict]:
        start = (today - timedelta(days=days_ago_start)).isoformat()
        end = (today - timedelta(days=days_ago_end)).isoformat()
        return [d for d in data_points if start <= d["date"] < end]

    recent = _slice(window, 0)
    previous = _slice(2 * window, window)
    # Même fenêtre saisonnière un an plus tôt (la forme d'un cycliste est
    # très saisonnière : comparer août à juin n'a pas de sens).
    year_ago = _slice(365 + window, 365)

    def _summarize(points: list[dict], k: int) -> dict[str, Any] | None:
        if not points or k <= 0:
            return None
        top = sorted(points, key=lambda x: x["ftp_estimate"], reverse=True)[:k]
        dates = sorted(d["date"] for d in points)
        return {
            "count": len(points),
            "period": f"{dates[0]} → {dates[-1]}",
            "avg_top": round(float(np.mean([d["ftp_estimate"] for d in top])), 0),
            "best": [
                {"date": d["date"], "ftp": d["ftp_estimate"], "source": d["source"], "name": d["name"]}
                for d in top
            ],
        }

    result: dict[str, Any] = {
        "window_days": window,
        "total_data_points": len(data_points),
    }

    MIN_POINTS = 3
    if len(recent) < MIN_POINTS:
        result["status"] = "insufficient_data"
        result["note"] = f"Seulement {len(recent)} séance(s) exploitable(s) sur les {window} derniers jours."
        return result

    # k identique des deux côtés pour que la comparaison soit honnête
    for label, points in (("previous", previous), ("year_ago", year_ago)):
        if len(points) < MIN_POINTS:
            continue
        k = min(5, len(recent), len(points))
        recent_sum = _summarize(recent, k)
        other_sum = _summarize(points, k)
        result["recent"] = recent_sum
        result[label] = other_sum
        result["top_n_used"] = k
        delta = recent_sum["avg_top"] - other_sum["avg_top"]
        result[f"delta_vs_{label}"] = round(float(delta), 0)

    result.setdefault("recent", _summarize(recent, min(5, len(recent))))

    delta_prev = result.get("delta_vs_previous")
    if delta_prev is None:
        result["trend"] = "pas de fenêtre comparable de même durée"
    elif delta_prev > 5:
        result["trend"] = "en progression ↗️"
    elif delta_prev < -5:
        result["trend"] = "en régression ↘️"
    else:
        result["trend"] = "stable →"

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

        # Provenance : à quelle séance correspond chaque record ? Sans ça le
        # chiffre est invérifiable (impossible de le rapprocher d'une sortie).
        sessions_by_id = {s.get("id"): s for s in (sessions or [])}
        for entry in profile.values():
            src = sessions_by_id.get(entry.get("activity_id"))
            if src:
                entry["date"] = src.get("date")
                entry["activity_name"] = src.get("name")

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

def _session_zone_secs(session: dict) -> dict[str, float]:
    """
    Secondes par zone pour une séance.

    Utilise zone_secs quand il est présent (séances enrichies récemment),
    sinon reconstruit depuis le résumé texte `zones` ("Z1:56% | Z2:28% …")
    et la durée — approximation suffisante pour agréger une distribution
    sur plusieurs semaines, et qui évite de tout ré-enrichir.
    """
    stored = session.get("zone_secs")
    if stored:
        return {z: float(s) for z, s in stored.items()}

    zones_str = session.get("zones") or ""
    duration = float(session.get("moving_time_s") or 0)
    if not zones_str or duration <= 0:
        return {}

    out: dict[str, float] = {}
    for part in zones_str.split("|"):
        part = part.strip()
        if ":" not in part:
            continue
        zid, pct_str = part.split(":", 1)
        try:
            pct = float(pct_str.strip().rstrip("%"))
        except ValueError:
            continue
        out[zid.strip()] = duration * pct / 100
    return out


def compute_zone_distribution(sessions: list[dict], days: int = 90) -> dict[str, Any]:
    """
    Distribution du temps par zone sur une période, et lecture "méthode
    d'entraînement" : polarisé, pyramidal ou orienté seuil.

    Le modèle à 3 zones est celui utilisé dans la littérature :
      - bas    : sous le premier seuil (Z1-Z2)
      - milieu : tempo / seuil (Z3-Z4)
      - haut   : au-dessus du second seuil (Z5+)
    """
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    recent = [s for s in sessions if (s.get("date") or "") >= cutoff]

    totals: dict[str, float] = {}
    pi_values: list[tuple[float, float]] = []  # (polarization_index, poids=durée)
    for s in recent:
        for zid, secs in _session_zone_secs(s).items():
            totals[zid] = totals.get(zid, 0) + secs
        pi = s.get("polarization_index")
        dur = float(s.get("moving_time_s") or 0)
        if pi and dur > 0:
            pi_values.append((float(pi), dur))

    total_secs = sum(totals.values())
    if total_secs <= 0:
        return {"status": "insufficient_data", "period_days": days, "sessions": len(recent)}

    def _pct(zone_ids: list[str]) -> float:
        return round(100 * sum(totals.get(z, 0) for z in zone_ids) / total_secs, 1)

    low = _pct(["Z1", "Z2"])
    mid = _pct(["Z3", "Z4"])
    high = _pct(["Z5", "Z6", "Z7"])

    if low >= 70 and high >= mid:
        model = "polarisé"
        comment = "Beaucoup de facile, peu de zone intermédiaire, une vraie part d'intensité haute."
    elif low >= 70:
        model = "pyramidal"
        comment = "Base facile solide, avec plus de tempo/seuil que d'intensité haute."
    elif mid >= 30:
        model = "orienté seuil"
        comment = "Part importante de tempo/seuil — attention à la zone grise (trop dur pour récupérer, trop facile pour progresser)."
    else:
        model = "mixte"
        comment = "Répartition sans dominante nette."

    result: dict[str, Any] = {
        "period_days": days,
        "sessions": len(recent),
        "total_hours": round(total_secs / 3600, 1),
        "zone_pct": {z: round(100 * s / total_secs, 1) for z, s in sorted(totals.items())},
        "low_pct": low,
        "mid_pct": mid,
        "high_pct": high,
        "intensity_pct": round(mid + high, 1),
        "model": model,
        "comment": comment,
    }

    if pi_values:
        weight = sum(w for _, w in pi_values)
        result["polarization_index_avg"] = round(
            sum(pi * w for pi, w in pi_values) / weight, 2
        )

    return result


def _parse_hours_target(raw: Any) -> tuple[float, float] | None:
    """
    Parse un objectif de volume hebdo du profil ("8-14h", "10h", 12…)
    en (min, max). Renvoie None si non interprétable.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw), float(raw)

    cleaned = str(raw).lower().replace("h", " ").replace(",", ".")
    numbers = []
    for token in cleaned.replace("-", " - ").split():
        try:
            numbers.append(float(token))
        except ValueError:
            continue
    if not numbers:
        return None
    return min(numbers), max(numbers)


def compute_volume_vs_target(
    activities: list[dict],
    target_raw: Any,
    weeks: int = 8,
) -> dict[str, Any]:
    """
    Compare le volume hebdomadaire réellement réalisé à l'objectif du profil.

    La semaine en cours est exclue (elle est incomplète et fausserait la lecture).
    """
    target = _parse_hours_target(target_raw)

    usable = filter_usable(activities)
    hours_by_week: dict[pd.Timestamp, float] = {}
    for act in usable:
        raw_date = (act.get("start_date_local") or "")[:10]
        if not raw_date:
            continue
        try:
            ts = pd.to_datetime(raw_date)
        except (ValueError, TypeError):
            continue
        week_end = ts + pd.offsets.Week(weekday=6)  # dimanche de la semaine
        hours_by_week[week_end] = hours_by_week.get(week_end, 0) + (act.get("moving_time") or 0) / 3600

    if not hours_by_week:
        return {"status": "insufficient_data"}

    today = pd.Timestamp(date.today())
    complete = sorted((wk, h) for wk, h in hours_by_week.items() if wk < today)
    recent = complete[-weeks:]
    if not recent:
        return {"status": "insufficient_data"}

    rows = []
    for week_end, hours in recent:
        row = {"week_ending": week_end.strftime("%Y-%m-%d"), "hours": round(hours, 1)}
        if target:
            lo, hi = target
            row["status"] = "sous l'objectif" if hours < lo else ("au-dessus" if hours > hi else "dans la cible")
        rows.append(row)

    avg = round(sum(h for _, h in recent) / len(recent), 1)
    result: dict[str, Any] = {
        "weeks_analyzed": len(recent),
        "avg_weekly_hours": avg,
        "weekly": rows,
    }

    if target:
        lo, hi = target
        result["target_min_hours"] = lo
        result["target_max_hours"] = hi
        result["target_label"] = str(target_raw)
        in_range = sum(1 for r in rows if r.get("status") == "dans la cible")
        result["weeks_in_target"] = in_range
        if avg < lo:
            result["verdict"] = f"Volume moyen sous l'objectif ({avg}h vs {lo}h minimum)."
        elif avg > hi:
            result["verdict"] = f"Volume moyen au-dessus de l'objectif ({avg}h vs {hi}h maximum)."
        else:
            result["verdict"] = f"Volume moyen dans la cible ({avg}h pour {lo}-{hi}h visées)."

    return result


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
        # Trie par date, garde les 7 plus récentes
        enriched_sorted = sorted(
            enriched,
            key=lambda s: s.get("date", ""),
            reverse=True,
        )[:7]
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

            # Récupère le poids et l'objectif de volume depuis le profil
            weight = 63.0
            hours_target = None
            try:
                from ai_coach.profile import load_profile
                profile_data = load_profile()
                weight = profile_data.get("athlete", {}).get("weight_kg", 63.0)
                hours_target = profile_data.get("context", {}).get("weekly_training_hours_target")
            except Exception:
                pass

            # 3. Durabilité
            report["durability"] = compute_durability_index(enriched_chrono)

            # 4. Tendance FTP
            report["ftp_trend"] = compute_ftp_trend(enriched_chrono)

            # 5. Profil de puissance
            report["power_profile"] = compute_power_profile(enriched_chrono, weight_kg=weight)

            # 6. Méthode d'entraînement : répartition des zones (polarisé /
            #    pyramidal / seuil) et volume réalisé vs objectif du profil
            report["zone_distribution"] = compute_zone_distribution(enriched_chrono, days=90)
            report["volume_vs_target"] = compute_volume_vs_target(usable, hours_target, weeks=8)
    return report