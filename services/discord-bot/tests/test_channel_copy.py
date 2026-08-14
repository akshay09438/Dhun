"""The copy in every room: is it short, is it true, and does it actually reach the server?

Written against four things that were live and wrong on 2026-08-11, all found by reading the real
server rather than the code:

1. #read-this-first was showing a post from two versions ago - it advertised `/mix`, `/set` and
   `/songs` (all deleted), pointed at #make-a-mix and #i-made-this (neither exists) and told people
   to grab @Session Crew (deleted). Cause: the posting step SKIPS any channel that already has a
   message, so no copy rewrite could ever land on a server that had been set up once.
2. The copy hardcoded channel names. The founder renamed the rooms by hand, so #best-mixes said
   "hit the pin in #the-grinder" about a channel that does not exist.
3. Neither voice room had an intro, because the posting step only ever walked text channels.
4. /help promised `/grind beat: ... vocal: ...`, a shortcut removed when /grind lost its options.

Each test here failed against the code as it was.
"""
import os
import re

import discord

os.environ.setdefault("DISCORD_TOKEN", "x" * 59)

import server_setup                                    # noqa: E402
import ui                                              # noqa: E402
from test_server_setup import (FakeCategory, FakeChannel, FakeGuild,  # noqa: E402
                               FakeMessage, run_async)

import bot as botmod                                   # noqa: E402


# --- helpers ---------------------------------------------------------------------------

def _text(e: discord.Embed) -> str:
    parts = [e.title or "", e.description or "",
             (e.footer.text or "") if e.footer else ""]
    for f in e.fields:
        parts += [f.name or "", f.value or ""]
    return "\n".join(parts)


def _all_copy_text(guild=None, links=None) -> list[tuple[str, str]]:
    """(where, text) for every word the setup copy can put on the server."""
    guild = guild or FakeGuild()
    links = links if links is not None else server_setup.resolve_links(guild)
    out = [(f"welcome[{i}]", _text(e))
           for i, e in enumerate(server_setup.welcome_embeds(guild, links))]
    for name, (title, body) in server_setup.channel_copy(links).items():
        out.append((f"#{name}", f"{title}\n{body}"))
    out.append(("room", _text(server_setup.room_embed("Bollywood_House", links))))
    return out


def _live_command_names() -> set[str]:
    return {c.name for c in botmod.bot.tree.walk_commands()}


# --- 1. the copy has to actually reach a server that was already set up ------------------

@run_async
async def test_updated_copy_REPLACES_an_old_post_instead_of_being_skipped():
    """The bug behind everything else. A channel that already holds Grinder's own old intro must
    end up carrying the NEW words, not keep the stale ones forever."""
    stale = FakeMessage(bot_author=True)
    stale.embeds = [discord.Embed(title="Welcome to Grinder", description="type /mix to start")]
    ch = FakeChannel("rules", messages=[stale])
    g = FakeGuild(channels=[ch])
    stale.author.id = g.me.id

    await server_setup.run(g)

    assert len(ch.sent) == 0, "an existing intro should be EDITED, not posted beside"
    assert stale.edited, "the stale post was left exactly as it was"
    new = stale.embeds[0]
    assert "/mix" not in _text(new), "the new copy still carries the dead command"
    assert "find out" in _text(new).lower(), "the rules copy did not land"


@run_async
async def test_a_second_run_still_does_not_add_a_second_post():
    """Re-running /setup is the documented fix for a partial failure, so refreshing must never
    turn into spamming."""
    g = FakeGuild()
    await server_setup.run(g)
    first = {c.name: len(c._messages) for c in g.text_channels + g.voice_channels}
    await server_setup.run(g)
    after = {c.name: len(c._messages) for c in g.text_channels + g.voice_channels}
    assert first == after, f"a second run added messages: {first} -> {after}"


@run_async
async def test_a_persons_message_is_NEVER_edited():
    """The safety property of refreshing in place. Grinder may only ever rewrite its own words."""
    theirs = FakeMessage(bot_author=False)
    theirs.embeds = [discord.Embed(title="hi", description="mine")]
    ch = FakeChannel("general", messages=[theirs])
    g = FakeGuild(channels=[ch])

    await server_setup.run(g)

    assert not theirs.edited, "somebody else's message was rewritten"
    assert theirs.embeds[0].title == "hi"


@run_async
async def test_a_grind_card_in_a_room_is_not_mistaken_for_the_intro():
    """A listening room's first bot message is usually a grind card, not an intro. Adopting it
    would rewrite somebody's grind, so only a PINNED post counts outside the read-only channels."""
    card = FakeMessage(bot_author=True)
    card.embeds = [discord.Embed(title="🎧  GRIND #7", description="A x B")]
    room = FakeChannel("Bollywood_House", voice=True, messages=[card])
    g = FakeGuild(channels=[room], categories=[FakeCategory("Grind some music")])
    room.category = g.categories[0]
    card.author.id = g.me.id

    await server_setup.run(g)

    assert not card.edited, "a grind card was overwritten with room copy"
    assert len(room.sent) == 1, "the room should get its own, separate intro"


