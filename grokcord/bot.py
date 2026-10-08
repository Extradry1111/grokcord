"""The Discord side: slash commands, right-click apps, and @mention chat."""

from __future__ import annotations

import io
import logging
from typing import Any

import aiohttp
import discord
import openai
from discord import app_commands

from . import formatting as fmt
from . import prompts
from .config import Config
from .grok import Grok, user_content
from .store import Store

log = logging.getLogger("grokcord")

FEATURES = {
    "chat": "@mention chat and replies",
    "ask": "/ask",
    "factcheck": "Fact-check (right-click)",
    "explain": "Explain (right-click)",
    "translate": "Translate (right-click)",
    "tldr": "/tldr channel summaries",
    "pulse": "/pulse live X search",
    "imagine": "/imagine images",
}
CHAT_CONTEXT = 12      # messages of channel context for @mention chat
THREAD_CONTEXT = 40    # messages of memory inside a Grok thread
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")


def image_urls(message: discord.Message) -> list[str]:
    urls = [a.url for a in message.attachments if (a.content_type or "").split(";")[0] in IMAGE_TYPES]
    urls += [e.image.url for e in message.embeds if e.image and e.image.url]
    return urls[:4]


def strip_mention(text: str, user_id: int) -> str:
    return text.replace(f"<@{user_id}>", "").replace(f"<@!{user_id}>", "").strip()


def friendly_error(exc: Exception) -> str:
    if isinstance(exc, openai.AuthenticationError):
        return "🔑 The xAI API key was rejected. The server owner needs to check `XAI_API_KEY`."
    if isinstance(exc, openai.RateLimitError):
        return "🐢 Grok is rate-limited or out of credits right now. Try again in a minute."
    if isinstance(exc, openai.BadRequestError):
        return "🙅 Grok refused or couldn't process that request. Try rephrasing it."
    if isinstance(exc, (openai.APITimeoutError, openai.APIConnectionError)):
        return "📡 Couldn't reach Grok. Try again in a moment."
    return "💥 Something went wrong talking to Grok. It's been logged."


