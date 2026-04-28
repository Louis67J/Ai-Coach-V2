"""
Client pour l'API Intervals.icu.

Gère l'authentification, le fetch des activités, et le cache local en JSON.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from ai_coach.config import DATA_DIR, load_config


ACTIVITIES_CACHE = DATA_DIR / "activities.json"


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

        print(f"  → GET {url}")
        print(f"    oldest={params['oldest']} newest={params['newest']}")

        response = requests.get(url, params=params, auth=self.auth, timeout=30)
        response.raise_for_status()

        activities = response.json()
        print(f"  ✓ {len(activities)} activités récupérées")
        return activities


def refresh_cache(days: int = 30) -> list[dict]:
    """
    Rafraîchit le cache local avec les activités des N derniers jours.

    Écrit data/activities.json et renvoie la liste.
    """
    client = IntervalsClient()

    end = date.today()
    start = end - timedelta(days=days)

    print(f"📡 Fetch Intervals.icu (derniers {days} jours)")
    activities = client.fetch_activities(start=start, end=end)

    # Ajoute un petit wrapper avec des métadonnées
    payload = {
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "count": len(activities),
        "activities": activities,
    }

    ACTIVITIES_CACHE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"💾 Cache écrit: {ACTIVITIES_CACHE}")

    return activities


def load_cached_activities() -> list[dict]:
    """Charge les activités depuis le cache local. Renvoie [] si pas de cache."""
    if not ACTIVITIES_CACHE.exists():
        return []

    payload = json.loads(ACTIVITIES_CACHE.read_text(encoding="utf-8"))
    return payload.get("activities", [])

# --- Enrichissement des séances ---

SESSIONS_CACHE = DATA_DIR / "sessions.json"


def _load_sessions_cache() -> dict[str, dict]:
    """Charge le cache de sessions enrichies. Clé = activity id."""
    if not SESSIONS_CACHE.exists():
        return {}
    return json.loads(SESSIONS_CACHE.read_text(encoding="utf-8"))


def _save_sessions_cache(cache: dict[str, dict]) -> None:
    SESSIONS_CACHE.write_text(
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
        print(f"  ⚠️ Échec fetch détail {activity_id}: {e}")
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
        print(f"  ⚠️ Échec fetch intervalles {activity_id}: {e}")
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
        print(f"  ⚠️ Échec fetch streams {activity_id}: {e}")
        return None

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
        print(f"  ⚠️ Échec fetch power curves: {e}")
        return None


def _build_group_summaries(groups: list[dict], ftp: int = 310) -> list[dict]:
    """
    Transforme les icu_groups en résumés riches pour le coach.
    Chaque groupe = un bloc d'effort agrégé par Intervals.icu.
    """
    summaries = []
    for g in groups:
        watts = g.get("average_watts") or 0
        pct_ftp = round(watts / ftp * 100) if ftp else 0

        # Détermine la zone
        if pct_ftp < 56:
            zone = "Z1"
        elif pct_ftp < 76:
            zone = "Z2"
        elif pct_ftp < 91:
            zone = "Z3"
        elif pct_ftp < 106:
            zone = "Z4"
        elif pct_ftp < 120:
            zone = "Z5"
        elif pct_ftp < 150:
            zone = "Z6"
        else:
            zone = "Z7"

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
            if pct_ftp < 56:
                zone = "Z1"
            elif pct_ftp < 76:
                zone = "Z2"
            elif pct_ftp < 91:
                zone = "Z3"
            elif pct_ftp < 106:
                zone = "Z4"
            elif pct_ftp < 120:
                zone = "Z5"
            elif pct_ftp < 150:
                zone = "Z6"
            else:
                zone = "Z7"

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

def _classify_session(detail: dict) -> str:
    """
    Classifie la séance en un tag court basé sur les zones, l'intensité,
    ET la structure des intervalles détectés.
    """
    # Activités non-vélo
    act_type = (detail.get("type") or "").lower()
    if act_type in ("run", "walk", "hike", "yoga", "weighttraining", "swim",
                     "virtualrun", "nordicski", "backcountryski"):
        return act_type.upper()

    zone_times = detail.get("icu_zone_times") or []
    if not zone_times:
        return (detail.get("type") or "INCONNU").upper()

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

def build_session_summary(detail: dict, intervals_data: dict | None = None) -> dict:
    """
    Construit une fiche de séance enrichie à partir des détails API
    et optionnellement des intervalles détaillés.
    """
    # Intervalles résumés (format texte simple d'Intervals)
    intervals_raw = detail.get("interval_summary") or []
    intervals = [iv for iv in intervals_raw if isinstance(iv, str)]

    # Zones résumées
    zones_str = _format_zones_summary(detail.get("icu_zone_times"))

    # Classification auto
    tag = _classify_session(detail)

    # Pattern d'intervalles
    ftp = detail.get("icu_ftp") or 310
    interval_pattern = _detect_interval_pattern(intervals, ftp=ftp)

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

        # Zones (résumé texte)
        "zones": zones_str,
        "sweet_spot_min": round(ss_secs / 60, 1) if ss_secs else 0,

        # Intervalles (résumé texte)
        "intervals": intervals,
        "interval_pattern": interval_pattern,

        # Intervalles détaillés (groupes avec FC, cadence, pente, etc.)
        "detailed_groups": detailed_groups,

        # Modèle de puissance
        "p_max": detail.get("p_max"),
        "polarization_index": detail.get("polarization_index"),

        "rolling_ftp": detail.get("icu_rolling_ftp"),
    }
    return summary

def enrich_sessions(activities: list[dict], max_new: int = 20) -> list[dict]:
    """
    Enrichit les activités exploitables en fetchant leurs détails.
    Utilise un cache pour ne pas re-fetcher ce qu'on a déjà.

    Args:
        activities: liste brute des activités du cache principal
        max_new: nombre max de nouvelles activités à fetcher (rate limit)

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

    new_count = 0
    for act in usable:
        act_id = act.get("id", "")
        if act_id in cache:
            continue  # déjà enrichi
        if new_count >= max_new:
            print(f"  ⏸️ Limite de {max_new} nouveaux enrichissements atteinte. "
                  f"Relance pour continuer.")
            break

        name = act.get("name", "?")[:40]
        print(f"  🔍 Enrichissement: {name}...")
        detail = fetch_activity_detail(act_id)
        if detail:
            # Fetch aussi les intervalles détaillés
            intervals_data = fetch_activity_intervals(act_id)
            summary = build_session_summary(detail, intervals_data=intervals_data)
            cache[act_id] = summary
            new_count += 1

    _save_sessions_cache(cache)
    print(f"  💾 Cache sessions: {len(cache)} fiches "
          f"(+{new_count} nouvelles)")

    return list(cache.values())


def load_enriched_sessions() -> list[dict]:
    """Charge les sessions enrichies depuis le cache."""
    cache = _load_sessions_cache()
    return list(cache.values())