# --- 2. the copy must not hardcode a channel name -----------------------------------------

@run_async
async def test_the_copy_points_at_real_channels_not_hardcoded_names():
    """The founder renames rooms. A channel MENTION renders whatever the room is called today; a
    typed '#the-grinder' rots the moment it is renamed, and rotted signposts are what a newcomer
    hits first."""
    g = FakeGuild()
    await server_setup.run(g)
    links = server_setup.resolve_links(g)

    # A typed name looks like "#the-grinder". A real mention is "<#123>", so the lookbehind keeps
    # the check on the thing that actually rots.
    hardcoded = []
    for where, text in _all_copy_text(g, links):
        for m in re.findall(r"(?<!<)#[a-z][a-z0-9\-]{2,}", text):
            hardcoded.append((where, m))
    assert not hardcoded, ("typed channel names go stale on a rename, use a <#id> mention: "
                           f"{hardcoded}")


@run_async
async def test_a_renamed_room_is_still_linked_correctly():
    """The exact live case: the grind channel is called #get-shit-done, not #the-grinder."""
    grind = FakeChannel("get-shit-done")
    g = FakeGuild(channels=[grind])
    links = server_setup.resolve_links(g, {"grind": grind.id})
    assert links.grind is grind
    body = "\n".join(t for _w, t in _all_copy_text(g, links))
    assert f"<#{grind.id}>" in body, "the copy never links to the real grind channel"


# --- 3. every room says what it is for, including the voice ones --------------------------

@run_async
async def test_EVERY_channel_gets_an_intro_including_the_voice_rooms():
    """A room with nothing in it tells a newcomer nothing. Voice channels carry a text chat, so
    there is no reason for one to be blank."""
    rooms = [FakeChannel("Bollywood_House", voice=True), FakeChannel("Hollywood_Blends", voice=True)]
    cat = FakeCategory("Grind some music")
    g = FakeGuild(channels=rooms, categories=[cat])
    for r in rooms:
        r.category = cat

    await server_setup.run(g)

    for r in rooms:
        assert r.sent, f"🔊 {r.name} was left with no intro at all"
        assert r._messages[0].pinned, f"🔊 {r.name}'s intro should be pinned"


@run_async
async def test_a_room_intro_is_not_posted_TWICE_when_pinning_is_not_allowed():
    """Found by running the real thing twice. A room's intro was recognised only by its pin, and
    Grinder cannot pin on this server (no Manage Messages), so every run posted another copy. The
    "does it already have one" check cannot depend on a permission the bot might not have."""
    room = FakeChannel("Bollywood_House", voice=True)
    room.pin_allowed = False                     # exactly what the live server does
    cat = FakeCategory("Grind some music")
    g = FakeGuild(channels=[room], categories=[cat])
    room.category = cat

    await server_setup.run(g)
    await server_setup.run(g)

    assert len(room.sent) == 1, f"the room ended up with {len(room.sent)} intros"


@run_async
async def test_the_room_intro_names_the_room_it_is_in():
    """Two rooms with identical copy read as a copy-paste job."""
    links = server_setup.resolve_links(FakeGuild())
    body = _text(server_setup.room_embed("Hollywood_Blends", links))
    assert "Hollywood_Blends" in body


# --- 4. read-this-first: short, spaced, and the right picture -----------------------------

@run_async
async def test_read_this_first_is_ONE_short_post():
    """The founder's note: too much message, too chaotic. Three stacked embeds is a wall; a
    first-timer reading a wall closes the tab."""
    g = FakeGuild()
    embeds = server_setup.welcome_embeds(g, server_setup.resolve_links(g))
    assert len(embeds) == 1, f"the welcome post is {len(embeds)} embeds, it should be one"
    body = _text(embeds[0])
    assert len(body) <= 600, f"{len(body)} characters is not a 30 second read"
    assert len(embeds[0].fields) <= 1, "stacked fields are what made it chaotic"


@run_async
async def test_the_welcome_post_can_breathe():
    """'Give space' - the copy has to carry real blank lines, not one dense paragraph."""
    g = FakeGuild()
    body = server_setup.welcome_embeds(g, server_setup.resolve_links(g))[0].description or ""
    assert body.count("\n\n") >= 3, "no blank lines, so it reads as a wall"


@run_async
async def test_the_welcome_post_shows_the_remix_anything_banner():
    g = FakeGuild()
    e = server_setup.welcome_embeds(g, server_setup.resolve_links(g))[0]
    assert e.image is not None and e.image.url, "the welcome post has no picture"
    assert e.image.url == f"attachment://{server_setup.WELCOME_IMAGE_NAME}"
    assert "remix" in server_setup.WELCOME_IMAGE_NAME, \
        "the founder asked for the 'remix anything' banner, not the wordmark disc"