class Grokcord(discord.Client):
    def __init__(self, config: Config, grok: Grok | None = None, store: Store | None = None) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.config = config
        self.grok = grok or Grok(config.xai_api_key, config.model, config.image_model, config.base_url)
        self.store = store or Store(config.database_path)
        self.tree = app_commands.CommandTree(self)
        register_commands(self)

    async def setup_hook(self) -> None:
        await self.store.open()
        if self.config.dev_guild_id:
            guild = discord.Object(id=self.config.dev_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Synced commands to dev guild %s", self.config.dev_guild_id)
        else:
            await self.tree.sync()
            log.info("Synced global commands (can take a while to appear)")

    async def close(self) -> None:
        await self.store.close()
        await super().close()

    async def on_ready(self) -> None:
        log.info("Logged in as %s in %d servers", self.user, len(self.guilds))
        await self.change_presence(activity=discord.Activity(
            type=discord.ActivityType.listening, name="@mentions · /ask · right-click → Apps"))

    # ── quota gate ───────────────────────────────────────────
    async def gate(self, guild_id: int, user_id: int, feature: str, units: int) -> str | None:
        """Return an error message if the call is not allowed, else None."""
        if guild_id and not await self.store.is_enabled(guild_id, feature):
            return f"🚫 **{FEATURES[feature]}** is turned off in this server."
        user_limit, guild_limit = await self.store.get_limits(
            guild_id, self.config.daily_user_limit, self.config.daily_guild_limit)
        used, _tokens, guild_used = await self.store.usage(guild_id, user_id)
        if used + units > user_limit:
            return f"⏳ You've used your {user_limit} Grok units for today. Resets at 00:00 UTC."
        if guild_id and guild_used + units > guild_limit:
            return "⏳ This server hit its daily Grok budget. Resets at 00:00 UTC."
        return None

    async def footer(self, guild_id: int, user_id: int) -> str:
        user_limit, _ = await self.store.get_limits(
            guild_id, self.config.daily_user_limit, self.config.daily_guild_limit)
        used, _tokens, _guild = await self.store.usage(guild_id, user_id)
        return f"grokcord · {max(user_limit - used, 0)} units left today"

    async def persona(self, guild_id: int, channel_id: int) -> str:
        if not guild_id:
            return self.config.default_persona
        return await self.store.get_persona(guild_id, channel_id, self.config.default_persona)

    # ── @mention chat ────────────────────────────────────────
    def wants_reply(self, message: discord.Message) -> bool:
        if message.author.bot or not self.user:
            return False
        if isinstance(message.channel, discord.DMChannel):
            return True
        if isinstance(message.channel, discord.Thread) and message.channel.owner_id == self.user.id:
            return True  # threads opened with /chat
        return self.user in message.mentions and not message.mention_everyone

    async def build_history(self, message: discord.Message) -> list[dict[str, Any]]:
        limit = THREAD_CONTEXT if isinstance(message.channel, discord.Thread) else CHAT_CONTEXT
        earlier = [m async for m in message.channel.history(limit=limit, before=message)]
        history: list[dict[str, Any]] = []
        for m in reversed(earlier):
            if not m.content and not m.embeds:
                continue
            if m.author.id == self.user.id:
                text = m.content or "\n".join(e.description or "" for e in m.embeds)
                history.append({"role": "assistant", "content": text})
            else:
                text = fmt.transcript_line(m.author.display_name, strip_mention(m.content, self.user.id),
                                           len(m.attachments))
                history.append({"role": "user", "content": user_content(text)})

        prompt = strip_mention(message.content, self.user.id) or "(no text, see the image)"
        images = image_urls(message)
        ref = message.reference.resolved if message.reference else None
        if isinstance(ref, discord.Message):
            prompt = (f"[Replying to {ref.author.display_name}: \"{ref.content[:1500]}\"]\n"
                      f"{message.author.display_name}: {prompt}")
            images = image_urls(ref) + images
        else:
            prompt = f"{message.author.display_name}: {prompt}"
        history.append({"role": "user", "content": user_content(prompt, images[:4])})
        return history

    async def on_message(self, message: discord.Message) -> None:
        if not self.wants_reply(message):
            return
        gid = message.guild.id if message.guild else 0
        error = await self.gate(gid, message.author.id, "chat", 1)
        if error:
            await message.reply(error, mention_author=False, delete_after=20)
            return
        async with message.channel.typing():
            try:
                history = await self.build_history(message)
                answer = await self.grok.chat(await self.persona(gid, message.channel.id), history, search=True)
            except Exception as exc:  # noqa: BLE001 - surface every failure to the user
                log.exception("chat failed")
                await message.reply(friendly_error(exc), mention_author=False)
                return
        await self.store.add_usage(gid, message.author.id, 1, answer.tokens)
        body = answer.text
        if answer.sources:
            body = f"{body}\n\n-# {fmt.sources_line(answer.sources)}"
        chunks = fmt.split_text(body)
        await message.reply(chunks[0], mention_author=False, suppress_embeds=True)
        for chunk in chunks[1:]:
            await message.channel.send(chunk, suppress_embeds=True)


# ── helpers for interactions ────────────────────────────────
def ids(interaction: discord.Interaction) -> tuple[int, int, int]:
    return (interaction.guild_id or 0, interaction.channel_id or 0, interaction.user.id)


async def run_interaction(bot: Grokcord, interaction: discord.Interaction, feature: str, units: int,
                          work, *, ephemeral: bool = False) -> None:
    """Gate, defer, run ``work()`` -> (embeds, files, tokens), charge, and reply."""
    gid, _cid, uid = ids(interaction)
    error = await bot.gate(gid, uid, feature, units)
    if error:
        await interaction.response.send_message(error, ephemeral=True)
        return
    await interaction.response.defer(thinking=True, ephemeral=ephemeral)
    try:
        embeds, files, tokens = await work()
    except Exception as exc:  # noqa: BLE001
        log.exception("%s failed", feature)
        await interaction.followup.send(friendly_error(exc), ephemeral=True)
        return
    await bot.store.add_usage(gid, uid, units, tokens)
    footer = await bot.footer(gid, uid)
    if embeds:
        embeds[-1].set_footer(text=footer)
    await interaction.followup.send(embeds=embeds[:10], files=files or discord.utils.MISSING,
                                    ephemeral=ephemeral)


def register_commands(bot: Grokcord) -> None:
    tree = bot.tree

    # ── right-click → Apps ───────────────────────────────────
    @tree.context_menu(name="Fact-check with Grok")
    async def fact_check(interaction: discord.Interaction, message: discord.Message) -> None:
        if not message.content and not image_urls(message):
            await interaction.response.send_message("Nothing to check in that message.", ephemeral=True)
            return

        async def work():
            result = await bot.grok.fact_check(message.content, message.author.display_name,
                                               image_urls(message))
            return fmt.verdict_embeds(result.verdict, result.text, result.sources, message.jump_url), None, \
                result.tokens

        await run_interaction(bot, interaction, "factcheck", 1, work)

    @tree.context_menu(name="Explain with Grok")
    async def explain(interaction: discord.Interaction, message: discord.Message) -> None:
        async def work():
            result = await bot.grok.explain(message.content or "(image only)", image_urls(message))
            return fmt.answer_embeds(result.text, result.sources, title="🧠 Explained"), None, result.tokens

        await run_interaction(bot, interaction, "explain", 1, work, ephemeral=True)

    @tree.context_menu(name="Translate with Grok")
    async def translate(interaction: discord.Interaction, message: discord.Message) -> None:
        if not message.content:
            await interaction.response.send_message("That message has no text to translate.", ephemeral=True)
            return
        language = interaction.locale.name.replace("_", " ").title()

        async def work():
            result = await bot.grok.translate(message.content, language)
            return fmt.answer_embeds(result.text, [], title=f"🌍 {language}"), None, result.tokens

        await run_interaction(bot, interaction, "translate", 1, work, ephemeral=True)

    # ── slash commands ───────────────────────────────────────
    @tree.command(description="Ask Grok anything. It can search the web and X live.")
    @app_commands.describe(question="What do you want to know?", image="Optional image for Grok to look at",
                           search="Search the web and X (default: on)", private="Only you see the answer")
    async def ask(interaction: discord.Interaction, question: str, image: discord.Attachment | None = None,
                  search: bool = True, private: bool = False) -> None:
        gid, cid, _uid = ids(interaction)

        async def work():
            urls = [image.url] if image and (image.content_type or "").split(";")[0] in IMAGE_TYPES else []
            text = f"{interaction.user.display_name}: {question}"
            result = await bot.grok.chat(await bot.persona(gid, cid),
                                         [{"role": "user", "content": user_content(text, urls)}], search=search)
            return fmt.answer_embeds(result.text, result.sources, title=question[:250]), None, result.tokens

        await run_interaction(bot, interaction, "ask", 1, work, ephemeral=private)

    @tree.command(description="What did I miss? Summarise the recent messages in this channel.")
    @app_commands.describe(messages="How many recent messages to read (default 150)",
                           private="Only you see the summary (default: on)")
    async def tldr(interaction: discord.Interaction, messages: app_commands.Range[int, 20, 500] = 150,
                   private: bool = True) -> None:
        channel = interaction.channel
        if channel is None or not hasattr(channel, "history"):
            await interaction.response.send_message("I can't read this channel.", ephemeral=True)
            return

        async def work():
            lines = [fmt.transcript_line(m.author.display_name, m.content, len(m.attachments))
                     async for m in channel.history(limit=messages, oldest_first=False)
                     if not m.author.bot and (m.content or m.attachments)]
            lines.reverse()
            if len(lines) < 3:
                return [discord.Embed(description="Not enough conversation here to summarise yet.",
                                      color=fmt.BRAND)], None, 0
            result = await bot.grok.tldr(fmt.clamp_transcript(lines), getattr(channel, "name", "chat"))
            title = f"📜 TL;DR of the last {len(lines)} messages"
            return fmt.answer_embeds(result.text, [], title=title), None, result.tokens

        await run_interaction(bot, interaction, "tldr", 1, work, ephemeral=private)

    @tree.command(description="What is X saying about something right now? Live search with sources.")
    @app_commands.describe(topic="A coin, person, game, launch, anything", hours="How far back to look")
    @app_commands.choices(hours=[app_commands.Choice(name=n, value=v) for n, v in
                                 (("Last hour", 1), ("Last 6 hours", 6), ("Last 24 hours", 24),
                                  ("Last 3 days", 72), ("Last week", 168))])
    async def pulse(interaction: discord.Interaction, topic: str,
                    hours: app_commands.Choice[int] | None = None) -> None:
        window = hours.value if hours else 24

        async def work():
            result = await bot.grok.pulse(topic, window)
            return fmt.answer_embeds(result.text, result.sources, title=f"📡 Pulse: {topic[:200]}"), None, \
                result.tokens

        await run_interaction(bot, interaction, "pulse", 1, work)

    @tree.command(description="Generate an image with Grok Imagine.")
    @app_commands.describe(prompt="Describe the image")
    async def imagine(interaction: discord.Interaction, prompt: str) -> None:
        async def work():
            image = await bot.grok.imagine(prompt)
            data = image.data
            if data is None and image.url:
                async with aiohttp.ClientSession() as session, session.get(image.url) as resp:
                    resp.raise_for_status()
                    data = await resp.read()
            if data is None:
                raise RuntimeError("image API returned neither bytes nor a URL")
            file = discord.File(io.BytesIO(data), filename="grokcord.png")
            embed = discord.Embed(description=f"**Prompt:** {prompt[:1000]}", color=fmt.BRAND)
            embed.set_image(url="attachment://grokcord.png")
            return [embed], [file], 0

        await run_interaction(bot, interaction, "imagine", bot.config.image_cost, work)

    @tree.command(description="Open a thread where Grok replies to every message, no @mention needed.")
    @app_commands.describe(topic="What the thread is about")
    @app_commands.guild_only()
    async def chat(interaction: discord.Interaction, topic: app_commands.Range[str, 1, 90]) -> None:
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("Use this in a normal text channel.", ephemeral=True)
            return
        error = await bot.gate(interaction.guild_id, interaction.user.id, "chat", 0)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await interaction.response.send_message(f"🧵 Opening a Grok thread: **{topic}**")
        starter = await interaction.original_response()
        thread = await starter.create_thread(name=f"grok · {topic}"[:100], auto_archive_duration=1440)
        await thread.send(f"Hey {interaction.user.mention}, I'm listening. Ask away, no @mention needed "
                          "in here. I remember this whole thread.",
                          allowed_mentions=discord.AllowedMentions(users=[interaction.user]))

    @tree.command(description="See how many Grok units you have left today.")
    async def usage(interaction: discord.Interaction) -> None:
        gid, _cid, uid = ids(interaction)
        user_limit, guild_limit = await bot.store.get_limits(gid, bot.config.daily_user_limit,
                                                             bot.config.daily_guild_limit)
        used, tokens, guild_used = await bot.store.usage(gid, uid)
        lines = [f"**You:** {used}/{user_limit} units today ({tokens:,} tokens)"]
        if gid:
            lines.append(f"**This server:** {guild_used}/{guild_limit} units today")
        lines.append(f"-# A text answer costs 1 unit, an image costs {bot.config.image_cost}. "
                     "Resets at 00:00 UTC.")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @tree.command(name="help", description="Everything grokcord can do.")
    async def help_(interaction: discord.Interaction) -> None:
        embed = discord.Embed(title="grokcord", color=fmt.BRAND, description=(
            "**Talk to Grok:** @mention me, or reply to any message with `@grokcord is this true?`\n"
            "**Right-click a message → Apps:** Fact-check · Explain · Translate\n"
            "**/ask** anything, with live web + X search and image input\n"
            "**/tldr** catch up on a busy channel\n"
            "**/pulse** what X is saying about a topic right now\n"
            "**/imagine** generate an image\n"
            "**/chat** open a thread where Grok answers everything\n"
            "**/usage** your daily units\n"
            "**/grokcord** server settings (personas, limits, features) for admins"))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── admin group ──────────────────────────────────────────
    admin = app_commands.Group(name="grokcord", description="Server settings for grokcord",
                               default_permissions=discord.Permissions(manage_guild=True), guild_only=True)

    @admin.command(name="persona", description="Set Grok's personality for this server or one channel.")
    @app_commands.describe(style="A built-in personality", custom="Or write your own (overrides style)",
                           scope="Whole server or just this channel")
    @app_commands.choices(
        style=[app_commands.Choice(name=label[:100], value=key) for key, (label, _p) in prompts.PERSONAS.items()],
        scope=[app_commands.Choice(name="Whole server", value="server"),
               app_commands.Choice(name="This channel only", value="channel")])
    async def persona_cmd(interaction: discord.Interaction, style: app_commands.Choice[str] | None = None,
                          custom: app_commands.Range[str, 10, 1500] | None = None,
                          scope: app_commands.Choice[str] | None = None) -> None:
        gid, cid, _uid = ids(interaction)
        channel_id = cid if scope and scope.value == "channel" else 0
        where = "this channel" if channel_id else "the whole server"
        if custom:
            value, name = prompts.CUSTOM_PREFIX + custom, "your custom persona"
        elif style:
            value, name = style.value, f"**{style.name}**"
        else:
            current = await bot.store.get_persona(gid, cid, bot.config.default_persona)
            label = "custom" if current.startswith(prompts.CUSTOM_PREFIX) else prompts.PERSONAS.get(
                current, ("?",))[0]
            await interaction.response.send_message(f"Current persona here: **{label}**", ephemeral=True)
            return
        await bot.store.set_persona(gid, channel_id, value)
        await interaction.response.send_message(f"🎭 Grok now uses {name} in {where}.", ephemeral=True)

    @admin.command(name="reset-persona", description="Go back to the default personality.")
    @app_commands.choices(scope=[app_commands.Choice(name="Whole server", value="server"),
                                 app_commands.Choice(name="This channel only", value="channel")])
    async def reset_persona(interaction: discord.Interaction,
                            scope: app_commands.Choice[str] | None = None) -> None:
        gid, cid, _uid = ids(interaction)
        await bot.store.clear_persona(gid, cid if scope and scope.value == "channel" else 0)
        await interaction.response.send_message("🎭 Persona reset.", ephemeral=True)

    @admin.command(name="limits", description="Set daily spend caps (in units) for this server.")
    @app_commands.describe(per_user="Units each member can use per day", per_server="Units the whole server can use per day")
    async def limits(interaction: discord.Interaction, per_user: app_commands.Range[int, 0, 10_000] | None = None,
                     per_server: app_commands.Range[int, 0, 1_000_000] | None = None) -> None:
        gid, _cid, _uid = ids(interaction)
        if per_user is not None or per_server is not None:
            await bot.store.set_limits(gid, per_user, per_server)
        user_limit, guild_limit = await bot.store.get_limits(gid, bot.config.daily_user_limit,
                                                             bot.config.daily_guild_limit)
        await interaction.response.send_message(
            f"💸 Daily caps: **{user_limit}** units per member, **{guild_limit}** for the server.", ephemeral=True)

    @admin.command(name="feature", description="Turn a grokcord feature on or off in this server.")
    @app_commands.choices(feature=[app_commands.Choice(name=label, value=key) for key, label in FEATURES.items()])
    async def feature(interaction: discord.Interaction, feature: app_commands.Choice[str], enabled: bool) -> None:
        gid, _cid, _uid = ids(interaction)
        await bot.store.set_enabled(gid, feature.value, enabled)
        state = "on ✅" if enabled else "off 🚫"
        await interaction.response.send_message(f"**{feature.name}** is now {state}.", ephemeral=True)

    @admin.command(name="status", description="Show grokcord's settings for this server.")
    async def status(interaction: discord.Interaction) -> None:
        gid, cid, _uid = ids(interaction)
        user_limit, guild_limit = await bot.store.get_limits(gid, bot.config.daily_user_limit,
                                                             bot.config.daily_guild_limit)
        off = await bot.store.disabled_features(gid)
        current = await bot.store.get_persona(gid, cid, bot.config.default_persona)
        label = "custom" if current.startswith(prompts.CUSTOM_PREFIX) else prompts.PERSONAS.get(current, ("?",))[0]
        embed = discord.Embed(title="grokcord status", color=fmt.BRAND)
        embed.add_field(name="Model", value=f"`{bot.config.model}`", inline=True)
        embed.add_field(name="Persona here", value=label, inline=True)
        embed.add_field(name="Daily caps", value=f"{user_limit}/member · {guild_limit}/server", inline=False)
        embed.add_field(name="Turned off", value=", ".join(FEATURES[f] for f in off if f in FEATURES) or "Nothing",
                        inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    tree.add_command(admin)
