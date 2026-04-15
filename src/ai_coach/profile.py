"""
Chargement et accès au profil athlète.

Le profil vit dans data/profile.json (gitignored). Il décrit l'athlète
de manière persistante : identité, objectifs, contraintes, préférences.

Toute modification du profil doit incrémenter _meta.last_updated.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ai_coach.config import DATA_DIR


PROFILE_PATH = DATA_DIR / "profile.json"


class ProfileNotFoundError(RuntimeError):
    pass


def load_profile() -> dict[str, Any]:
    """Charge le profil depuis disque. Lève si absent."""
    if not PROFILE_PATH.exists():
        raise ProfileNotFoundError(
            f"❌ Aucun profil trouvé à {PROFILE_PATH}. "
            f"Crée-le manuellement (voir documentation)."
        )
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def save_profile(profile: dict[str, Any]) -> None:
    """Écrit le profil à disque + met à jour last_updated."""
    profile.setdefault("_meta", {})
    profile["_meta"]["last_updated"] = date.today().isoformat()
    PROFILE_PATH.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def update_field(path: list[str], value: Any) -> dict[str, Any]:
    """
    Met à jour un champ du profil via un chemin (liste de clés).
    Ex: update_field(['athlete', 'ftp_watts'], 320)
    """
    profile = load_profile()
    cursor = profile
    for key in path[:-1]:
        cursor = cursor.setdefault(key, {})
    cursor[path[-1]] = value
    save_profile(profile)
    return profile


def format_profile_for_llm(profile: dict[str, Any]) -> str:
    """
    Construit une représentation texte du profil pour l'injecter dans
    le prompt système du coach. Optimisé pour la lisibilité par un LLM.
    """
    athlete = profile.get("athlete", {})
    context = profile.get("context", {})
    objectives = profile.get("season_2026_objectives", [])
    strengths = profile.get("strengths", [])
    weaknesses = profile.get("weaknesses", [])
    injuries = profile.get("injury_history", {})
    prefs = profile.get("coaching_preferences", {})
    history = profile.get("recent_history", {})

    # Calcul de l'âge si possible
    age_str = ""
    if "birth_date" in athlete:
        try:
            bd = datetime.fromisoformat(athlete["birth_date"]).date()
            age = (date.today() - bd).days // 365
            age_str = f", {age} ans"
        except Exception:
            pass

    lines = []
    lines.append("=== PROFIL ATHLÈTE ===\n")

    lines.append("### Identité et physique")
    lines.append(
        f"- {athlete.get('name', '?')}{age_str}, "
        f"{athlete.get('weight_kg', '?')}kg, "
        f"{athlete.get('height_cm', '?')}cm"
    )
    if athlete.get("weight_target_kg"):
        lines.append(
            f"- Objectif poids : {athlete['weight_target_kg']}kg "
            f"(actuel : {athlete.get('weight_kg', '?')}kg)"
        )
    lines.append(
        f"- FTP : {athlete.get('ftp_watts', '?')}W "
        f"(testée {athlete.get('ftp_updated', '?')})"
    )
    if athlete.get("ftp_target"):
        lines.append(
            f"- Objectif FTP : {athlete['ftp_target']}W "
            f"d'ici {athlete.get('ftp_target_date', '?')}"
        )
    if athlete.get("pma_watts"):
        lines.append(f"- PMA : {athlete['pma_watts']}W ({athlete.get('pma_updated', '?')})")
    lines.append(
        f"- FCmax {athlete.get('fc_max', '?')} "
        f"({athlete.get('fc_max_note', '')}), "
        f"FC repos {athlete.get('fc_resting', '?')}"
    )
    lines.append(
        f"- Catégorie : {athlete.get('category', '?')} | "
        f"{athlete.get('years_structured_training', '?')} ans d'entraînement structuré"
    )

    lines.append("\n### Contexte de vie")
    lines.append(f"- Base : {context.get('base_location', '?')}")
    lines.append(
        f"- Profession : {context.get('profession', '?')} "
        f"({context.get('weekly_work_hours', '?')}h/sem)"
    )
    lines.append(f"- Volume cible : {context.get('weekly_training_hours_target', '?')}/sem")
    schedule = context.get("typical_schedule", {})
    if schedule:
        lines.append("- Créneaux types :")
        for day, slot in schedule.items():
            lines.append(f"  • {day}: {slot}")
    if context.get("unavailable_dates"):
        lines.append(f"- Indisponibilités à venir : {', '.join(context['unavailable_dates'])}")

    if objectives:
        lines.append("\n### Objectifs saison (priorité A=majeur, B=important, C=bonus)")
        for obj in objectives:
            lines.append(
                f"- [{obj.get('priority', '?')}] {obj.get('name', '?')} "
                f"({obj.get('date', '?')}, {obj.get('type', '?')})"
            )
            if obj.get("notes"):
                lines.append(f"    → {obj['notes']}")

    if strengths:
        lines.append("\n### Points forts")
        for s in strengths:
            lines.append(f"- {s}")

    if weaknesses:
        lines.append("\n### Points faibles")
        for w in weaknesses:
            lines.append(f"- {w}")

    if injuries:
        lines.append("\n### Sensibilités physiques actuelles")
        for s in injuries.get("current_sensitivities", []):
            lines.append(f"- {s}")
        if injuries.get("prevention_routine"):
            lines.append(
                f"- Routine de prévention : {', '.join(injuries['prevention_routine'])}"
            )

    if prefs:
        lines.append("\n### Préférences de coaching")
        if prefs.get("must_include"):
            lines.append(f"- Inclure systématiquement : {', '.join(prefs['must_include'])}")
        if prefs.get("constraints"):
            lines.append("- Contraintes :")
            for c in prefs["constraints"]:
                lines.append(f"  • {c}")
        if prefs.get("methodologies_familiar"):
            lines.append(
                f"- Familier avec : {', '.join(prefs['methodologies_familiar'])}"
            )
        if prefs.get("methodologies_to_explore"):
            lines.append(
                f"- Souhaite découvrir : {', '.join(prefs['methodologies_to_explore'])}"
            )

    if history:
        lines.append("\n### Historique récent")
        if history.get("season_2025_summary"):
            lines.append(f"- 2025 : {history['season_2025_summary']}")
        if history.get("winter_2025_2026"):
            lines.append(f"- Hiver 25-26 : {history['winter_2025_2026']}")
        if history.get("best_recent_performance"):
            lines.append(f"- Meilleure perf récente : {history['best_recent_performance']}")
        if history.get("key_learning"):
            lines.append(f"- Apprentissage clé : {history['key_learning']}")

    return "\n".join(lines)