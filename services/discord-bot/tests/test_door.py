"""The door: applying, pooling, and choosing the first fifty.

The founder is CHOOSING from a pool, not approving a feed, so the tests that matter most are the
ones about the pool surviving and staying searchable - not the happy path of one approval.
"""
import asyncio
import json
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


ANSWERS = {
    "Your name": "Akshay",
    "Your email": "akshay@example.com",
    "Your relation to music": "I DJ at weekends",
    "AI tools you have used": "Suno and Midjourney",
    "Why you want to join": "want to make mashups",
}


def _apply(uid: int, name: str = "someone", **over):
    answers = {**ANSWERS, **over}
    store.save_application(user_id=uid, user_name=name, answers=answers, when=f"2026-08-13T00:00:{uid:02d}")
    return answers


# --- the pool ------------------------------------------------------------------------------
def test_an_application_waits_in_the_pool_until_somebody_decides():
    _apply(1, "Akshay")
    pending = store.pending_applications()
    assert len(pending) == 1
    assert pending[0]["state"] == "pending"
    assert store.approved_count() == 0


def test_the_pool_survives_a_restart():
    """THE reason applications are in SQLite and not in memory. The founder compares people over
    days; a restart that emptied the queue would silently throw away everyone who had applied."""
    _apply(1, "Akshay")
    _apply(2, "Sam")
    store.reset_for_tests(store.DB_PATH)      # same file, fresh connection: a restart
    assert len(store.pending_applications()) == 2


def test_re_applying_replaces_rather_than_duplicating():
    """Somebody fixing a typo must not show up twice in a pool that is being compared."""
    _apply(1, "Akshay", **{"Your name": "first try"})
    _apply(1, "Akshay", **{"Your name": "second try"})
    pending = store.pending_applications()
    assert len(pending) == 1
    assert json.loads(pending[0]["answers"])["Your name"] == "second try"


def test_re_applying_can_never_revoke_access_somebody_already_has():
    _apply(1, "Akshay")
    store.decide_application(user_id=1, state="approved", by=99, when="t")
    _apply(1, "Akshay", **{"Your name": "again"})
    assert store.application(1)["state"] == "approved"
    assert store.approved_count() == 1


# --- "I want to spot them" -----------------------------------------------------------------
def test_the_pool_can_be_filtered_by_a_word_the_founder_types():
    """The founder's words: "I don't want random gamers... but people who actually use Suno.ai, who
    use Midjourney, or who are actually DJs. I want to spot them." This is that, mechanically -
    a substring search over answers they already have, not a judgement the bot is making."""
    def _explicit(uid, name, music, tools):
        store.save_application(
            user_id=uid, user_name=name,
            answers={"Your name": name, "Your relation to music": music,
                     "AI tools you have used": tools, "Why you want to join": "",
                     "What you expect": ""},
            when=f"2026-08-13T00:00:{uid:02d}")

    _explicit(1, "A", "producer", "Suno")
    _explicit(2, "B", "I play games", "none")
    _explicit(3, "C", "resident DJ at a club", "none")

    assert [r["user_id"] for r in store.pending_applications("suno")] == [1]
    assert [r["user_id"] for r in store.pending_applications("dj")] == [3]
    assert store.pending_applications("games")[0]["user_id"] == 2
    assert store.pending_applications("nobody-said-this") == []


def test_the_filter_is_a_plain_substring_and_the_founder_should_know_it():
    """Recorded rather than hidden: this is `in`, not word matching, so a SHORT word can catch a
    longer one. "dj" finds "Midjourney".

    Left as a substring on purpose - it is predictable, and the founder can always type a longer
    word. Word-boundary matching brings its own edge cases (hyphens, punctuation, "DJ-ing") for a
    pool that will hold tens of applications, not thousands. The test exists so the behaviour is a
    known choice and not a surprise."""
    store.save_application(user_id=1, user_name="A",
                           answers={"AI tools you have used": "Midjourney"}, when="t")
    assert len(store.pending_applications("dj")) == 1


def test_the_filter_is_case_insensitive_and_searches_every_answer():
    _apply(1, "A", **{"What you expect": "To learn ABLETON properly"})
    assert len(store.pending_applications("ableton")) == 1


# --- deciding ------------------------------------------------------------------------------
def test_approving_takes_a_seat_and_declining_does_not():
    _apply(1)
    _apply(2)
    assert store.decide_application(user_id=1, state="approved", by=9, when="t") is True
    assert store.decide_application(user_id=2, state="declined", by=9, when="t") is True
    assert store.approved_count() == 1
    assert store.pending_applications() == []


