"""Turn Grok answers into Discord messages: splitting, embeds, sources, transcripts."""

from __future__ import annotations

from urllib.parse import urlparse

import discord

BRAND = 0xC8FF2E  # acid lime
VERDICT_STYLE = {
    "TRUE": (0x2ECC71, "✅"),
    "MOSTLY TRUE": (0x9BE15D, "🟢"),
    "MISLEADING": (0xF5A623, "⚠️"),
    "FALSE": (0xFF4D6D, "❌"),
    "UNVERIFIED": (0x8E9AAF, "❔"),
}
EMBED_LIMIT = 4000
MESSAGE_LIMIT = 2000


def split_text(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    """Split on paragraph, then line, then word boundaries so chunks fit Discord's limit."""
    chunks: list[str] = []
    rest = text.strip()
    while len(rest) > limit:
        cut = -1
        for sep in ("\n\n", "\n", " "):
            cut = rest.rfind(sep, 0, limit)
            if cut > limit // 3:
                break
        if cut <= 0:
            cut = limit
        chunks.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest:
        chunks.append(rest)
    return chunks or [""]


def domain(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host or url


def sources_line(sources: list[tuple[str, str]]) -> str:
    if not sources:
        return ""
    links = [f"[{i}. {domain(url)}](<{url}>)" for i, (url, _title) in enumerate(sources, 1)]
    return "**Sources:** " + " · ".join(links)


def answer_embeds(text: str, sources: list[tuple[str, str]], *, title: str | None = None,
                  color: int = BRAND, footer: str | None = None) -> list[discord.Embed]:
    body = text
    src = sources_line(sources)
    if src:
        body = f"{body}\n\n{src}"
    parts = split_text(body, EMBED_LIMIT)
    embeds = []
    for i, part in enumerate(parts[:10]):
        embed = discord.Embed(description=part, color=color)
        if i == 0 and title:
            embed.title = title[:256]
        embeds.append(embed)
    if footer:
        embeds[-1].set_footer(text=footer)
    return embeds


def verdict_embeds(verdict: str, text: str, sources: list[tuple[str, str]], jump_url: str,
                   footer: str | None = None) -> list[discord.Embed]:
    color, icon = VERDICT_STYLE.get(verdict, VERDICT_STYLE["UNVERIFIED"])
    embeds = answer_embeds(f"{text}\n\n[↗ Original message]({jump_url})", sources,
                           title=f"{icon}  {verdict}", color=color, footer=footer)
    return embeds


def transcript_line(author: str, content: str, attachments: int = 0, limit: int = 400) -> str:
    content = " ".join(content.split())
    if len(content) > limit:
        content = content[: limit - 1] + "…"
    if attachments:
        content = f"{content} [+{attachments} attachment{'s' if attachments > 1 else ''}]".strip()
    return f"{author}: {content}"


def clamp_transcript(lines: list[str], max_chars: int = 60_000) -> str:
    """Keep the most recent lines that fit in ``max_chars`` (lines are oldest first)."""
    kept: list[str] = []
    total = 0
    for line in reversed(lines):
        total += len(line) + 1
        if total > max_chars:
            break
        kept.append(line)
    return "\n".join(reversed(kept))
