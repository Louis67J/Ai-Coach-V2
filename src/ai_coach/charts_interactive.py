"""
Graphes interactifs en HTML (Plotly).
Générés comme fichiers .html que le bot Discord peut envoyer.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd

from ai_coach.config import OUTPUTS_DIR


def build_fitness_fig(
    fitness_df: pd.DataFrame,
    objectives: list[dict] | None = None,
    forecast: list[dict] | None = None,
    plan_projection: list[dict] | None = None,
) -> go.Figure | None:
    """
    Construit la Figure Plotly CTL/ATL/TSB (sans l'écrire sur disque).

    `forecast` projette la charge moyenne récente ; `plan_projection`
    (cf analysis.compute_fitness_projection_from_plan) trace la trajectoire
    obtenue si le plan en cours est suivi à la lettre.
    """
    if fitness_df.empty:
        return None

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # Barres TSS
    fig.add_trace(
        go.Bar(x=fitness_df.index, y=fitness_df["tss"],
               name="TSS", marker=dict(color="rgba(148,163,184,0.35)", line_width=0),
               width=86400000),
        secondary_y=False,
    )

    # CTL
    fig.add_trace(
        go.Scatter(x=fitness_df.index, y=fitness_df["ctl"],
                   name="CTL (forme)", line=dict(color="#1f77b4", width=2.5)),
        secondary_y=True,
    )

    # ATL
    fig.add_trace(
        go.Scatter(x=fitness_df.index, y=fitness_df["atl"],
                   name="ATL (fatigue)", line=dict(color="#d62728", width=2)),
        secondary_y=True,
    )

    # TSB
    fig.add_trace(
        go.Scatter(x=fitness_df.index, y=fitness_df["tsb"],
                   name="TSB (fraîcheur)", line=dict(color="#2ca02c", width=1.5, dash="dash"),
                   fill="tozeroy", fillcolor="rgba(44,160,44,0.05)"),
        secondary_y=True,
    )

    # Projection CTL
    if forecast:
        last_date = fitness_df.index[-1]
        last_ctl = float(fitness_df["ctl"].iloc[-1])
        proj_dates = [last_date] + [pd.to_datetime(f["target_date"]) for f in forecast]
        proj_ctls = [last_ctl] + [f["projected_ctl"] for f in forecast]
        fig.add_trace(
            go.Scatter(x=proj_dates, y=proj_ctls, name="CTL projeté",
                       line=dict(color="#1f77b4", width=2, dash="dot"), opacity=0.6),
            secondary_y=True,
        )

    # Trajectoire "si je suis le plan"
    if plan_projection:
        last_date = fitness_df.index[-1]
        last_ctl = float(fitness_df["ctl"].iloc[-1])
        last_tsb = float(fitness_df["tsb"].iloc[-1])
        plan_dates = [last_date] + [pd.to_datetime(p["date"]) for p in plan_projection]
        fig.add_trace(
            go.Scatter(
                x=plan_dates, y=[last_ctl] + [p["ctl"] for p in plan_projection],
                name="CTL si plan suivi",
                line=dict(color="#8b5cf6", width=2.5),
                hovertemplate="%{x|%d %b}<br>CTL projeté %{y:.1f}<extra></extra>",
            ),
            secondary_y=True,
        )
        fig.add_trace(
            go.Scatter(
                x=plan_dates, y=[last_tsb] + [p["tsb"] for p in plan_projection],
                name="TSB si plan suivi",
                line=dict(color="#8b5cf6", width=1.2, dash="dot"), opacity=0.7,
                hovertemplate="%{x|%d %b}<br>TSB projeté %{y:.1f}<extra></extra>",
            ),
            secondary_y=True,
        )

    # Marqueurs d'objectifs
    if objectives:
        for obj in objectives:
            try:
                obj_date = pd.to_datetime(obj.get("date"))
                priority = obj.get("priority", "C")
                name = obj.get("name", "?")
                color = {"A": "red", "B": "orange", "C": "blue"}.get(priority, "gray")
                symbol = "🏆" if priority == "A" else "🎯"
                fig.add_vline(x=obj_date, line_dash="dash", line_color=color, opacity=0.6)
                fig.add_annotation(
                    x=obj_date, y=1, yref="paper",
                    text=f"{symbol} {name}", showarrow=False,
                    font=dict(size=10, color=color),
                    textangle=-45, yshift=10,
                )
            except Exception:
                continue

    # Ligne "aujourd'hui"
    fig.add_vline(x=pd.to_datetime("today"), line_dash="solid",
                  line_color="black", opacity=0.2)
    fig.add_annotation(
        x=pd.to_datetime("today"), y=1, yref="paper",
        text="aujourd'hui", showarrow=False, font=dict(size=9, color="gray"),
    )

    # Ligne TSB = 0
    fig.add_hline(y=0, line_dash="solid", line_color="black",
                  opacity=0.2, secondary_y=True)

    fig.update_layout(
        title=dict(text="Forme & Fatigue (CTL / ATL / TSB)", font=dict(size=16)),
        height=480,
        template="plotly_white",
        hovermode="x unified",
        margin=dict(l=50, r=50, t=60, b=40),
        plot_bgcolor="white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(
        title_text="TSS", secondary_y=False, showgrid=False, zeroline=False,
    )
    fig.update_yaxes(
        title_text="CTL / ATL / TSB", secondary_y=True,
        showgrid=True, gridcolor="rgba(0,0,0,0.06)", zeroline=False,
    )

    return fig


def plot_fitness_interactive(
    fitness_df: pd.DataFrame,
    objectives: list[dict] | None = None,
    forecast: list[dict] | None = None,
    filename: str = "fitness_interactive.html",
) -> Path | None:
    """Graphe CTL/ATL/TSB interactif avec Plotly, écrit en HTML pour le bot Discord."""
    fig = build_fitness_fig(fitness_df, objectives=objectives, forecast=forecast)
    if fig is None:
        return None

    path = OUTPUTS_DIR / filename
    fig.write_html(str(path), include_plotlyjs="cdn")
    return path


def build_session_fig(
    streams: dict[str, list],
    session_summary: dict | None = None,
) -> go.Figure | None:
    """Construit la Figure Plotly d'analyse de séance (sans l'écrire sur disque)."""
    time_s = streams.get("time", [])
    watts = streams.get("watts", [])
    hr = streams.get("heartrate", [])
    altitude = streams.get("altitude", [])
    cadence = streams.get("cadence", [])

    if not time_s or not watts:
        return None

    import numpy as np

    time_min = [t / 60 for t in time_s]
    watts_clean = [w if w is not None else 0 for w in watts]

    # Lisse puissance
    window = 30
    watts_smooth = np.convolve(watts_clean, np.ones(window) / window, mode="same").tolist()

    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        row_heights=[0.5, 0.25, 0.25],
        vertical_spacing=0.03,
        subplot_titles=("Puissance (W)", "FC (bpm)", "Cadence (rpm)"),
    )

    # Puissance
    fig.add_trace(
        go.Scatter(x=time_min, y=watts_smooth, name="Puissance",
                   line=dict(color="#1f77b4", width=1.5),
                   fill="tozeroy", fillcolor="rgba(31,119,180,0.1)"),
        row=1, col=1,
    )

    # Altitude en arrière-plan
    alt_clean = [a if a is not None else 0 for a in altitude]
    if any(a > 0 for a in alt_clean):
        fig.add_trace(
            go.Scatter(x=time_min[:len(alt_clean)], y=alt_clean[:len(time_min)],
                       name="Altitude", fill="tozeroy",
                       fillcolor="rgba(139,115,85,0.1)",
                       line=dict(color="rgba(139,115,85,0.3)", width=0.5)),
            row=1, col=1,
        )

    # FTP line
    ftp = session_summary.get("ftp_used", 310) if session_summary else 310
    fig.add_hline(y=ftp, line_dash="dash", line_color="red", opacity=0.4,
                  annotation_text=f"FTP {ftp}W", row=1, col=1)

    # Surbrillance des efforts détectés via le stream (power bests), pour
    # rendre visible ce que la détection basée sur les laps Intervals.icu rate
    power_bests = (session_summary or {}).get("power_bests") or {}
    for label, best in power_bests.items():
        if best.get("pct_ftp", 0) < 90:
            continue  # sous tempo, pas un "effort" à mettre en avant visuellement
        start_min = best["start_s"] / 60
        end_min = (best["start_s"] + best["duration_s"]) / 60
        fig.add_vrect(
            x0=start_min, x1=end_min,
            fillcolor="rgba(255,0,0,0.08)", line_width=1, line_color="rgba(255,0,0,0.3)",
            annotation_text=f"{label} @ {best['watts']}W", annotation_position="top left",
            annotation_font_size=9,
            row=1, col=1,
        )

    # FC
    hr_clean = [h if h is not None else 0 for h in hr]
    if any(h > 0 for h in hr_clean):
        hr_smooth = np.convolve(hr_clean, np.ones(15) / 15, mode="same").tolist()
        fig.add_trace(
            go.Scatter(x=time_min[:len(hr_smooth)], y=hr_smooth[:len(time_min)],
                       name="FC", line=dict(color="#d62728", width=1.2),
                       fill="tozeroy", fillcolor="rgba(214,39,40,0.08)"),
            row=2, col=1,
        )

    # Cadence
    cad_clean = [c if c is not None else 0 for c in cadence]
    if any(c > 0 for c in cad_clean):
        cad_smooth = np.convolve(cad_clean, np.ones(15) / 15, mode="same").tolist()
        fig.add_trace(
            go.Scatter(x=time_min[:len(cad_smooth)], y=cad_smooth[:len(time_min)],
                       name="Cadence", line=dict(color="#2ca02c", width=1),
                       fill="tozeroy", fillcolor="rgba(46,204,113,0.08)"),
            row=3, col=1,
        )

    # Titre
    title = "Analyse de séance"
    if session_summary:
        title = (
            f"{session_summary.get('date', '')} — {session_summary.get('name', '?')} "
            f"[{session_summary.get('tag', '?')}] "
            f"NP={session_summary.get('np_watts', '?')}W | TSS={session_summary.get('tss', '?')}"
        )

    fig.update_layout(
        title=title,
        height=700,
        template="plotly_white",
        hovermode="x unified",
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_xaxes(title_text="Temps (minutes)", row=3, col=1)

    return fig


def plot_session_interactive(
    streams: dict[str, list],
    session_summary: dict | None = None,
    filename: str | None = None,
) -> Path | None:
    """Graphe de séance interactif avec Plotly, écrit en HTML pour le bot Discord."""
    fig = build_session_fig(streams, session_summary=session_summary)
    if fig is None:
        return None

    if not filename:
        date_str = session_summary.get("date", "unknown") if session_summary else "unknown"
        filename = f"session_{date_str}_interactive.html"

    path = OUTPUTS_DIR / filename
    fig.write_html(str(path), include_plotlyjs="cdn")
    return path