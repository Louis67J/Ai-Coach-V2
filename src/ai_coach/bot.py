"""
Bot Discord pour interagir avec le coach IA en direct.

Commandes disponibles:
    !ask <question>   Pose une question libre au coach
    !plan [jours]     Plan d'entraînement (défaut 7 jours)
    !stats            Résumé rapide de la forme actuelle
    !refresh          Re-fetch les données Intervals.icu
    !fitness          Envoie le graphe CTL/ATL/TSB
    !help_coach       Affiche l'aide
"""
from __future__ import annotations

import logging
from pathlib import Path

import discord
from discord.ext import commands

from ai_coach.analysis import build_report
from ai_coach.coach import ask_coach, generate_plan
from ai_coach.config import OUTPUTS_DIR, load_config
from ai_coach.intervals import load_cached_activities, refresh_cache


# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("ai_coach.bot")


# --- Bot instance ---
intents = discord.Intents.default()
intents.message_content = True  # nécessaire pour lire les commandes texte

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None,  # on fait notre propre !help_coach
)


# --- Helpers ---

MAX_DISCORD_MSG = 1900  # marge sous la limite 2000 de Discord


def _chunks(text: str, size: int = MAX_DISCORD_MSG) -> list[str]:
    """
    Découpe un long texte en morceaux qui tiennent dans un message Discord,
    en coupant de préférence sur un saut de ligne.
    """
    if len(text) <= size:
        return [text]

    chunks = []
    remaining = text
    while len(remaining) > size:
        # Cherche le dernier saut de ligne dans la fenêtre
        cut = remaining.rfind("\n", 0, size)
        if cut == -1 or cut < size // 2:
            cut = size  # fallback: coupe brutalement
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    if remaining:
        chunks.append(remaining)
    return chunks


async def send_long(ctx: commands.Context, text: str) -> None:
    """Envoie un message long en le découpant si nécessaire."""
    for chunk in _chunks(text):
        await ctx.send(chunk)


def _load_report_or_error() -> dict | str:
    """
    Charge le cache et construit le rapport.
    Retourne le rapport (dict) ou un message d'erreur (str).
    """
    activities = load_cached_activities()
    if not activities:
        return "❌ Aucune donnée en cache. Lance `!refresh` d'abord."
    try:
        return build_report(activities)
    except Exception as e:
        log.exception("build_report failed")
        return f"❌ Erreur pendant l'analyse: {e}"


# --- Events ---

@bot.event
async def on_ready() -> None:
    log.info(f"Connecté en tant que {bot.user}")
    log.info(f"Serveurs: {[g.name for g in bot.guilds]}")


@bot.event
async def on_command_error(ctx: commands.Context, error: Exception) -> None:
    if isinstance(error, commands.CommandNotFound):
        return  # on ignore les commandes inconnues
    log.exception("Command error")
    await ctx.send(f"❌ Erreur: {error}")


# --- Commandes ---

@bot.command(name="help_coach")
async def help_coach(ctx: commands.Context) -> None:
    """Affiche l'aide du bot coach."""
    text = (
        "**🚴 AI Coach — commandes**\n"
        "`!ask <question>` — pose une question au coach (avec mémoire)\n"
        "`!plan [jours]` — plan d'entraînement (défaut 7)\n"
        "`!stats` — résumé rapide de ta forme\n"
        "`!refresh` — re-fetch Intervals.icu (fais-le après une sortie)\n"
        "`!fitness` — envoie le graphe CTL/ATL/TSB\n"
        "`!profile` — affiche ton profil athlète\n"
        "`!set_ftp <W>` — met à jour ta FTP\n"
        "`!set_weight <kg>` — met à jour ton poids\n"
        "`!add_note <texte>` — ajoute une note de contexte au profil\n"
        "`!history [n]` — affiche les n derniers échanges (défaut 5)\n"
        "`!forget yes` — efface toute la mémoire\n"
        "`!forget_last` — supprime le dernier échange\n"
        "`!enrich [max]` — enrichit les séances (détails + intervalles)\n"
        "`!session <date|last>` — graphe détaillé d'une séance\n"
        "`!help_coach` — cette aide\n"
    )
    await ctx.send(text)

