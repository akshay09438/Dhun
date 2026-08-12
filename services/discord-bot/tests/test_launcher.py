"""Start-Grinder.bat must actually reach the line that starts the bot.

WHY THIS EXISTS. On 2026-08-12 the launcher was edited to prefer the Intel environment (the one
where voice works). The edit was correct. But the same edit left an `echo` containing a bare
`(best-effort)` inside an if/else block, and cmd.exe parses a whole block BEFORE executing any of
it - so the bare `)` closed the block early and the launcher died with

    ... was unexpected at this time.

immediately after step [1/3]. It never reached step [3/3], so the bot never started. Discord then
answered every `/grind` with "The application did not respond", which looks like a bot bug and is
not one.

The branch containing the offending line NEVER RUNS on a machine that already has a virtualenv.
That is the whole danger: the file looks fine, the logic is right, the broken line is unreachable,
and it still kills the script. Reading the batch file is not enough to catch this, and the previous
session's handoff correctly flagged the launcher as "edited but never run end to end" - the claim
was true and closing it by re-reading the code was a mistake.

These tests are cheap and they fail loudly on the exact class of bug.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

LAUNCHER = Path(__file__).resolve().parents[3] / "Start-Grinder.bat"


def _lines() -> list[tuple[int, str]]:
    text = LAUNCHER.read_text(encoding="utf-8", errors="replace")
    return list(enumerate(text.splitlines(), start=1))


def test_launcher_exists() -> None:
    assert LAUNCHER.is_file(), f"the launcher went missing: {LAUNCHER}"


def _all_batch_files() -> list[Path]:
    """EVERY double-clickable script we ship, not just the one that broke.

    Generalised on 2026-08-12 after a second .bat was added: a guard that protects one file while
    the next one is written freehand only catches the bug we already know about."""
    return sorted(LAUNCHER.parent.glob("*.bat"))


def test_there_is_something_to_check() -> None:
    assert _all_batch_files(), "no .bat files found - this guard would pass vacuously"


def test_echo_lines_escape_their_parentheses() -> None:
    """Any `echo` in any of our .bat files must escape ( and ) as ^( ^).

    Checked on every echo rather than only the ones inside blocks: telling "inside a block" from
    "outside" needs a real batch parser, and escaping everywhere is harmless - `echo ^(x^)` prints
    exactly the same text as `echo (x)` when it does parse.
    """
    offenders: list[str] = []
    for bat in _all_batch_files():
        text = bat.read_text(encoding="utf-8", errors="replace")
        for num, raw in enumerate(text.splitlines(), start=1):
            line = raw.strip()
            if not re.match(r"^echo\b", line, flags=re.IGNORECASE):
                continue
            # Strip the legal escaped forms, then anything left is a bare parenthesis.
            stripped = line.replace("^(", "").replace("^)", "")
            if "(" in stripped or ")" in stripped:
                offenders.append(f"  {bat.name} line {num}: {line}")

    assert not offenders, (
        "These echo lines contain unescaped parentheses. Inside an if/else block cmd.exe treats a "
        "bare ')' as the end of the block and the script dies with '... was unexpected at this "
        "time' BEFORE reaching its real work - even if the line is on a branch that never runs.\n"
        "Write them as ^( and ^).\n" + "\n".join(offenders)
    )


def test_launcher_still_starts_the_bot() -> None:
    """The last thing the file does must be run bot.py. A launcher that reaches the end without
    starting the bot is the same failure wearing a different hat."""
    text = LAUNCHER.read_text(encoding="utf-8", errors="replace")
    assert "bot.py" in text, "the launcher no longer starts bot.py at all"
    assert "%BOTPY%" in text, "the launcher no longer uses the chosen interpreter (BOTPY)"


def test_launcher_prefers_the_environment_where_voice_works() -> None:
    """`.venv-x64` is the Intel environment; it is the only one on this machine where `davey`
    imports and therefore the only one that can make a sound in a listening room."""
    text = LAUNCHER.read_text(encoding="utf-8", errors="replace")
    assert ".venv-x64" in text, (
        "the launcher no longer prefers the Intel environment - voice playback will silently "
        "stop working in the listening rooms"
    )


def test_no_script_names_a_command_the_bot_does_not_have() -> None:
    """A launcher window is the first instruction a newcomer reads.

    Start-Grinder.bat pointed at `/mix` for a while, which does not exist. Generalising this check
    across every .bat immediately found the SAME bug hiding in Set-Grinder-Server.bat - which is
    the whole argument for not guarding one file at a time."""
    bot_py = (LAUNCHER.parent / "services" / "discord-bot" / "bot.py").read_text(
        encoding="utf-8", errors="replace"
    )
    real = set(re.findall(r'command\(name="(\w+)"', bot_py))
    assert real, "could not read the bot's command list - the check would pass vacuously"

    offenders = []
    for bat in _all_batch_files():
        text = bat.read_text(encoding="latin-1")
        # Only slash-words that read as an instruction, so a path like a/b is not mistaken for one.
        for name in re.findall(r"(?<![\w/])/(\w+)\b", text):
            if name in {"c", "d", "f", "s", "q", "k", "b", "v", "a", "e", "r", "l", "y", "n",
                        "online", "sagerun", "NoProfile", "Command", "Verb"}:
                continue        # cmd.exe and PowerShell switches, not Discord commands
            if name not in real and name.lower() in {"mix", "set", "songs", "grind", "play",
                                                     "skip", "stop", "help", "setup", "mygrinds"}:
                offenders.append(f"  {bat.name}: /{name}")

    assert not offenders, (
        "These scripts tell people to type a command the bot does not have:\n"
        + "\n".join(offenders) + f"\nreal commands: {sorted(real)}"
    )


@pytest.mark.parametrize("bad", ["echo  Installing voice support (best-effort)..."])
def test_the_detector_actually_catches_the_original_bug(bad: str) -> None:
    """A guard nobody has seen fail is a guard nobody should trust. This is the exact line that
    broke the launcher; the check above must reject it."""
    stripped = bad.strip().replace("^(", "").replace("^)", "")
    assert "(" in stripped or ")" in stripped