def test_a_second_press_cannot_decide_the_same_application_twice():
    """Two presses of Approve, or the founder and a second admin at once, must not grant twice."""
    _apply(1)
    assert store.decide_application(user_id=1, state="approved", by=9, when="t") is True
    assert store.decide_application(user_id=1, state="approved", by=9, when="t") is False
    assert store.approved_count() == 1


def test_a_decision_always_records_who_made_it():
    _apply(1)
    store.decide_application(user_id=1, state="approved", by=4242, when="2026-08-13T10:00:00")
    row = store.application(1)
    assert row["decided_by"] == 4242 and row["decided_at"] == "2026-08-13T10:00:00"


def test_an_unknown_state_is_refused_rather_than_stored():
    _apply(1)
    with pytest.raises(ValueError):
        store.decide_application(user_id=1, state="maybe", by=9, when="t")


# --- the form and the cards ----------------------------------------------------------------
def test_the_form_asks_exactly_the_founders_five_questions():
    """Discord allows five short inputs in one modal and the founder named five, so this fits
    exactly. A sixth would silently fail to render."""
    labels = [label for label, _, _ in door.QUESTIONS]
    assert labels == ["Your name", "Your email", "Your relation to music",
                      "AI tools you have used", "Why you want to join"]
    assert len(door.QUESTIONS) <= 5


def test_the_review_card_shows_every_answer_and_the_seats_left():
    e = door.application_embed(user_name="Akshay", user_id=1, answers=ANSWERS, taken=23)
    blob = "\n".join([f.name + " " + f.value for f in e.fields])
    for label, _, _ in door.QUESTIONS:
        assert label in blob
    assert "Suno and Midjourney" in blob
    assert f"23 of {door.MEMBER_CAP} taken" in blob


def test_a_blank_answer_reads_as_blank_rather_than_breaking_the_card():
    e = door.application_embed(user_name="A", user_id=1, answers={"Your name": "A"}, taken=0)
    assert any("(left blank)" in f.value for f in e.fields)


def test_the_cap_is_fifty():
    assert door.MEMBER_CAP == 50


# --- the rule that shapes everything Grinder says -------------------------------------------
JUDGEMENT_WORDS = (
    "promising", "strong candidate", "weak", "good fit", "bad fit", "score", "rating", "rated",
    "rank", "ranked", "recommend", "suggest", "likely", "unlikely", "quality", "best applicant",
    "spam", "suspicious", "genuine", "legit",
)


def test_the_bot_never_passes_judgement_on_an_applicant():
    """The same rule that stops a card judging a grind, on a new surface. An opinion shown before
    the founder's own read poisons that read - and here it would be an opinion about a PERSON."""
    cards = [
        door.application_embed(user_name="A", user_id=1, answers=ANSWERS, taken=0),
        door.application_embed(user_name="A", user_id=1, answers=ANSWERS, taken=50,
                               state="approved"),
        door.application_embed(user_name="A", user_id=1, answers=ANSWERS, taken=50,
                               state="declined"),
        door.lobby_embed(),
    ]
    for e in cards:
        blob = " ".join([e.title or "", e.description or ""]
                        + [f.name + " " + f.value for f in e.fields]).lower()
        # The answers themselves are the applicant's words, not Grinder's - only check the parts
        # Grinder writes.
        written_by_grinder = " ".join([e.title or "", e.description or ""]).lower()
        for word in JUDGEMENT_WORDS:
            assert word not in written_by_grinder, f"Grinder judged an applicant: {word!r}"
        assert blob  # the card is not empty


def test_no_fancy_dashes_anywhere_a_user_reads():
    """Founder rule: em and en dashes read as machine-written. Same check the cards already get."""
    texts = [door.lobby_embed().description or "",
             door.lobby_embed().title or "",
             door._ROLE_MISSING]
    for label, placeholder, _ in door.QUESTIONS:
        texts += [label, placeholder]
    for t in texts:
        assert "—" not in t and "–" not in t, f"fancy dash in {t!r}"


