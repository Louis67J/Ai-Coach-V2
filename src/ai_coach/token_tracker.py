"""
Suivi de la consommation de tokens et estimation des coûts.
Stocke chaque appel dans un fichier JSONL pour historique.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ai_coach.config import athlete_path


def tracker_path() -> Path:
    """Chemin du fichier token_usage.jsonl pour l'athlète courant."""
    return athlete_path("token_usage.jsonl")
# Tarifs ($/million tokens). Ces valeurs sont figées ici : le coût affiché
# est donc une estimation locale, pas une facture. En cas de doute sur le
# montant réel, la console Anthropic fait foi.
PRICING = {
    "claude-sonnet-5": {"input": 2.0, "output": 10.0},
    "claude-sonnet-4-5": {"input": 3.0, "output": 15.0},
    "claude-sonnet-4-5-20250929": {"input": 3.0, "output": 15.0},
    "claude-opus-5": {"input": 5.0, "output": 25.0},
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0},
    "claude-haiku-3-5": {"input": 0.80, "output": 4.0},
}
DEFAULT_PRICING = {"input": 3.0, "output": 15.0}


def log_usage(
    model: str,
    input_tokens: int,
    output_tokens: int,
    source: str = "cli",
    question_preview: str = "",
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> dict:
    """
    Enregistre un appel API.

    Les tokens de cache sont comptés séparément car ils ne coûtent pas le
    même prix : écrire dans le cache coûte ~1,25x l'entrée normale, le relire
    ~0,1x. Sans cette distinction, un appel largement servi par le cache
    apparaîtrait aussi cher qu'un appel à froid.
    """
    pricing = PRICING.get(model, DEFAULT_PRICING)
    cost_input = input_tokens / 1_000_000 * pricing["input"]
    cost_output = output_tokens / 1_000_000 * pricing["output"]
    cost_cache_write = cache_creation_tokens / 1_000_000 * pricing["input"] * 1.25
    cost_cache_read = cache_read_tokens / 1_000_000 * pricing["input"] * 0.1
    cost_total = cost_input + cost_output + cost_cache_write + cost_cache_read

    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "date": date.today().isoformat(),
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_creation_tokens": cache_creation_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cost_usd": round(cost_total, 6),
        "source": source,
        "question": question_preview[:80],
    }

    with tracker_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return entry


def get_usage_summary() -> dict[str, Any]:
    """Résumé de la consommation : aujourd'hui, cette semaine, total."""
    if not tracker_path().exists():
        return {"total_calls": 0, "total_cost": 0}

    entries = []
    with tracker_path().open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    if not entries:
        return {"total_calls": 0, "total_cost": 0}

    today = date.today().isoformat()
    week_start = (date.today() - __import__("datetime").timedelta(days=date.today().weekday())).isoformat()
    month_start = date.today().replace(day=1).isoformat()

    today_entries = [e for e in entries if e.get("date") == today]
    week_entries = [e for e in entries if e.get("date", "") >= week_start]
    month_entries = [e for e in entries if e.get("date", "") >= month_start]

    def _sum(elist):
        return {
            "calls": len(elist),
            "input_tokens": sum(e.get("input_tokens", 0) for e in elist),
            "output_tokens": sum(e.get("output_tokens", 0) for e in elist),
            "cost_usd": round(sum(e.get("cost_usd", 0) for e in elist), 4),
        }

    return {
        "today": _sum(today_entries),
        "this_week": _sum(week_entries),
        "this_month": _sum(month_entries),
        "all_time": _sum(entries),
        "billing_url": "https://console.anthropic.com/settings/billing",
    }