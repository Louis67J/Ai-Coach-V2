"""Voir le contenu réel des streams."""
import json
import requests
from ai_coach.intervals import IntervalsClient, load_cached_activities

client = IntervalsClient()

activities = load_cached_activities()
target = None
for a in activities:
    if "Provesieux" in (a.get("name") or ""):
        target = a
        break

act_id = target["id"]
print(f"Activité : {target.get('name')} (id={act_id})")
print("=" * 60)

url = f"{client.base_url}/activity/{act_id}/streams?types=time,watts,heartrate,cadence,altitude,distance"
resp = requests.get(url, auth=client.auth, timeout=30)
data = resp.json()

print(f"\n{len(data)} streams reçus :\n")
for stream in data:
    stype = stream.get("type", "?")
    sdata = stream.get("data", [])
    print(f"  {stype:15s} | {len(sdata)} points | "
          f"premiers: {sdata[:5]} | derniers: {sdata[-3:]}")

# Sauvegarde
with open("data/streams_sample.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False)
print(f"\n💾 Sauvegardé dans data/streams_sample.json")