# --- the live-server script's one non-negotiable ---------------------------------------------
def test_the_lock_script_grants_before_it_restricts():
    """THE thing that could lock the founder out of their own server.

    Read as source rather than run: the script needs a real gateway connection. The order of these
    two steps is the entire safety story, so it is asserted rather than trusted - restrict-then-
    grant would leave every existing member, founder included, unable to see the server for as long
    as the grant takes, and permanently if the script died in between."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "scripts" / "lock_the_door.py").read_text(
        encoding="utf-8")
    grant = src.index("keeping existing members in")
    restrict = src.index("The door: members only")
    assert grant < restrict, "the lock script restricts before it grants - that locks people out"


def test_the_lock_script_is_a_dry_run_unless_told_otherwise():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "scripts" / "lock_the_door.py").read_text(
        encoding="utf-8")
    assert 'apply = "--apply" in sys.argv' in src
    assert 'input(' in src, "applying must require a typed confirmation"


# --- the gate the founder actually asked for -------------------------------------------------
# "Once I approve those users, they will only get to use the Discord bot."
# Channel permissions alone cannot carry that: `_grinding_allowed_here` allows grinding EVERYWHERE
# when no grind category is configured, and the lobby is a channel every unapproved person can see
# by design. So the bot checks who you are, not only where you are.
class _Perms:
    def __init__(self, admin=False):
        self.manage_guild = admin
        self.administrator = admin


class _Role:
    def __init__(self, name):
        self.name = name


class _User:
    def __init__(self, uid, roles=(), admin=False):
        self.id = uid
        self.roles = [_Role(r) for r in roles]
        self.guild_permissions = _Perms(admin)


class _Interaction:
    def __init__(self, user):
        self.user = user


@pytest.fixture
def _door_open(monkeypatch):
    monkeypatch.setattr(door.CFG, "door_channel_id", 12345, raising=False)


def test_with_no_door_configured_nothing_is_blocked(monkeypatch):
    """The feature is dormant until the founder switches it on. A bot that started refusing people
    the moment this shipped would be a change to the live server by accident."""
    monkeypatch.setattr(door.CFG, "door_channel_id", None, raising=False)
    assert door.blocked_reason(_Interaction(_User(1))) is None


def test_a_stranger_cannot_use_the_bot_once_the_door_is_open(_door_open):
    reason = door.blocked_reason(_Interaction(_User(1)))
    assert reason is not None and "invite only" in reason
    assert "<#12345>" in reason, "it should point them at the door"


def test_somebody_waiting_is_told_they_are_waiting_not_told_to_apply_again(_door_open):
    """A pending applicant reading "go and apply" would apply twice and think it was broken."""
    _apply(1, "Akshay")
    reason = door.blocked_reason(_Interaction(_User(1)))
    assert reason is not None and "application is in" in reason


def test_an_approved_member_can_use_the_bot(_door_open):
    assert door.blocked_reason(_Interaction(_User(1, roles=[door.MEMBER_ROLE]))) is None


def test_the_founder_is_never_locked_out_of_their_own_bot(_door_open):
    """They have no @Member role - they are the one who hands it out. Enforcing their own rule
    against them would be absurd, and would strand them the moment the door closed."""
    assert door.blocked_reason(_Interaction(_User(1, admin=True))) is None


def test_the_grind_command_checks_membership_before_anything_else():
    """Read as source: /grind needs a gateway to run. The ORDER matters - the membership check has
    to come before the where-am-I check, because the where-check allows everywhere when no grind
    category is configured, which would let a stranger grind from the lobby."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")
    body = src[src.index("async def grind_cmd"):]
    body = body[:body.index("@bot.tree.command", 1)] if "@bot.tree.command" in body[1:] else body
    assert "door.blocked_reason" in body, "/grind does not check membership at all"
    assert body.index("door.blocked_reason") < body.index("_grinding_allowed_here"), \
        "the membership check must run BEFORE the where-am-I check"


# --- the email, now a required question inside the form --------------------------------------
# Founder, 2026-08-13: "I want the email to be the second thing that users have to fill in
# compulsorily." It could not stay a follow-up pop-up, because Discord cannot force anybody through
# one - they can dismiss it and walk away. Inside the modal, Discord refuses the submission.
def test_the_email_is_question_two_and_discord_will_not_accept_a_blank_one():
    labels = [label for label, _, _ in door.QUESTIONS]
    assert labels[1] == door.EMAIL_LABEL, "the email must be the second thing they fill in"
    assert door.EMAIL_LABEL in door.REQUIRED
    m = door.ApplicationModal()
    required = [t.label for t in m._inputs if t.required]
    assert door.EMAIL_LABEL in required, "Discord would let somebody submit without an email"


def test_the_form_still_fits_discords_five_box_limit():
    """A sixth box does not error - it silently fails to render, which would lose a question
    without anybody noticing."""
    assert len(door.ApplicationModal()._inputs) <= 5


