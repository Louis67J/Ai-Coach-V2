"""
Point d'entrée principal du AI Coach.
Pour l'instant : vérifie juste que l'environnement et la config sont OK.
"""
import os
from dotenv import load_dotenv


def main() -> None:
    load_dotenv()

    print("🚴 AI Coach v2 — Check de l'environnement")
    print("=" * 50)

    expected_vars = [
        "ANTHROPIC_API_KEY",
        "INTERVALS_API_KEY",
        "INTERVALS_ATHLETE_ID",
        "DISCORD_BOT_TOKEN",
        "DISCORD_CHANNEL_ID",
    ]

    for var in expected_vars:
        value = os.getenv(var)
        if value and value not in ("xxxxx", "i000000", "000000000000000000"):
            masked = value[:6] + "…" if len(value) > 6 else "…"
            print(f"  ✅ {var:25s} = {masked}")
        elif value:
            print(f"  ⚠️  {var:25s} = (placeholder, à remplir)")
        else:
            print(f"  ❌ {var:25s} = MANQUANT")

    print("=" * 50)
    print("Fondations OK ✨")


if __name__ == "__main__":
    main()