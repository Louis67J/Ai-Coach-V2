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

from ai_coach.weather import fetch_forecast, format_weather_for_llm

from ai_coach.wellness import fetch_wellness, build_wellness_summary, format_wellness_for_llm

from ai_coach.journal import format_journal_for_llm, load_recent_entries

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

Préparation Physique Générale (PPG) / Renforcement musculaire :
- Tu intègres SYSTÉMATIQUEMENT 2-3 séances de renforcement par semaine dans tes plans.
- Adapte le renforcement aux besoins spécifiques de l'athlète :
  * Gainage et stabilité du bassin (priorité vu ses fragilités hanche/TFL/psoas gauche)
  * Travail unilatéral pour corriger les déséquilibres gauche/droite
  * Force maximale jambes en période de base (squats, fentes, step-ups)
  * Force-endurance en période de compétition (circuits légers, proprioception)
- Format des séances PPG : précise les exercices, séries, répétitions, et le moment dans la journée (matin, post-entraînement, jour off)
- Intègre aussi des étirements ciblés TFL/psoas/hanche dans les jours de récup
- Le renforcement ne remplace jamais le vélo mais le complète : place-le sur les jours légers ou en complément d'une séance courte
- Adapte le volume PPG à la phase de la saison :
  * Hors-saison : 3x/sem, charges lourdes, focus force max
  * Pré-compétition : 2x/sem, charges modérées, focus explosivité et gainage
  * Compétition : 1-2x/sem, maintien, circuits légers
- Un des objectifs de l'athlète est de devenir plus complet (haut du corps ceinture, bras, épaule,etc..)  

Métriques (conventions TrainingPeaks) :
- CTL (42j) : forme long terme
- ATL (7j) : fatigue court terme
- TSB = CTL - ATL : fraîcheur
  * TSB > +5 : reposé (sous-chargé si durable)
  * TSB 0 à +5 : frais
  * TSB -10 à 0 : charge productive
  * TSB -20 à -10 : chargé, surveillance
  * TSB < -20 : surcharge
- Adapte la longueur de ta réponse à la complexité de la question.
  * Question simple ("comment je vais ?") → 3-5 lignes max
  * Question d'analyse ("analyse mes 5 dernières séances") → réponse structurée complète
  * Plan d'entraînement → détaillé mais sans bavardage
