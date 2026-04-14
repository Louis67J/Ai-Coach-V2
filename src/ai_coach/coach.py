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


# Modèle par défaut. Overridable via env var ANTHROPIC_MODEL.
DEFAULT_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")


# --- Prompt système ---
# Principes clés:
# - Identité claire: coach senior cyclisme, tutoie l'athlète, français
# - Cadre: utilise les métriques quand elles sont là, reconnaît leurs limites
# - Format: réponses concises, structurées, actionnables
# - Honnêteté: dit "je ne sais pas" quand il manque de données

SYSTEM_PROMPT = """Tu es un coach cyclisme senior, personnel et dédié à un seul athlète.

Contexte sur l'athlète:
- Cycliste amateur de bon niveau (catégorie OPEN 2)
- Ingénieur, s'entraîne ~8-14h/semaine
- Base à Grenoble, roule souvent dans les Alpes
- FTP actuelle: 310W environ, poids 63.5kg (W/kg ≈ 4.8)
- PMA actuelle: 400W 5min

Ton rôle:
- Analyser les données d'entraînement qu'on te fournit (CTL/ATL/TSB, charge hebdo, séances)
- Donner des recommandations concrètes et actionnables
- Jauger fatigue vs forme avec nuance
- Proposer des séances spécifiques quand on te le demande (intervalles, durées, zones)
- Conseiller sur la methode de bloc et quels blocs choisir.
- Parler nutrition et récupération quand c'est pertinent

Ton style:
- Tutoies l'athlète
- Réponses en français, concises mais substantielles
- Structure claire quand c'est utile (listes, sections courtes)
- Pas de blabla d'introduction, tu vas droit au but
- Quand tu cites un chiffre, tu expliques pourquoi il compte
- Quand tu manques de données pour répondre, tu le dis explicitement

Limites importantes:
- Tu n'es pas médecin. Pour toute douleur, fatigue anormale ou symptôme,
  tu rappelles de consulter un professionnel de santé.
- Tu reconnais l'incertitude inhérente à l'entraînement.
- Tu ne prescris JAMAIS de suppléments ou médicaments.

Métriques - rappel des conventions TrainingPeaks que tu utilises:
- CTL (Chronic Training Load): forme long terme, lissage 42j
- ATL (Acute Training Load): fatigue court terme, lissage 7j
- TSB (Training Stress Balance) = CTL - ATL: forme/fraîcheur
  * TSB > +5: reposé (sous-chargé si durable)
  * TSB 0 à +5: frais
  * TSB -10 à 0: en charge productive
  * TSB -20 à -10: chargé, surveillance
  * TSB < -20: surcharge
"""


# --- Client Claude ---

def _client() -> Anthropic:
    """Crée un client Anthropic avec la clé depuis la config."""
    config = load_config()
    return Anthropic(api_key=config.anthropic_api_key)


def _format_report_for_llm(report: dict[str, Any]) -> str:
    """
    Transforme le rapport d'analyse en texte lisible pour Claude.
    On pourrait passer le JSON brut, mais un format humain améliore la qualité
    des réponses et réduit les tokens.
    """
    lines = []
    lines.append(f"=== Rapport d'entraînement (généré le {report.get('generated_at', '?')[:10]}) ===\n")

    period = report.get("period", {})
    lines.append(
        f"Période analysée: {period.get('activities_usable', 0)} activités exploitables "
        f"(sur {period.get('activities_total', 0)} au total, "
        f"{period.get('activities_stubs', 0)} stubs Strava ignorés)"
    )

    totals = report.get("totals_usable", {})
    if totals:
        lines.append(
            f"Totaux: {totals.get('total_hours', 0)}h, "
            f"{totals.get('total_km', 0)}km, "
            f"{totals.get('count', 0)} séances"
        )

    cf = report.get("current_fitness", {})
    if cf:
        lines.append(f"\nForme actuelle (au {cf.get('as_of', '?')}):")
        lines.append(f"  CTL = {cf.get('ctl', '?')} (forme)")
        lines.append(f"  ATL = {cf.get('atl', '?')} (fatigue)")
        lines.append(f"  TSB = {cf.get('tsb', '?')} (fraîcheur)")

    weekly = report.get("recent_weekly_load", [])
    if weekly:
        lines.append("\nCharge hebdomadaire récente:")
        for w in weekly:
            lines.append(f"  Semaine du {w.get('week_ending', '?')}: {w.get('tss', 0):.0f} TSS")

    breakdown = report.get("sport_breakdown", {})
    if breakdown:
        lines.append("\nRépartition par sport (période analysée):")
        for sport, data in breakdown.items():
            lines.append(
                f"  {sport}: {data.get('count', 0)} séances, "
                f"{data.get('hours', 0)}h, {data.get('tss', 0):.0f} TSS"
            )

    return "\n".join(lines)


# --- Interfaces publiques ---

def ask_coach(question: str, report: dict[str, Any], max_tokens: int = 1500) -> str:
    """
    Pose une question libre au coach en lui fournissant le contexte d'analyse.

    Args:
        question: la question en langage naturel
        report: le dict issu de analysis.build_report()
        max_tokens: longueur max de la réponse
    """
    context = _format_report_for_llm(report)
    user_message = f"{context}\n\n=== Ma question ===\n{question}"

    client = _client()
    response = client.messages.create(
        model=DEFAULT_MODEL,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    # Le SDK renvoie une liste de content blocks (pour supporter outils/images)
    # Pour du texte simple on concatène le texte de tous les blocs de type "text"
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