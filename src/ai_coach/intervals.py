"""
Client pour l'API Intervals.icu.

Gère l'authentification, le fetch des activités, et le cache local en JSON.
"""
from __future__ import annotations

import logging

import json
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import requests

from ai_coach.config import athlete_path, load_config, utc_now_iso


logger = logging.getLogger(__name__)


def activities_cache_path() -> Path:
    """Chemin du fichier activities.json pour l'athlète courant."""
    return athlete_path("activities.json")
class IntervalsClient:
    """Client minimal pour l'API Intervals.icu."""

    def __init__(self) -> None:
        config = load_config()
        self.base_url = config.intervals_base_url
        self.athlete_id = config.intervals_athlete_id
        # Intervals.icu utilise Basic Auth : username "API_KEY" + password = la clé
        self.auth = ("API_KEY", config.intervals_api_key)

    def fetch_activities(
        self,
        start: date,
        end: date,
    ) -> list[dict]:
        """
        Récupère toutes les activités entre start et end (dates incluses).

        Returns:
            Liste de dicts, un par activité. Le schéma exact vient d'Intervals.icu.
        """
        url = f"{self.base_url}/athlete/{self.athlete_id}/activities"
        params = {
            "oldest": start.isoformat(),
            "newest": end.isoformat(),
        }

        logger.debug("GET %s", url)
        logger.debug("oldest=%s newest=%s", params["oldest"], params["newest"])

        response = requests.get(url, params=params, auth=self.auth, timeout=30)
        response.raise_for_status()

        activities = response.json()
        logger.info("%d activités récupérées", len(activities))
        return activities


def refresh_cache(
    days: int = 30,
    start: date | None = None,
    end: date | None = None,
) -> list[dict]:
    """
    Rafraîchit le cache local avec les activités d'une période.

    Par défaut : les N derniers jours. Passe start/end pour une plage
    explicite (utile pour remonter plusieurs années d'historique).

    Écrit data/activities.json et renvoie la liste.
    """
    client = IntervalsClient()

    end = end or date.today()
    start = start or (end - timedelta(days=days))

    logger.info("Fetch Intervals.icu (%s → %s)", start.isoformat(), end.isoformat())
    activities = client.fetch_activities(start=start, end=end)

    # Ajoute un petit wrapper avec des métadonnées
    payload = {
        "fetched_at": utc_now_iso(),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "count": len(activities),
        "activities": activities,
    }

    activities_cache_path().write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Cache écrit: %s", activities_cache_path())

    return activities


def load_cached_activities() -> list[dict]:
    """Charge les activités depuis le cache local. Renvoie [] si pas de cache."""
    if not activities_cache_path().exists():
        return []

    payload = json.loads(activities_cache_path().read_text(encoding="utf-8"))
    return payload.get("activities", [])

# --- Enrichissement des séances ---

def sessions_cache_path() -> Path:
    """Chemin du fichier sessions.json pour l'athlète courant."""
    return athlete_path("sessions.json")
def _load_sessions_cache() -> dict[str, dict]:
    """Charge le cache de sessions enrichies. Clé = activity id."""
    if not sessions_cache_path().exists():
        return {}
    return json.loads(sessions_cache_path().read_text(encoding="utf-8"))


def _save_sessions_cache(cache: dict[str, dict]) -> None:
    sessions_cache_path().write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def fetch_activity_detail(activity_id: str) -> dict | None:
    """Fetch les détails complets d'une activité depuis l'API Intervals."""
    client = IntervalsClient()
    url = f"{client.base_url}/athlete/{client.athlete_id}/activities/{activity_id}"
    try:
        response = requests.get(url, auth=client.auth, timeout=30)
        response.raise_for_status()
        data = response.json()
        # L'API renvoie une liste à 1 élément
        if isinstance(data, list) and len(data) > 0:
            return data[0]
        elif isinstance(data, dict):
            return data
        return None
    except Exception as e:
        logger.warning("Échec fetch détail %s: %s", activity_id, e)
        return None

