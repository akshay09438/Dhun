"""Tests for `/setup` — the command that builds the community server.

No Discord gateway and no token: a small fake guild records what would have been created. The
behaviour that matters most here is IDEMPOTENCY — the first run can partly fail on a rate limit or
a missing permission, so the fix has to be "run it again", which is only true if a second run never
duplicates anything.
"""
import asyncio
import functools

import discord

import brand
import server_setup
import ui


def run_async(fn):
    """Run an async test body without pulling in pytest-asyncio — every other test in this
    package is sync, and a six-line decorator is cheaper than a new dependency."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


# --- fakes -----------------------------------------------------------------------------

class FakeRole:
    _next_id = [500]

    def __init__(self, name, guild=None):
        self.name = name
        self.guild = guild
        FakeRole._next_id[0] += 1
        self.id = FakeRole._next_id[0]

    async def delete(self, reason=None):
        if self.guild is not None:
            self.guild.roles.remove(self)
            self.guild.deleted_roles.append(self.name)


class FakeChannel:
    _next_id = [1000]
    # Set False on a channel to model a server where the bot lacks Manage Messages, which is the
    # live situation and is why nearly every intro on the real server is unpinned.
    pin_allowed = True

    def __init__(self, name, *, voice=False, topic=None, messages=(), members=()):
        self.name = name
        self.voice = voice
        self.topic = topic
        self.sent = []
        self.perms = {}
        self.category = None
        self.edits = []
        self._messages = list(messages)
        self.members = list(members)
        self.deleted = False
        self.guild = None
        FakeChannel._next_id[0] += 1
        self.id = FakeChannel._next_id[0]

    @staticmethod
    def _aiter(msgs):
        class _Iter:
            def __aiter__(self):
                async def gen():
                    for m in msgs:
                        yield m
                return gen()

        return _Iter()

    def history(self, limit=None, oldest_first=False):
        # discord.py hands back NEWEST first unless asked otherwise. The fake used to always give
        # oldest-first, which would have hidden a refresh that adopted the wrong message.
        msgs = list(self._messages) if oldest_first else list(reversed(self._messages))
        return self._aiter(msgs[:limit] if limit else msgs)

    def pins(self):
        # discord.py 2.7 made this an async ITERATOR; awaiting it is deprecated. Refreshing copy in
        # place depends on finding the pinned intro, so the fake mirrors the current shape.
        return self._aiter([m for m in self._messages if m.pinned])

    def __post_init__(self):
        pass

    async def edit(self, **kwargs):
        self.edits.append(kwargs)
        if "category" in kwargs:
            self.category = kwargs["category"]
        # discord.py really does rename the channel. A fake that only recorded the call let a
        # rename "succeed" while the channel kept its old name.
        if "name" in kwargs:
            self.name = kwargs["name"]
        # Same trap for the topic: recording the call without applying it would let a stale
        # description "get fixed" in the test and stay wrong on the real server.
        if "topic" in kwargs:
            self.topic = kwargs["topic"]

    async def set_permissions(self, target, **perms):
        self.perms[getattr(target, "name", str(target))] = perms

    async def send(self, *args, **kwargs):
        self.sent.append(kwargs)
        # Sending genuinely leaves a message behind, so history() must see it - without this the
        # fake would let the "is it empty?" guard pass twice and hide a real double-post.
        msg = FakeMessage(kwargs)
        msg.embeds = list(kwargs.get("embeds") or ([kwargs["embed"]] if kwargs.get("embed") else []))
        msg.author.id = getattr(getattr(self.guild, "me", None), "id", 1)
        msg._pin_allowed = self.pin_allowed
        self._messages.append(msg)
        return msg

    async def delete(self, reason=None):
        self.deleted = True
        if self.guild is not None:
            self.guild.deleted_channels.append(self.name)


class FakeMessage:
    """discord.py returns a Message from send(), and setup pins it. A fake that returned None hid
    that entirely - the same class of gap that let six real /setup bugs through on 2026-08-11."""

    _next_id = [1]

    def __init__(self, payload=None, *, bot_author=True):
        self.payload = payload or {}
        self.pinned = False
        FakeMessage._next_id[0] += 1
        self.id = FakeMessage._next_id[0]
        # `id` matters as much as `bot`: refreshing copy in place is only safe because Grinder can
        # tell ITS OWN post from another bot's, and a fake with no id let that check pass for free.
        self.author = type("A", (), {"bot": bot_author, "display_name": "someone",
                                     "id": 1 if bot_author else 99})()
        self.embeds = []
        self.attachments = []
        self.edited = False

    async def pin(self, reason=None):
        if not getattr(self, "_pin_allowed", True):
            raise discord.HTTPException(_Resp(), "Missing Permissions")
        self.pinned = True

    async def edit(self, **kwargs):
        # discord.py replaces the embeds outright, so a refresh that forgets one drops it.
        self.edited = True
        if "embeds" in kwargs:
            self.embeds = list(kwargs["embeds"] or [])
        elif "embed" in kwargs:
            self.embeds = [kwargs["embed"]] if kwargs["embed"] else []
        if "attachments" in kwargs:
            self.attachments = list(kwargs["attachments"] or [])


class FakeCategory:
    _next_id = [9000]

    def __init__(self, name, guild=None):
        self.name = name
        self.guild = guild
        FakeCategory._next_id[0] += 1
        self.id = FakeCategory._next_id[0]

    @property
    def channels(self):
        if self.guild is None:
            return []
        return [c for c in self.guild.text_channels + self.guild.voice_channels
                if c.category is self]

    async def delete(self, reason=None):
        if self.guild is not None:
            self.guild.categories.remove(self)
            self.guild.deleted_categories.append(self.name)


class FakeEmoji:
    def __init__(self, name):
        self.name = name


class FakeGuild:
    """Enough of discord.Guild for server_setup, recording every mutation."""

    def __init__(self, *, icon=None, features=(), channels=(), categories=(),
                 roles=(), emojis=(), fail_on=()):
        self.name = "Grinder"
        self.icon = icon
        self.features = list(features)
        self._channels = list(channels)
        self.categories = list(categories)
        self.roles = list(roles)
        self.emojis = list(emojis)
        self.default_role = FakeRole("@everyone")
        self.me = FakeRole("Grinder")          # the bot's own member, for permission overwrites
        self.me.id = 1                          # matches FakeMessage's bot author id
        self.edits = []
        self.deleted_channels = []
        self.deleted_roles = []
        self.deleted_categories = []
        self.fail_on = set(fail_on)   # names of operations that should raise
        for c in self._channels:
            c.guild = self
        for cat in self.categories:
            cat.guild = self

    def _maybe_fail(self, op):
        if op in self.fail_on:
            raise discord.Forbidden(_Resp(), "Missing Permissions")

    @property
    def channels(self):
        # Faithful to discord.py: this view includes CATEGORIES as well as text/voice channels,
        # which is how a channel named "welcome" wrongly matched a category named "WELCOME".
        return self._channels + self.categories

    @property
    def text_channels(self):
        return [c for c in self._channels if not c.voice and not c.deleted]

    @property
    def voice_channels(self):
        return [c for c in self._channels if c.voice and not c.deleted]

    def get_channel(self, cid):
        """Resolving a CONFIGURED id is how the copy finds the founder's renamed rooms, so the
        fake needs the same lookup discord.py offers."""
        for c in self._channels + self.categories:
            if getattr(c, "id", None) == cid and not getattr(c, "deleted", False):
                return c
        return None

    async def edit(self, **kwargs):
        self._maybe_fail("edit")
        if "icon" in kwargs:
            self._maybe_fail("icon")
            self.icon = "set"
        if "banner" in kwargs:
            self._maybe_fail("banner")
            self.banner = "set"
        self.edits.append(kwargs)

    async def create_category(self, name, **kw):
        self._maybe_fail(f"category:{name}")
        c = FakeCategory(name, guild=self)
        self.categories.append(c)
        return c

    async def create_text_channel(self, name, **kw):
        self._maybe_fail(f"channel:{name}")
        # Faithful to discord.py: it rejects overwrites=None with exactly this TypeError. The fake
        # used to accept None happily, which is why the first real /setup run failed on 5 channels
        # while every test passed.
        ow = kw.get("overwrites", discord.utils.MISSING)
        if ow is None:
            raise TypeError("overwrites parameter expects a dict.")
        c = FakeChannel(name, topic=kw.get("topic"))
        c.overwrites = ow
        c.category = kw.get("category")
        self._channels.append(c)
        return c

    async def create_voice_channel(self, name, **kw):
        self._maybe_fail(f"channel:{name}")
        c = FakeChannel(name, voice=True)
        c.category = kw.get("category")
        self._channels.append(c)
        return c

    async def create_role(self, name, **kw):
        self._maybe_fail(f"role:{name}")
        r = FakeRole(name, guild=self)
        self.roles.append(r)
        return r

    async def create_custom_emoji(self, *, name, image, **kw):
        self._maybe_fail(f"emoji:{name}")
        e = FakeEmoji(name)
        self.emojis.append(e)
        return e


class _Resp:
    status = 403
    reason = "Forbidden"


# --- the structure itself ---------------------------------------------------------------

def test_channel_names_are_unique():
    """A duplicate name would make the idempotency check match the wrong channel."""
    names = [c.name for cat in server_setup.STRUCTURE for c in cat.channels]
    assert len(names) == len(set(names))


def test_structure_has_exactly_one_voice_channel_for_the_booth():
    voices = [c for cat in server_setup.STRUCTURE for c in cat.channels if c.voice]
    assert [c.name for c in voices] == [server_setup.VOICE_CHANNEL]
    assert voices[0].label == "The Booth", "the voice channel should read nicely, not as a slug"


def test_the_name_a_channel_is_created_with_is_the_name_it_is_looked_up_by():
    """The bug this pins: the booth was created as "The Booth" but looked up as "the-booth", so
    every re-run of /setup added another voice channel."""
    for cat in server_setup.STRUCTURE:
        for c in cat.channels:
            assert c.label == (c.display or c.name)


def test_the_channels_chatter_would_ruin_are_read_only():
    """A welcome channel that fills with chatter stops being a welcome channel, and a curated
    "best of" that anyone can post into stops being curated."""
    read_only = {c.name for cat in server_setup.STRUCTURE for c in cat.channels if c.read_only}
    assert read_only == {"read-this-first", "rules", "announcements"}


def test_best_mixes_is_the_open_music_room_not_a_locked_showcase():
    """#the-grinder is the ONE music room: you run /grind there
    AND the good ones live there. If it were read-only there would be nowhere to make a mix."""
    ch = next(c for cat in server_setup.STRUCTURE for c in cat.channels if c.name == "the-grinder")
    assert ch.read_only is False


def test_requests_exists_exactly_once():
    """The founder asked for a Feedback room; it was already in HANGOUT. Guard against someone
    "adding" a second one later and splitting the replies across two channels."""
    names = [c.name for cat in server_setup.STRUCTURE for c in cat.channels]
    assert names.count("requests") == 1


def test_every_text_channel_explains_itself():
    for cat in server_setup.STRUCTURE:
        for c in cat.channels:
            if not c.voice:
                assert c.topic, f"#{c.name} has no topic"


# --- a full build on an empty server ----------------------------------------------------

@run_async
async def test_run_builds_everything_on_an_empty_server():
    g = FakeGuild()
    report = await server_setup.run(g)

    assert [c.name for c in g.categories] == [c.name for c in server_setup.STRUCTURE]
    made = {c.name for c in g.channels}
    for cat in server_setup.STRUCTURE:
        for c in cat.channels:
            assert c.label in made, f"{c.label} was never created"
    assert {r.name for r in g.roles} >= {name for name, _, _ in server_setup.ROLES}
    assert {e.name for e in g.emojis} == {n for n, _ in brand.emoji_files()}
    assert g.icon == "set"
    assert not report.failed


@run_async
async def test_the_welcome_post_lands_in_welcome_with_the_logo():
    g = FakeGuild()
    await server_setup.run(g)
    welcome = next(c for c in g.channels if c.name == "read-this-first")
    assert len(welcome.sent) == 1
    payload = welcome.sent[0]
    assert payload["embeds"], "the welcome post should be embeds, not plain text"
    assert payload["files"], "the wordmark should be attached"


# --- idempotency: the property that makes "just run it again" true ----------------------

@run_async
async def test_a_second_run_creates_nothing_new():
    g = FakeGuild()
    await server_setup.run(g)
    before = (len(g.categories), len(g.channels), len(g.roles), len(g.emojis))

    second = await server_setup.run(g)

    assert (len(g.categories), len(g.channels), len(g.roles), len(g.emojis)) == before
    assert not second.created, f"second run created: {second.created}"
    assert second.skipped


@run_async
async def test_an_existing_channel_is_left_alone():
    g = FakeGuild(channels=[FakeChannel("general", topic="do not touch")])
    await server_setup.run(g)
    generals = [c for c in g.channels if c.name == "general"]
    assert len(generals) == 1
    assert generals[0].topic == "do not touch"


@run_async
async def test_an_icon_the_founder_already_chose_is_not_overwritten():
    g = FakeGuild(icon="the founder's own art")
    report = await server_setup.run(g)
    assert g.icon == "the founder's own art"
    assert any("server icon" in s for s in report.skipped)


@run_async
async def test_the_welcome_post_is_REFRESHED_not_repeated():
    """This used to assert "post nothing at all if the channel has anything in it". That rule is
    what left the live #read-this-first advertising three deleted commands through two rewrites of
    this file, so the guard is now the thing actually worth guarding: Grinder's own welcome gets
    the NEW words, and there is still only one of it."""
    ch = FakeChannel("read-this-first")
    g = FakeGuild(channels=[ch])
    await server_setup.run(g)
    assert len(ch.sent) == 1

    # A rewrite of the copy, exactly as a real session would produce.
    original = server_setup.welcome_embeds
    try:
        server_setup.welcome_embeds = lambda guild, links=None: [
            discord.Embed(title="you're in.", description="completely new words")]
        await server_setup.run(g)
    finally:
        server_setup.welcome_embeds = original

    assert len(ch.sent) == 1, "the new copy was posted beside the old one instead of replacing it"
    assert ch._messages[0].embeds[0].description == "completely new words"


@run_async
async def test_a_stranger_posting_first_does_not_stop_grinder_introducing_itself():
    """Someone talking in the welcome channel before setup ran must not leave the server with no
    welcome at all - and their message must not be touched."""
    theirs = FakeMessage(bot_author=False)
    theirs.embeds = [discord.Embed(title="hello?")]
    ch = FakeChannel("read-this-first", messages=[theirs])
    g = FakeGuild(channels=[ch])

    await server_setup.run(g)

    assert len(ch.sent) == 1, "no welcome post was written"
    assert not theirs.edited, "somebody else's message was rewritten"


# --- the banner, which Discord gates behind boosts --------------------------------------

@run_async
async def test_the_banner_is_skipped_with_a_plain_reason_when_the_server_cannot_have_one():
    g = FakeGuild()
    report = await server_setup.run(g)
    note = next(s for s in report.skipped if s.startswith("banner"))
    assert "boost" in note.lower(), "the founder should be told WHY there's no banner"
    assert not any("banner" in f for f in report.failed), "not having boosts is not a failure"


@run_async
async def test_the_banner_is_applied_once_the_server_is_boosted():
    g = FakeGuild(features=["BANNER"])
    report = await server_setup.run(g)
    assert "banner" in report.created


# --- failure handling -------------------------------------------------------------------

@run_async
async def test_one_failing_step_does_not_abort_the_rest():
    """A missing emoji permission must not cost you the channels."""
    g = FakeGuild(fail_on=["emoji:grind_fire"])
    report = await server_setup.run(g)
    assert any("grind_fire" in f for f in report.failed)
    assert len(g.channels) >= 4, "channels should still have been built"
    assert any("grind_mic" in c for c in report.created), "the other emojis should still upload"


@run_async
async def test_a_failed_category_does_not_abort_the_whole_run():
    g = FakeGuild(fail_on=["category:⚙️ GRIND"])
    report = await server_setup.run(g)
    assert any("GRIND" in f for f in report.failed)
    # the run must still COMPLETE (emojis, icon) rather than abort on the first bad step
    assert g.icon == "set"
    assert {e.name for e in g.emojis} == {n for n, _ in brand.emoji_files()}


@run_async
async def test_the_failure_reason_is_reported_not_just_the_exception_type():
    g = FakeGuild(fail_on=["icon"])
    report = await server_setup.run(g)
    assert any("Missing Permissions" in f for f in report.failed)


# --- the report the founder actually reads ----------------------------------------------

def test_report_embed_lists_created_and_skipped():
    r = server_setup.Report(created=["#general"], skipped=["#welcome"])
    e = server_setup.report_embed(r, "Grinder")
    names = [f.name for f in e.fields]
    assert any("Created (1)" in n for n in names)
    assert any("Already there (1)" in n for n in names)
    assert e.colour.value == brand.PRIMARY


def test_report_embed_turns_red_and_explains_when_something_failed():
    r = server_setup.Report(failed=["#general — Missing Permissions"])
    e = server_setup.report_embed(r, "Grinder")
    assert e.colour.value == brand.FAIL
    assert "permission" in (e.footer.text or "").lower()


def test_report_embed_says_how_many_it_left_out_rather_than_silently_truncating():
    r = server_setup.Report(created=[f"#c{i}" for i in range(30)])
    e = server_setup.report_embed(r, "Grinder")
    body = next(f.value for f in e.fields if "Created" in f.name)
    assert "and 12 more" in body


def test_welcome_embeds_tell_a_first_timer_what_to_do():
    """The list used to include the literal strings "#the-grinder" and "#fresh-grinds". Those are
    the hardcoded names that went stale the moment the founder renamed a room, so the requirement
    is now the SAME promise made durably: name the command, and LINK the rooms."""
    g = FakeGuild()
    grind = FakeChannel("get-shit-done")          # deliberately not the planned name
    show = FakeChannel("best-mixes")
    g._channels += [grind, show]
    for c in (grind, show):
        c.guild = g
    links = server_setup.resolve_links(g, {"grind": grind.id, "showcase": show.id})

    text = " ".join(
        (e.title or "") + (e.description or "") + " ".join(f.name + f.value for f in e.fields)
        for e in server_setup.welcome_embeds(g, links)
    )
    assert "/grind" in text, "the welcome post never names the one command that matters"
    assert f"<#{grind.id}>" in text, "it never points at the channel to grind in"
    assert f"<#{show.id}>" in text, "it never points at where the good ones go"
    for reaction in ui.REACTIONS:
        assert reaction in text, f"the welcome post never mentions the {reaction} reaction"


# --- command sync: /setup has to EXIST in a server you just made -------------------------

class FakeTree:
    def __init__(self, refuse=()):
        self.copied, self.synced = [], []
        self.refuse = set(refuse)

    def copy_global_to(self, *, guild):
        self.copied.append(guild.id)

    async def sync(self, *, guild=None):
        gid = getattr(guild, "id", None)
        if gid in self.refuse:
            raise discord.Forbidden(_Resp(), "Missing Access")
        self.synced.append(gid)


class FakeGuildRef:
    def __init__(self, gid, name="g"):
        self.id = gid
        self.name = name


class SyncOnly:
    """Just the sync behaviour, lifted off the bot so it can be tested without a gateway."""
    def __init__(self, tree):
        self.tree = tree
        self._synced_guilds = set()

    sync_to_guilds = None  # bound below


def _make(tree):
    import bot as botmod
    s = SyncOnly(tree)
    s.sync_to_guilds = botmod.PromptDJBot.sync_to_guilds.__get__(s, SyncOnly)
    return s


@run_async
async def test_commands_are_synced_to_every_guild_the_bot_is_in():
    """The gotcha this pins: commands used to sync only to DISCORD_GUILD_ID, so /setup didn't
    exist in a server you'd just created — exactly where you need it."""
    tree = FakeTree()
    s = _make(tree)
    await s.sync_to_guilds([FakeGuildRef(1), FakeGuildRef(2)])
    assert tree.synced == [1, 2]


