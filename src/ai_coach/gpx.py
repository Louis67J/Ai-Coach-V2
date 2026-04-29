"""
Analyse de fichiers GPX pour la préparation de courses/sorties.

Parse un GPX, extrait le profil altimétrique, détecte les montées/descentes,
et croise avec la météo prévue.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np


@dataclass
class GpxPoint:
    lat: float
    lon: float
    ele: float
    dist_cum_km: float = 0.0


@dataclass
class Climb:
    """Une montée détectée dans le parcours."""
    start_km: float
    end_km: float
    length_km: float
    elevation_gain: float
    avg_gradient: float
    max_gradient: float
    start_ele: float
    summit_ele: float


@dataclass
class GpxSummary:
    """Résumé complet d'un parcours GPX."""
    total_distance_km: float
    total_elevation_gain: float
    total_elevation_loss: float
    min_elevation: float
    max_elevation: float
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    climbs: list[Climb] = field(default_factory=list)
    # Profil simplifié : liste de (km, altitude) pour le coach
    profile_points: list[tuple[float, float]] = field(default_factory=list)


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance en mètres entre deux points GPS."""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def parse_gpx(gpx_content: str) -> list[GpxPoint]:
    """Parse le contenu XML d'un fichier GPX et retourne les points."""
    root = ET.fromstring(gpx_content)

    # GPX namespace
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    points = []
    # Cherche dans <trk><trkseg><trkpt> ou <rte><rtept>
    for trkpt in root.iter(f"{ns}trkpt"):
        lat = float(trkpt.attrib["lat"])
        lon = float(trkpt.attrib["lon"])
        ele_elem = trkpt.find(f"{ns}ele")
        ele = float(ele_elem.text) if ele_elem is not None else 0.0
        points.append(GpxPoint(lat=lat, lon=lon, ele=ele))

    if not points:
        for rtept in root.iter(f"{ns}rtept"):
            lat = float(rtept.attrib["lat"])
            lon = float(rtept.attrib["lon"])
            ele_elem = rtept.find(f"{ns}ele")
            ele = float(ele_elem.text) if ele_elem is not None else 0.0
            points.append(GpxPoint(lat=lat, lon=lon, ele=ele))

    # Calcule la distance cumulée
    cum = 0.0
    for i, pt in enumerate(points):
        if i > 0:
            cum += _haversine(points[i - 1].lat, points[i - 1].lon, pt.lat, pt.lon)
        pt.dist_cum_km = cum / 1000

    return points


