"""
Interface avec l'API Claude (Anthropic) pour le rôle coach cycliste.

Gère le chargement du prompt système, l'injection du contexte d'analyse,
et les appels à l'API.
"""
from __future__ import annotations

import json
import os
from typing import Any

from anthropic import Anthropic

from ai_coach.config import load_config

from ai_coach.profile import format_profile_for_llm, load_profile, ProfileNotFoundError

from datetime import date

# Modèle par défaut. Overridable via env var ANTHROPIC_MODEL.
DEFAULT_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")


# --- Prompt système ---
# Principes clés:
# - Identité claire: coach senior cyclisme, tutoie l'athlète, français
# - Cadre: utilise les métriques quand elles sont là, reconnaît leurs limites
# - Format: réponses concises, structurées, actionnables
# - Honnêteté: dit "je ne sais pas" quand il manque de données

SYSTEM_PROMPT = """Tu es un coach cyclisme senior, personnel et dédié à un seul athlète.

Tu reçois à chaque conversation :
1. Le PROFIL complet de l'athlète (identité, objectifs, contraintes, préférences)
2. Un RAPPORT D'ENTRAÎNEMENT avec ses métriques actuelles (CTL/ATL/TSB, charge récente)
3. Une question ou une demande

Ton rôle :
- Analyser les données objectives en les croisant avec le profil
- Donner des recommandations concrètes, actionnables, adaptées à CET athlète
- Respecter scrupuleusement ses contraintes (jours off, max séances intenses, sensibilités)
- Travailler en cohérence avec ses objectifs prioritaires (A > B > C)
- Jauger fatigue vs forme avec nuance
- Proposer des séances précises (durée, intensité cible en W ou %FTP, structure d'intervalles)
- Parler nutrition et récupération quand pertinent

Style :
- Tutoie l'athlète, par son prénom
- Réponses en français, concises mais substantielles
- Structure claire (sections courtes, listes quand utile)
- Pas de blabla d'introduction, va droit au but
- Quand tu cites un chiffre, explique son sens
- Quand tu manques de données, dis-le explicitement
- Adapte tes propositions à la date du jour et aux indisponibilités connues

Limites :
- Tu n'es pas médecin. Pour toute douleur ou symptôme inquiétant, recommande un professionnel de santé.
- Pour les sensibilités musculaires connues, tu intègres systématiquement de la prévention.
- Tu ne prescris JAMAIS de suppléments ou médicaments.

Métriques (conventions TrainingPeaks) :
- CTL (42j) : forme long terme
- ATL (7j) : fatigue court terme
- TSB = CTL - ATL : fraîcheur
  * TSB > +5 : reposé (sous-chargé si durable)
  * TSB 0 à +5 : frais
  * TSB -10 à 0 : charge productive
  * TSB -20 à -10 : chargé, surveillance
  * TSB < -20 : surcharge
"""


# --- Client Claude ---

def _client() -> Anthropic:
    """Crée un client Anthropic avec la clé depuis la config."""
    config = load_config()
    return Anthropic(api_key=config.anthropic_api_key)


def _format_report_for_llm(report: dict[str, Any]) -> str:
    """
    Transforme le rapport d'analyse en texte lisible pour Claude.
    """
    lines = []

    # Ancrage temporel explicite
    today = report.get("today", "?")
    weekday = report.get("today_weekday", "?")
    lines.append(f"=== CONTEXTE TEMPOREL ===")
    lines.append(f"Aujourd'hui : {weekday} {today}")

    lines.append(f"\n=== RAPPORT D'ENTRAÎNEMENT ===\n")

    period = report.get("period", {})
    lines.append(
        f"Période analysée: {period.get('activities_usable', 0)} activités exploitables "
        f"sur {period.get('activities_total', 0)} ({period.get('stub_pct', 0):.0f}% de stubs Strava ignorés). "
        f"⚠️ Les CTL/ATL/TSB sont sous-estimés dans cette proportion."
    )

    totals = report.get("totals_usable", {})
    if totals:
        lines.append(
            f"Totaux exploitables : {totals.get('total_hours', 0)}h, "
            f"{totals.get('total_km', 0)}km, {totals.get('count', 0)} séances"
        )

    cf = report.get("current_fitness", {})
    if cf:
        lines.append(f"\nForme actuelle (au {cf.get('as_of', '?')}):")
        lines.append(f"  CTL = {cf.get('ctl', '?')} (forme)")
        lines.append(f"  ATL = {cf.get('atl', '?')} (fatigue)")
        lines.append(f"  TSB = {cf.get('tsb', '?')} (fraîcheur)")

    weekly = report.get("recent_weekly_load", [])
    if weekly:
        lines.append("\nCharge hebdomadaire récente :")
        for w in weekly:
            status = w.get("status", "")
            status_str = f" [{status}]" if status else ""
            lines.append(f"  Semaine du {w.get('week_ending', '?')}: {w.get('tss', 0):.0f} TSS{status_str}")

    daily = report.get("recent_daily_log", [])
    if daily:
        lines.append("\nDétail des 14 derniers jours (jour par jour) :")
        for day in daily:
            sessions = day.get("sessions", [])
            if not sessions:
                lines.append(f"  {day['weekday']:9s} {day['date']} : (repos)")
            else:
                # Une ligne par séance du jour
                first = True
                for s in sessions:
                    prefix = f"  {day['weekday']:9s} {day['date']}" if first else " " * 22
                    lines.append(
                        f"{prefix} : {s['type']:12s} "
                        f"{s['duration_h']:>4.1f}h  {s['distance_km']:>5.1f}km  "
                        f"TSS={s['tss']:>3d}  {s['name'][:40]}"
                    )
                    first = False

    breakdown = report.get("sport_breakdown", {})
    if breakdown:
        lines.append("\nRépartition par sport (période analysée) :")
        for sport, data in breakdown.items():
            lines.append(
                f"  {sport}: {data.get('count', 0)} séances, "
                f"{data.get('hours', 0)}h, {data.get('tss', 0):.0f} TSS"
            )

    return "\n".join(lines)


# --- Interfaces publiques ---

def ask_coach(question: str, report: dict[str, Any], max_tokens: int = 1500) -> str:
    """
    Pose une question au coach avec profil + contexte d'analyse + question.
    """
    # Profil athlète (obligatoire)
    try:
        profile = load_profile()
        profile_text = format_profile_for_llm(profile)
    except ProfileNotFoundError as e:
        # Le coach peut tourner sans profil mais on informe l'utilisateur
        profile_text = "(Aucun profil athlète défini — réponses génériques)"

    # Rapport d'analyse
    report_text = _format_report_for_llm(report)

    # Date du jour pour ancrer les recos temporellement
    today = date.today().isoformat()

    user_message = (
        f"Date du jour : {today}\n\n"
        f"{profile_text}\n\n"
        f"{report_text}\n\n"
        f"=== Ma question ===\n{question}"
    )

    client = _client()
    response = client.messages.create(
        model=DEFAULT_MODEL,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    parts = [block.text for block in response.content if block.type == "text"]
    return "\n".join(parts).strip()


def generate_plan(report: dict[str, Any], horizon_days: int = 7) -> str:
    """
    Demande au coach un plan d'entraînement structuré pour les N prochains jours.
    """
    question = (
        f"Propose-moi un plan d'entraînement pour les {horizon_days} prochains jours, "
        f"basé sur mon état de forme actuel. "
        f"Pour chaque jour: type de séance, durée, intensité cible, et une phrase sur l'objectif. "
        f"Termine par 2-3 phrases sur la logique globale du bloc."
    )
    return ask_coach(question, report, max_tokens=2000)