@run_async
async def test_a_reconnect_does_not_resync_the_same_guild():
    """on_ready fires again on every reconnect; re-syncing each time would burn the rate limit."""
    tree = FakeTree()
    s = _make(tree)
    await s.sync_to_guilds([FakeGuildRef(1)])
    await s.sync_to_guilds([FakeGuildRef(1)])
    assert tree.synced == [1]


@run_async
async def test_one_guild_refusing_does_not_block_the_others():
    tree = FakeTree(refuse={1})
    s = _make(tree)
    await s.sync_to_guilds([FakeGuildRef(1), FakeGuildRef(2)])
    assert tree.synced == [2]


@run_async
async def test_a_refused_guild_is_retried_next_time_rather_than_marked_done():
    tree = FakeTree(refuse={1})
    s = _make(tree)
    await s.sync_to_guilds([FakeGuildRef(1)])
    tree.refuse.clear()                     # permission fixed, e.g. re-invited properly
    await s.sync_to_guilds([FakeGuildRef(1)])
    assert tree.synced == [1]


# --- the two bugs the first real /setup run exposed ---------------------------------------

@run_async
async def test_an_ordinary_channel_is_created_without_None_overwrites():
    """The bug: overwrites=None raises "overwrites parameter expects a dict" in discord.py, so all
    five non-read-only channels silently failed to be created on the first real run."""
    g = FakeGuild()
    report = await server_setup.run(g)
    assert not report.failed, report.failed
    for name in ("the-grinder", "general"):
        ch = next((c for c in g.channels if c.name == name), None)
        assert ch is not None, f"#{name} was not created"
        assert ch.overwrites is discord.utils.MISSING, f"#{name} should have no overwrites"


