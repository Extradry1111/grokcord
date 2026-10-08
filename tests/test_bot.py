from types import SimpleNamespace as NS

import pytest

from grokcord.bot import Grokcord, image_urls, strip_mention
from grokcord.config import Config
from grokcord.store import Store


@pytest.fixture
async def bot(tmp_path):
    config = Config(discord_token="t", xai_api_key="k", daily_user_limit=3, daily_guild_limit=5, image_cost=2)
    store = Store(str(tmp_path / "b.db"))
    await store.open()
    b = Grokcord(config, grok=NS(), store=store)
    yield b
    await store.close()


def test_registers_every_command(bot):
    names = {c.name for c in bot.tree._get_all_commands()}
    assert {"ask", "tldr", "pulse", "imagine", "usage", "help", "grokcord",
            "chat", "Fact-check with Grok", "Explain with Grok", "Translate with Grok"} <= names


async def test_gate_user_and_server_caps(bot):
    assert await bot.gate(1, 7, "ask", 1) is None
    await bot.store.add_usage(1, 7, 3)
    assert "your 3 Grok units" in await bot.gate(1, 7, "ask", 1)
    await bot.store.add_usage(1, 8, 2)
    assert "server hit its daily" in await bot.gate(1, 9, "ask", 1)


async def test_gate_disabled_feature(bot):
    await bot.store.set_enabled(1, "imagine", False)
    assert "turned off" in await bot.gate(1, 7, "imagine", 2)


async def test_gate_dm_ignores_server_cap(bot):
    await bot.store.add_usage(0, 1, 2)
    assert await bot.gate(0, 2, "chat", 1) is None


def test_strip_mention():
    assert strip_mention("<@42> is this true?", 42) == "is this true?"
    assert strip_mention("hey <@!42>", 42) == "hey"


def test_image_urls_filters_types():
    msg = NS(attachments=[NS(url="a.png", content_type="image/png"), NS(url="b.zip", content_type="application/zip"),
                          NS(url="c.jpg", content_type="image/jpeg; charset=x")],
             embeds=[NS(image=NS(url="d.webp")), NS(image=None)])
    assert image_urls(msg) == ["a.png", "c.jpg", "d.webp"]


class FakeResponse:
    async def send_message(self, *a, **k):
        self.sent = (a, k)

    async def defer(self, **k):
        pass


class FakeFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, *a, **k):
        self.sent.append(k)


def fake_interaction():
    return NS(guild_id=1, channel_id=2, user=NS(id=7), response=FakeResponse(), followup=FakeFollowup())


async def test_run_interaction_charges_only_real_calls(bot):
    import discord
    from grokcord.bot import run_interaction

    async def no_call():
        return [discord.Embed(description="nothing")], None, None

    async def real_call():
        return [discord.Embed(description="answer")], None, 42

    await run_interaction(bot, fake_interaction(), "tldr", 1, no_call)
    assert await bot.store.usage(1, 7) == (0, 0, 0)
    inter = fake_interaction()
    await run_interaction(bot, inter, "ask", 1, real_call)
    assert await bot.store.usage(1, 7) == (1, 42, 1)
    assert inter.followup.sent[0]["embeds"][0].footer.text == "grokcord · 2 units left today"