def test_the_email_shows_on_the_review_card_like_any_other_answer():
    e = door.application_embed(user_name="Akshay", user_id=1, answers=ANSWERS, taken=0)
    rows = [(f.name, f.value) for f in e.fields]
    assert (door.EMAIL_LABEL, "akshay@example.com") in rows
    assert sum(1 for n, _ in rows if n == door.EMAIL_LABEL) == 1, "the email is rendered twice"


def test_the_email_is_searchable_like_every_other_answer():
    _apply(1, "Akshay")
    assert len(store.pending_applications("example.com")) == 1


@pytest.mark.parametrize("good", [
    "a@b.co", "akshay.09@gmail.com", "first+tag@sub.domain.org", "x@y.io",
])
def test_real_looking_addresses_are_accepted(good):
    assert door.looks_like_an_email(good) is True


@pytest.mark.parametrize("bad", [
    "akshay at gmail", "no-at-sign.com", "two@@at.com", "trailing@dot.", "@nolocal.com",
    "spaces in@email.com", "nodot@domain", "",
])
def test_typos_are_caught(bad):
    """Loose on purpose - the job is catching "akshay at gmail", not policing what a valid address
    is. Every strict email regex rejects somebody's real address, and a rejected applicant is a
    worse outcome than one bounced email."""
    assert door.looks_like_an_email(bad) is False


# --- what somebody reads while they wait -----------------------------------------------------
def test_the_waiting_message_says_a_human_reads_it_and_never_promises_a_time():
    """A promise like "within 24 hours" is one the founder has not made and cannot keep."""
    msg = door.waiting_message().lower()
    assert "by hand" in msg
    for promise in ("24 hours", "tomorrow", "shortly", "soon", "within"):
        assert promise not in msg


def test_a_sample_mix_link_is_included_when_one_is_configured(monkeypatch):
    """Founder, 2026-08-13: send them a music link too. Between applying and being approved they
    can see nothing and hear nothing, so this is the only proof that what they are waiting for is
    worth waiting for."""
    monkeypatch.setattr(door.CFG, "sample_mix_url", "https://example.com/a-mix", raising=False)
    assert "https://example.com/a-mix" in door.waiting_message()


def test_no_dangling_sentence_when_no_link_is_configured(monkeypatch):
    """The line is left out entirely rather than left hanging with nothing after it."""
    monkeypatch.setattr(door.CFG, "sample_mix_url", "", raising=False)
    msg = door.waiting_message()
    assert "this is the kind of thing" not in msg.lower()
    assert msg.strip().endswith(".")


def test_the_lock_script_grants_before_it_restricts():
    """THE thing that could lock the founder out of their own server.

    Read as source rather than run: the script needs a real gateway connection. The order of these
    two steps is the entire safety story, so it is asserted rather than trusted - restrict-then-
    grant would leave every existing member, founder included, unable to see the server for as long
    as the grant takes, and permanently if the script died in between."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "scripts" / "lock_the_door.py").read_text(
        encoding="utf-8")
    grant = src.index("keeping existing members in")
    restrict = src.index("The door: members only")
    assert grant < restrict, "the lock script restricts before it grants - that locks people out"


def test_the_lock_script_is_a_dry_run_unless_told_otherwise():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "scripts" / "lock_the_door.py").read_text(
        encoding="utf-8")
    assert 'apply = "--apply" in sys.argv' in src
    assert 'input(' in src, "applying must require a typed confirmation"


# --- the gate the founder actually asked for -------------------------------------------------
# "Once I approve those users, they will only get to use the Discord bot."
# Channel permissions alone cannot carry that: `_grinding_allowed_here` allows grinding EVERYWHERE
# when no grind category is configured, and the lobby is a channel every unapproved person can see
# by design. So the bot checks who you are, not only where you are.
class _Perms:
    def __init__(self, admin=False):
        self.manage_guild = admin
        self.administrator = admin


class _Role:
    def __init__(self, name):
        self.name = name


class _User:
    def __init__(self, uid, roles=(), admin=False):
        self.id = uid
        self.roles = [_Role(r) for r in roles]
        self.guild_permissions = _Perms(admin)


class _Interaction:
    def __init__(self, user):
        self.user = user


@pytest.fixture
def _door_open(monkeypatch):
    monkeypatch.setattr(door.CFG, "door_channel_id", 12345, raising=False)


def test_with_no_door_configured_nothing_is_blocked(monkeypatch):
    """The feature is dormant until the founder switches it on. A bot that started refusing people
    the moment this shipped would be a change to the live server by accident."""
    monkeypatch.setattr(door.CFG, "door_channel_id", None, raising=False)
    assert door.blocked_reason(_Interaction(_User(1))) is None


def test_a_stranger_cannot_use_the_bot_once_the_door_is_open(_door_open):
    reason = door.blocked_reason(_Interaction(_User(1)))
    assert reason is not None and "invite only" in reason
    assert "<#12345>" in reason, "it should point them at the door"


def test_somebody_waiting_is_told_they_are_waiting_not_told_to_apply_again(_door_open):
    """A pending applicant reading "go and apply" would apply twice and think it was broken."""
    _apply(1, "Akshay")
    reason = door.blocked_reason(_Interaction(_User(1)))
    assert reason is not None and "application is in" in reason


def test_an_approved_member_can_use_the_bot(_door_open):
    assert door.blocked_reason(_Interaction(_User(1, roles=[door.MEMBER_ROLE]))) is None


def test_the_founder_is_never_locked_out_of_their_own_bot(_door_open):
    """They have no @Member role - they are the one who hands it out. Enforcing their own rule
    against them would be absurd, and would strand them the moment the door closed."""
    assert door.blocked_reason(_Interaction(_User(1, admin=True))) is None


def test_the_grind_command_checks_membership_before_anything_else():
    """Read as source: /grind needs a gateway to run. The ORDER matters - the membership check has
    to come before the where-am-I check, because the where-check allows everywhere when no grind
    category is configured, which would let a stranger grind from the lobby."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")
    body = src[src.index("async def grind_cmd"):]
    body = body[:body.index("@bot.tree.command", 1)] if "@bot.tree.command" in body[1:] else body
    assert "door.blocked_reason" in body, "/grind does not check membership at all"
    assert body.index("door.blocked_reason") < body.index("_grinding_allowed_here"), \
        "the membership check must run BEFORE the where-am-I check"