@run_async
async def test_a_read_only_channel_still_lets_the_bot_post():
    """The second bug: denying send_messages to @everyone also silenced the bot, so the welcome
    post failed with Missing Permissions in the channel the bot had just made."""
    g = FakeGuild()
    await server_setup.run(g)
    welcome = next(c for c in g.channels if c.name == "read-this-first")
    ow = welcome.overwrites
    assert ow is not discord.utils.MISSING
    assert ow[g.default_role].send_messages is False, "@everyone should not be able to post"
    assert ow[g.me].send_messages is True, "the bot MUST be able to post its own welcome"


@run_async
async def test_a_rerun_repairs_a_read_only_channel_the_bot_cannot_post_in():
    """A channel from before the fix denies the bot. Skipping it on a re-run would leave the server
    permanently broken, so the idempotent path repairs permissions instead of stepping over it."""
    g = FakeGuild(channels=[FakeChannel("read-this-first")])   # exists, no bot allow
    await server_setup.run(g)
    welcome = next(c for c in g.channels if c.name == "read-this-first")
    assert welcome.perms.get("Grinder", {}).get("send_messages") is True


@run_async
async def test_an_ordinary_existing_channel_has_its_permissions_left_alone():
    g = FakeGuild(channels=[FakeChannel("general")])
    await server_setup.run(g)
    general = next(c for c in g.channels if c.name == "general")
    assert general.perms == {}, "a normal channel's permissions must not be touched"


