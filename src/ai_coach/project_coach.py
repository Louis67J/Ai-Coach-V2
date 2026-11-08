"""
Outils en ligne de commande pour un coach Claude qui travaille hors de l'app.

Ici le coach n'est pas `coach.py` (appel à l'API Anthropic) mais Claude lui-même,
dans une session de projet : il lance ces commandes, lit leur sortie Markdown
compacte, raisonne, puis écrit ses notes et met à jour un tableau de bord.
Aucune clé Anthropic n'est nécessaire, seulement INTERVALS_API_KEY et
INTERVALS_ATHLETE_ID. AI_COACH_DATA_DIR place les données hors du dépôt.

    python -m ai_coach.project_coach status
    python -m ai_coach.project_coach sync --days 30
    python -m ai_coach.project_coach recent --days 14
    python -m ai_coach.project_coach session 2026-11-07
    python -m ai_coach.project_coach fitness
    python -m ai_coach.project_coach wellness
    python -m ai_coach.project_coach dashboard-data --out dashboard.json
    python -m ai_coach.project_coach push-plan plan.json [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from ai_coach import config as cfg
from ai_coach.config import configure_logging


def _sessions() -> list[dict]:
    from ai_coach.intervals import load_enriched_sessions

    return sorted(load_enriched_sessions(), key=lambda s: s.get("date") or "")


def _fmt_duration(seconds: float | None) -> str:
    if not seconds:
        return "-"
    minutes = int(round(seconds / 60))
    return f"{minutes // 60}h{minutes % 60:02d}"


def _num(value: Any, digits: int = 0) -> str:
    if value is None or value == "":
        return "-"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _session_row(s: dict) -> str:
    return (
        f"| {s.get('date', '')[:10]} | {s.get('name', '')} | {s.get('tag') or '-'} "
        f"| {_fmt_duration(s.get('moving_time_s'))} | {_num(s.get('distance_km'), 1)} "
        f"| {_num(s.get('tss'))} | {_num(s.get('np_watts'))} | {_num(s.get('intensity_factor'), 2)} "
        f"| {_num(s.get('avg_hr'))} | {_num(s.get('decoupling_pct'), 1)} |"
    )


_SESSION_HEADER = (
    "| Date | Nom | Type | Durée | km | TSS | NP | IF | FC moy | Découplage % |\n"
    "|---|---|---|---|---|---|---|---|---|---|"
)


def _fitness_frame(sessions: list[dict]):
    """CTL/ATL/TSB recalculés depuis les séances enrichies, jusqu'à aujourd'hui."""
    import pandas as pd

    from ai_coach.analysis import build_daily_tss, compute_fitness

    rows = [{"start_date": s.get("date"), "tss": s.get("tss")} for s in sessions]
    daily = build_daily_tss(rows)
    if daily.empty:
        return compute_fitness(daily)
    today = pd.Timestamp(date.today())
    if daily.index.max() < today:
        daily = daily.reindex(pd.date_range(daily.index.min(), today, freq="D"), fill_value=0)
    return compute_fitness(daily)


# --- Commandes ---


def cmd_status(_: argparse.Namespace) -> None:
    print(f"Dossier de données : {cfg.DATA_DIR}")
    for var in ("INTERVALS_API_KEY", "INTERVALS_ATHLETE_ID"):
        print(f"{var} : {'définie' if os.getenv(var) else 'MANQUANTE'}")
    sessions = _sessions()
    print(f"Séances enrichies en cache : {len(sessions)}")
    if sessions:
        print(f"Dernière séance : {sessions[-1].get('date', '')[:10]} ({sessions[-1].get('name')})")
    for name in ("profile.json", "wellness.json", "activities.json", "journal.jsonl", "plans.jsonl"):
        path = cfg.athlete_path(name)
        print(f"{name} : {'présent' if path.exists() else 'absent'}")


def cmd_sync(args: argparse.Namespace) -> None:
    from ai_coach.intervals import enrich_sessions, refresh_cache
    from ai_coach.wellness import fetch_wellness

    known = {s.get("id") for s in _sessions()}
    activities = refresh_cache(days=args.days)
    sessions = enrich_sessions(activities, max_new=args.max_new)
    wellness = fetch_wellness(days=args.wellness_days)

    new = sorted((s for s in sessions if s.get("id") not in known), key=lambda s: s.get("date") or "")
    print(f"{len(activities)} activités sur {args.days} jours, {len(new)} nouvelle(s) séance(s) enrichie(s), "
          f"{len(wellness)} jour(s) de bien-être.")
    if new:
        print()
        print(_SESSION_HEADER)
        for s in new:
            print(_session_row(s))


def cmd_recent(args: argparse.Namespace) -> None:
    since = (date.today() - timedelta(days=args.days)).isoformat()
    recent = [s for s in _sessions() if (s.get("date") or "") >= since]
    if not recent:
        print(f"Aucune séance depuis le {since}.")
        return
    print(_SESSION_HEADER)
    for s in recent:
        print(_session_row(s))
    total_s = sum(s.get("moving_time_s") or 0 for s in recent)
    total_tss = sum(s.get("tss") or 0 for s in recent)
    print(f"\nTotal {args.days} j : {len(recent)} séances, {_fmt_duration(total_s)}, TSS {total_tss:.0f}")


def cmd_session(args: argparse.Namespace) -> None:
    """Fiche complète d'une ou plusieurs séances d'une date (JSON brut)."""
    matches = [s for s in _sessions() if (s.get("date") or "").startswith(args.date)]
    if not matches:
        print(f"Aucune séance le {args.date}.")
        return
    print(json.dumps(matches, ensure_ascii=False, indent=1, default=str))


def cmd_fitness(args: argparse.Namespace) -> None:
    from ai_coach.analysis import compute_weekly_load

    fit = _fitness_frame(_sessions())
    if fit.empty:
        print("Pas de données de charge.")
        return
    last = fit.iloc[-1]
    print(f"Aujourd'hui : CTL {last.ctl:.0f} · ATL {last.atl:.0f} · TSB {last.tsb:+.0f}")
    print(f"Il y a 7 j : CTL {fit.iloc[-8].ctl:.0f} · il y a 28 j : CTL {fit.iloc[-29].ctl:.0f}")
    print("\n| Semaine (fin) | TSS |\n|---|---|")
    for day, tss in compute_weekly_load(fit["tss"]).tail(args.weeks).items():
        print(f"| {day.date()} | {tss:.0f} |")


def cmd_wellness(args: argparse.Namespace) -> None:
    from ai_coach.wellness import build_wellness_summary, format_wellness_for_llm, load_cached_wellness

    data = load_cached_wellness()[-args.days:]
    summary = build_wellness_summary(data)
    print(format_wellness_for_llm(summary) if summary else "Pas de données de bien-être en cache (lance sync).")


def cmd_dashboard_data(args: argparse.Namespace) -> None:
    """Exporte en JSON ce dont le tableau de bord a besoin."""
    from ai_coach.analysis import compute_weekly_load
    from ai_coach.profile import load_profile
    from ai_coach.wellness import load_cached_wellness

    sessions = _sessions()
    fit = _fitness_frame(sessions).tail(120)
    weekly = compute_weekly_load(_fitness_frame(sessions)["tss"]).tail(16) if sessions else []
    weekly_hours: dict[str, float] = {}
    for s in sessions:
        d = s.get("date")
        if not d:
            continue
        day = date.fromisoformat(d[:10])
        week_end = (day + timedelta(days=6 - day.weekday())).isoformat()
        weekly_hours[week_end] = weekly_hours.get(week_end, 0) + (s.get("moving_time_s") or 0) / 3600

    profile = load_profile()
    athlete = profile.get("athlete", {})
    keep = ("id", "date", "name", "type", "tag", "moving_time_s", "distance_km", "elevation_gain",
            "tss", "np_watts", "avg_watts", "intensity_factor", "avg_hr", "decoupling_pct", "interval_pattern")
    payload = {
        "generated": date.today().isoformat(),
        "athlete": {k: athlete.get(k) for k in ("name", "weight_kg", "ftp_watts", "ftp_target", "fc_max")},
        "objectives": profile.get("objectives", []),
        "fitness": [
            {"date": idx.date().isoformat(), "tss": round(r.tss), "ctl": round(r.ctl, 1),
             "atl": round(r.atl, 1), "tsb": round(r.tsb, 1)}
            for idx, r in fit.iterrows()
        ],
        "weekly": [
            {"week_end": idx.date().isoformat(), "tss": round(v),
             "hours": round(weekly_hours.get(idx.date().isoformat(), 0), 1)}
            for idx, v in (weekly.items() if len(weekly) else [])
        ],
        "recent_sessions": [{k: s.get(k) for k in keep} for s in sessions[-20:]][::-1],
        "wellness": load_cached_wellness()[-28:],
    }
    out = Path(args.out)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"Écrit {out} ({len(payload['fitness'])} jours, {len(payload['recent_sessions'])} séances)")


def cmd_push_plan(args: argparse.Namespace) -> None:
    """
    Envoie un plan au calendrier Intervals.icu. Format du fichier :
    {"structured": {"days": [{"date": "2026-11-10", "type": "Sweet spot",
      "intensity": "3x12min à 90% FTP", "duration_min": 75, "target_tss": 70}, ...]}}
    Sans --apply, n'affiche que ce qui serait créé.
    """
    from ai_coach.intervals_sync import push_plan_to_calendar
    from ai_coach.profile import load_profile

    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    ftp = int(load_profile().get("athlete", {}).get("ftp_watts") or 0)
    result = push_plan_to_calendar(plan, ftp=ftp, dry_run=not args.apply, overwrite=args.overwrite)
    print(json.dumps(result, ensure_ascii=False, indent=1, default=str))


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(prog="project-coach")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status").set_defaults(func=cmd_status)

    p = sub.add_parser("sync")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--max-new", type=int, default=30)
    p.add_argument("--wellness-days", type=int, default=28)
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("recent")
    p.add_argument("--days", type=int, default=14)
    p.set_defaults(func=cmd_recent)

    p = sub.add_parser("session")
    p.add_argument("date", help="AAAA-MM-JJ")
    p.set_defaults(func=cmd_session)

    p = sub.add_parser("fitness")
    p.add_argument("--weeks", type=int, default=8)
    p.set_defaults(func=cmd_fitness)

    p = sub.add_parser("wellness")
    p.add_argument("--days", type=int, default=14)
    p.set_defaults(func=cmd_wellness)

    p = sub.add_parser("dashboard-data")
    p.add_argument("--out", default="dashboard.json")
    p.set_defaults(func=cmd_dashboard_data)

    p = sub.add_parser("push-plan")
    p.add_argument("plan")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(func=cmd_push_plan)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
