"""
Chargement centralisé de la configuration depuis les variables d'environnement.

Tout le reste du code importe ses secrets/paramètres d'ici, jamais via
os.getenv() directement. Ça nous donne un seul endroit pour valider,
typer, et documenter la config.
"""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _harden_console_encoding() -> None:
    """
    Rend stdout/stderr tolérants aux caractères non-ASCII.

    Sous Windows, la console (et toute redirection vers un fichier) utilise
    cp1252 par défaut : le moindre emoji dans un message de progression lève
    une UnicodeEncodeError et fait planter l'appel complet — l'enrichissement
    mourait sur son premier "🔁 Reclassification". On élargit l'encodage
    plutôt que de bannir les emojis d'une base de code qui en utilise partout.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            # Flux déjà remplacé (tests, capture) ou non reconfigurable :
            # on tente au moins de ne plus lever sur les caractères inconnus.
            try:
                stream.reconfigure(errors="replace")
            except (AttributeError, ValueError, OSError):
                pass


_harden_console_encoding()


def configure_logging(level: int = logging.INFO) -> None:
    """
    Branche les logs des modules métier sur la console.

    À appeler par les points d'entrée (CLI, bot, dashboard) uniquement : les
    modules métier se contentent d'émettre via `logging`, et c'est l'appelant
    qui décide où ça sort. C'est ce qui permet à la même fonction de servir la
    CLI, le bot Discord et Streamlit sans leur imposer sa sortie — et d'éviter
    qu'un message de progression fasse tomber l'application qui l'appelle.
    """
    logging.basicConfig(level=level, format="%(message)s")


# --- Athlète courant ---------------------------------------------------
#
# Tout est aujourd'hui mono-athlète, mais les chemins de données passent par
# ici plutôt que d'être figés à l'import. C'est la seule couture nécessaire
# pour qu'ouvrir l'app à quelqu'un d'autre ne demande pas de reprendre chaque
# module : il suffira de positionner l'athlète courant en début de requête.

DEFAULT_ATHLETE = "me"
_current_athlete = DEFAULT_ATHLETE


def current_athlete() -> str:
    return _current_athlete


def set_current_athlete(slug: str) -> None:
    """Bascule l'athlète dont on lit/écrit les données."""
    global _current_athlete
    _current_athlete = slug or DEFAULT_ATHLETE


def athlete_data_dir(athlete: str | None = None) -> Path:
    """
    Dossier de données d'un athlète.

    L'athlète par défaut garde la racine `data/` : les fichiers existants ne
    bougent pas, et rien ne change pour une installation mono-utilisateur.
    Tout autre athlète est isolé dans `data/athletes/<slug>/`.
    """
    athlete = athlete or current_athlete()
    if athlete == DEFAULT_ATHLETE:
        return DATA_DIR
    path = DATA_DIR / "athletes" / athlete
    path.mkdir(parents=True, exist_ok=True)
    return path


def athlete_path(filename: str, athlete: str | None = None) -> Path:
    """Chemin d'un fichier de données pour l'athlète courant."""
    return athlete_data_dir(athlete) / filename


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