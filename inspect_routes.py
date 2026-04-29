"""Explorer les endpoints de routes/GPX d'Intervals.icu."""
import json
import requests
from ai_coach.intervals import IntervalsClient

client = IntervalsClient()

# 1. Routes de l'athlète
endpoints = [
    f"/athlete/{client.athlete_id}/routes",
    f"/athlete/{client.athlete_id}/events",
]

for endpoint in endpoints:
    url = f"{client.base_url}{endpoint}"
    print(f"\n--- {url}")
    try:
        resp = requests.get(url, auth=client.auth, timeout=15)
        print(f"    Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                print(f"    Liste de {len(data)} éléments")
                if data and isinstance(data[0], dict):
                    print(f"    Clés: {list(data[0].keys())[:20]}")
                    print(f"    Premier: {json.dumps(data[0], ensure_ascii=False)[:500]}")
            elif isinstance(data, dict):
                print(f"    Clés: {list(data.keys())[:20]}")
    except Exception as e:
        print(f"    Erreur: {e}")

# 2. Streams GPS d'une activité existante (pour vérifier qu'on a accès aux coords)
from ai_coach.intervals import load_cached_activities
activities = load_cached_activities()
target = None
for a in activities:
    if "Chamrousse" in (a.get("name") or ""):
        target = a
        break

if target:
    act_id = target["id"]
    print(f"\n\n--- Streams GPS de {target.get('name')} ({act_id})")
    url = f"{client.base_url}/activity/{act_id}/streams?types=latlng,altitude,distance"
    try:
        resp = requests.get(url, auth=client.auth, timeout=30)
        print(f"    Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            for stream in data:
                stype = stream.get("type", "?")
                sdata = stream.get("data", [])
                if sdata:
                    print(f"    {stype}: {len(sdata)} points, premiers: {sdata[:3]}")
    except Exception as e:
        print(f"    Erreur: {e}")

# 3. Vérifie si on peut accéder à un événement/course planifié
print(f"\n\n--- Events à venir")
url = f"{client.base_url}/athlete/{client.athlete_id}/events"
try:
    resp = requests.get(url, auth=client.auth, timeout=15)
    print(f"    Status: {resp.status_code}")
    if resp.status_code == 200:
        events = resp.json()
        print(f"    {len(events)} événements")
        for e in events[:5]:
            print(f"    {json.dumps(e, ensure_ascii=False)[:300]}")
except Exception as e:
    print(f"    Erreur: {e}")