"""
Point d'entrée CLI du AI Coach.

Usage:
    python -m ai_coach.main check            # vérifie la config
    python -m ai_coach.main refresh           # fetch 30 derniers jours
    python -m ai_coach.main refresh --days 90 # fetch N derniers jours
    python -m ai_coach.main summary           # résumé des activités en cache
"""
from __future__ import annotations

import argparse
import sys

from ai_coach.config import load_config
from ai_coach.intervals import load_cached_activities, refresh_cache

import json

from ai_coach.analysis import build_daily_tss, build_report, compute_fitness, compute_weekly_load, filter_usable
from ai_coach.charts import plot_fitness, plot_sport_breakdown, plot_weekly_load
from ai_coach.config import OUTPUTS_DIR

from ai_coach.coach import ask_coach, generate_plan

from ai_coach.intervals import enrich_sessions

def cmd_check() -> None:
    """Vérifie que la config est chargeable."""
    print("🚴 AI Coach v2 — Check de la configuration")
    print("=" * 50)
    try:
        config = load_config()
        print(f"  ✅ Anthropic API key  : {config.anthropic_api_key[:10]}…")
        print(f"  ✅ Intervals API key  : {config.intervals_api_key[:6]}…")
        print(f"  ✅ Intervals athlete  : {config.intervals_athlete_id}")
        print("=" * 50)
        print("Config OK ✨")
    except RuntimeError as e:
        print(str(e))
        sys.exit(1)


def cmd_refresh(days: int) -> None:
    """Rafraîchit le cache depuis Intervals.icu."""
    try:
        activities = refresh_cache(days=days)
    except Exception as e:
        print(f"❌ Erreur pendant le fetch: {e}")
        sys.exit(1)

    if activities:
        print(f"\n✨ {len(activities)} activités récupérées.")
        print(f"   Dernière: {activities[0].get('name', '(sans nom)')}")


def cmd_summary() -> None:
    """Affiche un résumé rapide des activités exploitables en cache."""
    all_activities = load_cached_activities()
    if not all_activities:
        print("❌ Aucun cache trouvé. Lance d'abord: python -m ai_coach.main refresh")
        sys.exit(1)

    # Une activité est "exploitable" si elle a au moins une métrique utile.
    # Les stubs Strava renvoyés par Intervals.icu n'ont rien de tout ça.
    def is_usable(act: dict) -> bool:
        return bool(
            (act.get("distance") or 0) > 0
            or (act.get("moving_time") or 0) > 0
            or (act.get("icu_training_load") or 0) > 0
        )

    usable = [a for a in all_activities if is_usable(a)]
    stubs = len(all_activities) - len(usable)

    print(f"📊 Résumé du cache")
    print(f"   {len(all_activities)} activités au total")
    print(f"   {len(usable)} exploitables, {stubs} stubs (Strava → API bloquée)")
    print("=" * 80)

    if not usable:
        print("⚠️  Aucune activité exploitable pour l'instant.")
        print("   Voir les notes du projet sur la reconnexion Wahoo/Whoop → Intervals.")
        return

    # Affiche les 15 dernières exploitables
    for act in usable[:15]:
        name = (act.get("name") or "(sans nom)")[:40]
        sport = (act.get("type") or "?")[:12]
        date_str = (act.get("start_date_local") or "")[:10]
        distance_km = round((act.get("distance") or 0) / 1000, 1)
        duration_h = round((act.get("moving_time") or 0) / 3600, 1)
        tss = act.get("icu_training_load") or 0
        print(
            f"  {date_str}  {sport:12s}  "
            f"{distance_km:6.1f}km  {duration_h:4.1f}h  "
            f"TSS={tss:3.0f}  {name}"
        )

    if len(usable) > 15:
        print(f"  ... et {len(usable) - 15} autres exploitables")


