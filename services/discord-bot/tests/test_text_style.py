"""Every word a user reads must be typed in plain ASCII punctuation.

Founder rule (2026-08-11), stated bluntly: no em dashes, no en dashes. They read as machine-written.
This test walks the ACTUAL command tree and the ACTUAL card builders rather than grepping the
source, so it covers what Discord really shows and a new command can't quietly reintroduce them.

Emoji, arrows and bullets are fine - the ban is specifically the two dash characters that make text
look auto-generated.
"""
import os

import discord

os.environ.setdefault("DISCORD_BOT_TOKEN", "x" * 59)   # never used; no gateway connection is made

import bot as botmod          # noqa: E402  - must follow the env default above
import server_setup          # noqa: E402
import ui                    # noqa: E402

BANNED = {"—": "em dash (—)", "–": "en dash (–)"}

# Discord's own hard limit on a slash-command description.
MAX_COMMAND_DESCRIPTION = 100


def _offences(text: str | None) -> list[str]:
    return [name for ch, name in BANNED.items() if text and ch in text]


def _embed_text(e: discord.Embed) -> str:
    parts = [e.title or "", e.description or "",
             (e.footer.text or "") if e.footer else "",
             (e.author.name or "") if e.author else ""]
    for f in e.fields:
        parts += [f.name or "", f.value or ""]
    return "\n".join(parts)


def _all_command_text() -> list[tuple[str, str]]:
    """(where, text) for every command description and every parameter description."""
    out: list[tuple[str, str]] = []
    for cmd in botmod.bot.tree.walk_commands():
        out.append((f"/{cmd.name} description", cmd.description or ""))
        for p in getattr(cmd, "parameters", []):
            out.append((f"/{cmd.name} {p.name}", p.description or ""))
    return out


def _all_card_text() -> list[tuple[str, str]]:
    """(where, text) for every card the bot can post."""
    cards: list[tuple[str, discord.Embed]] = [
        ("help_embed", ui.help_embed()),
        ("submit_embed", ui.submit_embed(user=None, beat="Father Ocean", vocals="Der Lagi")),
        ("grind_embed", ui.grind_embed(
            number=147, user=None, pairs=[("Father Ocean", "Der Lagi")], total_secs=185)),
        ("grind_embed long", ui.grind_embed(
            number=148, user=None, pairs=[("A", "B"), ("C", "D")], total_secs=400,
            just_landed=True)),
        ("grind_embed in booth", ui.grind_embed(
            number=149, user=None, pairs=[("A", "B")], total_secs=200, booth_listeners=4)),
        ("grind_embed queued", ui.grind_embed(
            number=150, user=None, pairs=[("A", "B")], total_secs=200, queued_behind=2)),
        ("booth_live_embed", ui.booth_live_embed(
            listeners=4, grinds_this_session=12, last_up="A x B")),
        ("booth_quiet_embed", ui.booth_quiet_embed()),
        ("mygrinds_embed", ui.mygrinds_embed(user=None, total=3, rows=[(1, "A x B", None)])),
        ("mygrinds_embed empty", ui.mygrinds_embed(user=None, total=0, rows=[])),
        ("error_embed", ui.error_embed("Something went wrong.")),
        ("setup report", server_setup.report_embed(
            server_setup.Report(created=["#general"], skipped=["banner"],
                                failed=["#x - Missing Permissions"]), "Grinder")),
    ]

    class _G:
        name = "Grinder"

    for i, e in enumerate(server_setup.welcome_embeds(_G())):
        cards.append((f"welcome_embeds[{i}]", e))
    return [(where, _embed_text(e)) for where, e in cards]


def _all_channel_text() -> list[tuple[str, str]]:
    out = []
    for cat in server_setup.STRUCTURE:
        out.append((f"category {cat.name}", cat.name))
        for ch in cat.channels:
            out.append((f"#{ch.label} topic", ch.topic))
    for name, _colour, _why in server_setup.ROLES:
        out.append((f"role {name}", name))
    return out


def test_no_fancy_dashes_in_any_command_description():
    bad = [(where, _offences(text), text) for where, text in _all_command_text() if _offences(text)]
    assert not bad, "fancy dashes users would read:\n" + "\n".join(
        f"  {w}: {o} in {t!r}" for w, o, t in bad)


def test_no_fancy_dashes_on_any_card():
    bad = [(where, _offences(text), text) for where, text in _all_card_text() if _offences(text)]
    assert not bad, "fancy dashes users would read:\n" + "\n".join(
        f"  {w}: {o} in {t[:120]!r}" for w, o, t in bad)


def test_no_fancy_dashes_in_channel_topics_or_role_names():
    bad = [(where, _offences(text), text) for where, text in _all_channel_text() if _offences(text)]
    assert not bad, "fancy dashes users would read:\n" + "\n".join(
        f"  {w}: {o} in {t!r}" for w, o, t in bad)


# --- while we're here: the descriptions have to be usable, not just clean ------------------

def test_command_descriptions_fit_discords_limit():
    too_long = [(w, len(t)) for w, t in _all_command_text()
                if w.endswith("description") and len(t) > MAX_COMMAND_DESCRIPTION]
    assert not too_long, f"Discord rejects a description over {MAX_COMMAND_DESCRIPTION}: {too_long}"


def test_every_command_has_a_description():
    missing = [w for w, t in _all_command_text() if not t.strip()]
    assert not missing, f"a command with no description looks broken in the picker: {missing}"


def test_the_main_commands_stay_short_enough_to_read_at_a_glance():
    """A description that runs past ~70 characters gets truncated or ignored in Discord's picker,
    which is where a first-timer decides whether to try the command at all."""
    limit = 70
    long_ones = {}
    for cmd in botmod.bot.tree.walk_commands():
        if cmd.name in {"mix", "set", "songs", "help", "setup"}:
            if len(cmd.description or "") > limit:
                long_ones[cmd.name] = len(cmd.description)
    assert not long_ones, f"over {limit} chars: {long_ones}"
