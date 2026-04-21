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

from datetime import date, timedelta

from ai_coach.memory import append_exchange, load_recent_exchanges, to_anthropic_messages

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


def _build_calendar_window(profile: dict[str, Any], days_ahead: int = 14) -> str:
    """
    Construit une table claire des prochains jours avec annotation des
    indispos et créneaux types. Évite à Claude de calculer les jours
    de semaine lui-même (source d'erreurs fréquentes des LLM).
    """
    weekdays_fr = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

    # Récupère les indispos du profil
    unavailable = set(
        profile.get("context", {}).get("unavailable_dates", [])
    )

    # Récupère les créneaux types par jour de semaine
    schedule = profile.get("context", {}).get("typical_schedule", {})

    today = date.today()
    lines = ["=== AGENDA DES 14 PROCHAINS JOURS ==="]
    lines.append("(table de référence : ne calcule PAS les jours de semaine toi-même, "
                 "lis-les dans cette table)")
    lines.append("")

    for offset in range(days_ahead):
        day = today + timedelta(days=offset)
        day_str = day.isoformat()
        weekday = weekdays_fr[day.weekday()]

        markers = []
        if offset == 0:
            markers.append("AUJOURD'HUI")
        if day_str in unavailable:
            markers.append("INDISPONIBLE (vélo impossible)")
        if weekday == "lundi" and "monday" in schedule:
            markers.append(f"({schedule['monday']})")

        marker_str = "  ← " + " | ".join(markers) if markers else ""
        lines.append(f"  {weekday:9s} {day_str}{marker_str}")

    return "\n".join(lines)

def _format_report_for_llm(report: dict[str, Any]) -> str:
    """
    Transforme le rapport d'analyse en texte lisible pour Claude.
    """
    lines = []

    lines.append(f"=== RAPPORT D'ENTRAÎNEMENT ===\n")

    period = report.get("period", {})
    stub_pct = period.get("stub_pct", 0)
    lines.append(
        f"Période analysée: {period.get('activities_usable', 0)} activités exploitables "
        f"sur {period.get('activities_total', 0)} au total."
    )
    if stub_pct > 0:
        lines.append("")
        lines.append(
            f"⚠️ IMPORTANT — {stub_pct:.0f}% des activités sont des 'stubs Strava' : "
            f"l'athlète les a BIEN EFFECTUÉES, mais leurs détails ne sont pas accessibles "
            f"via cette API (limitation Strava côté API Intervals.icu). "
            f"Ces activités ne reflètent PAS un manque de consistance — l'athlète s'entraîne "
            f"davantage que les chiffres ci-dessous ne le montrent. "
            f"Les CTL/ATL/TSB sont mécaniquement sous-estimés. "
            f"N'interprète JAMAIS la part 'stubs' comme un signal d'inconsistance "
            f"ou de manque de motivation."
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
        lines.append("\nCharge hebdomadaire récente "
                     "(une semaine = lundi → dimanche, étiquetée par sa date de fin) :")
        for w in weekly:
            status = w.get("status", "")
            status_str = f" [{status}]" if status else ""
            lines.append(
                f"  Semaine se terminant le {w.get('week_ending', '?')}: "
                f"{w.get('tss', 0):.0f} TSS{status_str}"
            )

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

def ask_coach(
    question: str,
    report: dict[str, Any],
    max_tokens: int = 1500,
    source: str = "cli",
    metadata: dict[str, Any] | None = None,
    history_limit: int = 20,
    persist: bool = True,
) -> str:
    """
    Pose une question au coach avec profil + calendrier + rapport + historique conversationnel.

    Args:
        question: la question
        report: dict d'analyse
        max_tokens: longueur max de la réponse
        source: "cli" ou "discord" (pour traçage)
        metadata: contexte additionnel à logger (user, channel...)
        history_limit: nombre d'échanges précédents à charger en contexte
        persist: si True, sauvegarde l'échange dans la mémoire après réponse
    """
    # Profil athlète
    try:
        profile = load_profile()
        profile_text = format_profile_for_llm(profile)
    except ProfileNotFoundError:
        profile = {}
        profile_text = "(Aucun profil athlète défini — réponses génériques)"

    # Calendrier explicite
    calendar_text = _build_calendar_window(profile, days_ahead=14)

    # Rapport d'analyse
    report_text = _format_report_for_llm(report)

    # Historique conversationnel précédent
    history = load_recent_exchanges(limit=history_limit)
    history_messages = to_anthropic_messages(history)

    # Construction du dernier message user :
    # contexte fraîchement calculé + question
    current_user_message = (
        f"{profile_text}\n\n"
        f"{calendar_text}\n\n"
        f"{report_text}\n\n"
        f"=== Ma question ===\n{question}"
    )

    # Liste finale de messages : historique passé + question actuelle
    messages = history_messages + [
        {"role": "user", "content": current_user_message}
    ]

    client = _client()
    response = client.messages.create(
        model=DEFAULT_MODEL,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=messages,
    )

    parts = [block.text for block in response.content if block.type == "text"]
    answer = "\n".join(parts).strip()

    # Sauvegarde l'échange. On ne stocke QUE la question brute (pas tout le
    # contexte injecté), parce que celui-ci est régénéré frais à chaque appel.
    if persist:
        append_exchange(
            question=question,
            answer=answer,
            source=source,
            metadata=metadata,
        )

    return answer

def generate_plan(
    report: dict[str, Any],
    horizon_days: int = 10,
    source: str = "cli",
    metadata: dict[str, Any] | None = None,
) -> str:
    """
    Demande au coach un plan d'entraînement structuré pour les N prochains jours.
    """
    question = (
        f"Propose-moi un plan d'entraînement pour les {horizon_days} prochains jours, "
        f"basé sur mon état de forme actuel et nos discussions précédentes si pertinent. "
        f"Pour chaque jour: type de séance, durée, intensité cible, et une phrase sur l'objectif. "
        f"Termine par 2-3 phrases sur la logique globale du bloc."
    )
    return ask_coach(
        question, report,
        max_tokens=2000,
        source=source,
        metadata=metadata,
    )