"""Test rapide du parseur GPX."""
import sys
from ai_coach.gpx import analyze_gpx, format_gpx_for_llm

# Prend un fichier GPX en argument
if len(sys.argv) < 2:
    print("Usage: python test_gpx.py mon_parcours.gpx")
    exit(1)

with open(sys.argv[1], encoding="utf-8") as f:
    content = f.read()

summary = analyze_gpx(content)
text = format_gpx_for_llm(summary, ftp=310, weight_kg=63.0)
print(text)