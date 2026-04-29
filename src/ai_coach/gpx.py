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


def analyze_gpx(gpx_content: str) -> GpxSummary:
    """
    Analyse complète d'un fichier GPX.
    Utilise un rééchantillonnage à 200m + lissage 1km pour éliminer
    le bruit GPS qui crée des gradients et D+ fictifs.
    """
    points = parse_gpx(gpx_content)

    if len(points) < 2:
        raise ValueError("GPX invalide ou vide (moins de 2 points)")

    total_dist = points[-1].dist_cum_km

    # --- Rééchantillonnage à 200m + lissage pour des métriques fiables ---
    cum_dists_m = np.array([p.dist_cum_km * 1000 for p in points])
    raw_eles = np.array([p.ele for p in points])

    # Rééchantillonne tous les 200m
    sample_step = 200  # mètres
    sample_dists = np.arange(0, cum_dists_m[-1], sample_step)
    sample_eles = np.interp(sample_dists, cum_dists_m, raw_eles)

    # Lisse sur ~1km (5 points * 200m)
    smooth_window = max(5, 1)
    from scipy.ndimage import uniform_filter1d
    smoothed_eles = uniform_filter1d(sample_eles, size=smooth_window)

    # D+ et D- depuis les données lissées
    gain = 0.0
    loss = 0.0
    for i in range(1, len(smoothed_eles)):
        diff = smoothed_eles[i] - smoothed_eles[i - 1]
        if diff > 0:
            gain += diff
        else:
            loss += abs(diff)

    # Détecte les montées depuis les données rééchantillonnées
    climbs = _detect_climbs_resampled(sample_dists, smoothed_eles)

    # Profil simplifié (un point tous les 2km environ)
    step_km = max(1, round(total_dist / 50))
    profile = []
    next_km = 0
    for i, d_m in enumerate(sample_dists):
        d_km = d_m / 1000
        if d_km >= next_km:
            profile.append((round(d_km, 1), round(smoothed_eles[i])))
            next_km += step_km
    if profile and profile[-1][0] < total_dist - 0.5:
        profile.append((round(total_dist, 1), round(smoothed_eles[-1])))

    return GpxSummary(
        total_distance_km=round(total_dist, 1),
        total_elevation_gain=round(gain),
        total_elevation_loss=round(loss),
        min_elevation=round(float(smoothed_eles.min())),
        max_elevation=round(float(smoothed_eles.max())),
        start_lat=points[0].lat,
        start_lon=points[0].lon,
        end_lat=points[-1].lat,
        end_lon=points[-1].lon,
        climbs=climbs,
        profile_points=profile,
    )


def _detect_climbs_resampled(
    distances_m: np.ndarray,
    elevations: np.ndarray,
    min_gain: float = 50,
    min_gradient: float = 2.0,
) -> list[Climb]:
    """
    Détecte les montées depuis des données rééchantillonnées et lissées.
    Beaucoup plus fiable que la détection point par point.
    """
    if len(distances_m) < 5:
        return []

    # Calcule le gradient par segment (déjà lissé)
    step = distances_m[1] - distances_m[0]  # 200m typiquement
    gradients = np.diff(elevations) / step * 100  # en %

    # Clippe les gradients aberrants (>20% c'est déjà extrême sur route)
    gradients = np.clip(gradients, -25, 25)

    climbs = []
    in_climb = False
    climb_start_idx = 0
    climb_start_ele = 0

    for i in range(len(gradients)):
        if not in_climb and gradients[i] > min_gradient:
            in_climb = True
            climb_start_idx = i
            climb_start_ele = elevations[i]
        elif in_climb:
            # Fin de montée : gradient négatif ou fin du parcours
            if gradients[i] < -1 or i == len(gradients) - 1:
                end_idx = i
                gain = elevations[end_idx] - climb_start_ele
                length_m = distances_m[end_idx] - distances_m[climb_start_idx]
                length_km = length_m / 1000

                if gain >= min_gain and length_km > 0.3:
                    avg_grad = (gain / length_m) * 100
                    # Gradient max sur cette montée (déjà clippé)
                    section_grads = gradients[climb_start_idx:end_idx + 1]
                    max_grad = float(section_grads.max()) if len(section_grads) > 0 else avg_grad

                    if avg_grad >= min_gradient:
                        climbs.append(Climb(
                            start_km=round(distances_m[climb_start_idx] / 1000, 1),
                            end_km=round(distances_m[end_idx] / 1000, 1),
                            length_km=round(length_km, 1),
                            elevation_gain=round(gain),
                            avg_gradient=round(avg_grad, 1),
                            max_gradient=round(max_grad, 1),
                            start_ele=round(climb_start_ele),
                            summit_ele=round(float(elevations[end_idx])),
                        ))
                in_climb = False

    return climbs

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

    # Estimation de temps basée sur des moyennes réalistes cyclisme route
    # Méthode : vitesse de base ajustée par le D+/km
    d_plus_per_km = summary.total_elevation_gain / max(summary.total_distance_km, 1)
    if d_plus_per_km > 20:  # montagneux
        avg_speed = 22 + (ftp - 250) * 0.04  # ~24-26 km/h pour FTP 300-350
    elif d_plus_per_km > 10:  # vallonné
        avg_speed = 26 + (ftp - 250) * 0.04  # ~28-30 km/h
    else:  # plat
        avg_speed = 30 + (ftp - 250) * 0.05  # ~33-35 km/h
    est_time_h = summary.total_distance_km / avg_speed
    lines.append(
        f"\nEstimation temps (~{ftp}W FTP, {weight_kg}kg) : {est_time_h:.1f}h ({avg_speed:.0f} km/h moy estimée)")

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
            lines.append(f"     → Cible : ~{target_watts}W ({round(target_watts/weight_kg, 1)} W/kg)")
    else:
        lines.append("\nPas de montée significative détectée (parcours plat ou vallonné).")

    # Estimation du temps
    if summary.profile_points:
        lines.append(f"\nProfil altimétrique (simplifié) :")
        # Affiche max 40 points pour rester lisible
        step = max(1, len(summary.profile_points) // 40)
        displayed = summary.profile_points[::step]
        # Assure que le dernier point est inclus
        if displayed[-1] != summary.profile_points[-1]:
            displayed.append(summary.profile_points[-1])
        for km, ele in displayed:
            bar_len = max(0, int((ele - summary.min_elevation) / max(1,
                                                                     summary.max_elevation - summary.min_elevation) * 30))
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