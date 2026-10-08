"""Thin async wrapper around the xAI API (OpenAI-compatible Responses + Images endpoints)."""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from openai import AsyncOpenAI

from . import prompts

VERDICTS = ("MOSTLY TRUE", "TRUE", "MISLEADING", "FALSE", "UNVERIFIED")
_VERDICT_RE = re.compile(r"^\s*\**\s*VERDICT\s*:?\s*\**\s*([A-Z ]+?)\s*\**\s*$", re.M)


@dataclass
class Answer:
    text: str
    sources: list[tuple[str, str]] = field(default_factory=list)  # (url, title)
    tokens: int = 0


@dataclass
class FactCheck(Answer):
    verdict: str = "UNVERIFIED"


@dataclass
class Image:
    data: bytes | None = None
    url: str | None = None


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    value = getattr(obj, name, default)
    if value is default:
        extra = getattr(obj, "model_extra", None) or {}
        value = extra.get(name, default)
    return value


def extract_sources(response: Any, limit: int = 6) -> list[tuple[str, str]]:
    """Collect cited URLs from a Responses API result.

    xAI returns both inline ``url_citation`` annotations and a top-level ``citations`` list;
    we read both and keep the first ``limit`` unique URLs.
    """
    seen: dict[str, str] = {}
    for item in _get(response, "output", None) or []:
        for part in _get(item, "content", None) or []:
            for ann in _get(part, "annotations", None) or []:
                if _get(ann, "type") == "url_citation" and _get(ann, "url"):
                    seen.setdefault(_get(ann, "url"), _get(ann, "title") or "")
    for cite in _get(response, "citations", None) or []:
        url = cite if isinstance(cite, str) else _get(cite, "url")
        if url:
            seen.setdefault(url, "" if isinstance(cite, str) else (_get(cite, "title") or ""))
    return list(seen.items())[:limit]


def _tokens(response: Any) -> int:
    usage = _get(response, "usage", None)
    return int(_get(usage, "total_tokens", 0) or 0) if usage else 0


def parse_verdict(text: str) -> tuple[str, str]:
    """Split ``VERDICT: X`` off the top of a fact-check. Returns (verdict, body)."""
    match = _VERDICT_RE.search(text)
    if not match:
        return "UNVERIFIED", text.strip()
    raw = " ".join(match.group(1).split())
    verdict = next((v for v in VERDICTS if raw.startswith(v)), "UNVERIFIED")
    body = (text[: match.start()] + text[match.end():]).strip()
    return verdict, body


def user_content(text: str, image_urls: Iterable[str] = ()) -> list[dict[str, str]]:
    content: list[dict[str, str]] = [{"type": "input_text", "text": text}]
    content += [{"type": "input_image", "image_url": url} for url in image_urls]
    return content


class Grok:
    def __init__(self, api_key: str, model: str, image_model: str, base_url: str,
                 client: AsyncOpenAI | None = None) -> None:
        self.model = model
        self.image_model = image_model
        self.client = client or AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=120)

    async def _respond(self, instructions: str, messages: list[dict[str, Any]],
                       tools: list[dict[str, Any]] | None = None) -> Answer:
        kwargs: dict[str, Any] = {"model": self.model, "instructions": instructions, "input": messages}
        if tools:
            kwargs["tools"] = tools
        response = await self.client.responses.create(**kwargs)
        text = (_get(response, "output_text", "") or "").strip() or "_(Grok returned an empty answer.)_"
        return Answer(text=text, sources=extract_sources(response), tokens=_tokens(response))

    async def chat(self, persona: str, history: list[dict[str, Any]], *, search: bool = False) -> Answer:
        """Conversational answer. ``history`` is a list of Responses-API messages, oldest first."""
        tools = [{"type": "web_search"}, {"type": "x_search"}] if search else None
        return await self._respond(prompts.system_prompt(persona), history, tools)

    async def fact_check(self, message: str, author: str, image_urls: Iterable[str] = ()) -> FactCheck:
        answer = await self._respond(
            prompts.FACT_CHECK,
            [{"role": "user", "content": user_content(f"Message by {author}:\n\n{message}", image_urls)}],
            [{"type": "web_search"}, {"type": "x_search"}],
        )
        verdict, body = parse_verdict(answer.text)
        return FactCheck(text=body, sources=answer.sources, tokens=answer.tokens, verdict=verdict)

    async def explain(self, message: str, image_urls: Iterable[str] = ()) -> Answer:
        return await self._respond(prompts.EXPLAIN,
                                   [{"role": "user", "content": user_content(message, image_urls)}])

    async def translate(self, message: str, language: str) -> Answer:
        return await self._respond(prompts.TRANSLATE.format(language=language),
                                   [{"role": "user", "content": user_content(message)}])

    async def tldr(self, transcript: str, channel: str) -> Answer:
        return await self._respond(
            prompts.TLDR,
            [{"role": "user", "content": user_content(f"Channel #{channel}, oldest first:\n\n{transcript}")}],
        )

    async def pulse(self, topic: str, hours: int, now: datetime | None = None) -> Answer:
        now = now or datetime.now(timezone.utc)
        since = (now - timedelta(hours=hours)).date().isoformat()
        return await self._respond(
            prompts.PULSE,
            [{"role": "user", "content": user_content(f"Topic: {topic}\nTime window: last {hours} hours")}],
            [{"type": "x_search", "from_date": since}],
        )

    async def imagine(self, prompt: str) -> Image:
        result = await self.client.images.generate(model=self.image_model, prompt=prompt, n=1)
        item = result.data[0]
        if getattr(item, "b64_json", None):
            return Image(data=base64.b64decode(item.b64_json))
        return Image(url=item.url)
