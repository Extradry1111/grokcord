"""Settings, read once from the environment (and a .env file if present)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} must be a whole number, got {raw!r}") from exc


@dataclass(frozen=True)
class Config:
    discord_token: str
    xai_api_key: str
    model: str = "grok-4.7"
    image_model: str = "grok-imagine-image-2.0"
    base_url: str = "https://api.x.ai/v1"
    daily_user_limit: int = 40
    daily_guild_limit: int = 600
    image_cost: int = 5
    dev_guild_id: int | None = None
    database_path: str = "grokcord.db"
    default_persona: str = "helper"

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        missing = [n for n in ("DISCORD_TOKEN", "XAI_API_KEY") if not os.getenv(n, "").strip()]
        if missing:
            raise SystemExit(
                f"Missing {', '.join(missing)}. Copy .env.example to .env and fill it in "
                "(see docs/SETUP.md)."
            )
        dev_guild = os.getenv("DEV_GUILD_ID", "").strip()
        return cls(
            discord_token=os.environ["DISCORD_TOKEN"].strip(),
            xai_api_key=os.environ["XAI_API_KEY"].strip(),
            model=os.getenv("GROK_MODEL", "").strip() or cls.model,
            image_model=os.getenv("GROK_IMAGE_MODEL", "").strip() or cls.image_model,
            base_url=os.getenv("XAI_BASE_URL", "").strip() or cls.base_url,
            daily_user_limit=_int("DAILY_USER_LIMIT", cls.daily_user_limit),
            daily_guild_limit=_int("DAILY_GUILD_LIMIT", cls.daily_guild_limit),
            image_cost=_int("IMAGE_COST", cls.image_cost),
            dev_guild_id=int(dev_guild) if dev_guild else None,
            database_path=os.getenv("DATABASE_PATH", "").strip() or cls.database_path,
            default_persona=os.getenv("DEFAULT_PERSONA", "").strip() or cls.default_persona,
        )
