"""Explorer l'endpoint wellness d'Intervals.icu."""
import json
import requests
from ai_coach.intervals import IntervalsClient
from datetime import date, timedelta

client = IntervalsClient()

# Wellness des 14 derniers jours
end = date.today().isoformat()
start = (date.today() - timedelta(days=14)).isoformat()

url = f"{client.base_url}/athlete/{client.athlete_id}/wellness?oldest={start}&newest={end}"
print(f"--- {url}")

resp = requests.get(url, auth=client.auth, timeout=30)
print(f"Status: {resp.status_code}")

if resp.status_code == 200:
    data = resp.json()
    if isinstance(data, list):
        print(f"Liste de {len(data)} jours")
        if data:
            print(f"\nClés du premier jour ({len(data[0])} clés) :")
            for key in sorted(data[0].keys()):
                val = data[0][key]
                print(f"  {key}: {val}")
            print(f"\nDerniers 3 jours :")
            for day in data[-3:]:
                d = day.get("id", "?")
                sleep = day.get("sleepQuality") or day.get("sleep_quality") or "?"
                hrv = day.get("hrv") or "?"
                rhr = day.get("restingHR") or day.get("resting_hr") or "?"
                soreness = day.get("soreness") or "?"
                print(f"  {d}: sleep={sleep}, HRV={hrv}, RHR={rhr}, soreness={soreness}")

            with open("data/wellness_sample.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"\n💾 Sauvegardé dans data/wellness_sample.json")
    else:
        print(f"Type inattendu: {type(data)}")
        print(str(data)[:500])
else:
    print(f"Erreur: {resp.text[:300]}")