def test_the_lock_script_opens_a_channel_to_members_BEFORE_closing_it_to_everyone():
    """THE BUG THAT BIT THE FOUNDER'S LIVE SERVER, 2026-08-13.

    The script denied @everyone first and allowed @Member second. The bot's only roles are
    @Grinder and @everyone, so denying @everyone locked the BOT out of that same channel in the
    same instant - the allow-@Member call then failed with 50001 Missing Access, and the server was
    left half-locked: real members could see nothing, and the bot could neither finish nor undo it.
    Recovering needed the founder to grant Administrator by hand.

    The grant-before-restrict rule was already asserted one level up, on handing out the role. This
    asserts it at the CHANNEL level, which is where it was actually missing - the test existed but
    was pointed at the wrong step."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "scripts" / "lock_the_door.py").read_text(
        encoding="utf-8")
    body = src[src.index("for c in to_close:"):]
    grant_member = body.index("The door: members keep access")
    keep_bot = body.index("The door: keep the bot able to undo this")
    deny_everyone = body.index("The door: members only")
    assert grant_member < deny_everyone, \
        "the script denies @everyone before allowing @Member - that half-locks the server"
    assert keep_bot < deny_everyone, \
        "the script denies @everyone before securing its OWN access - that strands the bot"


def test_a_channel_is_left_open_rather_than_locked_with_nobody_able_to_see_it():
    """If the grant fails, the channel must stay OPEN. A channel closed to @everyone with no
    @Member allow is visible to admins only - worse than not locking it at all, and it is exactly
    the state the founder's server ended up in."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "scripts" / "lock_the_door.py").read_text(
        encoding="utf-8")
    body = src[src.index("for c in to_close:"):src.index("# ---- 5.")]
    assert body.count("continue") >= 2, \
        "a failed grant must skip the channel, not fall through to closing it"


# --- the card actually reaching the founder ---------------------------------------------------
class _PostSpy:
    def __init__(self, cid):
        self.id = cid
        self.sent = []

    async def send(self, **kw):
        self.sent.append(kw)
        return type("M", (), {"id": 555})()


class _GuildStub:
    def __init__(self, channel):
        self._channel = channel

    def get_channel(self, cid):
        return self._channel if self._channel and cid == self._channel.id else None

    def get_member(self, _uid):
        """Always None - exactly what the real bot does. It runs on Intents.default(), so it keeps
        NO member cache and this returns None for everybody, including people standing in the
        server. Any code that decides something from it is already broken."""
        return None


class _InteractionStub:
    def __init__(self, guild, user_id=7, name="Akshay"):
        self.guild = guild
        self.user = type("U", (), {"id": user_id, "display_name": name, "created_at": None})()
        self.client = type("C", (), {"guilds": [guild]})()


