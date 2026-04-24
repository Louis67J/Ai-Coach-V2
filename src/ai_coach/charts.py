"""
Génération des graphes à partir des résultats d'analyse.
PNG écrits dans outputs/.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # backend non-interactif, pas de fenêtre qui s'ouvre
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

from ai_coach.config import OUTPUTS_DIR


def plot_fitness(fitness_df: pd.DataFrame, filename: str = "fitness.png") -> Path | None:
    """
    Graphe CTL / ATL / TSB classique.
    fitness_df : DataFrame avec colonnes ['tss', 'ctl', 'atl', 'tsb']
    """
    if fitness_df.empty:
        return None

    fig, ax1 = plt.subplots(figsize=(11, 5))

    # Barres TSS quotidiennes en arrière-plan (axe de gauche)
    ax1.bar(fitness_df.index, fitness_df["tss"], color="#cccccc", width=1, label="TSS")
    ax1.set_ylabel("TSS quotidien", color="#888888")
    ax1.tick_params(axis="y", labelcolor="#888888")

    # CTL / ATL / TSB au premier plan (axe de droite)
    ax2 = ax1.twinx()
    ax2.plot(fitness_df.index, fitness_df["ctl"], label="CTL (forme)", linewidth=2, color="#1f77b4")
    ax2.plot(fitness_df.index, fitness_df["atl"], label="ATL (fatigue)", linewidth=2, color="#d62728")
    ax2.plot(fitness_df.index, fitness_df["tsb"], label="TSB (fraîcheur)", linewidth=1.5, color="#2ca02c", linestyle="--")
    ax2.axhline(0, color="black", linewidth=0.5, alpha=0.3)
    ax2.set_ylabel("CTL / ATL / TSB")
    ax2.legend(loc="upper left")

    plt.title("Forme & Fatigue (CTL / ATL / TSB)")
    fig.autofmt_xdate()
    plt.tight_layout()

    path = OUTPUTS_DIR / filename
    plt.savefig(path, dpi=120)
    plt.close(fig)
    return path


def plot_weekly_load(weekly_series: pd.Series, filename: str = "weekly_load.png") -> Path | None:
    """Barres de TSS hebdomadaire."""
    if weekly_series.empty:
        return None

    fig, ax = plt.subplots(figsize=(11, 4))
    ax.bar(weekly_series.index, weekly_series.values, width=5, color="#1f77b4")
    ax.set_ylabel("TSS hebdomadaire")
    ax.set_title("Charge d'entraînement hebdomadaire")
    ax.grid(axis="y", alpha=0.3)
    fig.autofmt_xdate()
    plt.tight_layout()

    path = OUTPUTS_DIR / filename
    plt.savefig(path, dpi=120)
    plt.close(fig)
    return path


def plot_sport_breakdown(sport_breakdown: dict, filename: str = "sport_breakdown.png") -> Path | None:
    """Camembert de la répartition heures par sport."""
    if not sport_breakdown:
        return None

    # Filtre les sports à 0h
    labels = []
    sizes = []
    for sport, data in sport_breakdown.items():
        if data["hours"] > 0:
            labels.append(f"{sport}\n{data['hours']}h")
            sizes.append(data["hours"])

    if not sizes:
        return None

    fig, ax = plt.subplots(figsize=(7, 7))
    ax.pie(sizes, labels=labels, autopct="%1.0f%%", startangle=90)
    ax.set_title("Répartition par sport (heures)")
    plt.tight_layout()

    path = OUTPUTS_DIR / filename
    plt.savefig(path, dpi=120)
    plt.close(fig)
    return path

def plot_session(
    streams: dict[str, list],
    session_summary: dict | None = None,
    intervals_data: dict | None = None,
    filename: str | None = None,
) -> Path | None:
    """
    Génère un graphe détaillé d'une séance individuelle.

    Contenu :
    - Courbe de puissance colorée par zone
    - Courbe FC superposée
    - Profil d'altitude en arrière-plan
    - Intervalles détectés surlignés

    Args:
        streams: dict {type: [valeurs]} (time, watts, heartrate, cadence, altitude)
        session_summary: fiche enrichie de la séance (optionnel, pour titre et métadonnées)
        intervals_data: dict avec icu_intervals et icu_groups (optionnel, pour surligner)
        filename: nom du fichier PNG (auto-généré si absent)
    """
    time_s = streams.get("time", [])
    watts = streams.get("watts", [])
    hr = streams.get("heartrate", [])
    altitude = streams.get("altitude", [])
    cadence = streams.get("cadence", [])

    if not time_s or not watts:
        return None

    # Convertit en minutes pour l'axe X
    time_min = [t / 60 for t in time_s]
    n = len(time_min)

    # Lisse la puissance (moyenne glissante 30s) pour lisibilité
    watts_clean = [w if w is not None else 0 for w in watts]
    window = 30
    watts_smooth = np.convolve(watts_clean, np.ones(window) / window, mode="same").tolist()

    # FTP pour les zones (depuis le résumé ou défaut)
    ftp = 310
    if session_summary:
        ftp = session_summary.get("ftp_used") or 310

    # Zones de puissance (% FTP)
    zone_colors = {
        "Z1": "#bbbbbb",  # gris
        "Z2": "#4a90d9",  # bleu
        "Z3": "#2ecc71",  # vert
        "Z4": "#f39c12",  # orange
        "Z5": "#e74c3c",  # rouge
        "Z6": "#9b59b6",  # violet
        "Z7": "#e91e63",  # rose foncé
    }

    zone_thresholds = [
        (0.56, "Z1"), (0.76, "Z2"), (0.91, "Z3"),
        (1.06, "Z4"), (1.20, "Z5"), (1.50, "Z6"), (99, "Z7"),
    ]

    def get_zone(w):
        pct = w / ftp if ftp else 0
        for threshold, zone in zone_thresholds:
            if pct < threshold:
                return zone
        return "Z7"

    # --- Figure ---
    fig, axes = plt.subplots(3, 1, figsize=(14, 8), height_ratios=[3, 1.2, 0.8],
                              sharex=True, gridspec_kw={"hspace": 0.08})
    ax_power, ax_hr, ax_cad = axes

    # --- Panel 1 : Puissance + Altitude ---

    # Altitude en arrière-plan (remplissage gris)
    alt_clean = [a if a is not None else 0 for a in altitude]
    if any(a > 0 for a in alt_clean):
        ax_alt_bg = ax_power.twinx()
        ax_alt_bg.fill_between(time_min[:len(alt_clean)], alt_clean[:len(time_min)],
                                alpha=0.12, color="#8B7355", linewidth=0)
        ax_alt_bg.set_ylabel("Altitude (m)", fontsize=8, color="#8B7355")
        ax_alt_bg.tick_params(axis="y", labelsize=7, colors="#8B7355")
        # Met l'altitude en arrière
        ax_alt_bg.set_zorder(0)
        ax_power.set_zorder(1)
        ax_power.patch.set_visible(False)

    # Puissance brute (très transparente)
    ax_power.fill_between(time_min[:len(watts_clean)], watts_clean[:len(time_min)],
                          alpha=0.08, color="#666666")

    # Puissance lissée colorée par zone
    for i in range(1, min(len(watts_smooth), n)):
        zone = get_zone(watts_smooth[i])
        color = zone_colors.get(zone, "#999999")
        ax_power.plot(
            [time_min[i - 1], time_min[i]],
            [watts_smooth[i - 1], watts_smooth[i]],
            color=color, linewidth=1.2, alpha=0.85,
        )

    # Lignes de seuil FTP et zones
    ax_power.axhline(ftp, color="#e74c3c", linewidth=1, linestyle="--", alpha=0.5, label=f"FTP {ftp}W")
    ax_power.axhline(ftp * 0.76, color="#4a90d9", linewidth=0.5, linestyle=":", alpha=0.3)
    ax_power.axhline(ftp * 0.91, color="#2ecc71", linewidth=0.5, linestyle=":", alpha=0.3)

    ax_power.set_ylabel("Puissance (W)")
    ax_power.set_ylim(0, max(watts_clean) * 1.1 if watts_clean else 500)
    ax_power.legend(loc="upper right", fontsize=8)

    # Titre
    if session_summary:
        title = (
            f"{session_summary.get('date', '')} — {session_summary.get('name', '?')} "
            f"[{session_summary.get('tag', '?')}]\n"
            f"NP={session_summary.get('np_watts', '?')}W | "
            f"IF={session_summary.get('intensity_factor', '?')} | "
            f"TSS={session_summary.get('tss', '?')} | "
            f"Découplage={session_summary.get('decoupling_pct', '?')}%"
        )
    else:
        title = "Analyse de séance"
    ax_power.set_title(title, fontsize=11, fontweight="bold")

    # --- Panel 2 : FC ---
    hr_clean = [h if h is not None else 0 for h in hr]
    if any(h > 0 for h in hr_clean):
        # Lissage 15s
        hr_smooth = np.convolve(hr_clean, np.ones(15) / 15, mode="same").tolist()
        ax_hr.plot(time_min[:len(hr_smooth)], hr_smooth[:len(time_min)],
                   color="#e74c3c", linewidth=1, alpha=0.8)
        ax_hr.fill_between(time_min[:len(hr_smooth)], hr_smooth[:len(time_min)],
                           alpha=0.15, color="#e74c3c")
        ax_hr.set_ylabel("FC (bpm)", color="#e74c3c")
        ax_hr.tick_params(axis="y", labelcolor="#e74c3c")

        # Lignes de repère FC
        ax_hr.axhline(196, color="#e74c3c", linewidth=0.5, linestyle="--", alpha=0.3)  # FCmax
    else:
        ax_hr.set_visible(False)

    # --- Panel 3 : Cadence ---
    cad_clean = [c if c is not None else 0 for c in cadence]
    if any(c > 0 for c in cad_clean):
        cad_smooth = np.convolve(cad_clean, np.ones(15) / 15, mode="same").tolist()
        ax_cad.plot(time_min[:len(cad_smooth)], cad_smooth[:len(time_min)],
                    color="#2ecc71", linewidth=0.8, alpha=0.7)
        ax_cad.fill_between(time_min[:len(cad_smooth)], cad_smooth[:len(time_min)],
                            alpha=0.1, color="#2ecc71")
        ax_cad.set_ylabel("Cadence", color="#2ecc71", fontsize=9)
        ax_cad.tick_params(axis="y", labelcolor="#2ecc71", labelsize=8)
    else:
        ax_cad.set_visible(False)

    ax_cad.set_xlabel("Temps (minutes)")

    # --- Légende des zones en bas ---
    zone_labels = [
        ("Z1 Récup", "#bbbbbb"), ("Z2 Endurance", "#4a90d9"),
        ("Z3 Tempo", "#2ecc71"), ("Z4 Seuil", "#f39c12"),
        ("Z5 VO2", "#e74c3c"), ("Z6 Anaérobie", "#9b59b6"),
    ]
    from matplotlib.patches import Patch
    legend_patches = [Patch(facecolor=c, label=l, alpha=0.7) for l, c in zone_labels]
    fig.legend(handles=legend_patches, loc="lower center", ncol=6,
               fontsize=7, frameon=False, bbox_to_anchor=(0.5, -0.02))

    fig.subplots_adjust(left=0.08, right=0.92, top=0.92, bottom=0.08, hspace=0.08)

    # Filename
    if not filename:
        date_str = session_summary.get("date", "unknown") if session_summary else "unknown"
        filename = f"session_{date_str}.png"

    path = OUTPUTS_DIR / filename
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path