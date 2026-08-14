"""The door opens below 30 REAL community members.

Founder, 2026-08-14: "before 30 members anyone can join", and when asked what counts:
"real people, excluding the Grinder bots + my two accounts (akshay5397 & bearwolf101)."

THE TESTS THAT MATTER MOST ARE THE COUNTING ONES, not the happy path. An implementation that
trusts Discord's own member number passes "under 30 they walk in" and "at 30 they get the form"
and STILL shuts the door four people early, because Discord counts the two Grinder identities and
the founder's two operator accounts as members. That is the bug this file exists to prevent.

Design: docs/door-open-below-30-design.md
"""
import asyncio
import os

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "x" * 59)

import door  # noqa: E402
import store  # noqa: E402


@pytest.fixture(autouse=True)
def _tmp_store(tmp_path):
    store.reset_for_tests(tmp_path / "grinder.db")
    yield
    store.reset_for_tests()


@pytest.fixture(autouse=True)
def _clean_announce():
    door._announced_shut.clear()
    yield
    door._announced_shut.clear()


# --- the world -----------------------------------------------------------------------------

OWNER_ID = 5397          # stands in for akshay5397, who owns the server
BACKUP_ADMIN_ID = 101    # stands in for bearwolf101, who holds @Backup Admin


class _Perms:
    def __init__(self, administrator=False, manage_guild=False):
        self.administrator = administrator
        self.manage_guild = manage_guild


class _Role:
    def __init__(self, name):
        self.name = name


class _Person:
    """Somebody sitting in the server, in whatever state.

    `member=False` is a lobby-sitter: they joined, they have no @Member, they are NOT in.
    """

    def __init__(self, uid, *, bot=False, member=True, administrator=False, manage_guild=False):
        self.id = uid
        self.bot = bot
        self.roles = [_Role(door.MEMBER_ROLE)] if member else []
        self.guild_permissions = _Perms(administrator, manage_guild)


class _Channel:
    def __init__(self):
        self.posts = []

    async def send(self, *a, **kw):
        self.posts.append(a[0] if a else kw)


class _Guild:
    def __init__(self, people, owner_id=OWNER_ID, gid=1):
        self.id = gid
        self.owner_id = owner_id
        self.members = list(people)
        self.roles = [_Role(door.MEMBER_ROLE)]
        self.granted = []
        self.channel = _Channel()

    def get_channel(self, _id):
        return self.channel

    async def invites(self):
        return []


class _Joiner:
    """Somebody arriving right now.

    They ARE already in `guild.members` - discord.py puts a member in the guild cache before it
    dispatches `on_member_join` - but they hold no `@Member` yet, so they do not count until we
    grant it. That ordering is what makes the 30th arrival the one who shuts the door: they walk
    in free, and the person after them meets the form."""

    def __init__(self, guild, uid=777, bot=False):
        self.id, self.bot, self.guild = uid, bot, guild
        self.roles = []
        self.guild_permissions = _Perms()
        self.dms = []
        guild.members.append(self)

    async def add_roles(self, role, **kw):
        self.guild.granted.append(role.name)
        self.roles.append(role)

    async def send(self, *a, **kw):
        self.dms.append(a[0] if a else kw)


def _crowd(n, start=1000):
    """`n` ordinary community members."""
    return [_Person(start + i) for i in range(n)]


@pytest.fixture
def _door_on(monkeypatch):
    """The door feature is configured. Without this, NOTHING in this file may change behaviour."""
    monkeypatch.setattr(door.CFG, "door_channel_id", 12345, raising=False)
    monkeypatch.setattr(door.CFG, "applications_channel_id", 6789, raising=False)
    door._invite_uses.clear()
    yield
    door._invite_uses.clear()


# --- WHAT COUNTS AS 30 ---------------------------------------------------------------------
# The founder's own sentence, made mechanical. These are the tests worth breaking the build over.

