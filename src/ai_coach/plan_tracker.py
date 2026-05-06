"""
Suivi des plans d'entraînement : stocke les plans prescrits
et permet de les comparer avec les séances réalisées.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from ai_coach.config import DATA_DIR


PLANS_PATH = DATA_DIR / "plans.jsonl"


def save_plan(plan_text: str, start_date: str, days: int) -> dict:
    """Stocke un plan généré par le coach."""
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "start_date": start_date,
        "days": days,
        "plan_text": plan_text,
    }

    with PLANS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return entry


def load_recent_plans(limit: int = 3) -> list[dict]:
    """Charge les N derniers plans."""
    if not PLANS_PATH.exists():
        return []

    plans = []
    with PLANS_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    plans.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    return plans[-limit:]


def build_plan_vs_actual(plan: dict, sessions: list[dict]) -> str:
    """
    Compare un plan prescrit avec les séances réellement effectuées.
    Retourne un texte de comparaison pour le coach.
    """
    plan_text = plan.get("plan_text", "")
    start = plan.get("start_date", "")
    days = plan.get("days", 7)

    if not start:
        return "Plan sans date de début, impossible de comparer."

    from datetime import timedelta
    start_date = date.fromisoformat(start)
    end_date = start_date + timedelta(days=days)

    # Filtre les séances dans la période du plan
    actual = [
        s for s in sessions
        if start <= (s.get("date") or "") <= end_date.isoformat()
    ]

    # Trie par date
    actual.sort(key=lambda s: s.get("date", ""))

    lines = [f"=== SUIVI PLAN ({start} → {end_date.isoformat()}) ===\n"]
    lines.append(f"Plan prescrit :\n{plan_text[:500]}...\n")
    lines.append(f"Séances réalisées ({len(actual)}) :")

    for s in actual:
        lines.append(
            f"  {s.get('date', '?')} [{s.get('tag', '?'):18s}] "
            f"TSS={s.get('tss', 0):>3} NP={s.get('np_watts', '?')}W "
            f"{s.get('name', '?')[:30]}"
        )

    if not actual:
        lines.append("  (aucune séance enregistrée sur cette période)")

    return "\n".join(lines)