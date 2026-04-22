"""Inspecter les intervalles et zones d'une activité."""
import json

with open("data/activity_detail_sample.json", encoding="utf-8") as f:
    data = json.load(f)

print("=== INTERVAL SUMMARY ===")
intervals = data.get("interval_summary", [])
print(json.dumps(intervals, indent=2, ensure_ascii=False)[:3000])

print("\n=== POWER ZONE TIMES ===")
zones = data.get("icu_zone_times", [])
print(json.dumps(zones, indent=2, ensure_ascii=False))

print("\n=== HR ZONE TIMES ===")
hr_zones = data.get("icu_hr_zone_times", [])
print(json.dumps(hr_zones, indent=2, ensure_ascii=False))

print("\n=== POWER ZONES (definitions) ===")
pz = data.get("icu_power_zones", [])
print(json.dumps(pz, indent=2, ensure_ascii=False))