@bot.command(name="session")
async def cmd_session(ctx: commands.Context, *, date_str: str = "last") -> None:
    """
    Graphe détaillé d'une séance.
    Usage: !session 2026-04-08  ou  !session last
    """
    from ai_coach.intervals import (
        fetch_activity_streams, fetch_activity_intervals,
        load_enriched_sessions,
    )
    from ai_coach.charts import plot_session

    sessions = load_enriched_sessions()

    if date_str.lower() in ("last", "derniere", "dernière"):
        bike = [s for s in sessions if s.get("type") in ("Ride", "VirtualRide")]
        if not bike:
            await ctx.send("❌ Aucune séance vélo enrichie.")
            return
        target = max(bike, key=lambda s: s.get("date", ""))
    else:
        matching = [s for s in sessions if date_str in s.get("date", "")]
        if not matching:
            await ctx.send(f"❌ Aucune séance trouvée pour '{date_str}'. Lance `!enrich` d'abord.")
            return
        target = max(matching, key=lambda s: s.get("tss", 0))

    await ctx.send(
        f"📊 **{target.get('name')}** ({target.get('date')}) "
        f"[{target.get('tag')}] TSS={target.get('tss')}\n"
        f"Chargement des données..."
    )

    async with ctx.typing():
        try:
            streams = fetch_activity_streams(target["id"])
            if not streams:
                await ctx.send("❌ Impossible de charger les streams.")
                return

            intervals_data = fetch_activity_intervals(target["id"])

            path = plot_session(
                streams=streams,
                session_summary=target,
                intervals_data=intervals_data,
            )
        except Exception as e:
            log.exception("session plot failed")
            await ctx.send(f"❌ Erreur : {e}")
            return

    if path and Path(path).exists():
        await ctx.send(file=discord.File(str(path)))
    else:
        await ctx.send("❌ Échec de la génération du graphe.")


@bot.command(name="stats")
async def cmd_stats(ctx: commands.Context) -> None:
    """Résumé rapide de la forme actuelle."""
    result = _load_report_or_error()
    if isinstance(result, str):
        await ctx.send(result)
        return
    report = result

    cf = report.get("current_fitness", {})
    totals = report.get("totals_usable", {})
    period = report.get("period", {})

    if not cf:
        await ctx.send("❌ Pas assez de données pour calculer la forme.")
        return

    lines = [
        f"**📊 État actuel** (au {cf.get('as_of', '?')})",
        f"• CTL (forme) : **{cf.get('ctl', '?')}**",
        f"• ATL (fatigue) : **{cf.get('atl', '?')}**",
        f"• TSB (fraîcheur) : **{cf.get('tsb', '?')}**",
        "",
        f"Période analysée : {period.get('activities_usable', 0)} activités "
        f"({totals.get('total_hours', 0)}h, {totals.get('total_km', 0)}km)",
    ]
    weekly = report.get("recent_weekly_load", [])
    if weekly:
        lines.append("\n**Charge hebdo récente :**")
        for w in weekly:
            lines.append(f"• Semaine du {w['week_ending']}: {w['tss']:.0f} TSS")

    await ctx.send("\n".join(lines))


@bot.command(name="ask")
async def cmd_ask(ctx: commands.Context, *, question: str) -> None:
    """Pose une question libre au coach."""
    result = _load_report_or_error()
    if isinstance(result, str):
        await ctx.send(result)
        return

    metadata = {
        "discord_user": str(ctx.author),
        "discord_channel": str(ctx.channel),
    }

    async with ctx.typing():
        try:
            answer = ask_coach(
                question, result,
                source="discord",
                metadata=metadata,
            )
        except Exception as e:
            log.exception("ask_coach failed")
            await ctx.send(f"❌ Le coach n'a pas pu répondre : {e}")
            return

    await send_long(ctx, answer)

@bot.command(name="plan")
async def cmd_plan(ctx: commands.Context, days: int = 7) -> None:
    """Génère un plan d'entraînement."""
    if days < 1 or days > 21:
        await ctx.send("Merci de demander un plan entre 1 et 21 jours.")
        return

    result = _load_report_or_error()
    if isinstance(result, str):
        await ctx.send(result)
        return

    metadata = {
        "discord_user": str(ctx.author),
        "discord_channel": str(ctx.channel),
    }

    async with ctx.typing():
        try:
            plan_text = generate_plan(
                result,
                horizon_days=days,
                source="discord",
                metadata=metadata,
            )
        except Exception as e:
            log.exception("generate_plan failed")
            await ctx.send(f"❌ Erreur : {e}")
            return

    await send_long(ctx, plan_text)

@bot.command(name="refresh")
async def cmd_refresh(ctx: commands.Context, days: int = 180) -> None:
    """Re-fetch les activités depuis Intervals.icu."""
    await ctx.send(f"📡 Fetch Intervals.icu ({days} jours)...")
    async with ctx.typing():
        try:
            activities = refresh_cache(days=days)
        except Exception as e:
            log.exception("refresh failed")
            await ctx.send(f"❌ Fetch failed : {e}")
            return

    await ctx.send(f"✅ {len(activities)} activités en cache.")


@bot.command(name="fitness")
async def cmd_fitness(ctx: commands.Context) -> None:
    """Envoie le graphe CTL/ATL/TSB."""
    # On déclenche une analyse pour régénérer le graphe au frais
    result = _load_report_or_error()
    if isinstance(result, str):
        await ctx.send(result)
        return

    # Regénère les graphes (on réutilise la logique de cmd_analyze en léger)
    from ai_coach.analysis import build_daily_tss, compute_fitness, filter_usable
    from ai_coach.charts import plot_fitness

    activities = load_cached_activities()
    usable = filter_usable(activities)
    daily_tss = build_daily_tss(usable)
    fitness_df = compute_fitness(daily_tss)
    path = plot_fitness(fitness_df)

    if not path or not Path(path).exists():
        await ctx.send("❌ Impossible de générer le graphe.")
        return

    await ctx.send(file=discord.File(str(path)))

