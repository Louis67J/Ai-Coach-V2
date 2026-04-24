"""Inspecter le contenu détaillé des intervalles."""
import json
import requests
from ai_coach.intervals import IntervalsClient, load_cached_activities

client = IntervalsClient()

# Trouve Provesieux
activities = load_cached_activities()
target = None
for a in activities:
    if "Provesieux" in (a.get("name") or ""):
        target = a
        break

act_id = target["id"]
print(f"Activité : {target.get('name')} (id={act_id})")
print("=" * 60)

# Fetch les intervalles détaillés
url = f"{client.base_url}/activity/{act_id}/intervals"
resp = requests.get(url, auth=client.auth, timeout=30)
resp.raise_for_status()
data = resp.json()

# Explore icu_intervals
intervals = data.get("icu_intervals", [])
print(f"\nicu_intervals : {len(intervals)} intervalles")

if intervals:
    print(f"\nClés du premier intervalle ({len(intervals[0])} clés) :")
    for key in sorted(intervals[0].keys()):
        val = intervals[0][key]
        print(f"  {key}: {val}")

    # Affiche les 5 premiers intervalles en résumé
    print(f"\n--- Résumé des {min(10, len(intervals))} premiers intervalles ---")
    for i, iv in enumerate(intervals[:10]):
        label = iv.get("label") or iv.get("type") or "?"
        duration = iv.get("elapsed_time") or iv.get("moving_time") or iv.get("seconds") or "?"
        watts = iv.get("average_watts") or iv.get("avg_watts") or "?"
        hr = iv.get("average_heartrate") or iv.get("avg_hr") or "?"
        cadence = iv.get("average_cadence") or iv.get("avg_cadence") or "?"
        print(f"  [{i}] {label:15s} | {duration:>6}s | {watts:>4}W | HR={hr} | cad={cadence}")

# Explore icu_groups
groups = data.get("icu_groups", [])
print(f"\nicu_groups : {len(groups)} groupes")
if groups:
    print(f"Clés du premier groupe : {list(groups[0].keys())}")
    for g in groups[:5]:
        print(f"  {json.dumps(g, ensure_ascii=False)[:300]}")

# Sauvegarde complète
with open("data/intervals_full_sample.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
print(f"\n💾 Sauvegardé dans data/intervals_full_sample.json")