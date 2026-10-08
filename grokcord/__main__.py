"""Run with ``python -m grokcord``."""

from __future__ import annotations

import logging
import sys

import discord

from .bot import Grokcord
from .config import Config


class _NoVoiceWarning(logging.Filter):
    """grokcord never uses voice, so hide discord.py's 'voice will NOT be supported' warnings."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "voice will NOT be supported" not in record.getMessage()


def main() -> None:
    config = Config.from_env()
    # stdout, so hosts like Railway don't paint normal logs red
    discord.utils.setup_logging(handler=logging.StreamHandler(sys.stdout), level=logging.INFO)
    logging.getLogger("discord.client").addFilter(_NoVoiceWarning())
    Grokcord(config).run(config.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