def fetch_activity_intervals(activity_id: str) -> dict | None:
    """
    Fetch les intervalles détaillés d'une activité.
    Retourne un dict avec 'icu_intervals' et 'icu_groups'.
    """
    client = IntervalsClient()
    url = f"{client.base_url}/activity/{activity_id}/intervals"
    try:
        response = requests.get(url, auth=client.auth, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.warning("Échec fetch intervalles %s: %s", activity_id, e)
        return None

def fetch_activity_streams(
    activity_id: str,
    types: str = "time,watts,heartrate,cadence,altitude,distance",
) -> dict[str, list] | None:
    """
    Fetch les streams (données seconde par seconde) d'une activité.
    Retourne un dict {type: [valeurs]} ou None en cas d'erreur.
    """
    client = IntervalsClient()
    url = f"{client.base_url}/activity/{activity_id}/streams?types={types}"
    try:
        response = requests.get(url, auth=client.auth, timeout=60)
        response.raise_for_status()
        raw = response.json()
        # Transforme la liste d'objets en dict simple
        streams = {}
        for s in raw:
            stype = s.get("type")
            sdata = s.get("data", [])
            if stype and sdata:
                streams[stype] = sdata
        return streams
    except Exception as e:
        logger.warning("Échec fetch streams %s: %s", activity_id, e)
        return None

def _compute_stream_analysis(streams: dict[str, list], ftp: int) -> dict:
    """
    Analyse le flux de puissance brut : meilleures moyennes glissantes
    (power bests) par durée standard, et zones estimées sur la séance entière.

    Sert à compléter la classification basée uniquement sur les laps que
    Intervals.icu détecte lui-même dans interval_summary, qui peut être trop
    grossière (ex: un test max de 5min non isolé comme un lap séparé) ou
    absente (icu_zone_times vide → fallback générique sur le type d'activité).
    """
    watts = streams.get("watts") or []
    clean = [w if isinstance(w, (int, float)) else 0 for w in watts]
    n = len(clean)
    if n < 30 or not ftp:
        return {"power_bests": {}, "zone_pct": {}}

    import numpy as np
    arr = np.array(clean, dtype=float)

    durations_s = {"30s": 30, "1min": 60, "5min": 300, "10min": 600, "20min": 1200}
    power_bests: dict[str, dict] = {}
    for label, dur in durations_s.items():
        if n < dur:
            continue
        window_avg = np.convolve(arr, np.ones(dur) / dur, mode="valid")
        best_idx = int(np.argmax(window_avg))
        best_watts = round(float(window_avg[best_idx]))
        pct_ftp = round(best_watts / ftp * 100)
        power_bests[label] = {
            "watts": best_watts,
            "pct_ftp": pct_ftp,
            "zone": _zone_from_pct_ftp(pct_ftp),
            "start_s": best_idx,  # streams Intervals.icu ~1 point/seconde
            "duration_s": dur,
        }

    zone_secs: dict[str, int] = {}
    for w in clean:
        zone = _zone_from_pct_ftp(w / ftp * 100)
        zone_secs[zone] = zone_secs.get(zone, 0) + 1
    total = sum(zone_secs.values()) or 1
    zone_pct = {z: round(100 * s / total) for z, s in zone_secs.items()}

    return {"power_bests": power_bests, "zone_pct": zone_pct}


def _stream_effort_override(stream_analysis: dict) -> tuple[str | None, str | None]:
    """
    Cherche, dans les power bests du stream, un effort assez significatif
    pour mériter une classification propre — même quand la séance dans son
    ensemble ressemble à une sortie endurance classique (cas du test de 5min
    perdu au milieu d'une longue sortie Z1/Z2).

    Retourne (tag, description) ou (None, None) si rien de significatif.
    """
    power_bests = stream_analysis.get("power_bests") or {}
    if not power_bests:
        return None, None

    # %FTP minimum pour qu'un effort de cette durée soit jugé significatif
    thresholds = {"30s": 150, "1min": 130, "5min": 105, "10min": 95, "20min": 88}
    duration_rank = {"30s": 30, "1min": 60, "5min": 300, "10min": 600, "20min": 1200}
    zone_rank = {"Z7": 7, "Z6": 6, "Z5": 5, "Z4": 4, "Z3": 3, "Z2": 2, "Z1": 1}

    candidates = [
        (label, best) for label, best in power_bests.items()
        if best["pct_ftp"] >= thresholds.get(label, 999)
    ]
    if not candidates:
        return None, None

    # Priorise la zone la plus haute atteinte, puis la durée la plus longue
    candidates.sort(
        key=lambda c: (zone_rank.get(c[1]["zone"], 0), duration_rank.get(c[0], 0)),
        reverse=True,
    )
    label, best = candidates[0]
    zone = best["zone"]
    if zone in ("Z5", "Z6", "Z7"):
        tag = "VO2_PMA"
    elif zone == "Z4":
        tag = "SEUIL"
    else:
        tag = "TEMPO"

    desc = f"Effort détecté (stream) : {label} @ {best['watts']}W ({zone}, {best['pct_ftp']}% FTP)"
    return tag, desc


def fetch_power_curves(sport_type: str = "Ride") -> dict | None:
    """
    Fetch la power curve de l'athlète depuis Intervals.icu.
    Retourne le dict complet avec secs, values, watts_per_kg, powerModels.
    """
    client = IntervalsClient()
    url = f"{client.base_url}/athlete/{client.athlete_id}/power-curves?type={sport_type}"
    try:
        response = requests.get(url, auth=client.auth, timeout=30)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and "list" in data:
            curves = data["list"]
            if curves and len(curves) > 0:
                return curves[0]  # Premier élément = courbe par défaut (1 an)
        return None
    except Exception as e:
        logger.warning("Échec fetch power curves: %s", e)
        return None


def _zone_from_pct_ftp(pct_ftp: float) -> str:
    """Détermine la zone Coggan (Z1-Z7) à partir d'un %FTP."""
    if pct_ftp < 56:
        return "Z1"
    elif pct_ftp < 76:
        return "Z2"
    elif pct_ftp < 91:
        return "Z3"
    elif pct_ftp < 106:
        return "Z4"
    elif pct_ftp < 120:
        return "Z5"
    elif pct_ftp < 150:
        return "Z6"
    else:
        return "Z7"


def _build_group_summaries(groups: list[dict], ftp: int = 310) -> list[dict]:
    """
    Transforme les icu_groups en résumés riches pour le coach.
    Chaque groupe = un bloc d'effort agrégé par Intervals.icu.
    """
    summaries = []
    for g in groups:
        watts = g.get("average_watts") or 0
        pct_ftp = round(watts / ftp * 100) if ftp else 0
        zone = _zone_from_pct_ftp(pct_ftp)

        count = g.get("count") or 1
        duration_s = g.get("moving_time") or g.get("elapsed_time") or 0

        # Format durée lisible
        if duration_s >= 60:
            dur_str = f"{duration_s // 60}m{duration_s % 60:02d}s" if duration_s % 60 else f"{duration_s // 60}min"
        else:
            dur_str = f"{duration_s}s"

        summary = {
            "count": count,
            "duration_s": duration_s,
            "duration_str": dur_str,
            "avg_watts": watts,
            "np_watts": g.get("weighted_average_watts"),
            "pct_ftp": pct_ftp,
            "zone": zone,
            "avg_hr": g.get("average_heartrate"),
            "max_hr": g.get("max_heartrate"),
            "avg_cadence": round(g.get("average_cadence") or 0),
            "avg_gradient": round((g.get("average_gradient") or 0) * 100, 1),
            "avg_speed_kmh": round((g.get("average_speed") or 0) * 3.6, 1),
            "lr_balance": round(g.get("avg_lr_balance") or 0, 1) if g.get("avg_lr_balance") else None,
            "elevation_gain": round(g.get("total_elevation_gain") or 0),
            "decoupling": round(g.get("decoupling") or 0, 1) if g.get("decoupling") else None,
            "tss": round(g.get("training_load") or 0, 1),
        }

        # Texte lisible pour le coach
        label_parts = [f"{count}x {dur_str} @ {watts}W ({zone}, {pct_ftp}% FTP)"]
        if summary["avg_hr"]:
            label_parts.append(f"FC moy={summary['avg_hr']}")
        if summary["avg_cadence"]:
            label_parts.append(f"cad={summary['avg_cadence']}")
        if summary["avg_gradient"] and abs(summary["avg_gradient"]) > 0.5:
            label_parts.append(f"pente={summary['avg_gradient']}%")
        if summary["lr_balance"] and abs(summary["lr_balance"] - 50) > 1:
            label_parts.append(f"G/D={summary['lr_balance']}%")

        summary["label"] = " | ".join(label_parts)
        summaries.append(summary)

    return summaries

def _format_zones_summary(zone_times: list[dict] | None) -> str:
    """Transforme les temps de zones en résumé lisible."""
    if not zone_times:
        return ""

    # zone_times peut être [{id: "Z1", secs: 6012}, ...] ou [secs1, secs2, ...]
    total = 0
    zones = {}
    for z in zone_times:
        if isinstance(z, dict):
            zid = z.get("id", "?")
            secs = z.get("secs", 0)
        else:
            continue
        if zid == "SS":
            continue  # Sweet Spot est un sous-ensemble, pas une zone séparée
        zones[zid] = secs
        total += secs

    if total == 0:
        return ""

    parts = []
    for zid, secs in zones.items():
        pct = round(100 * secs / total)
        if pct >= 1:  # n'affiche pas les zones à 0%
            parts.append(f"{zid}:{pct}%")
    return " | ".join(parts)

def _detect_interval_pattern(intervals: list[str], ftp: int | None = None) -> str | None:
    """
    Analyse les intervalles détectés par Intervals.icu et essaie de détecter
    un pattern structuré (30/30, 4x4min, etc.).

    Retourne une description textuelle du pattern détecté, ou None.

    Format d'entrée des intervalles (strings) :
        "1x 36m37s 271w"
        "29x 31s 387w"
        "2x 8m1s 290w"
    """
    if not intervals:
        return None

    ftp = ftp or 310  # fallback

    # Parse chaque intervalle
    parsed = []
    for iv in intervals:
        if not isinstance(iv, str):
            continue
        parts = iv.strip().split()
        if len(parts) < 3:
            continue
        try:
            # Parse "29x" -> count=29
            count = int(parts[0].replace("x", ""))

            # Parse durée "31s" ou "8m1s" ou "36m37s"
            dur_str = parts[1]
            secs = 0
            if "m" in dur_str and "s" in dur_str:
                m_part, s_part = dur_str.split("m")
                secs = int(m_part) * 60 + int(s_part.replace("s", ""))
            elif "m" in dur_str:
                secs = int(dur_str.replace("m", "")) * 60
            elif "s" in dur_str:
                secs = int(dur_str.replace("s", ""))

            # Parse watts "387w"
            watts = int(parts[2].replace("w", ""))

            # Zone approximative
            pct_ftp = watts / ftp * 100
            zone = _zone_from_pct_ftp(pct_ftp)

            parsed.append({
                "count": count,
                "secs": secs,
                "watts": watts,
                "zone": zone,
                "pct_ftp": round(pct_ftp),
                "raw": iv,
            })
        except (ValueError, IndexError):
            continue

    if not parsed:
        return None

    # --- Détection de patterns ---

    # Cherche des paires effort/récup (blocs consécutifs avec zones contrastées)
    descriptions = []

    # Pattern 30/30 : beaucoup de répétitions courtes (20-40s) à haute intensité
    # suivies d'un bloc similaire à basse intensité
    for i, block in enumerate(parsed):
        if block["count"] >= 10 and block["secs"] <= 45 and block["zone"] in ("Z5", "Z6", "Z7"):
            # Cherche le bloc de récup correspondant
            for j, other in enumerate(parsed):
                if (i != j and other["count"] >= 10
                    and abs(other["secs"] - block["secs"]) <= 10
                    and other["zone"] in ("Z1", "Z2", "Z3")):
                    descriptions.append(
                        f"{block['secs']}s/{other['secs']}s : "
                        f"{block['count']} reps @ {block['watts']}W ({block['zone']}) "
                        f"/ {other['watts']}W ({other['zone']} récup)"
                    )
                    break

    # Pattern répétitions longues : 2-6x 3-20min à haute intensité
    for block in parsed:
        if (block["count"] >= 2 and 180 <= block["secs"] <= 1200
                and block["zone"] in ("Z4", "Z5", "Z6")):
            dur_min = block["secs"] // 60
            dur_sec = block["secs"] % 60
            dur_str = f"{dur_min}min" + (f"{dur_sec:02d}s" if dur_sec else "")
            descriptions.append(
                f"{block['count']}x {dur_str} @ {block['watts']}W "
                f"({block['zone']}, {block['pct_ftp']}% FTP)"
            )

    # Blocs longs uniques significatifs (1x > 5min au-dessus de Z3)
    for block in parsed:
        if (block["count"] == 1 and block["secs"] >= 300
                and block["zone"] in ("Z3", "Z4", "Z5")):
            dur_min = block["secs"] // 60
            descriptions.append(
                f"1x {dur_min}min @ {block['watts']}W "
                f"({block['zone']}, {block['pct_ftp']}% FTP)"
            )

    # Sprints
    sprints = [b for b in parsed if b["secs"] <= 30 and b["zone"] in ("Z6", "Z7")]
    if sprints:
        total_sprints = sum(b["count"] for b in sprints)
        max_watts = max(b["watts"] for b in sprints)
        if total_sprints >= 3:
            descriptions.append(f"{total_sprints} sprints (max {max_watts}W)")

    if not descriptions:
        return None

    return " | ".join(descriptions)

# Tags jugés "faibles" : soit un fallback générique (zone_times absent, cf
# _classify_by_zones_and_laps), soit une classification par % de zones qui
# peut cacher un effort ponctuel raté par les laps Intervals.icu. Utilisé à
# la fois pour décider de fetcher le stream (enrich_sessions) et pour tenter
# l'override par power-bests (_classify_session).
_RECLASSIFY_CANDIDATE_TAGS = {
    "RECUP", "Z2_STRICT", "ENDURANCE", "MIXTE_ENDURANCE", "MIXTE_INTENSIF",
    "RIDE", "WORKOUT", "VIRTUALRIDE", "GRAVELRIDE", "INCONNU",
}

# Incrémenté quand la logique de classification évolue, pour que les fiches
# déjà en cache soient reprises au prochain enrichissement.
CLASSIFICATION_VERSION = 2


def hr_zone_secs(detail: dict) -> dict[str, float]:
    """
    Temps par zone de FC, calculé par Intervals.icu avec les seuils de
    l'athlète (icu_hr_zones / lthr). Format API : une simple liste ordonnée
    Z1→Z7, contrairement aux zones de puissance qui sont des dicts.
    """
    if detail.get("icu_ignore_hr"):
        return {}  # l'athlète a explicitement invalidé la FC de cette séance
    times = detail.get("icu_hr_zone_times") or []
    if not isinstance(times, list):
        return {}
    return {
        f"Z{i + 1}": float(secs)
        for i, secs in enumerate(times)
        if isinstance(secs, (int, float)) and secs > 0
    }


def _classify_by_hr_zones(pct: dict[str, float]) -> str:
    """
    Classification à partir de la répartition du temps en zones de FC.

    Seuils volontairement distincts de ceux de la puissance : la FC est
    inerte (elle met du temps à monter et à redescendre), donc les efforts
    courts y sont sous-représentés — un 30/30 ne fait quasiment jamais
    apparaître de temps en Z5 cardiaque.
    """
    z1 = pct.get("Z1", 0)
    z1z2 = z1 + pct.get("Z2", 0)
    z3 = pct.get("Z3", 0)
    z4 = pct.get("Z4", 0)
    z5plus = pct.get("Z5", 0) + pct.get("Z6", 0) + pct.get("Z7", 0)

    if z5plus >= 8:
        return "VO2_PMA"
    if z4 >= 12:
        return "SEUIL"
    if z3 >= 25:
        return "TEMPO"
    if z1 >= 80:
        return "RECUP"
    if z1z2 >= 90:
        return "Z2_STRICT"
    if z1z2 >= 75:
        return "ENDURANCE"
    if (z3 + z4 + z5plus) >= 30:
        return "MIXTE_INTENSIF"
    return "MIXTE_ENDURANCE"


def _classify_session(
    detail: dict,
    stream_analysis: dict | None = None,
) -> tuple[str, str | None, str]:
    """
    Classifie la séance en un tag court basé sur les zones, l'intensité,
    ET la structure des intervalles détectés.

    stream_analysis (optionnel, cf _compute_stream_analysis) sert à (1)
    estimer les zones quand icu_zone_times est vide, et (2) détecter un
    effort significatif que les laps Intervals.icu auraient raté.

    Retourne (tag, stream_pattern, basis) où basis vaut "power", "hr" ou
    "none" : sans puissance, la lecture cardiaque reste valable mais elle
    n'est pas équivalente, donc on garde la trace de ce sur quoi on s'appuie.
    """
    tag = _classify_by_zones_and_laps(detail, stream_analysis=stream_analysis)

    stream_pattern = None
    if stream_analysis and tag in _RECLASSIFY_CANDIDATE_TAGS:
        effort_tag, effort_desc = _stream_effort_override(stream_analysis)
        if effort_tag:
            tag = effort_tag
            stream_pattern = effort_desc

    has_power_zones = bool(detail.get("icu_zone_times")) or bool(
        (stream_analysis or {}).get("zone_pct")
    )
    if has_power_zones:
        return tag, stream_pattern, "power"

    # Pas de puissance exploitable : on retombe sur la FC plutôt que de
    # laisser le tag générique du type d'activité (RIDE, WORKOUT…).
    hr_secs = hr_zone_secs(detail)
    total = sum(hr_secs.values())
    if total > 0:
        hr_pct = {z: 100 * s / total for z, s in hr_secs.items()}
        return _classify_by_hr_zones(hr_pct), stream_pattern, "hr"

    return tag, stream_pattern, "none"


def _classify_by_zones_and_laps(detail: dict, stream_analysis: dict | None = None) -> str:
    """Logique de classification par zones + laps Intervals.icu (inchangée à part le fallback stream)."""
    # Activités non-vélo
    act_type = (detail.get("type") or "").lower()
    if act_type in ("run", "walk", "hike", "yoga", "weighttraining", "swim",
                     "virtualrun", "nordicski", "backcountryski"):
        return act_type.upper()

    zone_times = detail.get("icu_zone_times") or []
    if not zone_times:
        # icu_zone_times vide (cas fréquent ~20% des séances) : au lieu
        # d'abandonner sur le type brut de l'activité, on estime les zones
        # depuis le stream de puissance si on l'a.
        if stream_analysis and stream_analysis.get("zone_pct"):
            pct = stream_analysis["zone_pct"]
        else:
            return (detail.get("type") or "INCONNU").upper()
    else:
        # Parse les temps de zones
        zones = {}
        total = 0
        for z in zone_times:
            if isinstance(z, dict):
                zid = z.get("id", "?")
                secs = z.get("secs", 0)
                if zid != "SS":
                    zones[zid] = secs
                    total += secs

        if total == 0:
            return "INCONNU"

        pct = {z: 100 * s / total for z, s in zones.items()}

    z1z2 = pct.get("Z1", 0) + pct.get("Z2", 0)
    z3 = pct.get("Z3", 0)
    z4 = pct.get("Z4", 0)
    z5 = pct.get("Z5", 0)
    z6z7 = pct.get("Z6", 0) + pct.get("Z7", 0)
    z5plus = z5 + z6z7

    if_val = (detail.get("icu_intensity") or 0)

    # --- D'abord, regarde les intervalles pour détecter les séances structurées ---
    intervals_raw = detail.get("interval_summary") or []
    ftp = detail.get("icu_ftp") or 310
    pattern = _detect_interval_pattern(intervals_raw, ftp=ftp)

    # Si on a détecté du fractionné court (30/30, 15/15, etc.)
    if pattern and ("reps @" in pattern and ("s/" in pattern)):
        return "FRACTIONNE_COURT"

    # Si on a détecté des blocs longs au seuil/VO2
    if pattern:
        # Parse pour trouver la zone dominante des intervalles
        for block_desc in pattern.split(" | "):
            if "(Z5" in block_desc or "(Z6" in block_desc:
                return "VO2_PMA"
            if "(Z4" in block_desc:
                return "SEUIL"
            if "(Z3" in block_desc and "min" in block_desc:
                return "TEMPO"

    # Détecte les sprints significatifs (même dans une séance Z2 globale)
    sprint_blocks = [
        b for b in (detail.get("interval_summary") or [])
        if isinstance(b, str) and "s " in b
    ]
    has_significant_sprints = False
    for sb in sprint_blocks:
        parts = sb.strip().split()
        try:
            count = int(parts[0].replace("x", ""))
            dur_str = parts[1]
            watts = int(parts[2].replace("w", ""))
            secs = int(dur_str.replace("s", "")) if "m" not in dur_str else 999
            if secs <= 30 and watts > ftp * 1.5 and count >= 2:
                has_significant_sprints = True
                break
        except (ValueError, IndexError):
            continue

    if has_significant_sprints and z1z2 >= 70:
        return "ENDURANCE_SPRINTS"

    # --- Sinon, classification par zones globales ---
    if if_val < 55:
        return "RECUP"
    elif z1z2 >= 90:
        return "Z2_STRICT"
    elif z1z2 >= 75 and z3 < 15:
        return "ENDURANCE"
    elif z3 >= 25 and z4 < 10 and z5plus < 5:
        return "TEMPO"
    elif z4 >= 15 and z5plus < 10:
        return "SWEET_SPOT"
    elif z5plus >= 15:
        return "VO2_PMA"
    elif z1z2 >= 60 and (z3 + z4 + z5plus) >= 20:
        return "MIXTE_ENDURANCE"
    elif (z3 + z4 + z5plus) >= 30:
        return "MIXTE_INTENSIF"
    else:
        return "ENDURANCE"

def build_session_summary(
    detail: dict,
    intervals_data: dict | None = None,
    streams: dict[str, list] | None = None,
) -> dict:
    """
    Construit une fiche de séance enrichie à partir des détails API
    et optionnellement des intervalles détaillés et du stream de puissance.
    """
    # Intervalles résumés (format texte simple d'Intervals)
    intervals_raw = detail.get("interval_summary") or []
    intervals = [iv for iv in intervals_raw if isinstance(iv, str)]

    # Zones résumées
    zones_str = _format_zones_summary(detail.get("icu_zone_times"))

    ftp = detail.get("icu_ftp") or 310

    # Analyse du stream de puissance (si fourni) : power bests + zones estimées
    stream_analysis = _compute_stream_analysis(streams, ftp) if streams else None
    power_bests = (stream_analysis or {}).get("power_bests", {})

    # Classification auto (affinée par le stream, ou basée sur la FC sans puissance)
    tag, stream_pattern, basis = _classify_session(detail, stream_analysis=stream_analysis)

    # Pattern d'intervalles : priorité aux laps Intervals.icu, sinon le pattern détecté via stream
    interval_pattern = _detect_interval_pattern(intervals, ftp=ftp) or stream_pattern

    # Sweet spot time
    ss_secs = 0
    for z in (detail.get("icu_zone_times") or []):
        if isinstance(z, dict) and z.get("id") == "SS":
            ss_secs = z.get("secs", 0)

    # Groupes d'intervalles détaillés (si disponibles)
    detailed_groups = []
    if intervals_data:
        groups = intervals_data.get("icu_groups") or []
        detailed_groups = _build_group_summaries(groups, ftp=ftp)

    summary = {
        "id": detail.get("id"),
        "date": (detail.get("start_date_local") or "")[:10],
        "name": detail.get("name") or "(sans nom)",
        "type": detail.get("type") or "?",
        "source": detail.get("source") or "?",
        "tag": tag,
        # Sur quoi repose le tag : puissance, FC, ou rien d'exploitable
        "classification_basis": basis,
        "classification_version": CLASSIFICATION_VERSION,

        # Durée et distance
        "moving_time_s": detail.get("moving_time") or 0,
        "distance_km": round((detail.get("distance") or 0) / 1000, 1),
        "elevation_gain": detail.get("total_elevation_gain") or 0,

        # Puissance
        "avg_watts": detail.get("icu_average_watts"),
        "np_watts": detail.get("icu_weighted_avg_watts"),
        "ftp_used": detail.get("icu_ftp"),
        "intensity_factor": round((detail.get("icu_intensity") or 0) / 100, 2),
        "variability_index": detail.get("icu_variability_index"),
        "tss": detail.get("icu_training_load") or 0,

        # FC
        "avg_hr": detail.get("average_heartrate"),
        "max_hr": detail.get("max_heartrate"),
        "decoupling_pct": detail.get("decoupling"),
        "efficiency_factor": detail.get("icu_efficiency_factor"),

        # Cadence et équilibre
        "avg_cadence": detail.get("average_cadence"),
        "lr_balance": detail.get("avg_lr_balance"),

        # Zones (résumé texte + secondes brutes pour l'agrégation)
        "zones": zones_str,
        "zone_secs": {
            z.get("id"): z.get("secs", 0)
            for z in (detail.get("icu_zone_times") or [])
            if isinstance(z, dict) and z.get("id") and z.get("id") != "SS"
        },
        # Zones de FC, gardées à part : elles ne sont pas interchangeables
        # avec les zones de puissance et ne doivent pas être agrégées ensemble
        "hr_zone_secs": hr_zone_secs(detail),
        "lthr": detail.get("lthr"),
        "sweet_spot_min": round(ss_secs / 60, 1) if ss_secs else 0,

        # Intervalles (résumé texte)
        "intervals": intervals,
        "interval_pattern": interval_pattern,

        # Meilleures puissances glissantes calculées depuis le stream (si disponible)
        "power_bests": power_bests,

        # Intervalles détaillés (groupes avec FC, cadence, pente, etc.)
        "detailed_groups": detailed_groups,

        # Modèle de puissance
        "p_max": detail.get("p_max"),
        "polarization_index": detail.get("polarization_index"),

        "rolling_ftp": detail.get("icu_rolling_ftp"),
    }
    return summary

def _should_fetch_streams(detail: dict) -> bool:
    """
    Décide si ça vaut le coup de fetcher le stream de puissance (appel HTTP
    en plus, ~1 point/seconde) pour cette séance.
    """
    # Sans puissance enregistrée, le stream n'apportera rien à la
    # classification (elle passera par la FC) : autant s'épargner l'appel.
    if not (detail.get("icu_average_watts") or detail.get("icu_weighted_avg_watts")):
        return False
    if not detail.get("icu_zone_times"):
        return True
    prelim_tag, _, _ = _classify_session(detail)
    return prelim_tag in _RECLASSIFY_CANDIDATE_TAGS


def _needs_processing(cached_entry: dict | None) -> bool:
    """
    Faut-il (re)traiter cette activité ? Source unique de vérité, partagée
    par enrich_sessions et count_pending_enrichment pour qu'ils ne divergent pas.
    """
    if cached_entry is None:
        return True  # jamais enrichie
    if cached_entry.get("tag") not in _RECLASSIFY_CANDIDATE_TAGS:
        return False  # déjà classifiée de façon exploitable
    if cached_entry.get("classification_version", 1) < CLASSIFICATION_VERSION:
        return True  # la logique a évolué depuis
    return not cached_entry.get("stream_checked")


def count_pending_enrichment(activities: list[dict]) -> int:
    """Nombre d'activités qui seraient traitées par enrich_sessions (sans limite)."""
    from ai_coach.analysis import is_usable

    cache = _load_sessions_cache()
    return sum(
        1 for act in activities
        if is_usable(act) and _needs_processing(cache.get(act.get("id", "")))
    )


def enrich_sessions(
    activities: list[dict],
    max_new: int = 20,
    progress_cb: Callable[[int, int, str], None] | None = None,
    save_every: int = 25,
) -> list[dict]:
    """
    Enrichit les activités exploitables en fetchant leurs détails.
    Utilise un cache pour ne pas re-fetcher ce qu'on a déjà.

    Retraite aussi, dans la limite de max_new, les séances déjà en cache
    dont le tag est faible (fallback générique ou classification par zones
    qui peut cacher un effort ponctuel) et qui n'ont pas encore été
    vérifiées via le stream de puissance (`stream_checked`) — ça permet à un
    simple refresh répété de corriger progressivement l'historique.

    Args:
        activities: liste brute des activités du cache principal
        max_new: nombre max d'activités à traiter en un appel (rate limit)
        progress_cb: callback(traitées, total_prévu, nom) pour afficher une
                     progression (utilisé par le dashboard sur les gros lots)
        save_every: sauvegarde intermédiaire du cache tous les N traitements,
                    pour ne rien perdre si un long batch est interrompu

    Returns:
        Liste des fiches de session enrichies (toutes, pas juste les nouvelles)
    """
    from ai_coach.analysis import is_usable

    cache = _load_sessions_cache()
    usable = [a for a in activities if is_usable(a)]
    # Priorise les séances vélo avec TSS significatif
    usable.sort(
        key=lambda a: (a.get("icu_training_load") or 0),
        reverse=True,
    )

    todo = []
    for act in usable:
        cached_entry = cache.get(act.get("id", ""))
        if _needs_processing(cached_entry):
            todo.append((act, cached_entry is not None))
    total = min(len(todo), max_new)

    processed = 0
    reclassified_count = 0
    for act, is_reclassification in todo[:max_new]:
        act_id = act.get("id", "")
        name = act.get("name", "?")[:40]
        logger.info("%s: %s", "Reclassification" if is_reclassification else "Enrichissement", name)
        if progress_cb:
            progress_cb(processed, total, name)

        detail = fetch_activity_detail(act_id)
        if detail:
            intervals_data = fetch_activity_intervals(act_id)
            streams = fetch_activity_streams(act_id) if _should_fetch_streams(detail) else None
            summary = build_session_summary(detail, intervals_data=intervals_data, streams=streams)
            summary["stream_checked"] = True
            cache[act_id] = summary
            processed += 1
            if is_reclassification:
                reclassified_count += 1
            if save_every and processed % save_every == 0:
                _save_sessions_cache(cache)

    if len(todo) > max_new:
        logger.info("Limite de %d traitements atteinte (%d restantes)", max_new, len(todo) - max_new)

    _save_sessions_cache(cache)
    if progress_cb:
        progress_cb(processed, total, "terminé")
    logger.info("Cache sessions: %d fiches (+%d nouvelles, %d reclassifiées)",
                len(cache), processed - reclassified_count, reclassified_count)

    return list(cache.values())


def load_enriched_sessions() -> list[dict]:
    """Charge les sessions enrichies depuis le cache."""
    cache = _load_sessions_cache()
    return list(cache.values())