"""
Mémoire sémantique (RAG) — Retrieval Augmented Generation.

Utilise ChromaDB + sentence-transformers pour stocker et retrouver
des échanges passés par similarité sémantique.

Chaque échange (question + réponse) est vectorisé et stocké.
Quand une nouvelle question arrive, on cherche les échanges passés
les plus similaires pour les injecter dans le contexte du coach.
"""
from __future__ import annotations

import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

from ai_coach.config import DATA_DIR


RAG_DIR = DATA_DIR / "rag"
RAG_DIR.mkdir(exist_ok=True, parents=True)

# Singleton pour éviter de recharger le modèle à chaque appel
_embedding_model = None
_chroma_collection = None


def _get_embedding_model():
    """Charge le modèle d'embedding (une seule fois)."""
    global _embedding_model
    if _embedding_model is None:
        print("  🧠 Chargement du modèle d'embedding (première fois uniquement)...")
        from sentence_transformers import SentenceTransformer
        # Modèle léger et multilingue — bon pour le français
        _embedding_model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
        print("  ✅ Modèle chargé")
    return _embedding_model


def _get_collection():
    """Récupère ou crée la collection ChromaDB."""
    global _chroma_collection
    if _chroma_collection is None:
        import chromadb
        client = chromadb.PersistentClient(path=str(RAG_DIR))
        _chroma_collection = client.get_or_create_collection(
            name="conversations",
            metadata={"description": "Échanges coach-athlète pour recherche sémantique"},
        )
    return _chroma_collection


def _make_id(text: str, timestamp: str) -> str:
    """Crée un ID unique pour un échange."""
    raw = f"{timestamp}:{text[:100]}"
    return hashlib.md5(raw.encode()).hexdigest()


def index_exchange(
    question: str,
    answer: str,
    source: str = "cli",
    timestamp: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """
    Indexe un échange dans la base vectorielle.
    Le texte combiné (question + réponse résumée) est vectorisé.
    """
    ts = timestamp or (datetime.utcnow().isoformat() + "Z")
    doc_id = _make_id(question, ts)

    # Le document indexé = question + début de réponse (pour le contexte sémantique)
    # On ne met pas toute la réponse pour garder les vecteurs focalisés sur le sujet
    answer_preview = answer[:500] if len(answer) > 500 else answer
    document = f"Question: {question}\nRéponse: {answer_preview}"

    # Métadonnées stockées avec le vecteur
    meta = {
        "timestamp": ts,
        "date": ts[:10],
        "source": source,
        "question": question[:200],
        "answer_preview": answer[:300],
    }
    if metadata:
        for k, v in metadata.items():
            if isinstance(v, str):
                meta[k] = v[:100]

    collection = _get_collection()

    # Vérifie si déjà indexé (évite les doublons)
    existing = collection.get(ids=[doc_id])
    if existing and existing.get("ids"):
        return

    # Vectorise et stocke
    model = _get_embedding_model()
    embedding = model.encode(document).tolist()

    collection.add(
        ids=[doc_id],
        embeddings=[embedding],
        documents=[document],
        metadatas=[meta],
    )


def search_similar(
    query: str,
    n_results: int = 5,
    min_date: str | None = None,
) -> list[dict[str, Any]]:
    """
    Recherche les échanges passés les plus similaires à une requête.

    Returns:
        Liste de dicts avec : question, answer_preview, date, score
    """
    collection = _get_collection()

    if collection.count() == 0:
        return []

    model = _get_embedding_model()
    query_embedding = model.encode(query).tolist()

    # Requête ChromaDB
    where_filter = None
    if min_date:
        where_filter = {"date": {"$gte": min_date}}

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(n_results, collection.count()),
        where=where_filter if where_filter else None,
        include=["metadatas", "distances", "documents"],
    )

    # Formate les résultats
    matches = []
    if results and results.get("ids") and results["ids"][0]:
        for i, doc_id in enumerate(results["ids"][0]):
            meta = results["metadatas"][0][i] if results.get("metadatas") else {}
            distance = results["distances"][0][i] if results.get("distances") else 0

            # ChromaDB retourne des distances L2 (plus petit = plus similaire)
            # Pour des embeddings 384d normalisés, distances typiques : 0-50
            # On convertit en score de similarité inversé
            similarity = max(0, 1 - distance / 50)

            # Filtre les résultats très peu similaires
            if similarity < 0.1:
                continue

            matches.append({
                "question": meta.get("question", "?"),
                "answer_preview": meta.get("answer_preview", "?"),
                "date": meta.get("date", "?"),
                "source": meta.get("source", "?"),
                "similarity": round(similarity, 3),
            })

    return matches


def format_rag_results_for_llm(results: list[dict]) -> str:
    """Formate les résultats RAG pour le contexte du coach."""
    if not results:
        return ""

    lines = ["\n=== CONVERSATIONS PASSÉES PERTINENTES (mémoire sémantique) ==="]
    lines.append("(échanges passés retrouvés par similarité avec ta question actuelle)\n")

    for i, r in enumerate(results, 1):
        lines.append(f"  [{r['date']}] (pertinence: {r['similarity']:.0%})")
        lines.append(f"  Q: {r['question']}")
        lines.append(f"  R: {r['answer_preview']}")
        lines.append("")

    return "\n".join(lines)


def index_all_from_memory() -> int:
    """
    Indexe tous les échanges existants du fichier conversations.jsonl
    dans la base vectorielle. Utile pour la migration initiale.
    """
    from ai_coach.memory import CONVERSATIONS_PATH

    if not CONVERSATIONS_PATH.exists():
        return 0

    count = 0
    with CONVERSATIONS_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                exchange = json.loads(line)
                index_exchange(
                    question=exchange.get("question", ""),
                    answer=exchange.get("answer", ""),
                    source=exchange.get("source", "cli"),
                    timestamp=exchange.get("timestamp"),
                    metadata=exchange.get("metadata"),
                )
                count += 1
            except (json.JSONDecodeError, Exception):
                continue

    return count


def get_stats() -> dict[str, Any]:
    """Statistiques de la base RAG."""
    collection = _get_collection()
    return {
        "total_indexed": collection.count(),
        "storage_path": str(RAG_DIR),
    }