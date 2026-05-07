"""Debug RAG : vérifie que les embeddings fonctionnent."""
from ai_coach.rag import _get_collection, _get_embedding_model

collection = _get_collection()
print(f"Collection: {collection.count()} documents")

# Récupère un document pour voir
result = collection.peek(limit=1)
print(f"\nPremier document:")
print(f"  ID: {result['ids'][0]}")
print(f"  Metadata: {result['metadatas'][0]}")
if result.get('embeddings') is not None and len(result['embeddings']) > 0:
    print(f"  Embedding length: {len(result['embeddings'][0])}")
else:
    print(f"  Embedding: None (pas stocké dans peek)")

# Teste un embedding manuel
model = _get_embedding_model()
test_query = "TFL genou blessure"
embedding = model.encode(test_query)
print(f"\nTest embedding shape: {embedding.shape}")
print(f"Test embedding[:5]: {embedding[:5]}")

# Requête directe ChromaDB
print(f"\nRequête directe ChromaDB...")
results = collection.query(
    query_embeddings=[embedding.tolist()],
    n_results=3,
    include=["metadatas", "distances", "documents"],
)
print(f"  IDs trouvés: {results.get('ids', [[]])[0]}")
print(f"  Distances: {results.get('distances', [[]])[0]}")
if results.get('metadatas') and results['metadatas'][0]:
    for i, meta in enumerate(results['metadatas'][0]):
        print(f"  [{i}] {meta.get('date', '?')}: {meta.get('question', '?')[:80]}")