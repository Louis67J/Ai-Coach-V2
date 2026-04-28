"""
Météo via Open-Meteo (gratuit, sans clé API).
Fournit les prévisions J+7 pour les injecter dans le contexte du coach.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import requests


def fetch_forecast(
    latitude: float = 45.19,
    longitude: float = 5.72,
    location_name: str = "Grenoble",
) -> dict[str, Any] | None:
    """
    Récupère les prévisions météo J+7 depuis Open-Meteo.

    Retourne un dict avec les prévisions journalières :
    température min/max, précipitations, vent, code météo.
    """
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": ",".join([
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "precipitation_probability_max",
            "wind_speed_10m_max",
            "wind_gusts_10m_max",
            "weather_code",
        ]),
        "timezone": "Europe/Paris",
        "forecast_days": 7,
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"  ⚠️ Météo indisponible: {e}")
        return None

    daily = data.get("daily", {})
    dates = daily.get("time", [])
    if not dates:
        return None

    # Codes météo WMO -> description
    wmo_codes = {
        0: "☀️ Ciel dégagé", 1: "🌤️ Peu nuageux", 2: "⛅ Partiellement nuageux",
        3: "☁️ Couvert", 45: "🌫️ Brouillard", 48: "🌫️ Brouillard givrant",
        51: "🌧️ Bruine légère", 53: "🌧️ Bruine modérée", 55: "🌧️ Bruine dense",
        61: "🌧️ Pluie légère", 63: "🌧️ Pluie modérée", 65: "🌧️ Pluie forte",
        71: "🌨️ Neige légère", 73: "🌨️ Neige modérée", 75: "🌨️ Neige forte",
        80: "🌦️ Averses légères", 81: "🌦️ Averses modérées", 82: "🌦️ Averses violentes",
        85: "🌨️ Averses de neige", 95: "⛈️ Orage", 96: "⛈️ Orage + grêle",
    }

    weekdays_fr = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

    forecast_days = []
    for i, d in enumerate(dates):
        day_date = date.fromisoformat(d)
        weekday = weekdays_fr[day_date.weekday()]
        code = (daily.get("weather_code") or [None])[i]
        weather_desc = wmo_codes.get(code, f"Code {code}")

        forecast_days.append({
            "date": d,
            "weekday": weekday,
            "temp_min": (daily.get("temperature_2m_min") or [None])[i],
            "temp_max": (daily.get("temperature_2m_max") or [None])[i],
            "precipitation_mm": (daily.get("precipitation_sum") or [None])[i],
            "precipitation_prob": (daily.get("precipitation_probability_max") or [None])[i],
            "wind_max_kmh": (daily.get("wind_speed_10m_max") or [None])[i],
            "wind_gusts_kmh": (daily.get("wind_gusts_10m_max") or [None])[i],
            "weather": weather_desc,
        })

    return {
        "location": location_name,
        "forecast": forecast_days,
    }


def format_weather_for_llm(weather: dict[str, Any]) -> str:
    """Formate les prévisions météo pour le contexte du coach."""
    if not weather:
        return ""

    lines = [f"\n=== MÉTÉO {weather.get('location', '?').upper()} (7 PROCHAINS JOURS) ==="]

    for day in weather.get("forecast", []):
        temp_min = day.get("temp_min")
        temp_max = day.get("temp_max")
        precip = day.get("precipitation_mm") or 0
        prob = day.get("precipitation_prob") or 0
        wind = day.get("wind_max_kmh") or 0
        gusts = day.get("wind_gusts_kmh") or 0
        weather_desc = day.get("weather", "?")

        temp_str = f"{temp_min:.0f}-{temp_max:.0f}°C" if temp_min is not None else "?"
        wind_str = f"vent {wind:.0f}km/h" + (f" (rafales {gusts:.0f})" if gusts > wind * 1.3 else "")
        rain_str = ""
        if precip > 0 or prob > 30:
            rain_str = f" | 💧 {precip:.1f}mm ({prob}% prob)"

        # Signal pour le coach : conditions de sortie
        outdoor_ok = "✅" if precip < 2 and prob < 50 and wind < 40 else "⚠️"

        lines.append(
            f"  {outdoor_ok} {day['weekday']:9s} {day['date']} : "
            f"{weather_desc} | {temp_str} | {wind_str}{rain_str}"
        )

    return "\n".join(lines)