def cmd_analyze() -> None:
    """Analyse le cache et génère rapport + graphes."""
    from ai_coach.intervals import load_cached_activities

    activities = load_cached_activities()
    if not activities:
        print("❌ Aucun cache trouvé. Lance d'abord: python -m ai_coach.main refresh")
        sys.exit(1)

    print("🧠 Analyse en cours...")
    report = build_report(activities)

    # Graphes
    usable = filter_usable(activities)
    daily_tss = build_daily_tss(usable)
    fitness_df = compute_fitness(daily_tss)
    weekly = compute_weekly_load(daily_tss)

    charts_generated = []
    for path in [
        plot_fitness(fitness_df),
        plot_weekly_load(weekly),
        plot_sport_breakdown(report["sport_breakdown"]),
    ]:
        if path:
            charts_generated.append(path.name)

    # Sauvegarde du rapport JSON
    report_path = OUTPUTS_DIR / "report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Affichage synthétique
    print("=" * 60)
    print(f"📊 Activités analysées: {report['period']['activities_usable']} "
          f"(sur {report['period']['activities_total']} au total)")
    totals = report["totals_usable"]
    print(f"   {totals['total_hours']}h  •  {totals['total_km']}km  •  {totals['count']} séances")

    cf = report["current_fitness"]
    if cf:
        print(f"\n🏋️  Forme actuelle (au {cf['as_of']}):")
        print(f"   CTL (forme) = {cf['ctl']}")
        print(f"   ATL (fatigue) = {cf['atl']}")
        print(f"   TSB (fraîcheur) = {cf['tsb']}")

    if report["recent_weekly_load"]:
        print(f"\n📅 Charge des 4 dernières semaines:")
        for w in report["recent_weekly_load"]:
            print(f"   Semaine du {w['week_ending']}: {w['tss']:>4.0f} TSS")

    print(f"\n💾 Rapport écrit: {report_path}")
    if charts_generated:
        print(f"📈 Graphes générés dans outputs/: {', '.join(charts_generated)}")
    print("=" * 60)

def cmd_ask(question: str) -> None:
    """Pose une question libre au coach."""
    from ai_coach.intervals import load_cached_activities
    from ai_coach.analysis import build_report

    activities = load_cached_activities()
    if not activities:
        print("❌ Aucun cache. Lance d'abord: python -m ai_coach.main refresh")
        sys.exit(1)

    print("🧠 Interrogation du coach...\n")
    try:
        report = build_report(activities)
        answer = ask_coach(question, report)
    except Exception as e:
        print(f"❌ Erreur: {e}")
        sys.exit(1)

    print("=" * 60)
    print(answer)
    print("=" * 60)


def cmd_plan(days: int) -> None:
    """Génère un plan d'entraînement pour les N prochains jours."""
    from ai_coach.intervals import load_cached_activities
    from ai_coach.analysis import build_report

    activities = load_cached_activities()
    if not activities:
        print("❌ Aucun cache. Lance d'abord: python -m ai_coach.main refresh")
        sys.exit(1)

    print(f"🧠 Génération d'un plan {days} jours...\n")
    try:
        report = build_report(activities)
        plan = generate_plan(report, horizon_days=days)
    except Exception as e:
        print(f"❌ Erreur: {e}")
        sys.exit(1)

    print("=" * 60)
    print(plan)
    print("=" * 60)

def cmd_enrich(max_new: int) -> None:
    """Enrichit les séances avec les détails Intervals.icu."""
    from ai_coach.intervals import load_cached_activities

    activities = load_cached_activities()
    if not activities:
        print("❌ Aucun cache. Lance d'abord: python -m ai_coach.main refresh")
        sys.exit(1)

    print(f"🔬 Enrichissement des séances (max {max_new} nouvelles)...")
    sessions = enrich_sessions(activities, max_new=max_new)
    print(f"\n✨ {len(sessions)} séances enrichies au total.")

    # Affiche les 5 dernières fiches pour vérif
    recent = sorted(sessions, key=lambda s: s.get("date", ""), reverse=True)[:5]
    print("\n📋 5 dernières séances enrichies :")
    print("-" * 80)
    for s in recent:
        tag = s.get("tag", "?")
        name = s.get("name", "?")[:35]
        np_w = s.get("np_watts") or "?"
        if_val = s.get("intensity_factor") or "?"
        tss = s.get("tss", 0)
        zones = s.get("zones", "")
        intervals = s.get("intervals", [])
        iv_str = f" | {len(intervals)} intervalles" if intervals else ""
        print(
            f"  {s.get('date', '?')}  [{tag:18s}]  "
            f"NP={np_w}W  IF={if_val}  TSS={tss:>3}{iv_str}"
        )
        print(f"    {name}")
        if intervals:
            for iv in intervals[:4]:
                print(f"      → {iv}")
            if len(intervals) > 4:
                print(f"      ... +{len(intervals)-4} autres")
    print("-" * 80)


