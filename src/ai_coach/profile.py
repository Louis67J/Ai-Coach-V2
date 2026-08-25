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

from ai_coach.config import athlete_path


def profile_path() -> Path:
    """Chemin du fichier profile.json pour l'athlète courant."""
    return athlete_path("profile.json")
class ProfileNotFoundError(RuntimeError):
    pass


def load_profile() -> dict[str, Any]:
    """Charge le profil depuis disque. Lève si absent."""
    if not profile_path().exists():
        raise ProfileNotFoundError(
            f"❌ Aucun profil trouvé à {profile_path()}. "
            f"Crée-le manuellement (voir documentation)."
        )
    return json.loads(profile_path().read_text(encoding="utf-8"))


def save_profile(profile: dict[str, Any]) -> None:
    """Écrit le profil à disque + met à jour last_updated."""
    profile.setdefault("_meta", {})
    profile["_meta"]["last_updated"] = date.today().isoformat()
    profile_path().write_text(
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


OBJECTIVES_KEY = "objectives"
PRIORITIES = ("A", "B", "C")


def get_objectives(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Objectifs de l'athlète, triés par date.

    La clé historique était `season_2026_objectives` : figée sur une saison,
    elle obligeait à toucher le code à chaque nouvelle année. On lit encore
    les anciennes clés pour ne rien perdre, mais on écrit désormais dans une
    clé neutre.
    """
    objectives = profile.get(OBJECTIVES_KEY)
    if objectives is None:
        legacy = [
            key for key in profile
            if key.startswith("season_") and key.endswith("_objectives")
        ]
        objectives = [obj for key in sorted(legacy) for obj in (profile.get(key) or [])]

    return sorted(objectives or [], key=lambda o: o.get("date") or "9999")


def set_objectives(profile: dict[str, Any], objectives: list[dict[str, Any]]) -> None:
    """Écrit la liste dans la clé neutre et retire les anciennes clés de saison."""
    profile[OBJECTIVES_KEY] = sorted(objectives, key=lambda o: o.get("date") or "9999")
    for key in [k for k in list(profile) if k.startswith("season_") and k.endswith("_objectives")]:
        del profile[key]


def split_objectives(
    objectives: list[dict[str, Any]],
    today: date | None = None,
) -> tuple[list[dict], list[dict]]:
    """
    Sépare les objectifs à venir de ceux déjà passés.

    Sans cette distinction, le coach continue de préparer une course qui a
    eu lieu il y a trois mois.
    """
    today = today or date.today()
    today_str = today.isoformat()
    upcoming = [o for o in objectives if (o.get("date") or "9999") >= today_str]
    past = [o for o in objectives if (o.get("date") or "9999") < today_str]
    return upcoming, past


def resolve_location(profile: dict[str, Any]) -> dict[str, Any]:
    """
    Où se trouve l'athlète *maintenant*, pour la météo et le terrain.

    `context.current_location` prend le pas sur `base_location` : un
    déplacement change le climat et le relief, mais pas le domicile ni les
    habitudes que le reste du profil décrit.
    """
    context = profile.get("context", {})
    current = context.get("current_location") or {}

    if current.get("latitude") is not None and current.get("longitude") is not None:
        return {
            "name": current.get("name") or "?",
            "latitude": current["latitude"],
            "longitude": current["longitude"],
            "until": current.get("until"),
            "is_away": True,
        }

    return {
        "name": context.get("base_location", "Grenoble"),
        "latitude": context.get("latitude", 45.19),
        "longitude": context.get("longitude", 5.72),
        "until": None,
        "is_away": False,
    }


def format_profile_for_llm(profile: dict[str, Any]) -> str:
    """
    Construit une représentation texte du profil pour l'injecter dans
    le prompt système du coach. Optimisé pour la lisibilité par un LLM.
    """
    athlete = profile.get("athlete", {})
    context = profile.get("context", {})
    objectives = get_objectives(profile)
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

    # Un déplacement change le climat, le relief et les créneaux : le coach
    # doit le savoir, sinon il prescrit la Chartreuse depuis l'Espagne.
    location = resolve_location(profile)
    if location["is_away"]:
        away = f"- ⚠️ ACTUELLEMENT EN DÉPLACEMENT à {location['name']}"
        if location.get("until"):
            away += f" (jusqu'au {location['until']})"
        lines.append(away)
        lines.append(
            "  → météo, terrain et parcours à raisonner sur ce lieu, pas sur la base habituelle"
        )
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
        upcoming, past = split_objectives(objectives)
        today = date.today()

        def _render(obj: dict[str, Any], with_countdown: bool) -> None:
            line = (
                f"- [{obj.get('priority', '?')}] {obj.get('name', '?')} "
                f"({obj.get('date', '?')}, {obj.get('type', '?')})"
            )
            if with_countdown and obj.get("date"):
                try:
                    days = (date.fromisoformat(obj["date"]) - today).days
                    line += f" — dans {days} jours" if days else " — AUJOURD'HUI"
                except ValueError:
                    pass
            lines.append(line)
            if obj.get("notes"):
                lines.append(f"    → {obj['notes']}")

        lines.append("\n### Objectifs À VENIR (priorité A=majeur, B=important, C=bonus)")
        if upcoming:
            for obj in upcoming:
                _render(obj, with_countdown=True)
        else:
            lines.append("- Aucun objectif futur enregistré : à clarifier avec l'athlète.")

        if past:
            # Sans ce marquage, le coach prépare encore une course déjà courue.
            lines.append("\n### Objectifs PASSÉS (déjà écoulés — ne plus planifier pour eux)")
            for obj in past:
                _render(obj, with_countdown=False)

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