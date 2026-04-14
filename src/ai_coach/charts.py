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