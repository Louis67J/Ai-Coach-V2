import json

with open("data/activities.json", encoding="utf-8") as f:
    data = json.load(f)

for a in data["activities"]:
    if "2026-04-22" in (a.get("start_date_local") or ""):
        print(f"  {a.get('source','?'):15s} | {a.get('type','?'):15s} | "
              f"TSS={a.get('icu_training_load') or 0:>3} | {a.get('name','(sans nom)')[:40]}")