def cmd_session(date_str: str) -> None:
    """Génère le graphe détaillé d'une séance."""
    from ai_coach.intervals import (
        fetch_activity_intervals, fetch_activity_streams,
        load_cached_activities, load_enriched_sessions,
    )
    from ai_coach.charts import plot_session

    # Cherche la séance dans le cache enrichi
    sessions = load_enriched_sessions()

    if date_str.lower() in ("last", "derniere", "dernière"):
        # Dernière séance vélo
        bike_sessions = [s for s in sessions if s.get("type") in ("Ride", "VirtualRide")]
        if not bike_sessions:
            print("❌ Aucune séance vélo enrichie trouvée.")
            sys.exit(1)
        target = max(bike_sessions, key=lambda s: s.get("date", ""))
    else:
        # Cherche par date
        matching = [s for s in sessions if date_str in s.get("date", "")]
        if not matching:
            print(f"❌ Aucune séance enrichie trouvée pour la date '{date_str}'.")
            print("   Lance 'python -m ai_coach.main enrich --max 200' d'abord.")
            sys.exit(1)
        # Si plusieurs le même jour, prend celle avec le plus de TSS
        target = max(matching, key=lambda s: s.get("tss", 0))

    act_id = target["id"]
    print(f"📊 Séance : {target.get('name')} ({target.get('date')})")
    print(f"   [{target.get('tag')}] TSS={target.get('tss')} NP={target.get('np_watts')}W")

    # Fetch les streams
    print("   Chargement des streams...")
    streams = fetch_activity_streams(act_id)
    if not streams:
        print("❌ Impossible de charger les streams.")
        sys.exit(1)

    # Fetch les intervalles pour surlignage (optionnel)
    intervals_data = fetch_activity_intervals(act_id)

    # Génère le graphe
    print("   Génération du graphe...")
    path = plot_session(
        streams=streams,
        session_summary=target,
        intervals_data=intervals_data,
    )
    if path:
        print(f"✅ Graphe généré : {path}")
    else:
        print("❌ Échec de la génération.")

def cmd_metrics() -> None:
    """Affiche les métriques avancées."""
    from ai_coach.intervals import load_cached_activities
    from ai_coach.analysis import build_report

    activities = load_cached_activities()
    if not activities:
        print("❌ Aucun cache. Lance d'abord: python -m ai_coach.main refresh")
        sys.exit(1)

    print("📊 Calcul des métriques avancées...\n")
    report = build_report(activities)

    # Monotonie & Strain
    mono = report.get("monotony_strain", {})
    if mono:
        print("🔄 Monotonie & Strain (7 derniers jours)")
        print(f"   Monotonie : {mono.get('monotony', '?')} ({mono.get('monotony_status', '?')})")
        print(f"   Strain    : {mono.get('strain', '?')} ({mono.get('strain_status', '?')})")
        print(f"   TSS/jour  : {mono.get('daily_mean_tss', '?')} ± {mono.get('daily_std_tss', '?')}")
        print()

    # Projection CTL
    forecast = report.get("ctl_forecast", [])
    if forecast:
        print("📈 Projection CTL")
        for f in forecast:
            arrow = "↗️" if f["delta_vs_now"] > 0 else "↘️"
            print(f"   J+{f['horizon_days']:>2} ({f['target_date']}) : CTL = {f['projected_ctl']} ({arrow} {f['delta_vs_now']:+.1f})")
        print(f"   Hypothèse : ~{forecast[0]['assumption_daily_tss']:.0f} TSS/jour")
        print()

    # Durabilité
    dur = report.get("durability", {})
    if dur and dur.get("status") != "insufficient_data":
        print("🏋️  Durabilité")
        print(f"   Note       : {dur.get('durability_rating', '?')}")
        print(f"   Découplage : {dur.get('avg_decoupling_pct', '?')}% en moyenne")
        if "trend" in dur:
            print(f"   Tendance   : {dur['trend']}")
        print(f"   ({dur.get('count', '?')} sorties >2h analysées)")
        print()

    # Tendance FTP
    ftp = report.get("ftp_trend", {})
    if ftp and ftp.get("status") != "insufficient_data":
        print("📉 Tendance FTP")
        if "trend" in ftp:
            print(f"   Tendance : {ftp['trend']}")
        if "recent_avg_top5_np" in ftp:
            print(f"   Top 5 NP récent  : {ftp['recent_avg_top5_np']}W")
        if "older_avg_top5_np" in ftp:
            print(f"   Top 5 NP ancien  : {ftp['older_avg_top5_np']}W")
        if "np_delta" in ftp:
            print(f"   Delta            : {'+' if ftp['np_delta'] > 0 else ''}{ftp['np_delta']}W")
        print()

    # Profil de puissance
    pp = report.get("power_profile", {})
    if pp and pp.get("profile"):
        print(f"⚡ Profil de puissance ({pp.get('weight_kg_used', '?')}kg)")
        for duration, data in pp["profile"].items():
            bar = "█" * max(1, int(data["w_kg"] * 3))
            print(f"   {duration:>5s} : {data['watts']:>4d}W = {data['w_kg']:.1f} W/kg  {bar}  ({data['level']})")
        if pp.get("strengths"):
            print(f"   💪 Forces    : {', '.join(pp['strengths'])}")
        if pp.get("weaknesses"):
            print(f"   ⚠️  Faiblesses : {', '.join(pp['weaknesses'])}")

    models = pp.get("power_models", {})
    if models:
        print(f"\n   🔬 Modèles de puissance (Intervals.icu) :")
        for name, m in models.items():
            parts = []
            if m.get("cp"):
                parts.append(f"CP={m['cp']}W")
            if m.get("ftp"):
                parts.append(f"FTP={m['ftp']}W")
            if m.get("w_prime"):
                parts.append(f"W'={round(m['w_prime'] / 1000, 1)}kJ")
            if m.get("p_max"):
                parts.append(f"Pmax={m['p_max']}W")
            print(f"      {name}: {', '.join(parts)}")

    vo2 = pp.get("vo2max_estimated")
    if vo2:
        print(f"\n   🫁 VO2max estimée : {vo2:.1f} ml/kg/min")

