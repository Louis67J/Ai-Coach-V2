"""
Journal d'entraînement avec RPE (Rate of Perceived Exertion).
Stocke les sensations post-séance pour enrichir le coaching.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from ai_coach.config import DATA_DIR


JOURNAL_PATH = DATA_DIR / "journal.jsonl"


def add_entry(
    rpe: int,
    notes: str = "",
    activity_date: str | None = None,
    tags: list[str] | None = None,
) -> dict:
    """
    Ajoute une entrée au journal.

    Args:
        rpe: note RPE de 1 à 10
        notes: sensations libres en texte
        activity_date: date de l'activité (défaut: aujourd'hui)
        tags: mots-clés optionnels (fatigue, douleur, motivation, etc.)
    """
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "activity_date": activity_date or date.today().isoformat(),
        "rpe": rpe,
        "notes": notes,
        "tags": tags or [],
    }

    with JOURNAL_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return entry


def load_recent_entries(limit: int = 14) -> list[dict]:
    """Charge les N dernières entrées du journal."""
    if not JOURNAL_PATH.exists():
        return []

    entries = []
    with JOURNAL_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    return entries[-limit:]


def format_journal_for_llm(entries: list[dict]) -> str:
    """Formate les entrées du journal pour le contexte du coach."""
    if not entries:
        return ""

    weekdays_fr = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

    lines = ["\n=== JOURNAL D'ENTRAÎNEMENT (RPE + sensations) ==="]
    lines.append("Échelle RPE : 1-3 facile | 4-5 modéré | 6-7 dur | 8-9 très dur | 10 maximum\n")

    for entry in entries:
        d = entry.get("activity_date", "?")
        rpe = entry.get("rpe", "?")
        notes = entry.get("notes", "")
        tags = entry.get("tags", [])

        # RPE emoji
        if isinstance(rpe, int):
            if rpe <= 3:
                rpe_indicator = "🟢"
            elif rpe <= 5:
                rpe_indicator = "🟡"
            elif rpe <= 7:
                rpe_indicator = "🟠"
            else:
                rpe_indicator = "🔴"
        else:
            rpe_indicator = "⚪"

        try:
            weekday = weekdays_fr[date.fromisoformat(d).weekday()]
        except (ValueError, TypeError):
            weekday = "?"

        line = f"  {rpe_indicator} {weekday:9s} {d} — RPE {rpe}/10"
        if tags:
            line += f" [{', '.join(tags)}]"
        if notes:
            line += f"\n    → {notes[:200]}"
        lines.append(line)

    return "\n".join(lines)


def count_entries() -> int:
    if not JOURNAL_PATH.exists():
        return 0
    with JOURNAL_PATH.open("r", encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())