@bot.command(name="profile")
async def cmd_profile(ctx: commands.Context) -> None:
    """Affiche le profil athlète actuel."""
    from ai_coach.profile import format_profile_for_llm, load_profile, ProfileNotFoundError
    try:
        profile = load_profile()
    except ProfileNotFoundError as e:
        await ctx.send(str(e))
        return
    text = format_profile_for_llm(profile)
    await send_long(ctx, "```\n" + text + "\n```")

@bot.command(name="history")
async def cmd_history(ctx: commands.Context, n: int = 5) -> None:
    """Affiche les N derniers échanges en mémoire (défaut 5)."""
    from ai_coach.memory import count_exchanges, format_recent_for_display
    if n < 1 or n > 20:
        await ctx.send("Choisis entre 1 et 20.")
        return
    total = count_exchanges()
    text = format_recent_for_display(limit=n)
    header = f"🧠 **Mémoire** — {total} échange(s) au total, {min(n, total)} affiché(s) :\n"
    await send_long(ctx, header + "```\n" + text + "\n```")


@bot.command(name="forget")
async def cmd_forget(ctx: commands.Context, confirm: str = "") -> None:
    """
    Efface toute la mémoire conversationnelle.
    Usage: !forget yes (le mot 'yes' est obligatoire pour confirmer)
    """
    if confirm.lower() != "yes":
        await ctx.send(
            "⚠️ Cette commande efface tous les échanges en mémoire.\n"
            "Pour confirmer, retape : `!forget yes`"
        )
        return
    from ai_coach.memory import clear_all
    n = clear_all()
    await ctx.send(f"🧹 Mémoire effacée ({n} échanges supprimés).")


@bot.command(name="forget_last")
async def cmd_forget_last(ctx: commands.Context) -> None:
    """Supprime le dernier échange de la mémoire (utile si Claude a déraillé)."""
    from ai_coach.memory import remove_last
    if remove_last():
        await ctx.send("🧹 Dernier échange supprimé.")
    else:
        await ctx.send("(Rien à supprimer, mémoire vide.)")


@bot.command(name="set_ftp")
async def cmd_set_ftp(ctx: commands.Context, ftp: int) -> None:
    """Met à jour la FTP. Usage: !set_ftp 320"""
    from datetime import date as _date
    from ai_coach.profile import update_field
    if ftp < 100 or ftp > 600:
        await ctx.send("❌ FTP improbable, vérifie ta valeur (attendu : 100-600 W).")
        return
    update_field(["athlete", "ftp_watts"], ftp)
    update_field(["athlete", "ftp_updated"], _date.today().isoformat())
    await ctx.send(f"✅ FTP mise à jour : {ftp}W (test daté d'aujourd'hui)")


@bot.command(name="set_weight")
async def cmd_set_weight(ctx: commands.Context, weight: float) -> None:
    """Met à jour le poids actuel. Usage: !set_weight 63.5"""
    from ai_coach.profile import update_field
    if weight < 30 or weight > 200:
        await ctx.send("❌ Poids improbable, vérifie ta valeur.")
        return
    update_field(["athlete", "weight_kg"], weight)
    await ctx.send(f"✅ Poids mis à jour : {weight}kg")


@bot.command(name="enrich")
async def cmd_enrich(ctx: commands.Context, max_new: int = 10) -> None:
    """Enrichit les séances avec les détails Intervals.icu."""
    await ctx.send(f"🔬 Enrichissement en cours (max {max_new} nouvelles séances)...")
    async with ctx.typing():
        try:
            activities = load_cached_activities()
            from ai_coach.intervals import enrich_sessions
            sessions = enrich_sessions(activities, max_new=max_new)
        except Exception as e:
            log.exception("enrich failed")
            await ctx.send(f"❌ Erreur: {e}")
            return
    await ctx.send(f"✅ {len(sessions)} séances enrichies au total.")

@bot.command(name="add_note")
async def cmd_add_note(ctx: commands.Context, *, note: str) -> None:
    """
    Ajoute une note dans le profil (préférences évolutives, contexte ponctuel).
    Usage: !add_note Genou un peu chargé cette semaine, je vais lever le pied
    """
    from ai_coach.profile import load_profile, save_profile
    profile = load_profile()
    notes = profile.setdefault("running_notes", [])
    notes.append({
        "date": __import__("datetime").date.today().isoformat(),
        "note": note,
    })
    # Limite à 30 notes pour éviter la dérive
    profile["running_notes"] = notes[-30:]
    save_profile(profile)
    await ctx.send(f"✅ Note ajoutée ({len(profile['running_notes'])} notes en mémoire).")


# --- Entry point ---

def run_bot() -> None:
    """Démarre le bot en mode bloquant."""
    config = load_config(require_discord=True)
    log.info("Démarrage du bot Discord...")
    bot.run(config.discord_bot_token)