def cmd_power_curve() -> None:
    """Génère le graphe de power curve."""
    from ai_coach.charts import plot_power_curve
    print("⚡ Génération de la power curve...")
    path = plot_power_curve()
    if path:
        print(f"✅ Graphe généré : {path}")
    else:
        print("❌ Échec de la génération.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="ai-coach")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("check", help="Vérifie la config")

    refresh_parser = subparsers.add_parser("refresh", help="Fetch Intervals.icu")
    refresh_parser.add_argument(
        "--days", type=int, default=750, help="Nombre de jours à fetcher (défaut: 750)"
    )

    subparsers.add_parser("summary", help="Résumé du cache local")
    subparsers.add_parser("analyze", help="Analyse + graphes + rapport JSON")
    subparsers.add_parser("bot", help="Démarre le bot Discord")

    ask_parser = subparsers.add_parser("ask", help="Question libre au coach")
    ask_parser.add_argument("question", type=str, help="Ta question entre guillemets")

    plan_parser = subparsers.add_parser("plan", help="Plan d'entraînement N jours")
    plan_parser.add_argument(
        "--days", type=int, default=7, help="Horizon du plan (défaut: 7)"
    )

    enrich_parser = subparsers.add_parser("enrich", help="Enrichit les séances (détails + intervalles)")
    enrich_parser.add_argument(
        "--max", type=int, default=20, dest="max_new",
        help="Max de nouvelles séances à fetcher (défaut: 20)"
    )

    session_parser = subparsers.add_parser("session", help="Graphe détaillé d'une séance")
    session_parser.add_argument(
        "date", type=str,
        help="Date (ex: 2026-04-08) ou 'last' pour la dernière"
    )
    subparsers.add_parser("metrics", help="Métriques avancées (monotonie, projection, durabilité, FTP, profil)")

    subparsers.add_parser("power_curve", help="Graphe de power curve")

    args = parser.parse_args()

    if args.command == "check":
        cmd_check()
    elif args.command == "refresh":
        cmd_refresh(days=args.days)
    elif args.command == "summary":
        cmd_summary()
    elif args.command == "analyze":
        cmd_analyze()
    elif args.command == "ask":
        cmd_ask(args.question)
    elif args.command == "plan":
        cmd_plan(days=args.days)
    elif args.command == "bot":
        from ai_coach.bot import run_bot
        run_bot()
    elif args.command == "enrich":
        cmd_enrich(max_new=args.max_new)
    elif args.command == "session":
        cmd_session(date_str=args.date)
    elif args.command == "metrics":
        cmd_metrics()
    elif args.command == "power_curve":
            cmd_power_curve()

if __name__ == "__main__":
    main()