def test_the_application_card_reaches_the_review_channel(monkeypatch):
    """THE BUG THE FOUNDER FOUND ON THEIR FIRST REAL TEST, 2026-08-13.

    The form worked and the application was stored, but no card ever appeared. `post_for_review`
    located the server by asking each guild "is this user a member of yours?" - which needs a
    member cache the bot does not keep, so it answered None for everybody, no guild was found, and
    every application was silently filed and never shown.

    `_GuildStub.get_member` returns None deliberately: this test only passes if the code takes the
    guild from the INTERACTION rather than from a member lookup."""
    chan = _PostSpy(999)
    monkeypatch.setattr(door.CFG, "applications_channel_id", 999, raising=False)
    guild = _GuildStub(chan)
    _apply(7, "Akshay")

    asyncio.run(door.post_for_review(_InteractionStub(guild), ANSWERS))

    assert len(chan.sent) == 1, "the application never reached the review channel"
    embed = chan.sent[0]["embed"]
    blob = " ".join(f.name + " " + f.value for f in embed.fields)
    assert "akshay@example.com" in blob
    assert store.application(7)["message_id"] == 555, "the card was not linked to the application"


def test_nothing_is_posted_when_no_review_channel_is_configured(monkeypatch):
    """It must stay silent rather than crash - the application is stored either way, and
    /applications still finds it."""
    monkeypatch.setattr(door.CFG, "applications_channel_id", None, raising=False)
    _apply(8, "Sam")
    asyncio.run(door.post_for_review(_InteractionStub(_GuildStub(None), user_id=8), ANSWERS))
    assert store.application(8) is not None


# --- answering Discord in time ----------------------------------------------------------------
class _Recorder:
    """An interaction that records the ORDER of what was done to it."""

    def __init__(self, calls, guild=None, message_id=555):
        self.calls = calls
        self.guild = guild
        self.message = type("M", (), {"id": message_id})()
        self.user = type("U", (), {"id": 1})()
        self.client = type("C", (), {"guilds": [], "get_user": lambda s, i: None})()
        outer = self

        class _Resp:
            async def defer(self, *a, **k):
                outer.calls.append("defer")

            async def send_message(self, *a, **k):
                outer.calls.append("send_message")

        class _Follow:
            async def send(self, *a, **k):
                outer.calls.append("followup")

        self.response = _Resp()
        self.followup = _Follow()

    async def edit_original_response(self, **kw):
        self.calls.append("edit")


class _SlowGuild:
    """Stands in for the real thing: looking a member up and adding a role are API calls, and on a
    slow connection either can outlast Discord's three-second button deadline."""

    def __init__(self, calls):
        self.calls = calls
        self.roles = [type("R", (), {"name": door.MEMBER_ROLE})()]

    def get_member(self, _uid):
        return None                       # no member cache, exactly like the real bot

    async def fetch_member(self, _uid):
        self.calls.append("fetch_member")
        return type("M", (), {"add_roles": self._add_roles})()

    async def _add_roles(self, *a, **k):
        self.calls.append("add_roles")

    def get_channel(self, _cid):
        return None


def test_approve_answers_discord_BEFORE_it_starts_making_api_calls(monkeypatch):
    """THE BUG THE FOUNDER HIT ON THEIR FIRST APPROVAL, 2026-08-13: "Grinder didn't respond in
    time".

    A button gets THREE SECONDS to reply or Discord declares it broken to the person who pressed
    it. Approve then looks the member up and adds a role - two API calls - before answering, and on
    a slow connection that is easily over the limit. The fix is to acknowledge the press first and
    do the work after.

    Asserted as an ORDER, not as "defer is called somewhere": deferring after the slow part would
    be just as broken and would still contain the word defer."""
    _apply(7, "Akshay")
    store.set_application_message(7, 555)      # the card this button belongs to
    calls = []
    guild = _SlowGuild(calls)
    inter = _Recorder(calls, guild=guild, message_id=555)
    button = type("B", (), {"custom_id": "door:approve"})()

    asyncio.run(door._decide(inter, button, approved=True))

    assert "defer" in calls, "Approve never acknowledged the press - Discord will time it out"
    assert calls.index("defer") < calls.index("fetch_member"), (
        f"Approve made an API call before answering Discord: {calls}")
    assert "edit" in calls, "the card was never updated to say approved"
    assert store.application(7)["state"] == "approved"


