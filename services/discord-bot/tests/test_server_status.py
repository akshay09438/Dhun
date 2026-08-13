"""The read-only security check on scripts/server_status.py.

The point of these tests is that the check must not be able to go quietly blind. A permission
audit that reports a clean board because somebody typed a permission name wrong is worse than no
audit at all - it converts "we never looked" into "we looked and it was fine", which is the exact
false comfort the handoff warned about when it recorded the bot's Administrator as a CLAIM.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import discord
import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

_BOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BOT))
sys.path.insert(0, str(_BOT / "scripts"))

import server_status as ss  # noqa: E402


# ── the tables themselves ────────────────────────────────────────────────────

def test_every_permission_name_is_real():
    """A typo in any table would make `getattr(perms, name, False)` return False forever: the
    check would report the permission as missing (or never over-granted) and nobody would know.
    `manage_guild_expressions` was exactly this bug, caught while writing the check."""
    real = discord.Permissions.all()
    named = [n for n, _ in ss.CORE_PERMS] + [n for n, _ in ss.SETUP_PERMS] + list(ss.NEVER_NEEDED)
    unreal = [n for n in named if not hasattr(real, n)]
    assert not unreal, f"not real discord.py permissions: {unreal}"


def test_no_permission_is_both_needed_and_over_granted():
    """Discord aliases some permission bits under two names (manage_expressions ==
    manage_emojis_and_stickers). Listing an alias on both sides would report one permission as
    required and forbidden simultaneously, and the founder would be told to tick and untick the
    same box."""
    needed = {n for n, _ in ss.CORE_PERMS} | {n for n, _ in ss.SETUP_PERMS}
    both = needed & set(ss.NEVER_NEEDED)
    assert not both, f"listed as needed AND never-needed: {both}"

    # The alias check proper: compare the underlying bit values, not the spellings.
    for needed_name in sorted(needed):
        for banned_name in ss.NEVER_NEEDED:
            a = discord.Permissions(**{needed_name: True}).value
            b = discord.Permissions(**{banned_name: True}).value
            assert a != b, f"{needed_name} and {banned_name} are the same permission bit"


def test_the_destructive_permissions_are_all_on_the_never_needed_list():
    """The bot has no code that kicks, bans, times out or deletes. If a future change adds one,
    that permission must move off this list deliberately - not by accident."""
    for p in ("administrator", "kick_members", "ban_members", "moderate_members"):
        assert p in ss.NEVER_NEEDED


def test_every_needed_permission_explains_itself():
    """The report is read by somebody who does not code. A bare flag name is not an answer."""
    for name, why in ss.CORE_PERMS + ss.SETUP_PERMS:
        assert why.strip(), f"{name} has no plain-language reason"
        assert ss.reason_for(name) == why


# ── audit_permissions ────────────────────────────────────────────────────────

def _perms(**held):
    """A stub with only the named permissions turned on."""
    return type("P", (), {**{k: True for k in held}})()


def test_a_bot_with_exactly_what_it_needs_reports_clean():
    everything = {n for n, _ in ss.CORE_PERMS} | {n for n, _ in ss.SETUP_PERMS}
    audit = ss.audit_permissions(_perms(**{n: True for n in everything}))
    assert audit == {"missing_core": [], "missing_setup": [], "over_granted": []}


def test_administrator_is_reported_as_over_granted():
    audit = ss.audit_permissions(_perms(administrator=True))
    assert "administrator" in audit["over_granted"]


def test_administrator_does_not_paper_over_the_missing_boxes():
    """THE test. On Discord, Administrator really does grant every power - so it is tempting to
    score it as satisfying every need. If we did, the live server would report a perfect green
    board, the founder would untick Administrator on that basis, and the bot would lose Manage
    Roles without warning: approvals then record as approved and the person sees nothing. The
    audit must read the real boxes underneath."""
    audit = ss.audit_permissions(_perms(administrator=True))
    assert "manage_roles" in audit["missing_core"]
    assert len(audit["missing_core"]) == len(ss.CORE_PERMS)


def test_a_missing_daily_permission_is_named():
    everything = {n for n, _ in ss.CORE_PERMS} | {n for n, _ in ss.SETUP_PERMS}
    everything.discard("manage_messages")          # the known live gap: it cannot pin its posts
    audit = ss.audit_permissions(_perms(**{n: True for n in everything}))
    assert audit["missing_core"] == ["manage_messages"]
    assert audit["missing_setup"] == []


def test_setup_only_gaps_are_kept_separate_from_daily_gaps():
    """Missing a /setup permission is not an outage and must not read like one - /setup must never
    be run on the founder's live server anyway."""
    core = {n for n, _ in ss.CORE_PERMS}
    audit = ss.audit_permissions(_perms(**{n: True for n in core}))
    assert audit["missing_core"] == []
    assert set(audit["missing_setup"]) == {n for n, _ in ss.SETUP_PERMS}