- Pas d'emojis sauf pour les indicateurs visuels de statut (✅ ⚠️ 🚨).
- Pas de titres markdown (##) pour les réponses courtes.
- Va droit au but. Pas de "Bien sûr !", "Excellente question !", ou reformulation de la question.

- Quand l'athlète fournit un RPE, croise-le avec les données objectives (TSS, FC, puissance).
  Un RPE élevé pour un TSS bas = possible fatigue accumulée, stress, maladie, sous-nutrition.
  Un RPE bas pour un TSS élevé = bonne forme, adaptation réussie.
- Encourage l'athlète à utiliser le journal RPE après chaque séance importante.
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

    sessions = report.get("recent_sessions", [])
    if sessions:
        lines.append("\nDétail des séances récentes (les plus récentes en premier) :")
        for s in sessions:
            tag = s.get("tag", "?")
            name = (s.get("name") or "?")[:40]
            np_w = s.get("np_watts") or "?"
            if_val = s.get("intensity_factor") or "?"
            tss = s.get("tss", 0)
            duration_h = round((s.get("moving_time_s") or 0) / 3600, 1)
            dist = s.get("distance_km", 0)
            elev = s.get("elevation_gain", 0)
            zones = s.get("zones", "")
            hr = s.get("avg_hr") or "?"
            dec = s.get("decoupling_pct")

            lines.append(
                f"\n  📅 {s.get('date', '?')} — {name}"
            )
            lines.append(
                f"     [{tag}] {duration_h}h | {dist}km | {elev}m D+ | "
                f"NP={np_w}W | IF={if_val} | TSS={tss} | FC moy={hr}"
            )
            if zones:
                lines.append(f"     Zones: {zones}")
            if dec is not None:
                lines.append(f"     Découplage cardiaque: {dec:.1f}%")

                # Groupes d'intervalles détaillés (avec FC, cadence, pente, etc.)
                groups = s.get("detailed_groups", [])
                if groups:
                    lines.append(f"     Intervalles ({len(groups)} blocs) :")
                    for g in groups:
                        lines.append(f"       • {g.get('label', '?')}")
                else:
                    # Fallback sur le pattern détecté ou les intervalles bruts
                    pattern = s.get("interval_pattern")
                    if pattern:
                        lines.append(f"     🎯 Structure détectée : {pattern}")
                    intervals = s.get("intervals", [])
                    if intervals and not pattern:
                        lines.append(f"     Intervalles bruts ({len(intervals)}) :")
                        for iv in intervals[:6]:
                            lines.append(f"       • {iv}")
                        if len(intervals) > 6:
                            lines.append(f"       ... +{len(intervals) - 6} autres")

        # --- Métriques avancées ---
        mono = report.get("monotony_strain", {})
        if mono:
            lines.append("\n=== MÉTRIQUES AVANCÉES ===")
            lines.append(f"\n📊 Monotonie & Strain (7 derniers jours) :")
            lines.append(f"  Monotonie = {mono.get('monotony', '?')} ({mono.get('monotony_status', '?')})")
            lines.append(f"  Strain = {mono.get('strain', '?')} ({mono.get('strain_status', '?')})")
            lines.append(
                f"  TSS quotidien moyen = {mono.get('daily_mean_tss', '?')} ± {mono.get('daily_std_tss', '?')}")

        forecast = report.get("ctl_forecast", [])
        if forecast:
            lines.append(f"\n📈 Projection CTL (si charge actuelle maintenue) :")
            for f in forecast:
                lines.append(
                    f"  J+{f['horizon_days']} ({f['target_date']}) : "
                    f"CTL projeté = {f['projected_ctl']} "
                    f"({'↗️ +' if f['delta_vs_now'] > 0 else '↘️ '}{f['delta_vs_now']})"
                )
            lines.append(f"  Hypothèse : {forecast[0].get('assumption_daily_tss', '?')} TSS/jour en moyenne")

        durability = report.get("durability", {})
        if durability and durability.get("status") != "insufficient_data":
            lines.append(f"\n🏋️ Durabilité (sorties >2h) :")
            lines.append(f"  Note : {durability.get('durability_rating', '?')}")
            lines.append(f"  Découplage moyen : {durability.get('avg_decoupling_pct', '?')}%")
            if "trend" in durability:
                lines.append(f"  Tendance : {durability['trend']}")
            lines.append(f"  Basé sur {durability.get('count', '?')} sorties longues")

        ftp_trend = report.get("ftp_trend", {})
        if ftp_trend and ftp_trend.get("status") != "insufficient_data":
            lines.append(f"\n📉 Tendance FTP :")
            if "trend" in ftp_trend:
                lines.append(f"  Tendance : {ftp_trend['trend']}")
            if "recent_avg_top5" in ftp_trend:
                lines.append(f"  Top 5 estimations récentes (3 mois) : ~{ftp_trend['recent_avg_top5']}W")
            if "older_avg_top5" in ftp_trend:
                lines.append(f"  Top 5 estimations anciennes : ~{ftp_trend['older_avg_top5']}W")
            if "delta" in ftp_trend:
                lines.append(f"  Delta : {'+' if ftp_trend['delta'] > 0 else ''}{ftp_trend['delta']}W")
            if ftp_trend.get("recent_best"):
                lines.append(f"  Meilleures estimations récentes :")
                for perf in ftp_trend["recent_best"][:3]:
                    lines.append(f"    • {perf['date']} : ~{perf['ftp']}W ({perf['source']}, {perf['name']})")

        power = report.get("power_profile", {})
        if power and power.get("profile"):
            lines.append(f"\n⚡ Profil de puissance ({power.get('weight_kg_used', '?')}kg, "
                         f"source: {power.get('source', '?')}, "
                         f"période: {power.get('period', '?')})")
            for duration, data in power["profile"].items():
                lines.append(
                    f"  {duration:>5s} : {data['watts']:>4d}W = {data['w_kg']:.1f} W/kg ({data['level']})"
                )
            if power.get("strengths"):
                lines.append(f"  💪 Forces : {', '.join(power['strengths'])}")
            if power.get("weaknesses"):
                lines.append(f"  ⚠️ Faiblesses : {', '.join(power['weaknesses'])}")

            models = power.get("power_models", {})
            if models:
                lines.append(f"\n  Modèles de puissance (calculés par Intervals.icu) :")
                for model_name, m in models.items():
                    parts = []
                    if m.get("cp"):
                        parts.append(f"CP={m['cp']}W")
                    if m.get("ftp"):
                        parts.append(f"FTP={m['ftp']}W")
                    if m.get("w_prime"):
                        parts.append(f"W'={round(m['w_prime'] / 1000, 1)}kJ")
                    if m.get("p_max"):
                        parts.append(f"Pmax={m['p_max']}W")
                    lines.append(f"    {model_name}: {', '.join(parts)}")

            if power.get("vo2max_estimated"):
                lines.append(f"  VO2max estimée (5min power) : {power['vo2max_estimated']:.1f} ml/kg/min")

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
    max_tokens: int = 3000,
    source: str = "cli",
    metadata: dict[str, Any] | None = None,
    history_limit: int = 20,
    persist: bool = True,
    light: bool = False,
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

    # Météo J+7
    weather_data = fetch_forecast(
        latitude=profile.get("context", {}).get("latitude", 45.19),
        longitude=profile.get("context", {}).get("longitude", 5.72),
        location_name=profile.get("context", {}).get("base_location", "Grenoble"),
    )
    weather_text = format_weather_for_llm(weather_data) if weather_data else ""

    # Wellness / récupération
    wellness_data = fetch_wellness(days=14)
    wellness_summary = build_wellness_summary(wellness_data)
    wellness_text = format_wellness_for_llm(wellness_summary) if wellness_summary else ""

    # Journal RPE
    journal_entries = load_recent_entries(limit=14)
    journal_text = format_journal_for_llm(journal_entries) if journal_entries else ""

    # Rapport d'analyse
    report_text = _format_report_for_llm(report)

    # Historique conversationnel précédent
    history = load_recent_exchanges(limit=history_limit)
    history_messages = to_anthropic_messages(history)

    # Résumé de mémoire long terme (conversations anciennes compactées)
    from ai_coach.memory import load_memory_summary, summarize_old_exchanges
    # Auto-compacte si nécessaire
    summarize_old_exchanges(keep_recent=15, summary_trigger=25)
    memory_summary = load_memory_summary()
    memory_summary_text = ""
    if memory_summary:
        memory_summary_text = (
            f"\n=== MÉMOIRE LONG TERME (résumé de nos conversations passées) ===\n"
            f"{memory_summary}\n"
        )

    # Mode léger : questions courtes = contexte réduit
    # On détecte automatiquement si la question est simple
    is_simple = len(question.split()) < 15 and not any(
        kw in question.lower()
        for kw in ("analyse", "plan", "séance", "semaine", "détail", "compare",
                   "historique", "progression", "intervalle", "session")
    )

    if light or is_simple:
        # Contexte minimal : juste profil résumé + fitness actuelle + wellness
        report_text_short = ""
        cf = report.get("current_fitness", {})
        if cf:
            report_text_short = (
                f"Forme actuelle : CTL={cf.get('ctl')} ATL={cf.get('atl')} TSB={cf.get('tsb')}"
            )
        current_user_message = (
            f"{profile_text}\n\n"
            f"{calendar_text}\n\n"
            f"{wellness_text}\n\n"
            f"{journal_text}\n\n"
            f"{memory_summary_text}\n\n"
            f"{report_text_short}\n\n"
            f"=== Ma question ===\n{question}\n\n"
            f"INSTRUCTION : question simple → réponds en 3 à 5 lignes maximum. "
            f"Pas de tableau, pas de titres markdown, pas d'analyse détaillée. "
            f"Juste l'essentiel en quelques phrases."
        )
        max_tokens = min(max_tokens, 500)
    else:
        current_user_message = (
            f"{profile_text}\n\n"
            f"{calendar_text}\n\n"
            f"{weather_text}\n\n"
            f"{wellness_text}\n\n"
            f"{journal_text}\n\n"
            f"{memory_summary_text}\n\n"
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
    """
    Version async de ask_coach, pour le bot Discord.
    Exécute l'appel bloquant dans un thread séparé pour ne pas bloquer
    la boucle événementielle de Discord.
    """
    import asyncio
    import functools

    # Wrap l'appel synchrone dans un executor
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
    """Version async de generate_plan."""
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