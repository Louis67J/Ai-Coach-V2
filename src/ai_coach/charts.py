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


def plot_fitness(
    fitness_df: pd.DataFrame,
    objectives: list[dict] | None = None,
    forecast: list[dict] | None = None,
    filename: str = "fitness.png",
) -> Path | None:
    """
    Graphe CTL/ATL/TSB avec marqueurs de courses et projections.

    Args:
        fitness_df: DataFrame avec colonnes tss/ctl/atl/tsb
        objectives: liste d'objectifs [{name, date, priority}, ...]
        forecast: projections CTL [{target_date, projected_ctl}, ...]
    """
    if fitness_df.empty:
        return None

    fig, ax1 = plt.subplots(figsize=(13, 6))

    # Barres TSS quotidiennes en arrière-plan
    ax1.bar(fitness_df.index, fitness_df["tss"], color="#dddddd", width=1, label="TSS", zorder=1)
    ax1.set_ylabel("TSS quotidien", color="#aaaaaa", fontsize=9)
    ax1.tick_params(axis="y", labelcolor="#aaaaaa")

    # CTL / ATL / TSB au premier plan
    ax2 = ax1.twinx()
    ax2.plot(fitness_df.index, fitness_df["ctl"], label="CTL (forme)",
             linewidth=2.5, color="#1f77b4", zorder=3)
    ax2.plot(fitness_df.index, fitness_df["atl"], label="ATL (fatigue)",
             linewidth=2, color="#d62728", alpha=0.8, zorder=3)
    ax2.plot(fitness_df.index, fitness_df["tsb"], label="TSB (fraîcheur)",
             linewidth=1.5, color="#2ca02c", linestyle="--", alpha=0.7, zorder=3)

    # Zone TSB colorée
    ax2.fill_between(fitness_df.index, fitness_df["tsb"], 0,
                     where=fitness_df["tsb"] >= 0, alpha=0.08, color="#2ca02c", zorder=2)
    ax2.fill_between(fitness_df.index, fitness_df["tsb"], 0,
                     where=fitness_df["tsb"] < 0, alpha=0.08, color="#d62728", zorder=2)
    ax2.axhline(0, color="black", linewidth=0.5, alpha=0.3)

    # Zones TSB annotées
    ax2.axhspan(5, 30, alpha=0.03, color="#2ca02c")
    ax2.axhspan(-10, 0, alpha=0.03, color="#f39c12")
    ax2.axhspan(-30, -10, alpha=0.03, color="#d62728")

    ax2.set_ylabel("CTL / ATL / TSB")

    # --- Marqueurs d'objectifs (courses) ---
    if objectives:
        import matplotlib.dates as mdates
        for obj in objectives:
            try:
                obj_date = pd.to_datetime(obj.get("date"))
                priority = obj.get("priority", "C")
                name = obj.get("name", "?")[:25]
                color = {"A": "#e74c3c", "B": "#f39c12", "C": "#3498db"}.get(priority, "#999999")
                marker_size = {"A": 12, "B": 10, "C": 8}.get(priority, 8)

                # Ligne verticale
                ax2.axvline(obj_date, color=color, linewidth=1.5, linestyle="--", alpha=0.6, zorder=4)
                # Label
                ax2.annotate(
                    f"{'🏆' if priority == 'A' else '🎯'} {name}",
                    xy=(obj_date, ax2.get_ylim()[1] * 0.9),
                    fontsize=8, fontweight="bold", color=color,
                    rotation=45, ha="left", va="bottom",
                    bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.8, edgecolor=color),
                )
            except Exception:
                continue

    # --- Projection CTL ---
    if forecast:
        try:
            last_date = fitness_df.index[-1]
            last_ctl = float(fitness_df["ctl"].iloc[-1])

            proj_dates = [last_date]
            proj_ctls = [last_ctl]
            for f in forecast:
                proj_dates.append(pd.to_datetime(f["target_date"]))
                proj_ctls.append(f["projected_ctl"])

            ax2.plot(proj_dates, proj_ctls, linewidth=2, color="#1f77b4",
                     linestyle=":", alpha=0.5, zorder=3, label="CTL projeté")

            # Annotation du CTL projeté final
            ax2.annotate(
                f"CTL projeté\n{proj_ctls[-1]:.0f}",
                xy=(proj_dates[-1], proj_ctls[-1]),
                textcoords="offset points", xytext=(10, -5),
                fontsize=8, color="#1f77b4",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8),
                arrowprops=dict(arrowstyle="->", color="#1f77b4"),
            )
        except Exception:
            pass

    # Marqueur "aujourd'hui"
    today = pd.to_datetime("today")
    if fitness_df.index.min() <= today <= fitness_df.index.max() + pd.Timedelta(days=45):
        ax2.axvline(today, color="#333333", linewidth=1, linestyle="-", alpha=0.3)
        ax2.text(today, ax2.get_ylim()[1] * 0.95, " aujourd'hui",
                 fontsize=7, color="#333333", alpha=0.5)

    ax2.legend(loc="upper left", fontsize=8)
    plt.title("Forme & Fatigue (CTL / ATL / TSB)", fontsize=12, fontweight="bold")
    fig.autofmt_xdate()
    fig.subplots_adjust(left=0.08, right=0.92, top=0.92, bottom=0.12)

    path = OUTPUTS_DIR / filename
    plt.savefig(path, dpi=150, bbox_inches="tight")
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

