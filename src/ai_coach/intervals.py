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