def test_bots_do_not_count():
    """Grinder runs 2+ identities and Discord lists every one as a member. Counting them would
    shut the door two or three people early."""
    guild = _Guild(_crowd(29) + [_Person(1, bot=True), _Person(2, bot=True)])
    assert door.community_count(guild) == 29
    assert door.taking_all_comers(guild) is True, "two bots must not close the door"


def test_the_server_owner_does_not_count():
    """akshay5397 owns the server. The founder is not a community member of their own room."""
    guild = _Guild(_crowd(29) + [_Person(OWNER_ID)])
    assert door.community_count(guild) == 29


def test_an_administrator_does_not_count():
    """bearwolf101 holds @Backup Admin, which carries Administrator. Identified by what it IS,
    never by its username - a rename must not silently start counting it."""
    guild = _Guild(_crowd(29) + [_Person(BACKUP_ADMIN_ID, administrator=True)])
    assert door.community_count(guild) == 29


def test_a_manage_guild_holder_does_not_count():
    """A moderator without full Administrator is still staff, not community."""
    guild = _Guild(_crowd(29) + [_Person(4242, manage_guild=True)])
    assert door.community_count(guild) == 29


def test_lobby_sitters_do_not_count():
    """They joined the server but were never approved, so they hold no @Member and are not IN.
    If they counted, a queue of five would hold the door shut for ever and the founder's
    reopen-below-30 decision could never fire."""
    guild = _Guild(_crowd(28) + [_Person(50, member=False), _Person(51, member=False)])
    assert door.community_count(guild) == 28
    assert door.taking_all_comers(guild) is True


def test_the_founders_actual_server_shape():
    """THE ONE. 30 real people + 2 Grinder bots + akshay5397 + bearwolf101 is a server Discord
    reports as 34 members. It must read as exactly 30, and the door must be SHUT."""
    guild = _Guild(
        _crowd(30)
        + [_Person(1, bot=True), _Person(2, bot=True)]
        + [_Person(OWNER_ID), _Person(BACKUP_ADMIN_ID, administrator=True)]
    )
    assert len(guild.members) == 34, "the fake server really does look like 34 to Discord"
    assert door.community_count(guild) == 30
    assert door.taking_all_comers(guild) is False


def test_the_same_server_one_person_short_is_still_open():
    """The mirror of the test above: 29 real people among the same clutter stays OPEN. Without
    this, a counter that always returned 30 would pass the test above."""
    guild = _Guild(
        _crowd(29)
        + [_Person(1, bot=True), _Person(2, bot=True)]
        + [_Person(OWNER_ID), _Person(BACKUP_ADMIN_ID, administrator=True)]
    )
    assert door.community_count(guild) == 29
    assert door.taking_all_comers(guild) is True


def test_the_boundary_is_at_thirty_not_thirty_one():
    """'After 30 members the form starts' means 30 SHUTS it, not 31."""
    assert door.taking_all_comers(_Guild(_crowd(29))) is True
    assert door.taking_all_comers(_Guild(_crowd(30))) is False


# --- UNKNOWN COUNTS AS SHUT (the guard that stops a cold cache opening the server) -----------

def test_a_server_we_cannot_see_is_treated_as_shut():
    """No guild at all - a DM, say. Guessing "open" here would let somebody bypass the door
    entirely by talking to the bot in private."""
    assert door.taking_all_comers(None) is False


def test_an_empty_member_cache_is_treated_as_shut():
    """THE PRODUCTION FAILURE THIS PREVENTS. `guild.members` is a cache fed by a privileged
    intent. Straight after a restart it can be empty, which counts as 0 real members - and a
    naive implementation would read that as "tiny community, let everyone in" and hand `@Member`
    to every stranger who arrived in that window, on a server meant to be shut."""
    assert door.taking_all_comers(_Guild([])) is False


