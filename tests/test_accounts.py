"""
Tests des comptes et des clés API par athlète (mode multi-utilisateur).
"""
from __future__ import annotations

import threading

import pytest
from cryptography.fernet import Fernet

from ai_coach import accounts, config
from ai_coach.accounts import (
    AccountError,
    authenticate,
    create_account,
    has_credentials,
    load_credentials,
    mask_secret,
    save_credentials,
)
from ai_coach.config import (
    DEFAULT_ATHLETE,
    athlete_data_dir,
    current_athlete,
    load_config,
    outputs_path,
    set_current_athlete,
)

CREDS = {
    "anthropic_api_key": "sk-ant-bob-0123456789",
    "intervals_api_key": "bob-intervals-key",
    "intervals_athlete_id": "i424242",
}


@pytest.fixture(autouse=True)
def _isolated_data(tmp_path, monkeypatch):
    """Chaque test travaille dans son propre data/ et avec sa propre clé serveur."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(accounts, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path / "outputs")
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("APP_SECRET_KEY", Fernet.generate_key().decode())
    original = current_athlete()
    yield
    set_current_athlete(original)


def test_compte_cree_puis_authentifie():
    slug = create_account("Bob", "motdepasse123")
    assert slug == "bob"
    assert authenticate("bob", "motdepasse123") == "bob"
    assert authenticate(" BOB ", "motdepasse123") == "bob"


def test_mauvais_mot_de_passe_ou_compte_inconnu():
    create_account("bob", "motdepasse123")
    assert authenticate("bob", "mauvais-mot") is None
    assert authenticate("alice", "motdepasse123") is None


def test_mot_de_passe_jamais_stocke_en_clair():
    create_account("bob", "motdepasse123")
    assert "motdepasse123" not in accounts.accounts_path().read_text(encoding="utf-8")


def test_identifiant_deja_pris():
    create_account("bob", "motdepasse123")
    with pytest.raises(AccountError):
        create_account("Bob", "autremotdepasse")


@pytest.mark.parametrize("username", ["", "a", "../etc", "bob/alice", "me", "é" * 3, "x" * 40])
def test_identifiant_invalide_refuse(username):
    with pytest.raises(AccountError):
        create_account(username, "motdepasse123")


def test_mot_de_passe_trop_court():
    with pytest.raises(AccountError):
        create_account("bob", "court")


def test_slug_ne_peut_pas_sortir_du_dossier_athletes():
    with pytest.raises(ValueError):
        athlete_data_dir("../../etc")
    with pytest.raises(ValueError):
        set_current_athlete("../bob")


def test_cles_chiffrees_sur_disque_et_relues():
    save_credentials("bob", CREDS)
    raw = accounts.credentials_path("bob").read_bytes()
    assert CREDS["anthropic_api_key"].encode() not in raw
    assert load_credentials("bob") == CREDS
    assert has_credentials("bob")


def test_cles_incompletes_refusees():
    with pytest.raises(AccountError):
        save_credentials("bob", {**CREDS, "intervals_api_key": " "})


def test_cle_serveur_changee_donne_une_erreur_claire(monkeypatch):
    save_credentials("bob", CREDS)
    monkeypatch.setenv("APP_SECRET_KEY", Fernet.generate_key().decode())
    with pytest.raises(RuntimeError, match="APP_SECRET_KEY"):
        load_credentials("bob")


def test_load_config_utilise_les_cles_de_l_athlete(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-owner")
    monkeypatch.setenv("INTERVALS_API_KEY", "owner-key")
    monkeypatch.setenv("INTERVALS_ATHLETE_ID", "i111")
    save_credentials("bob", CREDS)

    set_current_athlete("bob")
    cfg = load_config()
    assert cfg.anthropic_api_key == CREDS["anthropic_api_key"]
    assert cfg.intervals_athlete_id == "i424242"

    set_current_athlete(DEFAULT_ATHLETE)
    assert load_config().anthropic_api_key == "sk-ant-owner"


def test_athlete_sans_cles_ne_retombe_pas_sur_celles_du_proprietaire(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-owner")
    set_current_athlete("alice")
    with pytest.raises(RuntimeError, match="Profil"):
        load_config()


def test_athlete_courant_propre_a_chaque_thread():
    """Deux visiteurs servis en parallèle ne doivent pas voir l'athlète de l'autre."""
    seen = {}
    ready = threading.Barrier(2)

    def visit(slug):
        set_current_athlete(slug)
        ready.wait()
        seen[slug] = current_athlete()

    threads = [threading.Thread(target=visit, args=(s,)) for s in ("bob", "alice")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert seen == {"bob": "bob", "alice": "alice"}


def test_sorties_separees_par_athlete():
    assert outputs_path("x.png", "bob") != outputs_path("x.png", "alice")
    assert outputs_path("x.png", DEFAULT_ATHLETE).parent == config.OUTPUTS_DIR


def test_masquage_des_cles():
    assert mask_secret("sk-ant-abcdefgh1234") == "sk-a…1234"
    assert "abcdefgh" not in mask_secret("sk-ant-abcdefgh1234")