def plot_power_curve(filename: str = "power_curve.png") -> Path | None:
    """
    Génère le graphe de power curve avec les niveaux Coggan en overlay.
    Utilise les données de l'API Intervals.icu.
    """
    from ai_coach.intervals import fetch_power_curves

    curve = fetch_power_curves()
    if not curve or "secs" not in curve or "values" not in curve:
        print("❌ Impossible de récupérer la power curve.")
        return None

    secs = curve["secs"]
    watts = curve["values"]
    wkg = curve.get("watts_per_kg", [])
    weight = curve.get("weight", 63.0)
    period_start = (curve.get("start_date_local") or "?")[:10]
    period_end = (curve.get("end_date_local") or "?")[:10]

    if not secs or not watts:
        return None

    # Convertit les secondes en labels lisibles pour l'axe X
    import numpy as np

    secs_arr = np.array(secs, dtype=float)
    watts_arr = np.array(watts, dtype=float)

    # --- Figure à 2 panels : Watts + W/kg ---
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 8), sharex=True,
                                     gridspec_kw={"hspace": 0.08, "height_ratios": [1.2, 1]})

    # Couleur par zone (basée sur FTP)
    ftp = 310  # FTP de référence
    models = curve.get("powerModels", [])
    for pm in models:
        if pm.get("type") == "ECP" and pm.get("ftp"):
            ftp = pm["ftp"]
            break

    zone_thresholds = [
        (0.56, "#bbbbbb", "Z1"), (0.76, "#4a90d9", "Z2"), (0.91, "#2ecc71", "Z3"),
        (1.06, "#f39c12", "Z4"), (1.20, "#e74c3c", "Z5"), (1.50, "#9b59b6", "Z6"),
        (99, "#e91e63", "Z7"),
    ]

    def get_color(w):
        pct = w / ftp if ftp else 0
        for threshold, color, _ in zone_thresholds:
            if pct < threshold:
                return color
        return "#e91e63"

    # Panel 1 : Watts
    for i in range(1, len(secs_arr)):
        color = get_color(watts_arr[i])
        ax1.plot([secs_arr[i-1], secs_arr[i]], [watts_arr[i-1], watts_arr[i]],
                 color=color, linewidth=2, solid_capstyle="round")

    # Lignes de référence FTP
    ax1.axhline(ftp, color="#e74c3c", linewidth=1, linestyle="--", alpha=0.5, label=f"FTP {ftp}W")
    ax1.axhline(ftp * 0.76, color="#4a90d9", linewidth=0.5, linestyle=":", alpha=0.3)
    ax1.axhline(ftp * 0.91, color="#2ecc71", linewidth=0.5, linestyle=":", alpha=0.3)

    # Marqueurs aux durées clés
    key_durations = {5: "5s", 60: "1min", 300: "5min", 1200: "20min", 3600: "60min"}
    for target_s, label in key_durations.items():
        closest_idx = min(range(len(secs)), key=lambda i: abs(secs[i] - target_s))
        w = watts[closest_idx]
        ax1.plot(secs[closest_idx], w, "o", color="#333333", markersize=6, zorder=5)
        ax1.annotate(
            f"{label}\n{w}W",
            xy=(secs[closest_idx], w),
            textcoords="offset points", xytext=(10, 10),
            fontsize=8, fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8, edgecolor="#cccccc"),
            arrowprops=dict(arrowstyle="-", color="#999999", lw=0.5),
        )

    ax1.set_ylabel("Puissance (W)", fontsize=10)
    ax1.set_xscale("log")
    ax1.set_ylim(0, max(watts) * 1.1)
    ax1.grid(True, alpha=0.2, which="both")
    ax1.legend(loc="upper right", fontsize=8)
    ax1.set_title(
        f"Power Curve — {period_start} → {period_end} ({weight}kg)",
        fontsize=12, fontweight="bold",
    )

    # Panel 2 : W/kg avec niveaux Coggan
    if wkg:
        wkg_arr = np.array(wkg, dtype=float)
        for i in range(1, len(secs_arr)):
            color = get_color(watts_arr[i])
            ax2.plot([secs_arr[i-1], secs_arr[i]], [wkg_arr[i-1], wkg_arr[i]],
                     color=color, linewidth=2, solid_capstyle="round")

        # Bandes de niveaux Coggan (approximatif, pour les durées 1-60min)
        coggan_bands = [
            (3.0, "Moyen", "#f0f0f0"),
            (4.0, "Bon", "#e8f5e9"),
            (5.0, "Très bon", "#c8e6c9"),
            (5.5, "Excellent", "#a5d6a7"),
            (6.5, "Exceptionnel", "#81c784"),
        ]
        for threshold, label, color in coggan_bands:
            ax2.axhline(threshold, color="#999999", linewidth=0.5, linestyle=":", alpha=0.4)
            ax2.text(secs_arr[-1] * 0.7, threshold + 0.05, label,
                     fontsize=7, color="#888888", alpha=0.7)

        # Marqueurs aux durées clés
        for target_s, label in key_durations.items():
            closest_idx = min(range(len(secs)), key=lambda i: abs(secs[i] - target_s))
            w_kg = wkg[closest_idx]
            ax2.plot(secs[closest_idx], w_kg, "o", color="#333333", markersize=5, zorder=5)
            ax2.annotate(
                f"{w_kg:.1f}",
                xy=(secs[closest_idx], w_kg),
                textcoords="offset points", xytext=(8, 5),
                fontsize=8, fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.8, edgecolor="#cccccc"),
            )

        ax2.set_ylabel("W/kg", fontsize=10)
        ax2.set_ylim(0, max(wkg) * 1.1)
        ax2.grid(True, alpha=0.2, which="both")

    # Axe X : labels lisibles
    tick_positions = [5, 10, 30, 60, 120, 300, 600, 1200, 1800, 3600, 7200, 14400]
    tick_labels = ["5s", "10s", "30s", "1min", "2min", "5min", "10min", "20min", "30min", "1h", "2h", "4h"]
    # Filtre les ticks qui sont dans la plage
    valid_ticks = [(p, l) for p, l in zip(tick_positions, tick_labels) if p <= max(secs)]
    if valid_ticks:
        ax2.set_xticks([p for p, _ in valid_ticks])
        ax2.set_xticklabels([l for _, l in valid_ticks])
    ax2.set_xlabel("Durée", fontsize=10)

    # Légende des zones
    from matplotlib.patches import Patch
    zone_labels = [
        ("Z1", "#bbbbbb"), ("Z2", "#4a90d9"), ("Z3", "#2ecc71"),
        ("Z4", "#f39c12"), ("Z5", "#e74c3c"), ("Z6", "#9b59b6"),
    ]
    legend_patches = [Patch(facecolor=c, label=l, alpha=0.7) for l, c in zone_labels]
    fig.legend(handles=legend_patches, loc="lower center", ncol=6,
               fontsize=7, frameon=False, bbox_to_anchor=(0.5, -0.02))

    # Modèles de puissance en annotation
    model_text_parts = []
    for pm in models:
        pm_type = pm.get("type", "?")
        cp = pm.get("criticalPower")
        w_prime = pm.get("wPrime")
        if cp and w_prime:
            model_text_parts.append(f"{pm_type}: CP={cp}W, W'={round(w_prime/1000, 1)}kJ")
    if model_text_parts:
        model_text = "\n".join(model_text_parts[:2])  # Max 2 modèles
        ax1.text(0.02, 0.02, model_text, transform=ax1.transAxes,
                 fontsize=7, verticalalignment="bottom",
                 bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5))

    fig.subplots_adjust(left=0.08, right=0.95, top=0.93, bottom=0.08)

    path = OUTPUTS_DIR / filename
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path