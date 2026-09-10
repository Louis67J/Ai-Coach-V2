"""
Tests du cas "budget de sortie épuisé".

Sur Sonnet 5, la réflexion adaptative consomme le même budget que le texte :
une réponse peut revenir tronquée en plein milieu, voire complètement vide.
Sans signal explicite, l'interface affiche un blanc et le coach paraît figé —
c'est exactement ce qui est arrivé en production.
"""
from __future__ import annotations

import types

import pytest

from ai_coach import coach


class _FakeMessages:
    def __init__(self, response):
        self._response = response

    def create(self, **kwargs):
        return self._response


class _FakeClient:
    def __init__(self, response):
        self.messages = _FakeMessages(response)


def _response(stop_reason: str, blocks: list, output_tokens: int = 3000):
    return types.SimpleNamespace(
        stop_reason=stop_reason,
        content=blocks,
        usage=types.SimpleNamespace(
            input_tokens=10,
            output_tokens=output_tokens,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        ),
    )


def _text(value: str):
    return types.SimpleNamespace(type="text", text=value)


@pytest.fixture
def _no_side_effects(monkeypatch):
    """Neutralise mémoire, RAG et compaction : on teste la seule extraction."""
    monkeypatch.setattr(coach, "summarize_old_exchanges", lambda **k: None)
    monkeypatch.setattr(coach, "load_memory_summary", lambda: "")
    monkeypatch.setattr(coach, "load_recent_exchanges", lambda **k: [])
    monkeypatch.setattr(coach, "search_similar", lambda *a, **k: [])
    monkeypatch.setattr(coach, "log_usage", lambda **k: None)


def _ask(monkeypatch, response) -> str:
    monkeypatch.setattr(coach, "_client", lambda: _FakeClient(response))
    return coach.ask_coach("Une question", {"current_fitness": {}}, persist=False)


def test_reponse_complete_intacte(monkeypatch, _no_side_effects):
    answer = _ask(monkeypatch, _response("end_turn", [_text("CTL 51, tu peux charger.")]))
    assert answer == "CTL 51, tu peux charger."
    assert "interrompue" not in answer


def test_reponse_tronquee_est_signalee(monkeypatch, _no_side_effects):
    """Le texte partiel est conservé, mais la coupure doit être visible."""
    answer = _ask(monkeypatch, _response("max_tokens", [_text("Début de rép")]))
    assert "Début de rép" in answer
    assert "interrompue" in answer


def test_reponse_vide_ne_renvoie_pas_du_blanc(monkeypatch, _no_side_effects):
    """
    Le cas qui figeait l'interface : tout le budget parti en réflexion,
    aucun bloc de texte, donc une réponse vide affichée telle quelle.
    """
    answer = _ask(monkeypatch, _response("max_tokens", []))
    assert answer.strip()
    assert "interrompue" in answer


# --- L'échange abîmé ne doit pas contaminer les appels suivants ---

def test_reponse_vide_nest_pas_memorisee(tmp_path, monkeypatch):
    """
    Le vrai enchaînement observé : un appel coupé renvoie une réponse vide,
    elle est mémorisée, puis chaque appel suivant échoue en 400 sur un bloc
    de texte vide. Un incident ponctuel devenait une panne permanente.
    """
    from ai_coach import memory

    monkeypatch.setattr(memory, "conversations_path", lambda: tmp_path / "conv.jsonl")

    memory.append_exchange(question="Une question", answer="")
    memory.append_exchange(question="Une autre", answer="   ")
    assert memory.count_exchanges() == 0

    memory.append_exchange(question="Une vraie", answer="Une vraie réponse")
    assert memory.count_exchanges() == 1


def test_echange_vide_deja_stocke_est_ignore():
    """L'historique déjà pollué doit rester utilisable sans nettoyage manuel."""
    from ai_coach.memory import to_anthropic_messages

    exchanges = [
        {"question": "q1", "answer": "r1"},
        {"question": "q2", "answer": ""},        # l'échange abîmé
        {"question": "q3", "answer": "r3"},
    ]
    messages = to_anthropic_messages(exchanges)

    assert len(messages) == 4  # deux échanges valides seulement
    assert all((m["content"] or "").strip() for m in messages)
