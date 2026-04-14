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
        "`!ask <question>` — pose une question au coach\n"
        "`!plan [jours]` — plan d'entraînement (défaut 7)\n"
        "`!stats` — résumé rapide de ta forme\n"
        "`!refresh` — re-fetch Intervals.icu (fais-le après une sortie)\n"
        "`!fitness` — envoie le graphe CTL/ATL/TSB\n"
        "`!help_coach` — cette aide\n"
    )
    await ctx.send(text)


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

    async with ctx.typing():
        try:
            answer = ask_coach(question, result)
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

    async with ctx.typing():
        try:
            plan_text = generate_plan(result, horizon_days=days)
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


# --- Entry point ---

def run_bot() -> None:
    """Démarre le bot en mode bloquant."""
    config = load_config(require_discord=True)
    log.info("Démarrage du bot Discord...")
    bot.run(config.discord_bot_token)