# --- refreshing branding onto an already-branded server ------------------------------------

@run_async
async def test_refresh_branding_replaces_an_existing_server_icon():
    """How updated artwork reaches a server that /setup already branded. Without this the icon is
    whatever the FIRST run set, forever."""
    g = FakeGuild(icon="the old G mark")
    report = await server_setup.run(g, refresh_branding=True)
    assert g.icon == "set"
    assert any("server icon" in c for c in report.created)


@run_async
async def test_without_the_flag_an_existing_icon_is_still_left_alone():
    """The default has to stay safe: an icon the founder chose themselves is not ours to replace."""
    g = FakeGuild(icon="the founder's own art")
    report = await server_setup.run(g)
    assert g.icon == "the founder's own art"
    note = next(s for s in report.skipped if "server icon" in s)
    assert "refresh_branding" in note, "the skip note should say how to override it"


@run_async
async def test_refresh_branding_on_a_bare_server_still_just_sets_the_icon():
    g = FakeGuild()
    report = await server_setup.run(g, refresh_branding=True)
    assert g.icon == "set"
    assert not report.failed


# --- the deliberately small layout (founder call 2026-08-11) --------------------------------

def test_the_server_stays_small_on_purpose():
    """Cut from ten channels to four. A near-empty server with ten rooms reads as abandoned - the
    few people there get spread thin and every channel looks dead. This pins the decision so it
    isn't quietly grown back one channel at a time."""
    channels = [c for cat in server_setup.STRUCTURE for c in cat.channels]
    assert len(server_setup.STRUCTURE) == 3, "three headers; more is scaffolding for a crowd"
    assert len(channels) == 8, [c.label for c in channels]
    assert [c.label for c in channels] == [
        "read-this-first", "rules", "announcements",
        "the-grinder", "fresh-grinds", "The Booth",
        "general", "requests"]


