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
    "Your relation to music": "I DJ at weekends",
    "AI tools you have used": "Suno and Midjourney",
    "Why you want to join": "want to make mashups",
    "What you expect": "to post clips",
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
    assert labels == ["Your name", "Your relation to music", "AI tools you have used",
                      "Why you want to join", "What you expect"]
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
