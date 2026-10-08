"""SQLite storage for per-server settings and daily usage. No setup needed."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS persona (
    guild_id   INTEGER NOT NULL,
    channel_id INTEGER NOT NULL DEFAULT 0,   -- 0 = whole server
    persona    TEXT    NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);
CREATE TABLE IF NOT EXISTS limits (
    guild_id   INTEGER PRIMARY KEY,
    user_daily INTEGER,
    guild_daily INTEGER
);
CREATE TABLE IF NOT EXISTS disabled (
    guild_id INTEGER NOT NULL,
    feature  TEXT    NOT NULL,
    PRIMARY KEY (guild_id, feature)
);
CREATE TABLE IF NOT EXISTS usage (
    day      TEXT    NOT NULL,
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    units    INTEGER NOT NULL DEFAULT 0,
    tokens   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, guild_id, user_id)
);
"""


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


class Store:
    def __init__(self, path: str) -> None:
        self.path = path
        self.db: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self.db = await aiosqlite.connect(self.path)
        await self.db.executescript(SCHEMA)
        await self.db.commit()

    async def close(self) -> None:
        if self.db:
            await self.db.close()

    async def _one(self, sql: str, *args) -> tuple | None:
        async with self.db.execute(sql, args) as cur:
            return await cur.fetchone()

    # ── personas ──────────────────────────────────────────────
    async def get_persona(self, guild_id: int, channel_id: int, default: str) -> str:
        row = await self._one(
            "SELECT persona FROM persona WHERE guild_id=? AND channel_id IN (?, 0) "
            "ORDER BY channel_id DESC LIMIT 1", guild_id, channel_id)
        return row[0] if row else default

    async def set_persona(self, guild_id: int, channel_id: int, persona: str) -> None:
        await self.db.execute(
            "INSERT INTO persona VALUES (?, ?, ?) ON CONFLICT(guild_id, channel_id) "
            "DO UPDATE SET persona=excluded.persona", (guild_id, channel_id, persona))
        await self.db.commit()

    async def clear_persona(self, guild_id: int, channel_id: int) -> None:
        await self.db.execute("DELETE FROM persona WHERE guild_id=? AND channel_id=?", (guild_id, channel_id))
        await self.db.commit()

    # ── features ──────────────────────────────────────────────
    async def is_enabled(self, guild_id: int, feature: str) -> bool:
        return await self._one("SELECT 1 FROM disabled WHERE guild_id=? AND feature=?", guild_id, feature) is None

    async def set_enabled(self, guild_id: int, feature: str, enabled: bool) -> None:
        if enabled:
            await self.db.execute("DELETE FROM disabled WHERE guild_id=? AND feature=?", (guild_id, feature))
        else:
            await self.db.execute("INSERT OR IGNORE INTO disabled VALUES (?, ?)", (guild_id, feature))
        await self.db.commit()

    async def disabled_features(self, guild_id: int) -> list[str]:
        async with self.db.execute("SELECT feature FROM disabled WHERE guild_id=? ORDER BY feature",
                                   (guild_id,)) as cur:
            return [r[0] for r in await cur.fetchall()]

    # ── limits & usage ────────────────────────────────────────
    async def get_limits(self, guild_id: int, user_default: int, guild_default: int) -> tuple[int, int]:
        row = await self._one("SELECT user_daily, guild_daily FROM limits WHERE guild_id=?", guild_id)
        if not row:
            return user_default, guild_default
        return (row[0] if row[0] is not None else user_default,
                row[1] if row[1] is not None else guild_default)

    async def set_limits(self, guild_id: int, user_daily: int | None, guild_daily: int | None) -> None:
        await self.db.execute(
            "INSERT INTO limits VALUES (?, ?, ?) ON CONFLICT(guild_id) DO UPDATE SET "
            "user_daily=COALESCE(excluded.user_daily, user_daily), "
            "guild_daily=COALESCE(excluded.guild_daily, guild_daily)",
            (guild_id, user_daily, guild_daily))
        await self.db.commit()

    async def usage(self, guild_id: int, user_id: int, day: str | None = None) -> tuple[int, int, int]:
        """Return (user units, user tokens, guild units) for the day."""
        day = day or today()
        user = await self._one("SELECT units, tokens FROM usage WHERE day=? AND guild_id=? AND user_id=?",
                               day, guild_id, user_id)
        guild = await self._one("SELECT COALESCE(SUM(units), 0) FROM usage WHERE day=? AND guild_id=?",
                                day, guild_id)
        return (user[0] if user else 0, user[1] if user else 0, guild[0])

    async def add_usage(self, guild_id: int, user_id: int, units: int, tokens: int = 0,
                        day: str | None = None) -> None:
        await self.db.execute(
            "INSERT INTO usage VALUES (?, ?, ?, ?, ?) ON CONFLICT(day, guild_id, user_id) "
            "DO UPDATE SET units=units+excluded.units, tokens=tokens+excluded.tokens",
            (day or today(), guild_id, user_id, units, tokens))
        await self.db.commit()