def test_there_is_somewhere_to_actually_make_a_mix():
    """The one thing the layout must not lose: a channel a normal member can run /mix in. Every
    read-only channel would leave the product unusable."""
    usable = [c for cat in server_setup.STRUCTURE for c in cat.channels
              if not c.voice and not c.read_only]
    assert usable, "every text channel is read-only; nobody could use /mix"


def test_there_is_a_voice_channel_for_listening_together():
    voices = [c for cat in server_setup.STRUCTURE for c in cat.channels if c.voice]
    assert [c.label for c in voices] == ["The Booth"]


# --- leftover channels are reported, never deleted -----------------------------------------

@run_async
async def test_channels_not_in_the_plan_are_reported():
    """Shrinking the layout leaves the old channels behind, because /setup only ever creates. The
    founder needs to be TOLD which ones those are."""
    g = FakeGuild(channels=[FakeChannel("now-playing"), FakeChannel("off-topic")])
    report = await server_setup.run(g)
    assert "#now-playing" in report.extra
    assert "#off-topic" in report.extra


@run_async
async def test_a_planned_channel_is_never_reported_as_extra():
    g = FakeGuild()
    report = await server_setup.run(g)
    assert report.extra == [], report.extra


@run_async
async def test_leftover_channels_are_not_deleted():
    """Deleting a channel could destroy conversation, so /setup reports and stops. This pins that
    it never quietly removes anything."""
    g = FakeGuild(channels=[FakeChannel("off-topic", messages=["something someone said"])])
    await server_setup.run(g)
    assert any(c.name == "off-topic" for c in g.channels), "it must still be there"


