"""Chercher les power bests / power curve dans l'API Intervals."""
import json
import requests
from ai_coach.intervals import IntervalsClient

client = IntervalsClient()

# Power curve de l'athlète
endpoints = [
    f"/athlete/{client.athlete_id}/power-curves",
    f"/athlete/{client.athlete_id}/power-curves?type=Ride",
]

for endpoint in endpoints:
    url = f"{client.base_url}{endpoint}"
    print(f"\n--- {url}")
    try:
        resp = requests.get(url, auth=client.auth, timeout=30)
        print(f"    Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                print(f"    Liste de {len(data)} éléments")
                if data:
                    first = data[0]
                    if isinstance(first, dict):
                        print(f"    Clés: {list(first.keys())[:15]}")
                        print(f"    Premier: {json.dumps(first, ensure_ascii=False)[:500]}")
                    else:
                        print(f"    Type: {type(first).__name__}, valeur: {first}")
            elif isinstance(data, dict):
                print(f"    Dict avec {len(data)} clés: {list(data.keys())[:20]}")
                # Si c'est un dict avec des durées comme clés
                for k in list(data.keys())[:10]:
                    print(f"      {k}: {data[k]}")
    except Exception as e:
        print(f"    Erreur: {e}")

# Aussi : les peak power d'une activité spécifique
print("\n\n--- Power peaks d'une activité ---")
# Prend ta sortie Chamrousse
from ai_coach.intervals import load_cached_activities
activities = load_cached_activities()
target = None
for a in activities:
    if "Chamrousse" in (a.get("name") or ""):
        target = a
        break

if target:
    act_id = target["id"]
    for endpoint in [
        f"/activity/{act_id}/power-curve",
        f"/activity/{act_id}/peaks",
    ]:
        url = f"{client.base_url}{endpoint}"
        print(f"\n--- {url}")
        try:
            resp = requests.get(url, auth=client.auth, timeout=30)
            print(f"    Status: {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict):
                    print(f"    Clés: {list(data.keys())[:15]}")
                    for k in list(data.keys())[:5]:
                        val = data[k]
                        if isinstance(val, list):
                            print(f"      {k}: [{len(val)} pts] premiers: {val[:5]}")
                        else:
                            print(f"      {k}: {str(val)[:200]}")
                elif isinstance(data, list):
                    print(f"    Liste de {len(data)} éléments")
                    if data and isinstance(data[0], (int, float)):
                        print(f"    Premiers: {data[:10]}")
                        print(f"    (probablement watts par seconde)")
        except Exception as e:
            print(f"    Erreur: {e}")