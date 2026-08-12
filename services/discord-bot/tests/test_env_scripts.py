"""Saving a token must never cost the founder the rest of their settings.

THE BUG THESE EXIST FOR, recorded as unfixed in the handoff of 2026-08-12. Set-Grinder-Token.bat
wrote the settings file with a single `>`:

    > "services\\discord-bot\\.env" echo DISCORD_TOKEN=%TOK%

which overwrites the WHOLE file. Running it a second time - the obvious thing to do after resetting
a token - silently discarded DISCORD_GUILD_ID and all four channel/category ids. The bot would come
back up with no rooms, no status message and no showcase, and NOTHING in the log explaining it,
because from its point of view those settings simply were not configured. This is the change that
walks the founder into that script, so it is fixed here.

WHAT THESE COVER: the writing, which is where the damage was. The prompting (hidden input, the
refusal to accept the main bot's own token) lives in Set-GrinderSecret.ps1 and needs a person at a
keyboard - it is on the morning test sheet instead.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DISCORD_BOT_TOKEN", "x" * 59)

import speakers  # noqa: E402

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "Set-EnvValue.ps1"

# A realistic settings file: exactly what the founder's own has in it, minus the real values.
REAL_WORLD_ENV = """\
DISCORD_TOKEN=old-token-value
DISCORD_GUILD_ID=1535000000000000000
GRINDER_ROOMS_CATEGORY_ID=1535000000000000001
GRINDER_GRIND_CATEGORY_ID=1535000000000000002
GRINDER_MAIN_CHANNEL_ID=1535000000000000003
GRINDER_SHOWCASE_CHANNEL_ID=1535000000000000004
"""

powershell = shutil.which("powershell") or shutil.which("pwsh")
needs_powershell = pytest.mark.skipif(
    powershell is None,
    reason="these prove a Windows .bat helper; there is no PowerShell on this machine")


def _run(path: Path, key: str, value: str):
    return subprocess.run(
        [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
         "-Path", str(path), "-Key", key, "-Value", value],
        capture_output=True, text=True, timeout=60)


def _settings(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            out.setdefault(k.strip(), v.strip())
    return out


@needs_powershell
def test_saving_a_token_keeps_every_other_setting(tmp_path):
    """THE REGRESSION. Everything except the one key must survive, byte for byte."""
    env = tmp_path / "grinder.env"
    env.write_text(REAL_WORLD_ENV, encoding="utf-8")

    r = _run(env, "DISCORD_TOKEN", "brand-new-token")
    assert r.returncode == 0, r.stderr

    got = _settings(env)
    assert got["DISCORD_TOKEN"] == "brand-new-token"
    assert got["DISCORD_GUILD_ID"] == "1535000000000000000"
    assert got["GRINDER_ROOMS_CATEGORY_ID"] == "1535000000000000001"
    assert got["GRINDER_GRIND_CATEGORY_ID"] == "1535000000000000002"
    assert got["GRINDER_MAIN_CHANNEL_ID"] == "1535000000000000003"
    assert got["GRINDER_SHOWCASE_CHANNEL_ID"] == "1535000000000000004"


@needs_powershell
def test_a_new_setting_is_added_without_disturbing_the_old_ones(tmp_path):
    """Adding the extra room tokens is exactly this case - the key has never been there before."""
    env = tmp_path / "grinder.env"
    env.write_text(REAL_WORLD_ENV, encoding="utf-8")

    assert _run(env, "GRINDER_ROOM_TOKENS", "tok-a,tok-b").returncode == 0

    got = _settings(env)
    assert got["GRINDER_ROOM_TOKENS"] == "tok-a,tok-b"
    assert len(got) == 7, "one added, none lost"


@needs_powershell
def test_the_line_keeps_its_place_in_the_file(tmp_path):
    """So the file still looks like the one the founder knows, rather than being reshuffled every
    time a token is set."""
    env = tmp_path / "grinder.env"
    env.write_text(REAL_WORLD_ENV, encoding="utf-8")
    _run(env, "GRINDER_MAIN_CHANNEL_ID", "999")
    keys = [ln.split("=", 1)[0] for ln in env.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert keys.index("GRINDER_MAIN_CHANNEL_ID") == 4


@needs_powershell
def test_comments_and_blank_lines_survive(tmp_path):
    env = tmp_path / "grinder.env"
    env.write_text("# my settings\n\nDISCORD_TOKEN=a\n\n# rooms\nGRINDER_MAIN_CHANNEL_ID=7\n",
                   encoding="utf-8")
    _run(env, "DISCORD_TOKEN", "b")
    text = env.read_text(encoding="utf-8")
    assert "# my settings" in text and "# rooms" in text
    assert _settings(env)["GRINDER_MAIN_CHANNEL_ID"] == "7"


@needs_powershell
def test_a_stale_duplicate_of_the_same_key_is_removed(tmp_path):
    """The bot's reader honours the FIRST occurrence, so a leftover second copy is a setting that
    looks changed and is not - the most confusing kind of wrong."""
    env = tmp_path / "grinder.env"
    env.write_text("DISCORD_TOKEN=one\nDISCORD_GUILD_ID=5\nDISCORD_TOKEN=two\n", encoding="utf-8")
    _run(env, "DISCORD_TOKEN", "three")
    lines = [ln for ln in env.read_text(encoding="utf-8").splitlines() if ln.startswith("DISCORD_TOKEN")]
    assert lines == ["DISCORD_TOKEN=three"]


@needs_powershell
def test_a_missing_file_is_created_rather_than_failing(tmp_path):
    """The very first run on a new machine."""
    env = tmp_path / "nested" / "grinder.env"
    assert _run(env, "DISCORD_TOKEN", "first-ever").returncode == 0
    assert _settings(env) == {"DISCORD_TOKEN": "first-ever"}


@needs_powershell
def test_the_value_is_never_printed(tmp_path):
    """A token in a window's scrollback is a token that has to be reset."""
    env = tmp_path / "grinder.env"
    r = _run(env, "DISCORD_TOKEN", "super-secret-value")
    assert "super-secret-value" not in (r.stdout + r.stderr)


# --- the same mistake, one step wider ---------------------------------------------------------
def test_the_main_grinders_own_token_is_refused_as_an_extra():
    """THE WORST PASTE MISTAKE. Nothing about it looks wrong - the token is valid and the login
    succeeds - but it is the SAME identity, so the moment the 'second' room started, the first room
    would go silent mid-song. That reads as a far worse bug than the one being fixed."""
    pool = speakers.SpeakerPool(["the-main-one", "a-real-second"], main_token="the-main-one")
    assert len(pool) == 1
    assert pool.speakers[0].token == "a-real-second"


def test_without_a_main_token_nothing_changes():
    """Every existing caller passes no main token; they must behave exactly as before."""
    assert len(speakers.SpeakerPool(["a", "b"])) == 2
