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
    # CATEGORIES, not single channels. The founder adds and renames rooms as the community grows,
    # and a category survives that - a channel id does not. Deleting the one configured voice
    # channel is exactly how playback silently stopped working on 2026-08-11.
    rooms_category_id: int | None = None         # every voice room grinds may play in
    grind_category_id: int | None = None         # text channels where /grind is allowed
    grinder_channel_id: int | None = None        # the main text channel: status + arrival notes
    fresh_grinds_channel_id: int | None = None   # where 📌 sends a grind
    # THE DOOR (2026-08-13). The lobby a newcomer lands in, and the private room the founder reads
    # applications in. Both optional: with neither set, nothing about the server changes and the
    # door simply does not exist - closing it is a separate, deliberate step
    # (`scripts/lock_the_door.py`), never something that happens because the bot started.
    door_channel_id: int | None = None           # the lobby: the only room a newcomer can see
    applications_channel_id: int | None = None   # private; where applications land to be read
    # A link to a real Grinder mix, shown to somebody the moment they apply. Between applying and
    # being approved they can see nothing and hear nothing, so this is the only proof that what
    # they are waiting for is worth waiting for. Blank is fine - the line is simply left out.
    sample_mix_url: str = ""
    # EXTRA VOICE IDENTITIES (2026-08-12). One bot application can hold ONE voice connection per
    # SERVER, so with a single Grinder every listening room but one is silent. Each token here is a
    # separate free Discord application that can hold its own connection, i.e. one more room with
    # sound in it. They never handle commands or post anything - see speakers.py. Empty is the
    # default and behaves exactly as before.
    room_tokens: list[str] = dataclasses.field(default_factory=list)


def _int_env(name: str) -> int | None:
    v = os.environ.get(name, "").strip()
    return int(v) if v.isdigit() else None


def _token_list(name: str) -> list[str]:
    """Comma-separated bot tokens, blanks dropped. These are SECRETS and live only in the
    founder-created .env, exactly like DISCORD_TOKEN - never committed, never written by the
    agent. Absent means an empty list, which is the ordinary single-Grinder setup."""
    return [t.strip() for t in os.environ.get(name, "").split(",") if t.strip()]


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
                  rooms_category_id=_int_env("GRINDER_ROOMS_CATEGORY_ID"),
                  grind_category_id=_int_env("GRINDER_GRIND_CATEGORY_ID"),
                  grinder_channel_id=_int_env("GRINDER_MAIN_CHANNEL_ID"),
                  fresh_grinds_channel_id=_int_env("GRINDER_SHOWCASE_CHANNEL_ID"),
                  door_channel_id=_int_env("GRINDER_DOOR_CHANNEL_ID"),
                  applications_channel_id=_int_env("GRINDER_APPLICATIONS_CHANNEL_ID"),
                  sample_mix_url=os.environ.get("GRINDER_SAMPLE_MIX_URL", "").strip(),
                  room_tokens=_token_list("GRINDER_ROOM_TOKENS"))