def test_the_remix_banner_is_actually_shipped():
    import brand
    assert brand.REMIX_BANNER.exists(), f"{brand.REMIX_BANNER} is missing from assets/"


# --- 5. the rules: three lines, and the sign-off ------------------------------------------

def test_the_rules_are_three_lines_or_fewer():
    _title, body = server_setup.channel_copy(server_setup.resolve_links(FakeGuild()))["rules"]
    lines = [ln for ln in body.splitlines() if ln.strip()]
    assert len(lines) <= 3, f"{len(lines)} lines is not the 2 to 3 the founder asked for: {lines}"


def test_the_rules_end_on_the_sign_off():
    _title, body = server_setup.channel_copy(server_setup.resolve_links(FakeGuild()))["rules"]
    last = [ln for ln in body.splitlines() if ln.strip()][-1]
    assert "find out" in last.lower(), f"the rules should end on the sign-off, they end on: {last!r}"


def test_the_rules_still_say_the_thing_that_gets_you_banned():
    """Short is the ask. Losing the one line that names the bannable behaviour is not."""
    _title, body = server_setup.channel_copy(server_setup.resolve_links(FakeGuild()))["rules"]
    low = body.lower()
    assert "slur" in low and "minor" in low, "the hard line has to survive the trim"


# --- 6. the one-line description under each channel name ----------------------------------

@run_async
async def test_a_description_the_founder_wrote_is_KEPT_and_reported():
    """Most of the live descriptions are in the founder's own voice, not the plan's. Replacing
    somebody's words with ours is the same presumption as renaming their server, so a disagreement
    is reported and left for them to settle."""
    show = FakeChannel("best-mixes", topic="Post a mix you're proud of.")
    g = FakeGuild(channels=[show])
    links = server_setup.resolve_links(g, {"showcase": show.id})
    report = server_setup.Report()

    await server_setup.sync_topics(g, report, links)

    assert show.topic == "Post a mix you're proud of.", "the founder's own words were overwritten"
    assert any("best-mixes" in s and "kept" in s for s in report.skipped), \
        "a description that disagrees with the plan should at least be reported"


@run_async
async def test_a_channel_with_no_description_gets_one():
    # Was #rules; that channel was removed on 2026-08-14 so it no longer has copy to sync. The
    # test is about a bare channel GETTING a description, not about which channel, so it moves to
    # one that still exists.
    welcome = FakeChannel("read-this-first", topic=None)
    g = FakeGuild(channels=[welcome])
    await server_setup.sync_topics(g, server_setup.Report(), server_setup.resolve_links(g))
    assert welcome.topic, "#read-this-first had no description at all"


@run_async
async def test_a_description_that_is_already_right_is_left_alone():
    """An edit per run for no change burns rate limit and makes the report lie."""
    ch = FakeChannel("general", topic=server_setup.topic_for("general"))
    g = FakeGuild(channels=[ch])
    await server_setup.sync_topics(g, server_setup.Report(), server_setup.resolve_links(g))
    assert ch.edits == [], "it edited a description that already said the right thing"


# --- 7. nothing anywhere may promise something that does not exist ------------------------

def test_no_copy_mentions_a_command_that_does_not_exist():
    """The live #read-this-first sent people to /mix, /set and /songs, all deleted. A newcomer
    following the welcome post hit three dead ends before reaching anything real."""
    live = _live_command_names()
    bad = []
    for where, text in _all_copy_text():
        for cmd in set(re.findall(r"/([a-z][a-z0-9_-]{1,31})", text)):
            if cmd not in live:
                bad.append((where, f"/{cmd}"))
    assert not bad, f"copy names commands the bot does not have: {sorted(set(bad))}"


def test_help_does_not_promise_grind_options_that_do_not_exist():
    """/help offered `/grind beat: ... vocal: ...`. /grind takes no options, so that is an
    instruction that silently does nothing."""
    grind = botmod.bot.tree.get_command("grind")
    assert not getattr(grind, "parameters", []), \
        "/grind grew options again, so this test needs rewriting rather than the copy"
    text = _text(ui.help_embed())
    assert not re.search(r"/grind\s+\w+\s*:", text), \
        "/help still shows a /grind option form the command does not accept"


def test_no_copy_mentions_a_role_that_was_deleted():
    """@Session Crew was removed. The live welcome post still told people to grab it."""
    gone = set(server_setup.RETIRED_ROLES)
    bad = [(where, r) for where, text in _all_copy_text() for r in gone if r.lower() in text.lower()]
    assert not bad, f"copy points at a deleted role: {bad}"
