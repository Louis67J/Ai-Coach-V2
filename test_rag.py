from ai_coach.rag import search_similar

results = search_similar("TFL genou blessure")
print(f"{len(results)} résultats :\n")
for r in results:
    print(f"  {r['date']} ({r['similarity']:.0%})")
    print(f"  Q: {r['question'][:100]}")
    print(f"  R: {r['answer_preview'][:150]}...")
    print()