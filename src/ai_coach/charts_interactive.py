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


def plot_fitness_interactive(
    fitness_df: pd.DataFrame,
    objectives: list[dict] | None = None,
    forecast: list[dict] | None = None,
    filename: str = "fitness_interactive.html",
) -> Path | None:
    """Graphe CTL/ATL/TSB interactif avec Plotly."""
    if fitness_df.empty:
        return None

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # Barres TSS
    fig.add_trace(
        go.Bar(x=fitness_df.index, y=fitness_df["tss"],
               name="TSS", marker_color="rgba(200,200,200,0.5)", width=86400000),
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
        title="Forme & Fatigue (CTL / ATL / TSB)",
        height=500,
        template="plotly_white",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_yaxes(title_text="TSS", secondary_y=False)
    fig.update_yaxes(title_text="CTL / ATL / TSB", secondary_y=True)

    path = OUTPUTS_DIR / filename
    fig.write_html(str(path), include_plotlyjs="cdn")
    return path


def plot_session_interactive(
    streams: dict[str, list],
    session_summary: dict | None = None,
    filename: str | None = None,
) -> Path | None:
    """Graphe de séance interactif avec Plotly."""
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

    if not filename:
        date_str = session_summary.get("date", "unknown") if session_summary else "unknown"
        filename = f"session_{date_str}_interactive.html"

    path = OUTPUTS_DIR / filename
    fig.write_html(str(path), include_plotlyjs="cdn")
    return path