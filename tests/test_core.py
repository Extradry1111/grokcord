from datetime import datetime, timezone
from types import SimpleNamespace as NS

import pytest

from grokcord import formatting as fmt
from grokcord import prompts
from grokcord.grok import Grok, extract_sources, parse_verdict, user_content
from grokcord.store import Store


# ── grok.py ─────────────────────────────────────────────────
def test_parse_verdict_variants():
    assert parse_verdict("VERDICT: FALSE\n- nope")[0] == "FALSE"
    assert parse_verdict("**VERDICT:** MOSTLY TRUE\n- close") == ("MOSTLY TRUE", "- close")
    assert parse_verdict("Verdict missing entirely") == ("UNVERIFIED", "Verdict missing entirely")
    assert parse_verdict("VERDICT: BANANAS\nx")[0] == "UNVERIFIED"


def test_extract_sources_dedupes_annotations_and_citations():
    ann = NS(type="url_citation", url="https://a.com/1", title="A")
    response = NS(
        output=[NS(content=[NS(annotations=[ann, ann])]), NS(content=None)],
        citations=["https://a.com/1", "https://x.com/user/status/2"],
    )
    assert extract_sources(response) == [("https://a.com/1", "A"), ("https://x.com/user/status/2", "")]


def test_user_content_adds_images():
    content = user_content("hi", ["https://cdn/img.png"])
    assert content == [{"type": "input_text", "text": "hi"},
                       {"type": "input_image", "image_url": "https://cdn/img.png"}]


class FakeResponses:
    def __init__(self, text):
        self.text = text
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return NS(output_text=self.text, output=[], citations=["https://example.com"],
                  usage=NS(total_tokens=321))


def fake_grok(text):
    responses = FakeResponses(text)
    client = NS(responses=responses, images=None)
    return Grok("k", "grok-test", "img-test", "https://api", client=client), responses


async def test_fact_check_uses_search_tools_and_parses():
    grok, calls = fake_grok("VERDICT: MISLEADING\n- half right")
    result = await grok.fact_check("BTC hit 1M today", "alice", ["https://img"])
    assert result.verdict == "MISLEADING" and result.text == "- half right"
    assert result.sources == [("https://example.com", "")] and result.tokens == 321
    sent = calls.calls[0]
    assert {t["type"] for t in sent["tools"]} == {"web_search", "x_search"}
    assert sent["input"][0]["content"][1]["type"] == "input_image"


async def test_pulse_sets_from_date():
    grok, calls = fake_grok("**Mood:** hype")
    await grok.pulse("grokcord", 48, now=datetime(2026, 10, 8, 12, tzinfo=timezone.utc))
    assert calls.calls[0]["tools"] == [{"type": "x_search", "from_date": "2026-10-06"}]


async def test_chat_without_search_sends_no_tools():
    grok, calls = fake_grok("hey")
    answer = await grok.chat("roast", [{"role": "user", "content": user_content("hi")}])
    assert answer.text == "hey"
    assert "tools" not in calls.calls[0]
    assert "savage" in calls.calls[0]["instructions"]


# ── prompts.py ──────────────────────────────────────────────
def test_custom_persona_and_fallback():
    assert prompts.persona_prompt("custom:Talk like a pirate") == "Talk like a pirate"
    assert prompts.persona_prompt("does-not-exist") == prompts.PERSONAS["helper"][1]


# ── formatting.py ───────────────────────────────────────────
def test_split_text_respects_limit_and_keeps_words():
    text = ("word " * 900).strip()
    chunks = fmt.split_text(text, 2000)
    assert all(len(c) <= 2000 for c in chunks)
    assert " ".join(chunks).split() == text.split()


def test_split_text_hard_cuts_unbroken_text():
    chunks = fmt.split_text("x" * 4500, 2000)
    assert [len(c) for c in chunks] == [2000, 2000, 500]


def test_sources_line_and_domain():
    line = fmt.sources_line([("https://www.reuters.com/a", ""), ("https://x.com/b", "")])
    assert line == "**Sources:** [1. reuters.com](<https://www.reuters.com/a>) · [2. x.com](<https://x.com/b>)"


def test_verdict_embed_color():
    embed = fmt.verdict_embeds("FALSE", "- wrong", [], "https://discord.com/x")[0]
    assert embed.title == "❌  FALSE" and embed.color.value == fmt.VERDICT_STYLE["FALSE"][0]


def test_clamp_transcript_keeps_latest():
    lines = [f"user{i}: " + "y" * 50 for i in range(100)]
    out = fmt.clamp_transcript(lines, max_chars=600)
    assert out.splitlines()[-1].startswith("user99") and len(out) <= 600


# ── store.py ────────────────────────────────────────────────
@pytest.fixture
async def store(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    await s.open()
    yield s
    await s.close()


async def test_persona_channel_overrides_server(store):
    assert await store.get_persona(1, 10, "helper") == "helper"
    await store.set_persona(1, 0, "analyst")
    await store.set_persona(1, 10, "roast")
    assert await store.get_persona(1, 10, "helper") == "roast"
    assert await store.get_persona(1, 11, "helper") == "analyst"
    await store.clear_persona(1, 10)
    assert await store.get_persona(1, 10, "helper") == "analyst"


async def test_usage_and_limits(store):
    await store.add_usage(1, 7, 1, 100, day="2026-10-08")
    await store.add_usage(1, 7, 5, 0, day="2026-10-08")
    await store.add_usage(1, 8, 2, 50, day="2026-10-08")
    assert await store.usage(1, 7, day="2026-10-08") == (6, 100, 8)
    assert await store.usage(1, 7, day="2026-10-09") == (0, 0, 0)
    assert await store.get_limits(1, 40, 600) == (40, 600)
    await store.set_limits(1, 10, None)
    await store.set_limits(1, None, 99)
    assert await store.get_limits(1, 40, 600) == (10, 99)


async def test_feature_toggle(store):
    assert await store.is_enabled(1, "imagine")
    await store.set_enabled(1, "imagine", False)
    assert not await store.is_enabled(1, "imagine")
    assert await store.disabled_features(1) == ["imagine"]
    await store.set_enabled(1, "imagine", True)
    assert await store.is_enabled(1, "imagine")
