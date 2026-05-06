"""
Interface avec l'API Claude (Anthropic) pour le rôle coach cycliste.

Gère le chargement du prompt système, l'injection du contexte d'analyse,
les appels à l'API, et le TOOL USE (function calling) pour donner au coach
un accès autonome aux données d'entraînement.
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta
from typing import Any

from anthropic import Anthropic

from ai_coach.config import load_config
from ai_coach.memory import (
    append_exchange,
    load_memory_summary,
    load_recent_exchanges,
    summarize_old_exchanges,
    to_anthropic_messages,
)
from ai_coach.profile import ProfileNotFoundError, format_profile_for_llm, load_profile
from ai_coach.journal import format_journal_for_llm, load_recent_entries
from ai_coach.weather import fetch_forecast, format_weather_for_llm
from ai_coach.wellness import build_wellness_summary, fetch_wellness, format_wellness_for_llm

from ai_coach.token_tracker import log_usage

# Modèle par défaut. Overridable via env var ANTHROPIC_MODEL.
DEFAULT_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")


# ============================================================
# SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = """Tu es un coach cyclisme senior, personnel et dédié à un seul athlète.

Tu reçois à chaque conversation :
1. Le PROFIL complet de l'athlète (identité, objectifs, contraintes, préférences)
2. Un contexte de base (calendrier, forme actuelle, mémoire)
3. Des OUTILS que tu peux appeler pour obtenir des données supplémentaires

IMPORTANT — OUTILS DISPONIBLES :
Tu disposes d'outils pour accéder aux données d'entraînement. UTILISE-LES quand tu as besoin
de détails plutôt que de deviner. Par exemple :
- Pour analyser une séance spécifique → appelle get_session_detail
- Pour voir la météo → appelle get_weather_forecast
- Pour les données de récupération → appelle get_wellness
- Pour le profil de puissance → appelle get_power_profile
- Pour chercher des séances par critère → appelle search_sessions
Tu peux appeler PLUSIEURS outils si nécessaire. N'hésite pas à combiner les données.

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
- Adapte la longueur de ta réponse à la complexité de la question.
  * Question simple ("comment je vais ?") → réponse concise mais actionnable (verdict + reco journée)
  * Question d'analyse ("analyse mes 5 dernières séances") → réponse structurée complète
  * Plan d'entraînement → détaillé mais sans bavardage