def test_a_decision_still_lands_even_if_the_role_grant_fails(monkeypatch):
    """The decision is recorded before the role work, so a permissions problem cannot leave an
    application stuck as pending forever with the founder believing they had decided it."""
    _apply(9, "Sam")
    store.set_application_message(9, 777)
    calls = []

    class _NoRole(_SlowGuild):
        def __init__(self, c):
            super().__init__(c)
            self.roles = []               # @Member does not exist

    inter = _Recorder(calls, guild=_NoRole(calls), message_id=777)
    asyncio.run(door._decide(inter, type("B", (), {"custom_id": "door:approve"})(),
                             approved=True))

    assert store.application(9)["state"] == "approved"
    assert "followup" in calls, "the founder was never told the role could not be granted"


def test_a_real_mix_link_ships_by_default(monkeypatch):
    """The founder's pick, 2026-08-13. It lives in botconfig rather than .env because it is copy,
    not a secret - and because an unset env var defaulting to "" would silently blank it for
    everybody, which is exactly what the first version did."""
    from botconfig import Config
    assert Config.sample_mix_url.startswith("http"), "no sample mix ships by default"
    monkeypatch.delenv("GRINDER_SAMPLE_MIX_URL", raising=False)
    from botconfig import load_config
    assert load_config().sample_mix_url == Config.sample_mix_url, (
        "an unset environment variable blanked the configured link")


def test_the_link_is_openable_by_somebody_who_is_not_in_the_server():
    """A Discord message link would be useless here: the applicant cannot see a single channel yet,
    so the one thing they are shown must live outside Discord."""
    from botconfig import Config
    assert "discord.com/channels" not in Config.sample_mix_url


def test_the_review_buttons_use_FIXED_ids_so_the_bot_recognises_its_own_cards():
    """THE REAL CAUSE of "Grinder didn't respond in time" on the founder's first approval.

    Discord matches a persistent button by its EXACT custom_id. Putting the applicant's id inside
    it (`door:approve:1536...`) meant the single view registered at startup (`door:approve:0`)
    matched no real card - the bot did not recognise its own buttons, never answered, and nothing
    appeared in the log because no handler ran. The applicant is now looked up from the card's
    message id, which is already stored.

    An id containing a user id is the specific mistake, so that is what this forbids."""
    ids = [c.custom_id for c in door.ReviewView().children]
    assert sorted(ids) == ["door:approve", "door:decline"]
    for cid in ids:
        assert cid.count(":") == 1, f"{cid} carries per-application data - it will never match"


def test_a_card_the_store_does_not_know_is_answered_rather_than_left_hanging():
    """Better a plain sentence than a dead button: an unrecognised card must still get a reply,
    or the presser sees the same "didn't respond in time" this whole fix is about."""
    calls = []
    inter = _Recorder(calls, guild=None, message_id=123456)   # no application for this message
    asyncio.run(door._decide(inter, type("B", (), {"custom_id": "door:approve"})(), approved=True))
    assert "send_message" in calls, "an unknown card was left with no response at all"


# --- vouch links: a friend the founder invites personally ------------------------------------
class _Invite:
    def __init__(self, code, uses=0):
        self.code, self.uses = code, uses


class _VouchGuild:
    def __init__(self, invites, gid=1):
        self.id = gid
        self._invites = invites
        self.roles = [type("R", (), {"name": door.MEMBER_ROLE})()]
        self.granted = []

    async def invites(self):
        return list(self._invites)


class _Joiner:
    def __init__(self, guild, uid=42, bot=False):
        self.id, self.bot, self.guild = uid, bot, guild
        self.roles = []

    async def add_roles(self, role, **kw):
        self.guild.granted.append(role.name)

    async def send(self, *a, **k):
        pass


@pytest.fixture
def _open_door(monkeypatch):
    monkeypatch.setattr(door.CFG, "door_channel_id", 12345, raising=False)
    door._invite_uses.clear()
    yield
    door._invite_uses.clear()


def test_a_friend_on_a_vouch_link_is_let_straight_in_without_the_form(_open_door):
    """Founder, 2026-08-13: "if I personally want to invite someone who I know, they don't have to
    fill out the form to enter"."""
    store.add_vouch(code="FRIEND1", created_by=1, when="t")
    guild = _VouchGuild([_Invite("FRIEND1", 0), _Invite("PUBLIC", 5)])
    door._invite_uses[guild.id] = {"FRIEND1": 0, "PUBLIC": 5}
    # They use it: a single-use invite VANISHES rather than counting up.
    guild._invites = [_Invite("PUBLIC", 5)]

    assert asyncio.run(door.on_member_join(_Joiner(guild))) is True
    assert guild.granted == [door.MEMBER_ROLE]
    assert store.vouch("FRIEND1")["used_by"] == 42


