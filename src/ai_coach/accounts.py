"""
Comptes utilisateurs et clés API de chaque athlète.

Deux choses distinctes vivent ici :

- les comptes (`data/accounts.json`) : identifiant + mot de passe haché
  (scrypt, sel aléatoire). On ne stocke jamais le mot de passe lui-même ;
- les clés API de chaque athlète (`data/athletes/<slug>/credentials.enc`),
  chiffrées avec la clé serveur APP_SECRET_KEY. Chaque athlète paie ainsi
  sa propre consommation Claude et lit ses propres données Intervals.icu.

L'athlète par défaut (installation mono-utilisateur) ne passe pas par ici :
ses clés restent dans .env.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import shutil
import threading
from pathlib import Path
from typing import Any

from ai_coach.config import DATA_DIR, DEFAULT_ATHLETE, athlete_path, is_valid_slug, utc_now_iso

# Paramètres scrypt recommandés pour un login interactif (~50 ms, 16 Mo).
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1

MIN_PASSWORD_LENGTH = 8

# Écritures du fichier de comptes sérialisées : deux inscriptions simultanées
# ne doivent pas s'écraser l'une l'autre.
_accounts_lock = threading.Lock()

CREDENTIAL_FIELDS = ("anthropic_api_key", "intervals_api_key", "intervals_athlete_id")


class AccountError(ValueError):
    """Erreur présentable telle quelle à l'utilisateur."""


def accounts_path() -> Path:
    return DATA_DIR / "accounts.json"


def credentials_path(slug: str) -> Path:
    return athlete_path("credentials.enc", slug)


# --- Comptes -------------------------------------------------------------


def _load_accounts() -> dict[str, Any]:
    path = accounts_path()
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_accounts(accounts: dict[str, Any]) -> None:
    path = accounts_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(accounts, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P
    )
    return "scrypt${}${}".format(
        base64.b64encode(salt).decode(), base64.b64encode(digest).decode()
    )


def _check_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_b64, digest_b64 = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    expected = _hash_password(password, base64.b64decode(salt_b64))
    return hmac.compare_digest(expected, stored)


def normalize_username(username: str) -> str:
    return (username or "").strip().lower()


def create_account(username: str, password: str) -> str:
    """Crée un compte et renvoie son slug (= identifiant normalisé)."""
    slug = normalize_username(username)
    if not is_valid_slug(slug) or slug == DEFAULT_ATHLETE:
        raise AccountError(
            "Identifiant invalide : 2 à 32 caractères, lettres minuscules, "
            "chiffres, « - » ou « _ »."
        )
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise AccountError(
            f"Le mot de passe doit faire au moins {MIN_PASSWORD_LENGTH} caractères."
        )
    with _accounts_lock:
        accounts = _load_accounts()
        if slug in accounts:
            raise AccountError("Cet identifiant est déjà pris.")
        accounts[slug] = {
            "password_hash": _hash_password(password),
            "created_at": utc_now_iso(),
        }
        _save_accounts(accounts)
    return slug


def authenticate(username: str, password: str) -> str | None:
    """Renvoie le slug si les identifiants sont bons, None sinon."""
    slug = normalize_username(username)
    account = _load_accounts().get(slug)
    if not account:
        # Hache quand même : la réponse prend le même temps qu'un compte
        # existant, ce qui n'indique pas quels identifiants sont pris.
        _hash_password(password or "")
        return None
    if _check_password(password or "", account.get("password_hash", "")):
        return slug
    return None


def account_exists(username: str) -> bool:
    return normalize_username(username) in _load_accounts()


# --- Données du propriétaire ----------------------------------------------

# Ce qui reste à la racine de data/ : l'annuaire des comptes, pas des données
# d'athlète.
_SHARED_DATA_ENTRIES = {"athletes", "accounts.json", "accounts.json.tmp"}


def move_default_data_to(slug: str) -> list[str]:
    """
    Range les données de l'installation mono-utilisateur (racine de data/)
    dans le dossier du compte `slug`, et renvoie les noms déplacés.

    Refuse d'écraser quoi que ce soit : si le dossier cible contient déjà un
    fichier du même nom, rien n'est déplacé.
    """
    if not is_valid_slug(slug) or slug == DEFAULT_ATHLETE:
        raise AccountError(f"Identifiant invalide : {slug!r}")
    target = DATA_DIR / "athletes" / slug
    entries = sorted(
        e for e in DATA_DIR.iterdir() if e.name not in _SHARED_DATA_ENTRIES
    ) if DATA_DIR.exists() else []
    clashes = [e.name for e in entries if (target / e.name).exists()]
    if clashes:
        raise AccountError(
            f"Le dossier {target} contient déjà : {', '.join(clashes)}. "
            "Rien n'a été déplacé."
        )
    target.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        shutil.move(str(entry), str(target / entry.name))
    return [e.name for e in entries]


# --- Clés API chiffrées --------------------------------------------------


def _fernet():
    from cryptography.fernet import Fernet

    key = os.getenv("APP_SECRET_KEY")
    if not key:
        raise RuntimeError(
            "❌ APP_SECRET_KEY n'est pas définie dans .env : elle est nécessaire "
            "pour chiffrer les clés des utilisateurs. Génère-la avec : "
            "python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        )
    return Fernet(key.encode())


def save_credentials(slug: str, credentials: dict[str, str]) -> None:
    """Chiffre et enregistre les clés API d'un athlète."""
    missing = [f for f in CREDENTIAL_FIELDS if not (credentials.get(f) or "").strip()]
    if missing:
        raise AccountError("Toutes les clés sont nécessaires.")
    payload = {f: credentials[f].strip() for f in CREDENTIAL_FIELDS}
    token = _fernet().encrypt(json.dumps(payload).encode("utf-8"))
    credentials_path(slug).write_bytes(token)


def load_credentials(slug: str) -> dict[str, str] | None:
    """Clés API déchiffrées d'un athlète, ou None s'il ne les a pas saisies."""
    path = credentials_path(slug)
    if not path.exists():
        return None
    from cryptography.fernet import InvalidToken

    try:
        data = _fernet().decrypt(path.read_bytes())
    except InvalidToken as e:
        raise RuntimeError(
            "❌ Impossible de déchiffrer les clés enregistrées : APP_SECRET_KEY a "
            "changé depuis leur saisie. Ressaisis-les depuis la page Profil."
        ) from e
    return json.loads(data)


def has_credentials(slug: str) -> bool:
    return credentials_path(slug).exists()


def mask_secret(value: str) -> str:
    """Affichage d'une clé sans la révéler : « sk-a…9xQz »."""
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:4]}…{value[-4:]}"
