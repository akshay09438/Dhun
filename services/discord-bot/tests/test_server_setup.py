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


def run_async(fn):
    """Run an async test body without pulling in pytest-asyncio — every other test in this
    package is sync, and a six-line decorator is cheaper than a new dependency."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


# --- fakes -----------------------------------------------------------------------------

class FakeRole:
    def __init__(self, name):
        self.name = name


class FakeChannel:
    def __init__(self, name, *, voice=False, topic=None, messages=()):
        self.name = name
        self.voice = voice
        self.topic = topic
        self.sent = []
        self.perms = {}
        self._messages = list(messages)

    def history(self, limit=None):
        msgs = self._messages[:limit] if limit else self._messages

        class _Iter:
            def __aiter__(self):
                async def gen():
                    for m in msgs:
                        yield m
                return gen()

        return _Iter()

    def __post_init__(self):
        pass

    async def set_permissions(self, target, **perms):
        self.perms[getattr(target, "name", str(target))] = perms

    async def send(self, *args, **kwargs):
        self.sent.append(kwargs)
        # Sending genuinely leaves a message behind, so history() must see it — without this the
        # fake would let the "is #read-me empty?" guard pass twice and hide a real double-post.
        self._messages.append(kwargs)


class FakeCategory:
    def __init__(self, name):
        self.name = name


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
        self.channels = list(channels)
        self.categories = list(categories)
        self.roles = list(roles)
        self.emojis = list(emojis)
        self.default_role = FakeRole("@everyone")
        self.me = FakeRole("Grinder")          # the bot's own member, for permission overwrites
        self.edits = []
        self.fail_on = set(fail_on)   # names of operations that should raise

    def _maybe_fail(self, op):
        if op in self.fail_on:
            raise discord.Forbidden(_Resp(), "Missing Permissions")

    @property
    def text_channels(self):
        return [c for c in self.channels if not c.voice]

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
        c = FakeCategory(name)
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
        self.channels.append(c)
        return c

    async def create_voice_channel(self, name, **kw):
        self._maybe_fail(f"channel:{name}")
        c = FakeChannel(name, voice=True)
        self.channels.append(c)
        return c

    async def create_role(self, name, **kw):
        self._maybe_fail(f"role:{name}")
        r = FakeRole(name)
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
    assert read_only == {"read-me", "announcements", "best-mixes"}


def test_best_mixes_sits_above_the_open_room_it_is_curated_from():
    """#best-mixes is the channel you point a newcomer at, so it comes first; #i-made-this is the
    open room the good ones get carried up from."""
    showcase = next(c for c in server_setup.STRUCTURE if c.name == "SHOWCASE")
    names = [c.name for c in showcase.channels]
    assert names.index("best-mixes") < names.index("i-made-this")


def test_feedback_exists_exactly_once():
    """The founder asked for a Feedback room; it was already in HANGOUT. Guard against someone
    "adding" a second one later and splitting the replies across two channels."""
    names = [c.name for cat in server_setup.STRUCTURE for c in cat.channels]
    assert names.count("feedback") == 1


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
async def test_the_welcome_post_lands_in_read_me_with_the_logo():
    g = FakeGuild()
    await server_setup.run(g)
    read_me = next(c for c in g.channels if c.name == "read-me")
    assert len(read_me.sent) == 1
    payload = read_me.sent[0]
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
async def test_the_welcome_post_is_not_repeated_into_a_used_channel():
    g = FakeGuild(channels=[FakeChannel("read-me", messages=["someone already posted"])])
    report = await server_setup.run(g)
    read_me = next(c for c in g.channels if c.name == "read-me")
    assert read_me.sent == []
    assert any("welcome post" in s for s in report.skipped)


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
    assert len(g.channels) > 5, "channels should still have been built"
    assert any("grind_mic" in c for c in report.created), "the other emojis should still upload"


@run_async
async def test_a_failed_category_skips_its_channels_but_not_the_next_category():
    g = FakeGuild(fail_on=["category:WELCOME"])
    report = await server_setup.run(g)
    assert any("WELCOME" in f for f in report.failed)
    assert any(c.name == "general" for c in g.channels), "later categories should still build"


@run_async
async def test_the_failure_reason_is_reported_not_just_the_exception_type():
    g = FakeGuild(fail_on=["icon"])
    report = await server_setup.run(g)
    assert any("Missing Permissions" in f for f in report.failed)


# --- the report the founder actually reads ----------------------------------------------

def test_report_embed_lists_created_and_skipped():
    r = server_setup.Report(created=["#general"], skipped=["#read-me"])
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
    g = FakeGuild()
    text = " ".join(
        (e.title or "") + (e.description or "") + " ".join(f.name + f.value for f in e.fields)
        for e in server_setup.welcome_embeds(g)
    )
    for expected in ("/mix", "/set", "/songs", "The Booth", "#i-made-this"):
        assert expected in text, f"the welcome post never mentions {expected}"


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
    for name in ("make-a-mix", "now-playing", "i-made-this", "requests", "feedback"):
        ch = next((c for c in g.channels if c.name == name), None)
        assert ch is not None, f"#{name} was not created"
        assert ch.overwrites is discord.utils.MISSING, f"#{name} should have no overwrites"


@run_async
async def test_a_read_only_channel_still_lets_the_bot_post():
    """The second bug: denying send_messages to @everyone also silenced the bot, so the welcome
    post failed with Missing Permissions in the channel the bot had just made."""
    g = FakeGuild()
    await server_setup.run(g)
    read_me = next(c for c in g.channels if c.name == "read-me")
    ow = read_me.overwrites
    assert ow is not discord.utils.MISSING
    assert ow[g.default_role].send_messages is False, "@everyone should not be able to post"
    assert ow[g.me].send_messages is True, "the bot MUST be able to post its own welcome"


@run_async
async def test_a_rerun_repairs_a_read_only_channel_the_bot_cannot_post_in():
    """A channel from before the fix denies the bot. Skipping it on a re-run would leave the server
    permanently broken, so the idempotent path repairs permissions instead of stepping over it."""
    g = FakeGuild(channels=[FakeChannel("read-me")])   # exists, no bot allow
    await server_setup.run(g)
    read_me = next(c for c in g.channels if c.name == "read-me")
    assert read_me.perms.get("Grinder", {}).get("send_messages") is True


@run_async
async def test_an_ordinary_existing_channel_has_its_permissions_left_alone():
    g = FakeGuild(channels=[FakeChannel("general")])
    await server_setup.run(g)
    general = next(c for c in g.channels if c.name == "general")
    assert general.perms == {}, "a normal channel's permissions must not be touched"
