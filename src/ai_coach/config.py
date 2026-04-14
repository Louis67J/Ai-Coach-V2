"""
Chargement centralisé de la configuration depuis les variables d'environnement.

Tout le reste du code importe ses secrets/paramètres d'ici, jamais via
os.getenv() directement. Ça nous donne un seul endroit pour valider,
typer, et documenter la config.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


# Charge .env une seule fois, au moment de l'import du module.
load_dotenv()


# Racine du projet (= le dossier qui contient pyproject.toml)
# __file__ est src/ai_coach/config.py → on remonte de 3 niveaux
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"


def _require(var_name: str) -> str:
    """Récupère une variable d'env obligatoire ou lève une erreur claire."""
    value = os.getenv(var_name)
    if not value or value.startswith("xxxxx") or value in ("i000000", "000000000000000000"):
        raise RuntimeError(
            f"❌ La variable {var_name} n'est pas définie dans .env "
            f"(ou contient encore un placeholder). "
            f"Édite ton fichier .env à la racine du projet."
        )
    return value


@dataclass(frozen=True)
class Config:
    """Configuration complète de l'application, chargée depuis .env."""

    # Anthropic
    anthropic_api_key: str

    # Intervals.icu
    intervals_api_key: str
    intervals_athlete_id: str  # format: "i123456"
    intervals_base_url: str = "https://intervals.icu/api/v1"

    # Discord (optionnel pour l'instant — on ne force pas leur présence)
    discord_bot_token: str | None = None
    discord_channel_id: str | None = None


def load_config(require_discord: bool = False) -> Config:
    """
    Charge et valide la configuration.

    Args:
        require_discord: si True, exige que les variables Discord soient
                         définies. Utile quand on lance le bot.
    """
    discord_token = os.getenv("DISCORD_BOT_TOKEN")
    discord_channel = os.getenv("DISCORD_CHANNEL_ID")

    if require_discord:
        discord_token = _require("DISCORD_BOT_TOKEN")
        discord_channel = _require("DISCORD_CHANNEL_ID")

    return Config(
        anthropic_api_key=_require("ANTHROPIC_API_KEY"),
        intervals_api_key=_require("INTERVALS_API_KEY"),
        intervals_athlete_id=_require("INTERVALS_ATHLETE_ID"),
        discord_bot_token=discord_token,
        discord_channel_id=discord_channel,
    )


# Assure que les dossiers de données existent
DATA_DIR.mkdir(exist_ok=True, parents=True)
OUTPUTS_DIR.mkdir(exist_ok=True, parents=True)