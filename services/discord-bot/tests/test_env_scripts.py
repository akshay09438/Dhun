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
refusal to accept the main bot's own token) lives in Ask-For-Token.ps1 and needs a person at a
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


# --- the double-click scripts must actually be able to find their helpers ---------------------
# CAUGHT FOR REAL while building this: the prompting helper was first called "Set-GrinderSecret.ps1",
# whose name matches the repo's `*secret*` ignore rule - so `git add` silently skipped it, and a
# fresh clone would have had a .bat pointing at a file that was not there. It worked perfectly on
# the one machine that happened to have it, which is the worst shape of bug for a founder-facing
# script. Renamed to Ask-For-Token.ps1; these two make sure it cannot happen again.

REPO = Path(__file__).resolve().parents[3]
BATS = [REPO / "Set-Grinder-Token.bat", REPO / "Add-Grinder-Rooms.bat", REPO / "Start-Grinder.bat"]


def _referenced_scripts():
    """Every PowerShell helper a .bat calls, as a repo-relative path.

    `%~dp0` is cmd for "the folder this .bat lives in", which for all of ours IS the repo root - and
    it is the CORRECT way to write these paths, because a .bat that `cd`s somewhere first (as
    Start-Grinder.bat does) breaks any path written relative to the working directory. That is a
    real bug this suite previously could not see: the old `services\\discord-bot\\scripts\\...` form
    resolved fine from the repo root, so this check passed, while at RUNTIME the launcher had
    already `cd`d into `services\\discord-bot` and the helper silently never ran (found 2026-08-14).

    So strip a leading `%~dp0` before resolving. Note the `0` of `%~dp0` is a word character and
    would otherwise be captured as part of the path, turning it into `0services/...`.
    """
    import re
    found = []
    for bat in BATS:
        for m in re.finditer(r'(?:%~dp0)?([\w\\/.-]*scripts[\\/][\w.-]+\.ps1)',
                             bat.read_text(encoding="utf-8")):
            rel = m.group(1).replace("\\", "/")
            found.append((bat.name, rel))
    return found


def test_every_helper_a_double_click_script_calls_actually_exists():
    refs = _referenced_scripts()
    assert refs, "the .bat files should be calling the PowerShell helpers"
    for bat_name, rel in refs:
        assert (REPO / rel).is_file(), f"{bat_name} calls {rel}, which is not there"


@pytest.mark.skipif(shutil.which("git") is None, reason="no git on this machine")
def test_those_helpers_are_actually_committed():
    """Existing on THIS machine is not enough - an ignored file is missing for everybody else."""
    for bat_name, rel in _referenced_scripts():
        r = subprocess.run(["git", "check-ignore", rel], cwd=REPO,
                           capture_output=True, text=True, timeout=30)
        assert r.returncode != 0, f"{bat_name} calls {rel}, which git is ignoring - it will not ship"


# --- one Grinder on shift at a time ---------------------------------------------------------------
# THE HOUR THIS COST, 2026-08-12: a Grinder from 18:34 was still running after its window was closed.
# The founder started a new one and two bots raced every command - the old one still had the
# auto-play station and knew nothing about the second room, so it started music on its own and
# answered "only one room can have sound" long after startup had said two. Every symptom looked like
# a bug in the new code. None of them were.

GUARD = REPO / "services" / "discord-bot" / "scripts" / "Stop-Other-Grinders.ps1"


def test_the_launcher_clears_the_shift_before_starting():
    """A second Grinder must never be able to start beside a first."""
    launcher = (REPO / "Start-Grinder.bat").read_text(encoding="utf-8")
    assert "Stop-Other-Grinders.ps1" in launcher
    assert launcher.index("Stop-Other-Grinders.ps1") < launcher.index('"%BOTPY%" bot.py'), \
        "it has to run BEFORE the new bot starts, or both are alive at once"


@needs_powershell
def test_the_guard_never_reaches_the_engine():
    """The engine runs python too, and killing it would take the whole app down rather than one
    duplicate bot. -WhatIf lists what it WOULD stop and stops nothing."""
    r = subprocess.run(
        [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(GUARD), "-WhatIf"],
        capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    named = [ln for ln in r.stdout.splitlines() if "would stop" in ln.lower()]
    assert not any("uvicorn" in ln.lower() for ln in named), \
        f"the guard must never name the engine: {named}"


@needs_powershell
def test_the_guard_is_quiet_and_harmless_when_nothing_is_running():
    """It runs on every single launch, so its do-nothing path has to be clean."""
    r = subprocess.run(
        [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(GUARD), "-WhatIf"],
        capture_output=True, text=True, timeout=120)
    assert r.returncode == 0
    assert "error" not in r.stderr.lower(), r.stderr
