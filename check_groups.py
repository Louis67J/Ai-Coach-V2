import json

with open("data/sessions.json", encoding="utf-8") as f:
    cache = json.load(f)

for act_id, session in cache.items():
    if "04-22" in session.get("date", ""):
        print(f"Séance: {session.get('name')} ({session.get('date')})")
        groups = session.get("detailed_groups", [])
        print(f"Groupes détaillés: {len(groups)}")
        if groups:
            for i, g in enumerate(groups[:5]):
                print(f"\n  Groupe {i}: {g.get('label', '?')}")
        else:
            print("  → AUCUN groupe détaillé !")
            print(f"  Intervals bruts: {session.get('intervals', [])}")
        break