def test_a_vanished_single_use_invite_is_recognised_as_used(_open_door):
    """THE case that is easy to miss. A single-use invite is DELETED the moment it is spent, so it
    never shows a higher count - it simply disappears. Code that only looks for "uses went up"
    would send every vouched friend to the lobby, and the feature would look like it did nothing."""
    store.add_vouch(code="GONE", created_by=1, when="t")
    guild = _VouchGuild([_Invite("GONE", 0)])
    door._invite_uses[guild.id] = {"GONE": 0}
    guild._invites = []                       # spent, therefore gone
    assert asyncio.run(door.on_member_join(_Joiner(guild))) is True


def test_a_multi_use_vouch_link_only_ever_lets_ONE_person_skip_the_form(_open_door):
    """The founder can make a link with more uses. The second arrival on it must NOT walk in - a
    vouch is for one named person, and a link that keeps working is a hole that widens every time
    it is forwarded."""
    store.add_vouch(code="SHARED", created_by=1, when="t")
    guild = _VouchGuild([_Invite("SHARED", 0)])
    door._invite_uses[guild.id] = {"SHARED": 0}

    guild._invites = [_Invite("SHARED", 1)]
    assert asyncio.run(door.on_member_join(_Joiner(guild, uid=1))) is True
    guild._invites = [_Invite("SHARED", 2)]
    assert asyncio.run(door.on_member_join(_Joiner(guild, uid=2))) is False, \
        "a second person walked in on a spent vouch"
    assert guild.granted == [door.MEMBER_ROLE]


def test_somebody_on_an_ordinary_invite_still_meets_the_door(_open_door):
    store.add_vouch(code="FRIEND1", created_by=1, when="t")
    guild = _VouchGuild([_Invite("FRIEND1", 0), _Invite("PUBLIC", 5)])
    door._invite_uses[guild.id] = {"FRIEND1": 0, "PUBLIC": 5}
    guild._invites = [_Invite("FRIEND1", 0), _Invite("PUBLIC", 6)]   # the public one grew

    assert asyncio.run(door.on_member_join(_Joiner(guild))) is False
    assert guild.granted == [], "a stranger was let past the door"


def test_two_people_joining_at_once_are_sent_to_the_lobby_rather_than_guessed_at(_open_door):
    """Ambiguity resolves to NOT vouched. A stranger let in by mistake is the failure that
    matters; a vouched friend who has to fill the form is an inconvenience."""
    store.add_vouch(code="FRIEND1", created_by=1, when="t")
    guild = _VouchGuild([_Invite("FRIEND1", 0), _Invite("PUBLIC", 5)])
    door._invite_uses[guild.id] = {"FRIEND1": 0, "PUBLIC": 5}
    guild._invites = [_Invite("FRIEND1", 1), _Invite("PUBLIC", 6)]   # both changed

    assert asyncio.run(door.on_member_join(_Joiner(guild))) is False


def test_nothing_happens_to_arrivals_when_the_door_is_not_switched_on(monkeypatch):
    monkeypatch.setattr(door.CFG, "door_channel_id", None, raising=False)
    guild = _VouchGuild([])
    assert asyncio.run(door.on_member_join(_Joiner(guild))) is False


def test_a_bot_joining_is_never_vouched(_open_door):
    store.add_vouch(code="FRIEND1", created_by=1, when="t")
    guild = _VouchGuild([])
    door._invite_uses[guild.id] = {"FRIEND1": 0}
    assert asyncio.run(door.on_member_join(_Joiner(guild, bot=True))) is False


def test_a_vouch_code_can_only_be_claimed_once_even_in_a_race():
    """The INNER guard, pinned directly.

    `on_member_join` already refuses a code that is no longer in `open_vouch_codes()`, which is why
    the multi-use test above passes with this guard removed - it never reaches it. But those are
    two separate reads with a gap between them, and two people joining in the same instant both
    pass the first check. The atomic `WHERE used_by IS NULL` is what actually decides it, so it
    gets its own test rather than living behind a check that happens to shadow it."""
    store.add_vouch(code="RACE", created_by=1, when="t")
    first = store.claim_vouch(code="RACE", used_by=100, when="t1")
    second = store.claim_vouch(code="RACE", used_by=200, when="t2")
    assert first is True
    assert second is False, "two people claimed the same vouch"
    assert store.vouch("RACE")["used_by"] == 100, "the second claim overwrote the first"


def test_claiming_a_code_that_was_never_vouched_does_nothing():
    assert store.claim_vouch(code="NEVER-EXISTED", used_by=1, when="t") is False