def test_the_report_tells_you_how_to_remove_a_leftover():
    r = server_setup.Report(extra=["#now-playing"])
    e = server_setup.report_embed(r, "Grinder")
    field = next(f for f in e.fields if "Not in the plan" in f.name)
    assert "Delete Channel" in field.value, "say HOW, not just that they exist"
    assert "won't delete them for you" in field.value


# --- bugs the second real /setup run exposed ------------------------------------------------

@run_async
async def test_a_channel_is_created_even_when_a_CATEGORY_shares_its_name():
    """The bug: guild.channels includes CATEGORIES, so looking up a channel called "welcome" matched
    the leftover "WELCOME" category. /setup reported "#welcome already there" and then failed with
    "#welcome doesn't exist" when it tried to post the welcome into it."""
    g = FakeGuild(categories=[FakeCategory("WELCOME")])
    report = await server_setup.run(g)
    assert any(c.name == "read-this-first" for c in g.text_channels), \
        "#welcome was never created; it matched the WELCOME category"
    assert not report.failed, report.failed


@run_async
async def test_the_welcome_post_lands_when_a_category_shares_the_channel_name():
    g = FakeGuild(categories=[FakeCategory("WELCOME")])
    await server_setup.run(g)
    welcome = next(c for c in g.text_channels if c.name == "read-this-first")
    assert welcome.sent, "the welcome post should have been written"


@run_async
async def test_an_existing_channel_is_moved_into_the_planned_category():
    """After the layout changed, #best-mixes and #feedback were left under their old SHOWCASE and
    HANGOUT headers while the new GRINDER category sat empty. Existing channels have to be adopted
    into the plan, not just left where they were."""
    old = FakeCategory("SHOWCASE")
    stray = FakeChannel("the-grinder")          # a PLANNED channel, sitting under the old header
    stray.category = old
    g = FakeGuild(channels=[stray], categories=[old])
    await server_setup.run(g)
    moved = next(c for c in g.text_channels if c.name == "the-grinder")
    assert moved is stray, "the existing channel should be adopted, not replaced by a new one"
    assert moved.category is not None and "GRIND" in moved.category.name, \
        f"still in {getattr(moved.category, 'name', None)}"


@run_async
async def test_a_channel_already_in_the_right_category_is_not_edited():
    """Don't spend an API call re-setting what's already correct."""
    g = FakeGuild()
    await server_setup.run(g)
    for c in g.text_channels:
        moves = [e for e in c.edits if "category" in e]
        assert not moves, f"#{c.name} was moved despite already being right"
