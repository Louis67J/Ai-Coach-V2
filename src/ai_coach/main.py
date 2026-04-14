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


def main() -> None:
    parser = argparse.ArgumentParser(prog="ai-coach")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("check", help="Vérifie la config")

    refresh_parser = subparsers.add_parser("refresh", help="Fetch Intervals.icu")
    refresh_parser.add_argument(
        "--days", type=int, default=30, help="Nombre de jours à fetcher (défaut: 30)"
    )

    subparsers.add_parser("summary", help="Résumé du cache local")

    args = parser.parse_args()

    if args.command == "check":
        cmd_check()
    elif args.command == "refresh":
        cmd_refresh(days=args.days)
    elif args.command == "summary":
        cmd_summary()


if __name__ == "__main__":
    main()