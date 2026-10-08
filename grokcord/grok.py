"""Thin async wrapper around the xAI API (OpenAI-compatible Responses + Images endpoints)."""

from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Iterable

import openai
from openai import AsyncOpenAI

from . import prompts

log = logging.getLogger("grokcord")

VERDICTS = ("MOSTLY TRUE", "TRUE", "MISLEADING", "FALSE", "UNVERIFIED")
_VERDICT_RE = re.compile(r"^\s*\**\s*VERDICT\s*:?\s*\**\s*([A-Z ]+?)\s*\**\s*$", re.M)
SEARCH_TOOLS = [{"type": "web_search"}, {"type": "x_search"}]

# How hard Grok thinks per task. Lower = faster. Fact-checks get a bit more care.
FAST, CAREFUL = "low", "medium"


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


def _is_reasoning_error(exc: Exception) -> bool:
    return isinstance(exc, openai.BadRequestError) and "reasoning" in str(exc).lower()


class Grok:
    def __init__(self, api_key: str, model: str, image_model: str, base_url: str,
                 client: AsyncOpenAI | None = None, reasoning: bool = True) -> None:
        self.model = model
        self.image_model = image_model
        # Send a reasoning effort unless turned off, or until the model rejects it once.
        self.reasoning = reasoning
        self.client = client or AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=120)

    def _kwargs(self, instructions: str, messages: list[dict[str, Any]],
                tools: list[dict[str, Any]] | None, effort: str) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"model": self.model, "instructions": instructions, "input": messages}
        if tools:
            kwargs["tools"] = tools
        if self.reasoning:
            kwargs["reasoning"] = {"effort": effort}
        return kwargs

    async def _create(self, kwargs: dict[str, Any], **extra: Any) -> Any:
        try:
            return await self.client.responses.create(**kwargs, **extra)
        except openai.BadRequestError as exc:
            if "reasoning" not in kwargs or not _is_reasoning_error(exc):
                raise
            log.warning("Model %s doesn't accept a reasoning effort; sending requests without it", self.model)
            self.reasoning = False
            kwargs = {k: v for k, v in kwargs.items() if k != "reasoning"}
            return await self.client.responses.create(**kwargs, **extra)

    async def _respond(self, instructions: str, messages: list[dict[str, Any]],
                       tools: list[dict[str, Any]] | None = None, effort: str = FAST) -> Answer:
        response = await self._create(self._kwargs(instructions, messages, tools, effort))
        text = (_get(response, "output_text", "") or "").strip() or "_(Grok returned an empty answer.)_"
        return Answer(text=text, sources=extract_sources(response), tokens=_tokens(response))

    async def chat(self, persona: str, history: list[dict[str, Any]], *, search: bool = False,
                   language: str | None = None) -> Answer:
        """Conversational answer. ``history`` is a list of Responses-API messages, oldest first."""
        return await self._respond(prompts.system_prompt(persona, language), history,
                                   SEARCH_TOOLS if search else None)

    async def chat_stream(self, persona: str, history: list[dict[str, Any]], *,
                          on_text: Callable[[str], Awaitable[None]], search: bool = False,
                          language: str | None = None) -> Answer:
        """Like :meth:`chat`, but calls ``on_text(text_so_far)`` as the answer is written."""
        kwargs = self._kwargs(prompts.system_prompt(persona, language), history,
                              SEARCH_TOOLS if search else None, FAST)
        stream = await self._create(kwargs, stream=True)
        text, final = "", None
        async for event in stream:
            kind = _get(event, "type", "")
            if kind == "response.output_text.delta":
                text += _get(event, "delta", "") or ""
                await on_text(text)
            elif kind == "response.completed":
                final = _get(event, "response")
        if final is None and not text.strip():
            log.warning("Streaming returned nothing; retrying without streaming")
            kwargs.pop("stream", None)
            return await self._respond(kwargs["instructions"], history, kwargs.get("tools"), FAST)
        if final is not None and not text.strip():
            text = _get(final, "output_text", "") or ""
        return Answer(text=text.strip() or "_(Grok returned an empty answer.)_",
                      sources=extract_sources(final) if final is not None else [],
                      tokens=_tokens(final) if final is not None else 0)

    async def fact_check(self, message: str, author: str, image_urls: Iterable[str] = (),
                         language: str | None = None) -> FactCheck:
        answer = await self._respond(
            prompts.FACT_CHECK + prompts.language_rule(language),
            [{"role": "user", "content": user_content(f"Message by {author}:\n\n{message}", image_urls)}],
            SEARCH_TOOLS, CAREFUL,
        )
        verdict, body = parse_verdict(answer.text)
        return FactCheck(text=body, sources=answer.sources, tokens=answer.tokens, verdict=verdict)

    async def explain(self, message: str, language: str, image_urls: Iterable[str] = ()) -> Answer:
        return await self._respond(prompts.EXPLAIN.format(language=language),
                                   [{"role": "user", "content": user_content(message, image_urls)}])

    async def translate(self, message: str, language: str) -> Answer:
        return await self._respond(prompts.TRANSLATE.format(language=language),
                                   [{"role": "user", "content": user_content(message)}])

    async def tldr(self, transcript: str, channel: str, language: str | None = None) -> Answer:
        return await self._respond(
            prompts.TLDR + prompts.language_rule(language),
            [{"role": "user", "content": user_content(f"Channel #{channel}, oldest first:\n\n{transcript}")}],
        )

    async def pulse(self, topic: str, hours: int, language: str, now: datetime | None = None) -> Answer:
        now = now or datetime.now(timezone.utc)
        since = (now - timedelta(hours=hours)).date().isoformat()
        return await self._respond(
            prompts.PULSE.format(language=language),
            [{"role": "user", "content": user_content(f"Topic: {topic}\nTime window: last {hours} hours")}],
            [{"type": "x_search", "from_date": since}],
        )

    async def imagine(self, prompt: str) -> Image:
        result = await self.client.images.generate(model=self.image_model, prompt=prompt, n=1)
        item = result.data[0]
        if getattr(item, "b64_json", None):
            return Image(data=base64.b64decode(item.b64_json))
        return Image(url=item.url)
