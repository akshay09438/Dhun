"""Moving an EXISTING server to the new layout: renames, deletions, and the retired role.

The deletion tests are the ones that matter. `/setup` is the only place in this codebase that
destroys something a person could have written, so "it refuses when the channel is not empty" is
not a nice-to-have, it is the whole safety argument for letting it delete at all.
"""
import asyncio
import functools

import server_setup
from test_server_setup import FakeChannel, FakeGuild, FakeMessage, FakeRole


def run_async(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


def _human_message():
    return FakeMessage(bot_author=False)


# --- renames keep the history -----------------------------------------------------------
@run_async
async def test_a_renamed_channel_keeps_its_messages():
    """A rename rather than create-and-delete, precisely so the conversation survives."""
    old = FakeChannel("getting-started", messages=[_human_message()])
    g = FakeGuild(channels=[old])
    report = await server_setup.run(g)
    assert old.name == "read-this-first"
    assert old._messages, "renaming must not lose what was in the channel"
    assert any("renamed" in c for c in report.created)


@run_async
async def test_renaming_does_not_leave_an_empty_duplicate_beside_it():
    """The rename runs before the create step for exactly this reason."""
    g = FakeGuild(channels=[FakeChannel("i-made-this")])
    await server_setup.run(g)
    assert [c.name for c in g.text_channels].count("fresh-grinds") == 1


@run_async
async def test_a_rename_is_skipped_if_the_new_channel_already_exists():
    g = FakeGuild(channels=[FakeChannel("getting-started"), FakeChannel("read-this-first")])
    await server_setup.run(g)
    assert "getting-started" in [c.name for c in g.text_channels], \
        "with both present, the old one is left alone rather than clobbering the new"


# --- deletions, and the refusal that makes them safe -------------------------------------
@run_async
async def test_an_empty_retired_channel_is_deleted():
    g = FakeGuild(channels=[FakeChannel("feedback")])
    report = await server_setup.run(g)
    assert "feedback" in g.deleted_channels
    assert any("feedback" in c and "deleted" in c for c in report.created)


@run_async
async def test_a_retired_channel_WITH_REAL_MESSAGES_IS_NEVER_DELETED():
    """The safety property. Losing somebody's conversation to a config change is indefensible, so
    the destructive step refuses and says why, and the founder decides having actually seen it."""
    ch = FakeChannel("feedback", messages=[_human_message(), _human_message()])
    g = FakeGuild(channels=[ch])
    report = await server_setup.run(g)
    assert ch.deleted is False
    assert "feedback" not in g.deleted_channels
    assert any("feedback" in s and "kept" in s for s in report.skipped)


@run_async
async def test_a_channel_holding_only_the_bots_own_posts_is_still_deleted():
    """Grinder's own welcome post is not somebody's conversation."""
    ch = FakeChannel("feedback", messages=[FakeMessage(bot_author=True)])
    g = FakeGuild(channels=[ch])
    await server_setup.run(g)
    assert "feedback" in g.deleted_channels


@run_async
async def test_the_second_voice_channel_goes_but_not_while_someone_is_in_it():
    """Two rooms guarantee both are empty. But cutting a room out from under someone mid-listen
    is worse than leaving it there."""
    empty = FakeChannel("General", voice=True)
    g = FakeGuild(channels=[empty])
    await server_setup.run(g)
    assert "General" in g.deleted_channels

    occupied = FakeChannel("General", voice=True, members=["somebody"])
    g2 = FakeGuild(channels=[occupied])
    report = await server_setup.run(g2)
    assert occupied.deleted is False
    assert any("General" in s and "kept" in s for s in report.skipped)


# --- the retired role --------------------------------------------------------------------
@run_async
async def test_session_crew_is_removed():
    """An opt-in role with no way to opt in. Only an admin could hand it out, so the promise
    'grab @Session Crew to be pinged' was never actually possible."""
    g = FakeGuild(roles=[FakeRole("Session Crew")])
    g.roles[0].guild = g
    report = await server_setup.run(g)
    assert "Session Crew" in g.deleted_roles
    assert "Session Crew" not in [r.name for r in g.roles]
    assert any("Session Crew" in c for c in report.created)


@run_async
async def test_resident_dj_is_left_alone():
    g = FakeGuild(roles=[FakeRole("Resident DJ")])
    g.roles[0].guild = g
    await server_setup.run(g)
    assert "Resident DJ" in [r.name for r in g.roles]


# --- the copy ----------------------------------------------------------------------------
@run_async
async def test_every_room_gets_a_pinned_message_saying_what_it_is_for():
    g = FakeGuild()
    await server_setup.run(g)
    for name in server_setup.CHANNEL_COPY:
        ch = next(c for c in g.text_channels if c.name == name)
        assert len(ch.sent) == 1, f"#{name} should get exactly one pinned post"
        assert ch._messages[0].pinned is True, f"#{name}'s post should be pinned"


@run_async
async def test_a_second_run_does_not_repost_the_copy():
    """Running /setup twice is the documented fix for a partial failure, so it must not spam."""
    g = FakeGuild()
    await server_setup.run(g)
    await server_setup.run(g)
    for name in server_setup.CHANNEL_COPY:
        ch = next(c for c in g.text_channels if c.name == name)
        assert len(ch.sent) == 1, f"#{name} was posted into twice"


@run_async
async def test_setup_reports_the_channel_ids_the_bot_needs():
    """Without these three ids the Booth, the status message and 📌 all silently do nothing, so
    the report has to hand them over rather than leave the founder hunting."""
    g = FakeGuild()
    report = await server_setup.run(g)
    assert set(report.channel_ids) == {
        "GRINDER_BOOTH_CHANNEL_ID", "GRINDER_MAIN_CHANNEL_ID", "GRINDER_SHOWCASE_CHANNEL_ID"}
    assert all(isinstance(v, int) for v in report.channel_ids.values())


# --- the leftover headers ----------------------------------------------------------------
@run_async
async def test_an_empty_leftover_category_is_removed():
    """Moving every channel into the new headers leaves the old ones as empty labels. Three dead
    headers at the top of the sidebar is the half-finished look this restructure exists to fix."""
    from test_server_setup import FakeCategory
    old = FakeCategory("SHOWCASE")
    g = FakeGuild(categories=[old])
    await server_setup.run(g)
    assert "SHOWCASE" in g.deleted_categories


@run_async
async def test_a_category_that_still_holds_a_channel_is_left_completely_alone():
    from test_server_setup import FakeCategory
    old = FakeCategory("SHOWCASE")
    keeper = FakeChannel("off-topic")
    g = FakeGuild(channels=[keeper], categories=[old])
    keeper.category = old
    report = await server_setup.run(g)
    assert "SHOWCASE" not in g.deleted_categories
    assert any("SHOWCASE" in s and "kept" in s for s in report.skipped)
