"""
Suivi des plans d'entraînement : stocke les plans prescrits
et permet de les comparer avec les séances réalisées.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from pathlib import Path

from ai_coach.config import athlete_path


def plans_path() -> Path:
    """Chemin du fichier plans.jsonl pour l'athlète courant."""
    return athlete_path("plans.jsonl")
def save_plan(
    plan_text: str,
    start_date: str,
    days: int,
    structured: dict | None = None,
) -> dict:
    """
    Stocke un plan généré par le coach.

    `structured` contient la version machine du plan ({"days": [...]}) quand
    le coach a réussi à l'émettre : c'est elle qui permet de mesurer
    l'adhérence et de projeter la forme, le texte seul n'étant pas analysable.
    """
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "start_date": start_date,
        "days": days,
        "plan_text": plan_text,
        "structured": structured or {},
    }

    with plans_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return entry


def compute_plan_adherence(plan: dict, activities: list[dict]) -> dict[str, Any]:
    """
    Compare, jour par jour, le TSS prescrit par un plan structuré au TSS
    réellement réalisé. Ne juge que les journées déjà écoulées.
    """
    days = (plan.get("structured") or {}).get("days") or []
    if not days:
        return {"status": "no_structured_plan"}

    from ai_coach.analysis import build_daily_tss, filter_usable

    daily = build_daily_tss(filter_usable(activities))
    actual_by_date = {
        (ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)): float(v)
        for ts, v in daily.items()
    }

    today = date.today().isoformat()
    rows: list[dict[str, Any]] = []
    planned_total = actual_total = 0.0
    done = missed = 0

    for day in sorted(days, key=lambda d: d.get("date") or ""):
        day_date = day.get("date")
        if not day_date:
            continue
        planned = float(day.get("target_tss") or 0)
        actual = actual_by_date.get(day_date, 0.0)
        # La journée en cours n'est pas terminée : la compter comme "ratée"
        # donnerait un verdict faux tous les matins.
        completed = day_date < today

        if completed:
            planned_total += planned
            actual_total += actual
            if planned > 0:
                if actual > 0:
                    done += 1
                else:
                    missed += 1

        rows.append({
            "date": day_date,
            "type": day.get("type"),
            "planned_tss": round(planned, 0),
            "actual_tss": round(actual, 0),
            "completed": completed,
            "is_today": day_date == today,
        })

    result: dict[str, Any] = {
        "start_date": plan.get("start_date"),
        "days": rows,
        "days_completed": sum(1 for r in rows if r["completed"]),
        "planned_tss_to_date": round(planned_total, 0),
        "actual_tss_to_date": round(actual_total, 0),
        "sessions_done": done,
        "sessions_missed": missed,
    }

    if planned_total > 0:
        pct = 100 * actual_total / planned_total
        result["adherence_pct"] = round(pct, 0)
        if pct >= 90:
            result["verdict"] = "Plan suivi — charge conforme au prescrit."
        elif pct >= 70:
            result["verdict"] = "Plan globalement suivi, avec un léger déficit de charge."
        elif pct >= 40:
            result["verdict"] = "Écart net : une bonne partie de la charge prescrite n'a pas été faite."
        else:
            result["verdict"] = "Plan très peu suivi — à reconsidérer plutôt qu'à répéter."
    elif rows:
        result["verdict"] = (
            "Plan tout juste démarré — aucune journée complète à évaluer pour l'instant."
        )

    return result


def load_recent_plans(limit: int = 3) -> list[dict]:
    """Charge les N derniers plans."""
    if not plans_path().exists():
        return []

    plans = []
    with plans_path().open("r", encoding="utf-8") as f:
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