def test_a_half_chunked_member_cache_is_treated_as_shut():
    """Discord says the server holds 200 people and we can only see 5. Counting the 5 would open
    a server of 200."""
    guild = _Guild(_crowd(5))
    guild.member_count = 200
    assert door.community_count(guild) == 5, "the raw count is honest about what it can see..."
    assert door.taking_all_comers(guild) is False, "...but the DECISION refuses to trust it"


def test_a_fully_chunked_cache_is_trusted():
    """The mirror: when what we hold matches what Discord says, the count is usable."""
    guild = _Guild(_crowd(10))
    guild.member_count = 10
    assert door.taking_all_comers(guild) is True


# --- WALKING IN ----------------------------------------------------------------------------

def test_below_thirty_a_newcomer_is_let_straight_in(_door_on):
    guild = _Guild(_crowd(10))
    joiner = _Joiner(guild)
    assert asyncio.run(door.on_member_join(joiner)) is True
    assert guild.granted == [door.MEMBER_ROLE], "they should hold @Member immediately"
    assert joiner.dms, "they should be told they are in and what to do next"


def test_at_thirty_a_newcomer_is_left_for_the_form(_door_on):
    guild = _Guild(_crowd(30))
    joiner = _Joiner(guild)
    assert asyncio.run(door.on_member_join(joiner)) is False
    assert guild.granted == [], "nobody may be granted @Member once the door is shut"


def test_a_bot_joining_is_never_granted_member(_door_on):
    """A bot arriving under 30 must not be handed the community role."""
    guild = _Guild(_crowd(10))
    assert asyncio.run(door.on_member_join(_Joiner(guild, bot=True))) is False
    assert guild.granted == []


def test_dropping_back_below_thirty_reopens_the_door(_door_on):
    """Founder decision 2026-08-14, taken against recommendation: the door tracks the number
    live rather than latching shut for ever."""
    people = _crowd(30)
    guild = _Guild(people)
    assert asyncio.run(door.on_member_join(_Joiner(guild))) is False   # shut at 30

    guild.members = people[:-1]                                        # somebody leaves
    assert asyncio.run(door.on_member_join(_Joiner(guild, uid=778))) is True
    assert guild.granted == [door.MEMBER_ROLE]


def test_a_vouched_friend_still_walks_in_when_the_door_is_shut(_door_on):
    """The regression that protects the OTHER way in. /invitefriend must keep working above 30."""
    store.add_vouch(code="FRIEND1", created_by=1, when="t")
    guild = _Guild(_crowd(30))
    door._invite_uses[guild.id] = {"FRIEND1": 0}
    assert asyncio.run(door.on_member_join(_Joiner(guild))) is True
    assert guild.granted == [door.MEMBER_ROLE]
    assert store.vouch("FRIEND1")["used_by"] == 777, "the vouch must still be spent"


# --- THE HARD BOUNDARY: pending applications are never touched -------------------------------

def test_reopening_the_door_never_touches_a_pending_application(_door_on):
    """Founder decision 2026-08-14, against recommendation: they keep deciding. So the door state
    governs NEW ARRIVALS ONLY and must never approve somebody who is waiting.

    The accepted consequence, written down so it is never mistaken for a bug: the person who
    filled the form is still waiting while the newcomer beside them strolls in free."""
    store.save_application(user_id=4242, user_name="waiting", answers={"Your name": "Sam"},
                           when="2026-08-14T00:00:00")
    people = _crowd(30)
    guild = _Guild(people)
    guild.members = people[:-1]                                        # door reopens

    assert asyncio.run(door.on_member_join(_Joiner(guild))) is True    # newcomer strolls in

    row = store.application(4242)
    assert row["state"] == "pending", "a waiting applicant must NEVER be auto-approved"
    assert store.approved_count() == 0


# --- THE ANNOUNCEMENT ----------------------------------------------------------------------