def _detect_climbs(points: list[GpxPoint], min_gain: float = 50, min_gradient: float = 2.0) -> list[Climb]:
    """
    Détecte les montées significatives dans le parcours.
    min_gain : dénivelé minimum en mètres pour considérer une montée
    min_gradient : pente moyenne minimum en % pour considérer une montée
    """
    if len(points) < 10:
        return []

    # Lisse l'altitude (moyenne glissante) pour éviter le bruit GPS
    window = min(20, len(points) // 5)
    if window < 3:
        window = 3
    elevations = np.array([p.ele for p in points])
    smoothed = np.convolve(elevations, np.ones(window) / window, mode="same")

    climbs = []
    in_climb = False
    climb_start_idx = 0
    climb_start_ele = 0
    max_gradient_in_climb = 0

    for i in range(1, len(points)):
        dist_delta = (points[i].dist_cum_km - points[i - 1].dist_cum_km) * 1000  # en mètres
        if dist_delta < 1:
            continue
        ele_delta = smoothed[i] - smoothed[i - 1]
        gradient = (ele_delta / dist_delta) * 100

        if not in_climb and gradient > min_gradient:
            in_climb = True
            climb_start_idx = i - 1
            climb_start_ele = smoothed[i - 1]
            max_gradient_in_climb = gradient
        elif in_climb:
            if gradient > max_gradient_in_climb:
                max_gradient_in_climb = gradient
            if gradient < -1 or i == len(points) - 1:
                # Fin de la montée
                gain = smoothed[i - 1] - climb_start_ele
                length_km = points[i - 1].dist_cum_km - points[climb_start_idx].dist_cum_km
                if gain >= min_gain and length_km > 0.3:
                    avg_grad = (gain / (length_km * 1000)) * 100
                    if avg_grad >= min_gradient:
                        climbs.append(Climb(
                            start_km=round(points[climb_start_idx].dist_cum_km, 1),
                            end_km=round(points[i - 1].dist_cum_km, 1),
                            length_km=round(length_km, 1),
                            elevation_gain=round(gain),
                            avg_gradient=round(avg_grad, 1),
                            max_gradient=round(max_gradient_in_climb, 1),
                            start_ele=round(climb_start_ele),
                            summit_ele=round(smoothed[i - 1]),
                        ))
                in_climb = False

    return climbs


def analyze_gpx(gpx_content: str) -> GpxSummary:
    """Analyse complète d'un fichier GPX."""
    points = parse_gpx(gpx_content)

    if len(points) < 2:
        raise ValueError("GPX invalide ou vide (moins de 2 points)")

    total_dist = points[-1].dist_cum_km
    elevations = [p.ele for p in points]

    # D+ et D-
    gain = 0.0
    loss = 0.0
    for i in range(1, len(points)):
        diff = points[i].ele - points[i - 1].ele
        if diff > 0:
            gain += diff
        else:
            loss += abs(diff)

    # Détecte les montées
    climbs = _detect_climbs(points)

    # Profil simplifié (un point tous les 2km environ)
    step_km = max(1, round(total_dist / 50))
    profile = []
    next_km = 0
    for pt in points:
        if pt.dist_cum_km >= next_km:
            profile.append((round(pt.dist_cum_km, 1), round(pt.ele)))
            next_km += step_km
    if profile[-1][0] < total_dist - 0.5:
        profile.append((round(total_dist, 1), round(points[-1].ele)))

    return GpxSummary(
        total_distance_km=round(total_dist, 1),
        total_elevation_gain=round(gain),
        total_elevation_loss=round(loss),
        min_elevation=round(min(elevations)),
        max_elevation=round(max(elevations)),
        start_lat=points[0].lat,
        start_lon=points[0].lon,
        end_lat=points[-1].lat,
        end_lon=points[-1].lon,
        climbs=climbs,
        profile_points=profile,
    )


def format_gpx_for_llm(
    summary: GpxSummary,
    weather: dict[str, Any] | None = None,
    target_date: str | None = None,
    ftp: int = 310,
    weight_kg: float = 63.0,
) -> str:
    """Formate l'analyse GPX pour le contexte du coach."""
    lines = []
    lines.append("=== ANALYSE DU PARCOURS GPX ===\n")

    lines.append(f"Distance : {summary.total_distance_km} km")
    lines.append(f"Dénivelé : D+ {summary.total_elevation_gain}m / D- {summary.total_elevation_loss}m")
    lines.append(f"Altitude : {summary.min_elevation}m → {summary.max_elevation}m")
    lines.append(f"Départ GPS : {summary.start_lat:.4f}, {summary.start_lon:.4f}")

    # Estimation de temps
    # Formule simplifiée : (distance/vitesse_plat) + (D+/vitesse_montée)
    flat_speed = ftp * 0.7 / weight_kg * 3.6 * 0.8  # estimation grossière km/h en plat
    climb_rate = (ftp * 0.85 - weight_kg * 9.81 * 0.005) / (weight_kg * 9.81) * 3600  # m D+/h
    if climb_rate < 500:
        climb_rate = 800
    est_time_h = (summary.total_distance_km / flat_speed) + (summary.total_elevation_gain / climb_rate)
    lines.append(f"\nEstimation temps (~{ftp}W FTP, {weight_kg}kg) : {est_time_h:.1f}h")

    # Montées détectées
    if summary.climbs:
        lines.append(f"\n🏔️ Montées détectées ({len(summary.climbs)}) :")
        for i, c in enumerate(summary.climbs, 1):
            lines.append(
                f"  {i}. km {c.start_km}-{c.end_km} : {c.length_km}km à {c.avg_gradient}% moy "
                f"(max {c.max_gradient}%) | D+ {c.elevation_gain}m "
                f"({c.start_ele}m → {c.summit_ele}m)"
            )
            # Estimation puissance cible par montée
            target_watts = round(ftp * (0.85 if c.avg_gradient < 6 else 0.80 if c.avg_gradient < 8 else 0.75))
            est_min = round(c.length_km / (climb_rate / 1000 / 60 * (c.avg_gradient / 5)))
            lines.append(f"     → Cible : ~{target_watts}W ({round(target_watts/weight_kg, 1)} W/kg)")
    else:
        lines.append("\nPas de montée significative détectée (parcours plat ou vallonné).")

    # Profil altimétrique résumé
    if summary.profile_points:
        lines.append(f"\nProfil altimétrique (simplifié) :")
        for km, ele in summary.profile_points[:30]:
            bar_len = max(0, int((ele - summary.min_elevation) / max(1, summary.max_elevation - summary.min_elevation) * 30))
            bar = "█" * bar_len
            lines.append(f"  km {km:>5.0f} | {ele:>4.0f}m | {bar}")

    # Météo si disponible
    if weather and target_date:
        forecast = weather.get("forecast", [])
        target_day = None
        for day in forecast:
            if day.get("date") == target_date:
                target_day = day
                break
        if target_day:
            lines.append(f"\n🌦️ Météo prévue le {target_date} ({target_day.get('weekday', '?')}) :")
            lines.append(f"  {target_day.get('weather', '?')}")
            lines.append(f"  Température : {target_day.get('temp_min', '?')}–{target_day.get('temp_max', '?')}°C")
            lines.append(f"  Vent : max {target_day.get('wind_max_kmh', '?')} km/h "
                         f"(rafales {target_day.get('wind_gusts_kmh', '?')})")
            precip = target_day.get("precipitation_mm", 0)
            prob = target_day.get("precipitation_prob", 0)
            if precip or prob > 20:
                lines.append(f"  Pluie : {precip}mm ({prob}% probabilité)")

    return "\n".join(lines)