def test_an_object_with_no_permissions_at_all_does_not_crash():
    """A read-only check must never be the thing that fails."""
    audit = ss.audit_permissions(object())
    assert audit["missing_core"] == [n for n, _ in ss.CORE_PERMS]
    assert audit["over_granted"] == []


# ── ticked_permissions: not fooled by Administrator ──────────────────────────

class _RoleWithBits:
    def __init__(self, **perms):
        self.permissions = discord.Permissions(**perms)


class _Me:
    def __init__(self, *roles):
        self.roles = list(roles)


def test_ticked_permissions_reads_the_real_boxes_not_the_administrator_shortcut():
    """THE bug this check exists to avoid, and it nearly shipped.

    Discord defines Administrator as granting everything, so `Member.guild_permissions` returns
    Permissions.all() for anyone holding it. The first live run of this report therefore said
    "everything it needs: present" about a bot whose only real tick was Administrator itself.
    Acting on that - untick Administrator, trust the green - takes Manage Roles away and breaks
    every approval silently."""
    admin_only = _Me(_RoleWithBits(administrator=True))

    # What Discord would tell us, and why we must not use it:
    assert discord.Permissions(administrator=True).administrator
    # What we actually read:
    ticked = ss.ticked_permissions(admin_only)
    assert ticked.administrator, "Administrator itself is genuinely ticked"
    assert not ticked.manage_roles, "but nothing else is - this is the whole point"

    audit = ss.audit_permissions(ticked)
    assert "manage_roles" in audit["missing_core"]
    assert "administrator" in audit["over_granted"]


def test_ticked_permissions_unions_every_role_the_bot_holds():
    me = _Me(_RoleWithBits(send_messages=True), _RoleWithBits(manage_roles=True, connect=True))
    ticked = ss.ticked_permissions(me)
    assert ticked.send_messages and ticked.manage_roles and ticked.connect
    assert not ticked.administrator


def test_ticked_permissions_on_a_bot_with_no_roles_is_empty_not_a_crash():
    assert ss.ticked_permissions(_Me()).value == 0
    assert ss.ticked_permissions(object()).value == 0


# ── admin_roles ──────────────────────────────────────────────────────────────

class _Role:
    def __init__(self, name, admin=False, managed=False, members=()):
        self.name = name
        self.managed = managed
        self.members = list(members)
        self.permissions = type("P", (), {"administrator": admin})()


class _Guild:
    def __init__(self, *roles):
        self.roles = list(roles)


def test_admin_roles_finds_every_role_that_can_do_anything():
    g = _Guild(_Role("everyone"), _Role("Member"),
               _Role("Backup Admin", admin=True), _Role("Grinder", admin=True))
    assert [r.name for r in ss.admin_roles(g)] == ["Backup Admin", "Grinder"]


def test_admin_roles_is_empty_on_a_clean_server():
    assert ss.admin_roles(_Guild(_Role("Member"), _Role("Resident DJ"))) == []


def test_admin_roles_survives_a_guild_it_cannot_read():
    assert ss.admin_roles(object()) == []


def test_two_roles_with_the_same_name_are_told_apart():
    """The live server really does have two roles both called "Grinder" - only one of which holds
    Administrator. Returning names and looking them back up answered about whichever came first,
    so the report could credit the wrong role with dangerous power, or miss it entirely."""
    harmless = _Role("Grinder", admin=False, members=["a", "b", "c"])
    dangerous = _Role("Grinder", admin=True, managed=True, members=["bot"])
    found = ss.admin_roles(_Guild(harmless, dangerous))
    assert len(found) == 1
    assert found[0] is dangerous, "must return the role that actually holds Administrator"
    assert len(found[0].members) == 1, "and its own member count, not the namesake's"


# ── the report must survive a Windows console ────────────────────────────────

def test_the_report_text_is_printable_on_a_plain_windows_console():
    """The first real run of this check STOPPED MID-REPORT and exited 0. A tick mark could not be
    encoded by the default Windows codepage, discord.py routed the error to a logger with no
    handler, and the truncated output looked like a finished clean report. The founder is on
    Windows; keep every fixed string in this file printable there."""
    source = (Path(ss.__file__)).read_text(encoding="utf-8")
    body = "\n".join(ln for ln in source.splitlines() if not ln.lstrip().startswith("#"))
    try:
        body.encode("cp1252")
    except UnicodeEncodeError as e:
        bad = body[e.start:e.end]
        pytest.fail(f"{bad!r} cannot be printed on a default Windows console")


def test_a_failed_check_exits_non_zero():
    """A check that fails must not be mistakable for a check that passed."""
    assert ss.Inspector._failed is False