def test_the_founder_is_told_once_when_the_door_closes(_door_on):
    guild = _Guild(_crowd(30))
    asyncio.run(door.on_member_join(_Joiner(guild, uid=1)))
    assert len(guild.channel.posts) == 1, "closing changes what strangers see; say so once"

    asyncio.run(door.on_member_join(_Joiner(guild, uid=2)))
    asyncio.run(door.on_member_join(_Joiner(guild, uid=3)))
    assert len(guild.channel.posts) == 1, "every later arrival must NOT repeat the announcement"


def test_reopening_is_silent(_door_on):
    """An opening is not actionable - there is nothing for the founder to do about it - and a
    member leaving and rejoining would otherwise post a pair of messages every time."""
    people = _crowd(30)
    guild = _Guild(people)
    asyncio.run(door.on_member_join(_Joiner(guild, uid=1)))            # closes, 1 post

    guild.members = people[:-2]                                        # two leave -> 28
    joiner = _Joiner(guild, uid=2)
    assert asyncio.run(door.on_member_join(joiner)) is True            # walks in -> 29, still open
    assert len(guild.channel.posts) == 1, "reopening must say nothing"


def test_closing_again_after_a_reopen_is_announced_again(_door_on):
    """It is news each time it becomes true."""
    people = _crowd(30)
    guild = _Guild(people)
    asyncio.run(door.on_member_join(_Joiner(guild, uid=1)))            # shut, 1 post

    guild.members = people[:-1]                                        # one leaves -> 29, open
    asyncio.run(door.on_member_join(_Joiner(guild, uid=2)))            # walks in -> back to 30
    assert len(guild.channel.posts) == 2


def test_a_broken_announcement_never_costs_somebody_their_entry(_door_on):
    """REGRESSION, found while building this. The announcement first ran BEFORE the grant, so a
    guild whose channel lookup raised took the whole arrival down with it - and the person was
    silently left in the lobby by a cosmetic notification.

    The note is the lowest-value thing on this path and the grant is the highest. Failing to post
    a message must never be able to fail a person."""
    class _AngryChannel(_Channel):
        async def send(self, *a, **kw):
            raise RuntimeError("Discord is having a bad day")

    guild = _Guild(_crowd(10))
    guild.channel = _AngryChannel()
    guild.members = _crowd(30)                 # shut, so the announcement will try to fire
    joiner = _Joiner(guild)                    # appended -> still 30 real, door shut

    assert asyncio.run(door.on_member_join(joiner)) is False, "shut door, so no free entry"

    guild.members = _crowd(10)                 # now open
    walker = _Joiner(guild, uid=778)
    assert asyncio.run(door.on_member_join(walker)) is True, \
        "a failing announcement must not stop somebody walking in"
    assert door.MEMBER_ROLE in guild.granted


# --- GRINDING ------------------------------------------------------------------------------

class _Interaction:
    def __init__(self, guild, uid=777, member=False):
        self.guild = guild
        self.user = _Person(uid, member=member)


def test_grind_is_not_blocked_while_the_door_is_open(_door_on):
    """Below 30 everybody is admitted anyway, so there is nothing to block."""
    guild = _Guild(_crowd(10))
    assert door.blocked_reason(_Interaction(guild)) is None


def test_grind_is_blocked_for_an_outsider_once_the_door_is_shut(_door_on):
    guild = _Guild(_crowd(30))
    assert door.blocked_reason(_Interaction(guild)) is not None


# --- THE DORMANT GUARD (the regression that matters most) ------------------------------------

def test_with_no_door_configured_nothing_in_this_feature_happens(monkeypatch):
    """A server that never set the door up must behave EXACTLY as it did before this existed -
    no free grants, no announcement, no blocking. This is the guard that keeps the whole feature
    invisible until somebody deliberately turns it on."""
    monkeypatch.setattr(door.CFG, "door_channel_id", None, raising=False)
    guild = _Guild(_crowd(5))
    joiner = _Joiner(guild)

    assert asyncio.run(door.on_member_join(joiner)) is False
    assert guild.granted == []
    assert guild.channel.posts == []
    assert door.blocked_reason(_Interaction(guild)) is None
