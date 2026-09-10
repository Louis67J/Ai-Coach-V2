"""
Tests de ce qui est réexpédié à chaque appel.

L'historique conversationnel est le plus gros poste de tokens de chaque
requête, et il grossit tout seul. Ces tests fixent ce qui est rejoué mot
pour mot et ce qui est délégué au résumé long terme.
"""
from __future__ import annotations

from ai_coach.memory import (
    KEEP_RECENT_EXCHANGES,
    MAX_REPLAYED_ANSWER_CHARS,
    SUMMARY_TRIGGER,
    _shorten_answer,
    to_anthropic_messages,
)


def test_reponse_courte_intacte():
    answer = "CTL 51, TSB -12. Tu peux sortir."
    assert _shorten_answer(answer) == answer


def test_reponse_longue_tronquee_et_signalee():
    """
    Un plan complet pèse ~2 400 tokens et se retrouve rejoué à chaque appel
    suivant, alors qu'il vit déjà dans plans.jsonl.
    """
    answer = "A" * (MAX_REPLAYED_ANSWER_CHARS + 5000)
    shortened = _shorten_answer(answer)

    assert len(shortened) < len(answer)
    # La coupure est annoncée, pas silencieuse
    assert "tronquée" in shortened
    assert "get_plan_followup" in shortened


def test_troncature_a_la_limite_exacte():
    answer = "A" * MAX_REPLAYED_ANSWER_CHARS
    assert _shorten_answer(answer) == answer


def test_conversion_alterne_user_assistant():
    exchanges = [
        {"question": "q1", "answer": "r1"},
        {"question": "q2", "answer": "r2"},
    ]
    messages = to_anthropic_messages(exchanges)
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[0]["content"] == "q1"


def test_conversion_tronque_les_longues_reponses():
    exchanges = [{"question": "Fais-moi un plan", "answer": "B" * 9000}]
    messages = to_anthropic_messages(exchanges)
    assert len(messages[1]["content"]) < 9000
    assert "tronquée" in messages[1]["content"]


def test_les_questions_ne_sont_jamais_tronquees():
    """Ce que l'athlète a demandé reste intact : c'est court et c'est le contexte."""
    exchanges = [{"question": "Q" * 9000, "answer": "ok"}]
    assert len(to_anthropic_messages(exchanges)[0]["content"]) == 9000


def test_compaction_declenchee_avant_que_lhistorique_ne_gonfle():
    """Le seuil doit rester au-dessus de ce qu'on garde, sinon rien n'est jamais résumé."""
    assert SUMMARY_TRIGGER > KEEP_RECENT_EXCHANGES
