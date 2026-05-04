"""
Mémoire conversationnelle persistante.

Stocke chaque échange (question, réponse) dans un fichier JSONL append-only.
Les N derniers échanges sont relus avant chaque appel au LLM pour donner
au coach une vraie continuité.

Format d'un échange (une ligne JSON par échange):
{
    "timestamp": "2026-04-15T18:42:33Z",
    "source": "discord" | "cli",
    "question": "...",
    "answer": "...",
    "metadata": {
        "discord_user": "Louisj",
        "discord_channel": "coach"
    }
}
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ai_coach.config import DATA_DIR


CONVERSATIONS_PATH = DATA_DIR / "conversations.jsonl"


def append_exchange(
    question: str,
    answer: str,
    source: str = "cli",
    metadata: dict[str, Any] | None = None,
) -> None:
    """
    Append un nouvel échange à la mémoire.

    Args:
        question: la question posée par l'athlète
        answer: la réponse du coach
        source: "discord" ou "cli" (ou autre canal futur)
        metadata: infos contextuelles libres (utilisateur, salon, etc.)
    """
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "source": source,
        "question": question,
        "answer": answer,
        "metadata": metadata or {},
    }
    # Append en mode 'a' = ajoute en fin de fichier sans écraser
    with CONVERSATIONS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_recent_exchanges(limit: int = 20) -> list[dict[str, Any]]:
    """
    Charge les N derniers échanges depuis le fichier.

    Returns:
        Liste des échanges du plus ancien au plus récent (ordre chronologique)
    """
    if not CONVERSATIONS_PATH.exists():
        return []

    # Lit tout le fichier — pour des volumes raisonnables (< 10k échanges)
    # c'est négligeable. À optimiser si on dépasse un jour.
    exchanges = []
    with CONVERSATIONS_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                exchanges.append(json.loads(line))
            except json.JSONDecodeError:
                # Ligne corrompue, on l'ignore plutôt que de tout casser
                continue

    return exchanges[-limit:]


def to_anthropic_messages(exchanges: list[dict[str, Any]]) -> list[dict[str, str]]:
    """
    Convertit une liste d'échanges en format messages pour l'API Anthropic.

    Format Anthropic: [
        {"role": "user", "content": "..."},
        {"role": "assistant", "content": "..."},
        ...
    ]

    On alterne strictement user/assistant, sans le contexte injecté
    (profil, calendrier, rapport) — celui-ci sera ajouté au dernier user message.
    """
    messages = []
    for ex in exchanges:
        messages.append({"role": "user", "content": ex["question"]})
        messages.append({"role": "assistant", "content": ex["answer"]})
    return messages


def count_exchanges() -> int:
    """Nombre total d'échanges en mémoire."""
    if not CONVERSATIONS_PATH.exists():
        return 0
    with CONVERSATIONS_PATH.open("r", encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def clear_all() -> int:
    """
    Efface toute la mémoire conversationnelle.
    Returns: nombre d'échanges qui ont été effacés.
    """
    n = count_exchanges()
    if CONVERSATIONS_PATH.exists():
        CONVERSATIONS_PATH.unlink()
    return n


def remove_last() -> bool:
    """
    Supprime le dernier échange.
    Returns: True si un échange a été supprimé, False sinon.
    """
    if not CONVERSATIONS_PATH.exists():
        return False

    lines = CONVERSATIONS_PATH.read_text(encoding="utf-8").splitlines()
    if not lines:
        return False

    # On retire la dernière ligne non vide
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return False
    lines.pop()

    CONVERSATIONS_PATH.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return True


def format_recent_for_display(limit: int = 5) -> str:
    """
    Formatte les N derniers échanges pour affichage humain (debug, !history).
    """
    exchanges = load_recent_exchanges(limit=limit)
    if not exchanges:
        return "(Aucun échange en mémoire.)"

    lines = []
    for i, ex in enumerate(exchanges, 1):
        ts = ex.get("timestamp", "?")[:19].replace("T", " ")
        src = ex.get("source", "?")
        q = ex.get("question", "")
        a = ex.get("answer", "")
        # Tronque pour éviter le bruit visuel
        q_short = q if len(q) <= 200 else q[:200] + "…"
        a_short = a if len(a) <= 400 else a[:400] + "…"
        lines.append(f"--- Échange #{i} [{ts}, {src}] ---")
        lines.append(f"❓ {q_short}")
        lines.append(f"💬 {a_short}")
        lines.append("")
    return "\n".join(lines)

def summarize_old_exchanges(
    keep_recent: int = 15,
    summary_trigger: int = 25,
) -> str | None:
    """
    Si le nombre d'échanges dépasse summary_trigger, résume les anciens
    et ne garde que les keep_recent plus récents en détail.

    Le résumé est stocké dans data/memory_summary.txt et rechargé
    à chaque appel au coach comme contexte permanent.

    Returns:
        Le résumé généré, ou None si pas nécessaire.
    """
    total = count_exchanges()
    if total < summary_trigger:
        return None

    all_exchanges = load_recent_exchanges(limit=10000)  # tout charger
    old_exchanges = all_exchanges[:-keep_recent]
    recent_exchanges = all_exchanges[-keep_recent:]

    if not old_exchanges:
        return None

    # Charge le résumé existant s'il y en a un
    existing_summary = load_memory_summary()

    # Construit le texte des anciens échanges à résumer
    old_text_parts = []
    if existing_summary:
        old_text_parts.append(f"Résumé précédent des conversations anciennes :\n{existing_summary}\n")
    old_text_parts.append("Nouveaux échanges à intégrer au résumé :")
    for ex in old_exchanges:
        ts = ex.get("timestamp", "?")[:10]
        old_text_parts.append(f"[{ts}] Question: {ex['question'][:200]}")
        old_text_parts.append(f"[{ts}] Réponse: {ex['answer'][:300]}")

    old_text = "\n".join(old_text_parts)

    # Appelle Claude pour résumer
    from anthropic import Anthropic
    from ai_coach.config import load_config
    import os

    config = load_config()
    client = Anthropic(api_key=config.anthropic_api_key)
    model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")

    response = client.messages.create(
        model=model,
        max_tokens=800,
        system=(
            "Tu es un assistant qui résume des conversations entre un coach cyclisme IA "
            "et son athlète. Produis un résumé concis (max 500 mots) qui capture : "
            "1) Les sujets abordés, 2) Les décisions prises, 3) Les problèmes identifiés, "
            "4) Les recommandations données, 5) Le contexte émotionnel/motivationnel. "
            "Ce résumé sera relu par le coach IA pour maintenir la continuité. "
            "Écris en français, à la 3e personne."
        ),
        messages=[{"role": "user", "content": old_text}],
    )

    summary = "\n".join(
        block.text for block in response.content if block.type == "text"
    ).strip()

    # Sauvegarde le résumé
    SUMMARY_PATH.write_text(summary, encoding="utf-8")

    # Réécrit le fichier conversations avec seulement les récents
    if CONVERSATIONS_PATH.exists():
        CONVERSATIONS_PATH.unlink()
    for ex in recent_exchanges:
        append_exchange(
            question=ex["question"],
            answer=ex["answer"],
            source=ex.get("source", "cli"),
            metadata=ex.get("metadata"),
        )

    print(f"  🧠 Mémoire compactée : {len(old_exchanges)} anciens échanges → résumé "
          f"({len(summary)} chars), {len(recent_exchanges)} récents gardés")

    return summary


SUMMARY_PATH = DATA_DIR / "memory_summary.txt"


def load_memory_summary() -> str:
    """Charge le résumé de mémoire long terme s'il existe."""
    if SUMMARY_PATH.exists():
        return SUMMARY_PATH.read_text(encoding="utf-8").strip()
    return ""