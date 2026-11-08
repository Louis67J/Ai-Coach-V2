"""Le coach en projet Claude n'a besoin que des accès Intervals.icu."""
import pytest

from ai_coach.config import load_config


def test_intervals_only_config_skips_anthropic_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("INTERVALS_API_KEY", "abc123")
    monkeypatch.setenv("INTERVALS_ATHLETE_ID", "i42")

    config = load_config(require_anthropic=False)

    assert config.intervals_api_key == "abc123"
    assert config.anthropic_api_key is None


def test_app_config_still_requires_anthropic_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("INTERVALS_API_KEY", "abc123")
    monkeypatch.setenv("INTERVALS_ATHLETE_ID", "i42")

    with pytest.raises(RuntimeError):
        load_config()
