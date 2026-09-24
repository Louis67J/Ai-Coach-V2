"""
Chargement centralisé de la configuration depuis les variables d'environnement.

Tout le reste du code importe ses secrets/paramètres d'ici, jamais via
os.getenv() directement. Ça nous donne un seul endroit pour valider,
typer, et documenter la config.
"""
from __future__ import annotations

import logging
import os
import re
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
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

    # Les bibliothèques réseau et ML sont très bavardes en INFO (chaque requête
    # HTTP, chaque fichier de modèle) : à ce niveau elles noient complètement
    # les quelques lignes utiles de l'application.
    for noisy in (
        "httpx", "httpcore", "urllib3", "requests",
        "huggingface_hub", "sentence_transformers", "transformers",
        "chromadb", "anthropic",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# --- Athlète courant ---------------------------------------------------
#
# Les chemins de données passent par ici plutôt que d'être figés à l'import :
# c'est la couture qui permet d'ouvrir l'app à d'autres athlètes sans
# reprendre chaque module. Le point d'entrée positionne l'athlète courant en
# début de requête.
#
# Une ContextVar plutôt qu'une globale : Streamlit sert chaque visiteur dans
# son propre thread, et une globale ferait lire à l'un les données de l'autre
# dès que deux pages se chargent en même temps.

DEFAULT_ATHLETE = "me"
_current_athlete: ContextVar[str] = ContextVar("current_athlete", default=DEFAULT_ATHLETE)

# Un slug devient un nom de dossier : on n'accepte que ce qui ne peut pas
# sortir de data/athletes/ (pas de « .. », pas de « / »).
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,31}$")


def is_valid_slug(slug: str) -> bool:
    return bool(slug) and bool(_SLUG_RE.match(slug))


def current_athlete() -> str:
    return _current_athlete.get()


def set_current_athlete(slug: str) -> None:
    """Bascule l'athlète dont on lit/écrit les données."""
    slug = slug or DEFAULT_ATHLETE
    if slug != DEFAULT_ATHLETE and not is_valid_slug(slug):
        raise ValueError(f"Identifiant d'athlète invalide : {slug!r}")
    _current_athlete.set(slug)


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
    if not is_valid_slug(athlete):
        raise ValueError(f"Identifiant d'athlète invalide : {athlete!r}")
    path = DATA_DIR / "athletes" / athlete
    path.mkdir(parents=True, exist_ok=True)
    return path


def athlete_path(filename: str, athlete: str | None = None) -> Path:
    """Chemin d'un fichier de données pour l'athlète courant."""
    return athlete_data_dir(athlete) / filename


def outputs_path(filename: str, athlete: str | None = None) -> Path:
    """
    Chemin d'un fichier généré (graphe, rapport) pour l'athlète courant.

    Même logique que les données : l'athlète par défaut garde `outputs/`,
    les autres ont leur sous-dossier, pour qu'un graphe tracé pour l'un ne
    soit jamais servi à l'autre.
    """
    athlete = athlete or current_athlete()
    if athlete == DEFAULT_ATHLETE:
        directory = OUTPUTS_DIR
    else:
        if not is_valid_slug(athlete):
            raise ValueError(f"Identifiant d'athlète invalide : {athlete!r}")
        directory = OUTPUTS_DIR / "athletes" / athlete
    directory.mkdir(parents=True, exist_ok=True)
    return directory / filename


# Horodatage : on écrit en UTC, on affiche en heure locale.
#
# Les fichiers de données survivent ainsi aux déplacements de l'athlète — Louis
# est passé de la France à Sagunto sans que l'historique ne bouge — et deux
# machines dans deux fuseaux produisent des lignes comparables. Mais un
# horodatage UTC affiché tel quel se lit comme une heure locale fausse : c'est
# la conversion ci-dessous qui manquait.


def utc_now_iso() -> str:
    """Horodatage courant en UTC, format ISO suffixé « Z »."""
    # datetime.utcnow() est déprécié depuis Python 3.12 : il renvoyait un
    # datetime naïf auquel on recollait un « Z » à la main, soit une
    # affirmation de fuseau que rien ne garantissait. Ici le datetime connaît
    # réellement le sien.
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def to_local_display(timestamp: str, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Rend un horodatage stocké lisible dans le fuseau de la machine.

    Un horodatage sans fuseau est supposé UTC : c'est ce que le code écrivait
    avant, et l'historique déjà sur disque en est plein.
    """
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        # Ligne abîmée : mieux vaut l'afficher brute que faire échouer !history.
        return str(timestamp)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone().strftime(fmt)


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


def multi_user_enabled() -> bool:
    """Mode multi-utilisateur de l'app web (MULTI_USER=1 dans .env)."""
    return os.getenv("MULTI_USER", "").strip().lower() in ("1", "true", "yes", "on")


def load_config(require_discord: bool = False) -> Config:
    """
    Charge et valide la configuration.

    L'athlète par défaut lit ses clés dans .env, comme avant. Tout autre
    athlète utilise les clés qu'il a saisies lui-même dans l'app, stockées
    chiffrées dans son dossier (voir accounts.py) : personne ne consomme les
    clés du propriétaire de l'installation.

    Args:
        require_discord: si True, exige que les variables Discord soient
                         définies. Utile quand on lance le bot.
    """
    discord_token = os.getenv("DISCORD_BOT_TOKEN")
    discord_channel = os.getenv("DISCORD_CHANNEL_ID")

    if require_discord:
        discord_token = _require("DISCORD_BOT_TOKEN")
        discord_channel = _require("DISCORD_CHANNEL_ID")

    athlete = current_athlete()
    if athlete != DEFAULT_ATHLETE:
        # Import tardif : accounts importe ce module.
        from ai_coach.accounts import load_credentials

        creds = load_credentials(athlete)
        if not creds:
            raise RuntimeError(
                "❌ Tes clés API ne sont pas encore renseignées. "
                "Ajoute-les depuis la page Profil."
            )
        return Config(
            anthropic_api_key=creds["anthropic_api_key"],
            intervals_api_key=creds["intervals_api_key"],
            intervals_athlete_id=creds["intervals_athlete_id"],
            discord_bot_token=discord_token,
            discord_channel_id=discord_channel,
        )

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