- Pas d'emojis sauf pour les indicateurs visuels de statut (✅ ⚠️ 🚨).
- Pas de titres markdown (##) pour les réponses courtes.
- Va droit au but. Pas de "Bien sûr !", "Excellente question !", ou reformulation de la question.

Limites :
- Tu n'es pas médecin. Pour toute douleur ou symptôme inquiétant, recommande un professionnel de santé.
- Pour les sensibilités musculaires connues, tu intègres systématiquement de la prévention.
- Tu ne prescris JAMAIS de suppléments ou médicaments.

Préparation Physique Générale (PPG) / Renforcement musculaire :
- Tu intègres SYSTÉMATIQUEMENT 2-3 séances de renforcement par semaine dans tes plans.
- Adapte le renforcement aux besoins spécifiques de l'athlète :
  * Gainage et stabilité du bassin (priorité vu ses fragilités hanche/TFL/psoas gauche)
  * Travail unilatéral pour corriger les déséquilibres gauche/droite
  * Force maximale jambes en période de base (squats, fentes, step-ups)
  * Force-endurance en période de compétition (circuits légers, proprioception)
- Format des séances PPG : précise les exercices, séries, répétitions, et le moment
- Intègre aussi des étirements ciblés TFL/psoas/hanche dans les jours de récup
- Le renforcement ne remplace jamais le vélo mais le complète
- Un des objectifs de l'athlète est de devenir plus complet (haut du corps, ceinture, bras, épaule)

Métriques (conventions TrainingPeaks) :
- CTL (42j) : forme long terme
- ATL (7j) : fatigue court terme
- TSB = CTL - ATL : fraîcheur
  * TSB > +5 : reposé | 0 à +5 : frais | -10 à 0 : charge productive
  * -20 à -10 : chargé, surveillance | < -20 : surcharge

RPE (Rate of Perceived Exertion) :
- Quand l'athlète fournit un RPE, croise-le avec les données objectives (TSS, FC, puissance).
  Un RPE élevé pour un TSS bas = possible fatigue accumulée, stress, maladie, sous-nutrition.
  Un RPE bas pour un TSS élevé = bonne forme, adaptation réussie.
- Encourage l'athlète à utiliser le journal RPE après chaque séance importante.
"""


# ============================================================
# TOOL DEFINITIONS
# ============================================================

TOOLS = [
    {
        "name": "get_session_detail",
        "description": (
            "Récupère la fiche enrichie d'une séance d'entraînement spécifique, "
            "incluant : puissance (NP, IF, zones), FC, cadence, découplage, "
            "intervalles détectés avec FC/cadence/pente par bloc, classification. "
            "Utilise ce tool quand l'athlète demande une analyse de séance ou "
            "quand tu as besoin de détails sur un entraînement précis."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date de la séance au format YYYY-MM-DD. "
                                   "Utilise 'last' pour la dernière séance vélo.",
                },
            },
            "required": ["date"],
        },
    },
    {
        "name": "get_weather_forecast",
        "description": (
            "Récupère les prévisions météo des 7 prochains jours pour la zone "
            "d'entraînement de l'athlète. Température, vent, pluie, conditions. "
            "Utilise ce tool pour adapter les recommandations indoor/outdoor."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_wellness",
        "description": (
            "Récupère les données de récupération des 14 derniers jours : "
            "HRV, FC repos, score de sommeil, durée de sommeil, readiness (Whoop). "
            "Inclut les tendances et les alertes. "
            "Utilise ce tool pour évaluer l'état de récupération."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Nombre de jours à récupérer (défaut 14).",
                },
            },
        },
    },
    {
        "name": "get_power_profile",
        "description": (
            "Récupère le profil de puissance complet de l'athlète : meilleurs watts "
            "sur 5s/1min/5min/20min/60min, niveaux Coggan, modèles de puissance "
            "(CP, W', FTP estimée), VO2max estimée. Données sur 1 an."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_advanced_metrics",
        "description": (
            "Récupère les métriques avancées : monotonie/strain (7j), projections CTL, "
            "indice de durabilité, tendance FTP. "
            "Utilise ce tool pour une analyse approfondie de la forme."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "search_sessions",
        "description": (
            "Cherche des séances d'entraînement par critère. Peut filtrer par : "
            "tag (SEUIL, VO2_PMA, FRACTIONNE_COURT, ENDURANCE, TEMPO, Z2_STRICT...), "
            "type de sport (Ride, VirtualRide, Run...), plage de dates, TSS minimum. "
            "Retourne une liste résumée des séances correspondantes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tag": {
                    "type": "string",
                    "description": "Tag de classification (ex: SEUIL, VO2_PMA, FRACTIONNE_COURT, "
                                   "ENDURANCE, TEMPO, Z2_STRICT, ENDURANCE_SPRINTS, MIXTE_ENDURANCE)",
                },
                "sport_type": {
                    "type": "string",
                    "description": "Type de sport (ex: Ride, VirtualRide, Run)",
                },
                "date_from": {
                    "type": "string",
                    "description": "Date de début au format YYYY-MM-DD",
                },
                "date_to": {
                    "type": "string",
                    "description": "Date de fin au format YYYY-MM-DD",
                },
                "min_tss": {
                    "type": "integer",
                    "description": "TSS minimum pour filtrer",
                },
                "limit": {
                    "type": "integer",
                    "description": "Nombre max de résultats (défaut 10)",
                },
            },
        },
    },
    {
        "name": "get_journal_rpe",
        "description": (
            "Récupère les entrées du journal RPE (sensations post-séance). "
            "Chaque entrée contient : date, RPE /10, notes libres, tags automatiques."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Nombre d'entrées à récupérer (défaut 14)",
                },
            },
        },
    },
    {
        "name": "get_plan_followup",
        "description": (
            "Récupère les derniers plans d'entraînement prescrits et compare "
            "avec les séances réellement effectuées. Permet de voir si l'athlète "
            "suit le plan ou s'en écarte."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Nombre de plans à récupérer (défaut 1, le dernier)",
                },
            },
        },
    },
]


# ============================================================
# TOOL EXECUTION
# ============================================================

def _execute_tool(name: str, input_data: dict) -> str:
    """
    Exécute un outil et retourne le résultat en JSON string.
    C'est ici que chaque outil est connecté à nos fonctions Python.
    """
    try:
        if name == "get_session_detail":
            return _tool_get_session_detail(input_data)
        elif name == "get_weather_forecast":
            return _tool_get_weather()
        elif name == "get_wellness":
            return _tool_get_wellness(input_data)
        elif name == "get_power_profile":
            return _tool_get_power_profile()
        elif name == "get_advanced_metrics":
            return _tool_get_advanced_metrics()
        elif name == "search_sessions":
            return _tool_search_sessions(input_data)
        elif name == "get_journal_rpe":
            return _tool_get_journal_rpe(input_data)
        elif name == "get_plan_followup":
            return _tool_get_plan_followup(input_data)
        else:
            return json.dumps({"error": f"Outil inconnu: {name}"})
    except Exception as e:
        return json.dumps({"error": f"Erreur {name}: {str(e)}"})


def _tool_get_plan_followup(input_data: dict) -> str:
    from ai_coach.plan_tracker import load_recent_plans, build_plan_vs_actual
    from ai_coach.intervals import load_enriched_sessions

    limit = input_data.get("limit", 1)
    plans = load_recent_plans(limit=limit)
    if not plans:
        return json.dumps({"message": "Aucun plan enregistré"})

    sessions = load_enriched_sessions()
    results = []
    for plan in plans:
        comparison = build_plan_vs_actual(plan, sessions)
        results.append(comparison)

    return "\n\n".join(results)


def _tool_get_session_detail(input_data: dict) -> str:
    from ai_coach.intervals import load_enriched_sessions

    date_str = input_data.get("date", "last")
    sessions = load_enriched_sessions()

    if date_str.lower() in ("last", "derniere", "dernière"):
        bike = [s for s in sessions if s.get("type") in ("Ride", "VirtualRide")]
        if not bike:
            return json.dumps({"error": "Aucune séance vélo trouvée"})
        target = max(bike, key=lambda s: s.get("date", ""))
    else:
        matching = [s for s in sessions if date_str in s.get("date", "")]
        if not matching:
            return json.dumps({"error": f"Aucune séance trouvée pour {date_str}"})
        target = max(matching, key=lambda s: s.get("tss", 0))

    return json.dumps(target, ensure_ascii=False, default=str)


def _tool_get_weather() -> str:
    try:
        profile = load_profile()
        lat = profile.get("context", {}).get("latitude", 45.19)
        lon = profile.get("context", {}).get("longitude", 5.72)
        loc = profile.get("context", {}).get("base_location", "Grenoble")
    except ProfileNotFoundError:
        lat, lon, loc = 45.19, 5.72, "Grenoble"

    data = fetch_forecast(latitude=lat, longitude=lon, location_name=loc)
    if not data:
        return json.dumps({"error": "Météo indisponible"})
    # Résumé compact au lieu du format texte complet
    compact_days = []
    for day in data.get("forecast", []):
        compact_days.append({
            "date": day.get("date"),
            "weather": day.get("weather"),
            "temp": f"{day.get('temp_min', '?')}-{day.get('temp_max', '?')}°C",
            "wind_kmh": day.get("wind_max_kmh"),
            "rain_mm": day.get("precipitation_mm"),
            "rain_prob": day.get("precipitation_prob"),
        })
    return json.dumps({"location": loc, "forecast": compact_days}, ensure_ascii=False)

def _tool_get_wellness(input_data: dict) -> str:
    days = min(input_data.get("days", 7), 7)  # Max 7 jours pour limiter les tokens
    data = fetch_wellness(days=days)
    summary = build_wellness_summary(data)
    if not summary:
        return json.dumps({"error": "Pas de données wellness disponibles"})
    # Résumé compact au lieu du format complet
    compact = {
        "hrv_avg": summary.get("hrv_avg_7d"),
        "hrv_latest": summary.get("hrv_latest"),
        "hrv_trend": summary.get("hrv_trend"),
        "rhr_avg": summary.get("rhr_avg_7d"),
        "rhr_latest": summary.get("rhr_latest"),
        "sleep_score_avg": summary.get("sleep_score_avg"),
        "sleep_hours_avg": summary.get("sleep_hours_avg"),
        "readiness_latest": summary.get("readiness_latest"),
        "alerts": summary.get("alerts", []),
    }
    return json.dumps(compact, ensure_ascii=False)

def _tool_get_power_profile() -> str:
    from ai_coach.intervals import load_enriched_sessions, fetch_power_curves

    curve = fetch_power_curves()
    if curve:
        # Résumé compact pour le LLM
        result = {
            "source": "intervals_api",
            "weight": curve.get("weight"),
            "period": f"{(curve.get('start_date_local') or '?')[:10]} → {(curve.get('end_date_local') or '?')[:10]}",
        }

        secs = curve.get("secs", [])
        values = curve.get("values", [])
        wkg = curve.get("watts_per_kg", [])

        targets = {"5s": 5, "1min": 60, "5min": 300, "20min": 1200, "60min": 3600}
        bests = {}
        for label, target_s in targets.items():
            closest = min(range(len(secs)), key=lambda i: abs(secs[i] - target_s))
            bests[label] = {
                "watts": values[closest],
                "w_kg": round(wkg[closest], 2) if closest < len(wkg) else None,
            }
        result["bests"] = bests

        models = {}
        for pm in curve.get("powerModels", []):
            models[pm.get("type", "?")] = {
                "cp": pm.get("criticalPower"),
                "ftp": pm.get("ftp"),
                "w_prime": pm.get("wPrime"),
            }
        result["power_models"] = models
        result["vo2max_5min"] = curve.get("vo2max_5m")

        return json.dumps(result, ensure_ascii=False)

    return json.dumps({"error": "Power curve indisponible"})


def _tool_get_advanced_metrics() -> str:
    from ai_coach.intervals import load_cached_activities
    from ai_coach.analysis import build_report

    activities = load_cached_activities()
    if not activities:
        return json.dumps({"error": "Pas de données en cache"})

    report = build_report(activities)

    metrics = {}
    for key in ("monotony_strain", "ctl_forecast", "durability", "ftp_trend"):
        if key in report:
            metrics[key] = report[key]

    return json.dumps(metrics, ensure_ascii=False, default=str)


def _tool_search_sessions(input_data: dict) -> str:
    from ai_coach.intervals import load_enriched_sessions

    sessions = load_enriched_sessions()

    tag = input_data.get("tag")
    sport_type = input_data.get("sport_type")
    date_from = input_data.get("date_from")
    date_to = input_data.get("date_to")
    min_tss = input_data.get("min_tss")
    limit = input_data.get("limit", 10)

    filtered = sessions
    if tag:
        filtered = [s for s in filtered if tag.upper() in (s.get("tag") or "").upper()]
    if sport_type:
        filtered = [s for s in filtered if sport_type.lower() in (s.get("type") or "").lower()]
    if date_from:
        filtered = [s for s in filtered if (s.get("date") or "") >= date_from]
    if date_to:
        filtered = [s for s in filtered if (s.get("date") or "") <= date_to]
    if min_tss:
        filtered = [s for s in filtered if (s.get("tss") or 0) >= min_tss]

    # Trie par date décroissante
    filtered.sort(key=lambda s: s.get("date", ""), reverse=True)
    filtered = filtered[:limit]

    # Résumé compact
    results = []
    for s in filtered:
        results.append({
            "date": s.get("date"),
            "name": s.get("name"),
            "tag": s.get("tag"),
            "tss": s.get("tss"),
            "np_watts": s.get("np_watts"),
            "intensity_factor": s.get("intensity_factor"),
            "avg_hr": s.get("avg_hr"),
            "decoupling_pct": s.get("decoupling_pct"),
            "intervals_count": len(s.get("detailed_groups") or []),
        })

    return json.dumps({"count": len(results), "sessions": results}, ensure_ascii=False)


def _tool_get_journal_rpe(input_data: dict) -> str:
    limit = input_data.get("limit", 14)
    entries = load_recent_entries(limit=limit)
    if not entries:
        return json.dumps({"message": "Journal RPE vide"})
    return format_journal_for_llm(entries)


# ============================================================
# HELPERS
# ============================================================

def _client() -> Anthropic:
    config = load_config()
    return Anthropic(api_key=config.anthropic_api_key)


def _build_calendar_window(profile: dict[str, Any], days_ahead: int = 14) -> str:
    weekdays_fr = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    unavailable = set(profile.get("context", {}).get("unavailable_dates", []))
    schedule = profile.get("context", {}).get("typical_schedule", {})

    today = date.today()
    lines = ["=== AGENDA DES 14 PROCHAINS JOURS ==="]
    lines.append("(table de référence : ne calcule PAS les jours de semaine toi-même)")
    lines.append("")

    for offset in range(days_ahead):
        day = today + timedelta(days=offset)
        day_str = day.isoformat()
        weekday = weekdays_fr[day.weekday()]

        markers = []
        if offset == 0:
            markers.append("AUJOURD'HUI")
        if day_str in unavailable:
            markers.append("INDISPONIBLE")
        if weekday == "lundi" and "monday" in schedule:
            markers.append(f"({schedule['monday']})")

        marker_str = "  ← " + " | ".join(markers) if markers else ""
        lines.append(f"  {weekday:9s} {day_str}{marker_str}")

    return "\n".join(lines)


# ============================================================
# MAIN ASK FUNCTION WITH TOOL USE
# ============================================================

def ask_coach(
    question: str,
    report: dict[str, Any],
    max_tokens: int = 3000,
    source: str = "cli",
    metadata: dict[str, Any] | None = None,
    history_limit: int = 20,
    persist: bool = True,
    light: bool = False,
    max_tool_rounds: int = 5,
) -> str:
    """
    Pose une question au coach avec tool use.

    Le coach reçoit un contexte de base léger (profil + calendrier + fitness)
    et des OUTILS qu'il peut appeler pour obtenir plus de données.
    Il décide lui-même quand il a besoin de détails.
    """
    # --- Contexte de base (toujours injecté, léger) ---
    try:
        profile = load_profile()
        profile_text = format_profile_for_llm(profile)
    except ProfileNotFoundError:
        profile = {}
        profile_text = "(Aucun profil athlète défini)"

    calendar_text = _build_calendar_window(profile, days_ahead=14)

    # Fitness actuelle (toujours utile, très léger)
    cf = report.get("current_fitness", {})
    fitness_text = ""
    if cf:
        fitness_text = (
            f"\nForme actuelle (au {cf.get('as_of', '?')}) : "
            f"CTL={cf.get('ctl')} ATL={cf.get('atl')} TSB={cf.get('tsb')}"
        )

    # Mémoire long terme
    summarize_old_exchanges(keep_recent=15, summary_trigger=25)
    memory_summary = load_memory_summary()
    memory_text = ""
    if memory_summary:
        memory_text = (
            f"\n=== MÉMOIRE LONG TERME ===\n{memory_summary}\n"
        )

    # Historique conversationnel
    history = load_recent_exchanges(limit=history_limit)
    history_messages = to_anthropic_messages(history)

    # --- Construction du message utilisateur ---
    current_user_message = (
        f"{profile_text}\n\n"
        f"{calendar_text}\n\n"
        f"{fitness_text}\n\n"
        f"{memory_text}\n\n"
        f"=== Ma question ===\n{question}"
    )

    messages = history_messages + [
        {"role": "user", "content": current_user_message}
    ]

    # --- Boucle d'appel avec tool use ---
    client = _client()
    tools_to_use = TOOLS if not light else []  # Pas d'outils en mode léger

    for round_num in range(max_tool_rounds + 1):
        import time
        for attempt in range(3):
            try:
                response = client.messages.create(
                    model=DEFAULT_MODEL,
                    max_tokens=max_tokens,
                    system=SYSTEM_PROMPT,
                    messages=messages,
                    tools=tools_to_use if tools_to_use else [],
                )
                break
            except Exception as e:
                if "rate_limit" in str(e).lower() and attempt < 2:
                    wait = 30 * (attempt + 1)
                    print(f"  ⏳ Rate limit, attente {wait}s...")
                    time.sleep(wait)
                else:
                    raise

        # --- Log de la consommation tokens ---
        if hasattr(response, "usage"):
            log_usage(
                model=DEFAULT_MODEL,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                source=source,
                question_preview=question,
            )
        # Si Claude ne demande pas d'outil, on a la réponse finale
        if response.stop_reason != "tool_use":
            break

        # --- Extraction de la réponse finale ---
        parts = [block.text for block in response.content if block.type == "text"]
        answer = "\n".join(parts).strip()

        # Claude veut utiliser un ou plusieurs outils
        # Ajoute la réponse de Claude (avec les tool_use blocks) aux messages
        messages.append({"role": "assistant", "content": response.content})

        # Exécute chaque outil demandé
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                print(f"  🔧 Outil appelé : {block.name}({json.dumps(block.input, ensure_ascii=False)})")
                result = _execute_tool(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        # Renvoie les résultats à Claude
        messages.append({"role": "user", "content": tool_results})

    # --- Extraction de la réponse finale ---
    parts = [block.text for block in response.content if block.type == "text"]
    answer = "\n".join(parts).strip()

    # Sauvegarde en mémoire
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
    question = (
        f"Propose-moi un plan d'entraînement pour les {horizon_days} prochains jours, "
        f"basé sur mon état de forme actuel et nos discussions précédentes si pertinent. "
        f"Utilise les outils disponibles pour consulter ma wellness, la météo, "
        f"et mes séances récentes si tu en as besoin. "
        f"Pour chaque jour: type de séance, durée, intensité cible, et une phrase sur l'objectif. "
        f"Inclus 2-3 séances de renforcement musculaire. "
        f"Termine par 2-3 phrases sur la logique globale du bloc."
    )
    plan_text = ask_coach(
        question, report,
        max_tokens=3000,
        source=source,
        metadata=metadata,
    )

    # Sauvegarde le plan pour le suivi
    from ai_coach.plan_tracker import save_plan
    save_plan(
        plan_text=plan_text,
        start_date=date.today().isoformat(),
        days=horizon_days,
    )

    return plan_text


async def ask_coach_async(
    question: str,
    report: dict[str, Any],
    max_tokens: int = 3000,
    source: str = "discord",
    metadata: dict[str, Any] | None = None,
    history_limit: int = 20,
    persist: bool = True,
    light: bool = False,
) -> str:
    import asyncio
    import functools

    loop = asyncio.get_event_loop()
    answer = await loop.run_in_executor(
        None,
        functools.partial(
            ask_coach,
            question=question,
            report=report,
            max_tokens=max_tokens,
            source=source,
            metadata=metadata,
            history_limit=history_limit,
            persist=persist,
            light=light,
        ),
    )
    return answer


async def generate_plan_async(
    report: dict[str, Any],
    horizon_days: int = 7,
    source: str = "discord",
    metadata: dict[str, Any] | None = None,
) -> str:
    import asyncio
    import functools

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        functools.partial(
            generate_plan,
            report=report,
            horizon_days=horizon_days,
            source=source,
            metadata=metadata,
        ),
    )
