"""
Interprétation de la description textuelle d'une séance en segments.

Le coach écrit ses séances en langage naturel ("2x8min tempo + 3x1min @ 90%
FTP"). Ce module en tire une suite de blocs chiffrés, de façon purement
déterministe : aucun appel au LLM, donc un même texte donne toujours le même
dessin et rien n'est inventé. Ce qui n'est pas compris est signalé plutôt que
comblé au jugé.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# %FTP représentatif de chaque zone (milieu de la fourchette Coggan)
ZONE_PCT = {"Z1": 50.0, "Z2": 65.0, "Z3": 83.0, "Z4": 98.0, "Z5": 113.0, "Z6": 135.0, "Z7": 170.0}

# Mots-clés d'intensité fréquents dans les plans, quand aucun % n'est donné
KEYWORD_PCT = {
    "récupération": 50.0, "recuperation": 50.0, "récup": 50.0, "recup": 50.0,
    "endurance": 65.0, "tempo": 83.0, "sweet spot": 90.0, "sweetspot": 90.0,
    "seuil": 98.0, "vo2": 113.0, "vo2max": 113.0, "pma": 118.0,
    "sprint": 170.0, "à fond": 105.0, "a fond": 105.0, "maximum": 105.0,
}

WARMUP_PCT = 55.0
RECOVERY_PCT = 50.0
DEFAULT_STEADY_PCT = 65.0


@dataclass
class Segment:
    """Un bloc homogène de la séance."""
    minutes: float
    pct_ftp: float
    kind: str  # warmup | work | recovery | steady | cooldown
    label: str = ""


@dataclass
class Workout:
    segments: list[Segment] = field(default_factory=list)
    understood: bool = True        # False = on n'a rien su lire, bloc unique par défaut
    notes: list[str] = field(default_factory=list)

    @property
    def total_minutes(self) -> float:
        return round(sum(s.minutes for s in self.segments), 1)


def _pct_from_text(text: str) -> float | None:
    """Trouve une intensité en %FTP, en zone, ou via un mot-clé."""
    lowered = text.lower()

    # "105-110% FTP" → milieu de la fourchette
    span = re.search(r"(\d{2,3})\s*[-–à]\s*(\d{2,3})\s*%", lowered)
    if span:
        return (float(span.group(1)) + float(span.group(2))) / 2

    single = re.search(r"(\d{2,3})\s*%", lowered)
    if single:
        return float(single.group(1))

    zone = re.search(r"\bz([1-7])\b", lowered)
    if zone:
        return ZONE_PCT[f"Z{zone.group(1)}"]

    for keyword, pct in KEYWORD_PCT.items():
        if keyword in lowered:
            return pct
    return None


def _parse_repetitions(text: str) -> list[tuple[int, float, float | None, str]]:
    """
    Extrait les blocs "N x durée" du texte.

    Retourne (répétitions, minutes, %FTP éventuel, libellé brut).
    """
    blocks = []
    pattern = re.compile(
        r"(\d+)\s*[x×]\s*"                      # nombre de répétitions
        r"(\d+(?:[.,]\d+)?)\s*(min|'|s|sec)?"   # durée + unité
        r"([^,;+.]*)",                          # suite : intensité éventuelle
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        reps = int(match.group(1))
        value = float(match.group(2).replace(",", "."))
        unit = (match.group(3) or "min").lower()
        minutes = value / 60 if unit in ("s", "sec") else value
        tail = match.group(4) or ""
        # L'intensité peut suivre la durée, sinon on la cherchera plus largement
        blocks.append((reps, minutes, _pct_from_text(tail), tail.strip()))
    return blocks


# Séances sans vélo : rien à dessiner en %FTP
OFF_BIKE_KEYWORDS = (
    "ppg", "muscu", "renforcement", "gainage", "étirement", "etirement",
    "foam roller", "yoga", "mobilité", "mobilite",
)


def _parse_single_effort(
    description: str, total: float
) -> tuple[float, float] | None:
    """
    Repère un effort chronométré unique ("20min à fond", "1x30min au seuil").

    Sans ça, un test de 20 minutes dans une séance d'une heure était étalé
    sur toute la séance : le dessin montrait une heure à 105% FTP.
    """
    matches = re.findall(
        r"(?:1\s*[x×]\s*)?(\d+(?:[.,]\d+)?)\s*(?:min|')", description, re.IGNORECASE
    )
    if len(matches) != 1:
        return None

    minutes = float(matches[0].replace(",", "."))
    # Un bloc qui occupe presque toute la séance, c'est une séance continue
    if minutes >= total * 0.8:
        return None

    pct = _pct_from_text(description)
    # On ne fabrique un effort isolé que s'il est réellement intense
    if pct is None or pct < 80:
        return None
    return minutes, pct


def parse_workout(
    description: str,
    duration_min: float | None = None,
    session_type: str = "",
) -> Workout:
    """
    Traduit la description d'une journée de plan en segments dessinables.

    duration_min borne la séance : le temps non couvert par les intervalles
    devient échauffement, liaison et retour au calme.
    """
    text = f"{session_type} {description or ''}".strip()
    total = float(duration_min or 0)

    if total <= 0 or re.search(r"\brepos\b", text, re.IGNORECASE):
        return Workout(segments=[], understood=True, notes=["Jour de repos"])

    reps_blocks = _parse_repetitions(description or "")
    global_pct = _pct_from_text(text) or DEFAULT_STEADY_PCT

    if not reps_blocks:
        single = _parse_single_effort(description or "", total)
        if single:
            minutes, pct = single
            return _single_effort_workout(total, minutes, pct)

        # Séance sans vélo : le dessiner en %FTP tromperait sur sa nature
        lowered = text.lower()
        if any(k in lowered for k in OFF_BIKE_KEYWORDS) and _pct_from_text(description or "") is None:
            return Workout(
                segments=[], understood=True,
                notes=["Séance hors vélo : pas de profil de puissance à tracer."],
            )

        # Séance continue : un seul bloc, éventuellement encadré
        return _steady_workout(total, global_pct, understood=_pct_from_text(text) is not None)

    # Séance structurée : échauffement + répétitions + retour au calme
    work_total = sum(reps * minutes for reps, minutes, _, _ in reps_blocks)
    # Récupération entre répétitions : même durée que l'effort, plafonnée
    recovery_each = {}
    for reps, minutes, _, _ in reps_blocks:
        recovery_each[(reps, minutes)] = min(minutes, 5.0)
    recovery_total = sum(
        (reps - 1) * recovery_each[(reps, minutes)] for reps, minutes, _, _ in reps_blocks
    )

    remaining = total - work_total - recovery_total
    if remaining < 10:
        # Pas la place pour un échauffement crédible : on garde les efforts
        warmup = cooldown = max(remaining / 2, 0)
    else:
        warmup = max(remaining * 0.6, 10)
        cooldown = remaining - warmup

    segments: list[Segment] = []
    if warmup > 0:
        segments.append(Segment(round(warmup, 1), WARMUP_PCT, "warmup", "Échauffement"))

    for reps, minutes, pct, label in reps_blocks:
        effort_pct = pct or global_pct
        recovery = recovery_each[(reps, minutes)]
        for i in range(reps):
            segments.append(
                Segment(minutes, effort_pct, "work", f"{minutes:g}min @ {effort_pct:.0f}% FTP")
            )
            if i < reps - 1:
                segments.append(Segment(recovery, RECOVERY_PCT, "recovery", "Récup"))

    if cooldown > 0:
        segments.append(Segment(round(cooldown, 1), WARMUP_PCT, "cooldown", "Retour au calme"))

    notes = []
    if remaining < 0:
        notes.append(
            "Les intervalles décrits dépassent la durée annoncée : dessin approximatif."
        )
    return Workout(segments=segments, understood=True, notes=notes)


def _single_effort_workout(total: float, effort_min: float, pct: float) -> Workout:
    """Un effort chronométré unique, encadré d'un échauffement et d'un retour au calme."""
    remaining = max(total - effort_min, 0)
    warmup = remaining * 0.6
    cooldown = remaining - warmup
    segments = []
    if warmup > 0:
        segments.append(Segment(round(warmup, 1), WARMUP_PCT, "warmup", "Échauffement"))
    segments.append(Segment(effort_min, pct, "work", f"{effort_min:g}min @ {pct:.0f}% FTP"))
    if cooldown > 0:
        segments.append(Segment(round(cooldown, 1), WARMUP_PCT, "cooldown", "Retour au calme"))
    return Workout(segments=segments)


def _steady_workout(total: float, pct: float, understood: bool) -> Workout:
    """Séance continue, avec échauffement et retour au calme si la durée le permet."""
    notes = [] if understood else ["Intensité non précisée : endurance supposée."]
    if total < 30:
        return Workout(
            segments=[Segment(total, pct, "steady", f"{pct:.0f}% FTP")],
            understood=understood,
            notes=notes,
        )

    warmup = min(10.0, total * 0.15)
    cooldown = min(10.0, total * 0.15)
    return Workout(
        segments=[
            Segment(round(warmup, 1), WARMUP_PCT, "warmup", "Échauffement"),
            Segment(round(total - warmup - cooldown, 1), pct, "steady", f"{pct:.0f}% FTP"),
            Segment(round(cooldown, 1), WARMUP_PCT, "cooldown", "Retour au calme"),
        ],
        understood=understood,
        notes=notes,
    )


def workout_from_plan_day(day: dict[str, Any]) -> Workout:
    """Interprète une journée telle que stockée dans un plan structuré."""
    return parse_workout(
        description=day.get("intensity") or "",
        duration_min=day.get("duration_min"),
        session_type=day.get("type") or "",
    )
