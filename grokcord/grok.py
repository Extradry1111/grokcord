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
WEB_SEARCH = [{"type": "web_search"}]  # chat: web only; X search is billed per post found, so it's kept for /pulse and fact-checks

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


class Grok:
    """xAI client. Light tasks (chat, explain, translate, tldr) run on the cheaper model;
    fact-checks and /pulse run on the main one. Every search-enabled call has a tool-call cap."""

    def __init__(self, api_key: str, model: str, image_model: str, base_url: str,
                 client: AsyncOpenAI | None = None, reasoning: bool = True,
                 cheap_model: str | None = None) -> None:
        self.model = model
        self.cheap_model = cheap_model or model
        self.image_model = image_model
        # Optional request settings, each dropped for good the first time the API rejects it.
        self.reasoning = reasoning
        self.tool_cap = True
        self.client = client or AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=120)

    def _kwargs(self, instructions: str, messages: list[dict[str, Any]],
                tools: list[dict[str, Any]] | None, effort: str, *, cheap: bool = False,
                max_tools: int | None = None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"model": self.cheap_model if cheap else self.model,
                                  "instructions": instructions, "input": messages}
        if tools:
            kwargs["tools"] = tools
            if max_tools and self.tool_cap:
                kwargs["max_tool_calls"] = max_tools
        if self.reasoning:
            kwargs["reasoning"] = {"effort": effort}
        return kwargs

    async def _create(self, kwargs: dict[str, Any], **extra: Any) -> Any:
        """Call the Responses API, dropping settings the model rejects and falling back from a
        cheap model that doesn't exist (anymore) to the main model."""
        kwargs = dict(kwargs)
        for _attempt in range(3):
            try:
                return await self.client.responses.create(**kwargs, **extra)
            except (openai.BadRequestError, openai.NotFoundError) as exc:
                msg = str(exc).lower()
                if "reasoning" in kwargs and "reasoning" in msg:
                    log.warning("%s doesn't accept a reasoning effort; not sending it anymore", kwargs["model"])
                    self.reasoning = False
                    kwargs.pop("reasoning")
                elif "max_tool_calls" in kwargs and "max_tool_calls" in msg:
                    log.warning("API doesn't accept max_tool_calls; not sending it anymore")
                    self.tool_cap = False
                    kwargs.pop("max_tool_calls")
                elif kwargs["model"] != self.model and (isinstance(exc, openai.NotFoundError) or "model" in msg):
                    log.warning("Cheap model %s unavailable; using %s for everything", kwargs["model"], self.model)
                    self.cheap_model = self.model
                    kwargs["model"] = self.model
                else:
                    raise
        return await self.client.responses.create(**kwargs, **extra)

    async def _respond(self, instructions: str, messages: list[dict[str, Any]],
                       tools: list[dict[str, Any]] | None = None, effort: str = FAST, *,
                       cheap: bool = False, max_tools: int | None = None) -> Answer:
        response = await self._create(self._kwargs(instructions, messages, tools, effort,
                                                   cheap=cheap, max_tools=max_tools))
        text = (_get(response, "output_text", "") or "").strip() or "_(Grok returned an empty answer.)_"
        return Answer(text=text, sources=extract_sources(response), tokens=_tokens(response))

    async def chat(self, persona: str, history: list[dict[str, Any]], *, search: bool = False,
                   language: str | None = None) -> Answer:
        """Conversational answer. ``history`` is a list of Responses-API messages, oldest first."""
        return await self._respond(prompts.system_prompt(persona, language), history,
                                   WEB_SEARCH if search else None, cheap=True, max_tools=2)

    async def chat_stream(self, persona: str, history: list[dict[str, Any]], *,
                          on_text: Callable[[str], Awaitable[None]], search: bool = False,
                          language: str | None = None) -> Answer:
        """Like :meth:`chat`, but calls ``on_text(text_so_far)`` as the answer is written."""
        kwargs = self._kwargs(prompts.system_prompt(persona, language), history,
                              WEB_SEARCH if search else None, FAST, cheap=True, max_tools=2)
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
            return await self._respond(kwargs["instructions"], history, kwargs.get("tools"), FAST,
                                       cheap=True, max_tools=2)
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
            SEARCH_TOOLS, CAREFUL, max_tools=4,
        )
        verdict, body = parse_verdict(answer.text)
        return FactCheck(text=body, sources=answer.sources, tokens=answer.tokens, verdict=verdict)

    async def explain(self, message: str, language: str, image_urls: Iterable[str] = ()) -> Answer:
        return await self._respond(prompts.EXPLAIN.format(language=language),
                                   [{"role": "user", "content": user_content(message, image_urls)}], cheap=True)

    async def translate(self, message: str, language: str) -> Answer:
        return await self._respond(prompts.TRANSLATE.format(language=language),
                                   [{"role": "user", "content": user_content(message)}], cheap=True)

    async def tldr(self, transcript: str, channel: str, language: str | None = None) -> Answer:
        return await self._respond(
            prompts.TLDR + prompts.language_rule(language),
            [{"role": "user", "content": user_content(f"Channel #{channel}, oldest first:\n\n{transcript}")}],
            cheap=True,
        )

    async def pulse(self, topic: str, hours: int, language: str, now: datetime | None = None) -> Answer:
        now = now or datetime.now(timezone.utc)
        since = (now - timedelta(hours=hours)).date().isoformat()
        return await self._respond(
            prompts.PULSE.format(language=language),
            [{"role": "user", "content": user_content(f"Topic: {topic}\nTime window: last {hours} hours")}],
            [{"type": "x_search", "from_date": since}], max_tools=3,
        )

    async def imagine(self, prompt: str) -> Image:
        result = await self.client.images.generate(model=self.image_model, prompt=prompt, n=1)
        item = result.data[0]
        if getattr(item, "b64_json", None):
            return Image(data=base64.b64decode(item.b64_json))
        return Image(url=item.url)
