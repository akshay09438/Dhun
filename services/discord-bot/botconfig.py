"""Bot configuration, read from the environment (and an optional local `.env`).

The `.env` file lives at services/discord-bot/.env and is created BY THE FOUNDER — never by
the agent, never committed (it holds the bot token, a secret). This module reads it with a
tiny built-in parser so the bot needs no extra dependency for it.

Required:
  DISCORD_TOKEN        the bot token from the Discord Developer Portal (Bot tab).
Optional:
  PROMPTDJ_API_BASE    where the Prompt-DJ engine is (default http://127.0.0.1:8000).
  DISCORD_GUILD_ID     your server's id — set it so the /mix command appears INSTANTLY in
                       your server (a global command can take up to an hour to show up).
"""
from __future__ import annotations

import dataclasses
import os
from pathlib import Path

_ENV_FILE = Path(__file__).with_name(".env")


def _load_dotenv() -> None:
    """Minimal KEY=VALUE reader for a local .env (no python-dotenv dependency)."""
    if not _ENV_FILE.exists():
        return
    for raw in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


@dataclasses.dataclass
class Config:
    token: str
    api_base: str
    guild_id: int | None
    # Channel ids, set by `/setup` writing them back or by hand. All optional: a missing id
    # disables that one feature and says so in the log, rather than the bot guessing at a channel
    # by name. Guessing is how a message ends up in the wrong room in somebody else's server.
    booth_channel_id: int | None = None          # the ONE voice channel grinds play in
    grinder_channel_id: int | None = None        # #the-grinder: status message + arrival notes
    fresh_grinds_channel_id: int | None = None   # #fresh-grinds: where 📌 sends a grind


def _int_env(name: str) -> int | None:
    v = os.environ.get(name, "").strip()
    return int(v) if v.isdigit() else None


def load_config() -> Config:
    _load_dotenv()
    token = os.environ.get("DISCORD_TOKEN", "").strip()
    if not token:
        raise SystemExit(
            "\nDISCORD_TOKEN is not set.\n"
            "Create the file  services/discord-bot/.env  with this one line:\n\n"
            "  DISCORD_TOKEN=your-bot-token-here\n\n"
            "(Get the token from https://discord.com/developers/applications -> your app -> Bot -> Reset Token.)\n"
            "Full walkthrough: services/discord-bot/README.md\n")
    api_base = os.environ.get("PROMPTDJ_API_BASE", "http://127.0.0.1:8000").strip()
    gid = os.environ.get("DISCORD_GUILD_ID", "").strip()
    return Config(token=token, api_base=api_base,
                  guild_id=int(gid) if gid.isdigit() else None,
                  booth_channel_id=_int_env("GRINDER_BOOTH_CHANNEL_ID"),
                  grinder_channel_id=_int_env("GRINDER_MAIN_CHANNEL_ID"),
                  fresh_grinds_channel_id=_int_env("GRINDER_SHOWCASE_CHANNEL_ID"))
