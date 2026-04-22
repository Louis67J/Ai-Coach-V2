"""Script temporaire : inspecter les détails d'une activité."""
import json
import requests
from ai_coach.intervals import IntervalsClient, load_cached_activities

client = IntervalsClient()

# Prend la première activité exploitable du cache
activities = load_cached_activities()
usable = [a for a in activities if (a.get("icu_training_load") or 0) > 0]

if not usable:
    print("Aucune activité exploitable en cache.")
    exit()

# Prend la plus grosse (TSS max) pour avoir du contenu intéressant
best = max(usable, key=lambda a: a.get("icu_training_load") or 0)
act_id = best["id"]
name = best.get("name", "?")
tss = best.get("icu_training_load", 0)

print(f"Activité choisie : {name} (TSS={tss}, id={act_id})")
print("=" * 60)

# Fetch les détails complets
url = f"{client.base_url}/athlete/{client.athlete_id}/activities/{act_id}"
response = requests.get(url, auth=client.auth, timeout=30)
response.raise_for_status()

data = response.json()

# Diagnostic : quel type de données on reçoit ?
print(f"\nType reçu : {type(data).__name__}")

if isinstance(data, list):
    print(f"C'est une liste de {len(data)} éléments.")
    if len(data) > 0:
        first = data[0]
        if isinstance(first, dict):
            print(f"\nPremier élément = dict avec {len(first)} clés :")
            for key in sorted(first.keys()):
                val = first[key]
                if isinstance(val, (str, int, float, bool, type(None))):
                    print(f"  {key}: {val}")
                elif isinstance(val, list):
                    print(f"  {key}: [liste, {len(val)} éléments]")
                elif isinstance(val, dict):
                    print(f"  {key}: {{dict, {len(val)} clés}}")
            data_to_save = first
        else:
            print(f"Premier élément type: {type(first).__name__}")
            print(f"Contenu: {str(first)[:500]}")
            data_to_save = data
elif isinstance(data, dict):
    print(f"Dict avec {len(data)} clés :")
    for key in sorted(data.keys()):
        val = data[key]
        if isinstance(val, (str, int, float, bool, type(None))):
            print(f"  {key}: {val}")
        elif isinstance(val, list):
            print(f"  {key}: [liste, {len(val)} éléments]")
        elif isinstance(val, dict):
            print(f"  {key}: {{dict, {len(val)} clés}}")
    data_to_save = data
else:
    print(f"Type inattendu : {type(data)}")
    print(str(data)[:1000])
    data_to_save = data

# Sauvegarde le JSON complet pour inspection
output = "data/activity_detail_sample.json"
with open(output, "w", encoding="utf-8") as f:
    json.dump(data_to_save, f, indent=2, ensure_ascii=False)
print(f"\n💾 Détails complets sauvegardés dans {output}")
print(f"   Ouvre {output} dans PyCharm pour explorer toutes les données.")