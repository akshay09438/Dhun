"""One door: `/grind` carries your own songs, so there is no separate errand.

WHY THIS EXISTS. The founder used `/add` for real and reported the JOURNEY, not the sound:
"I like the mixes they are making but this is the issue and the experience is the issue."
Three complaints, all reproduced in the code before a line was changed:

  1. `/add` takes ONE song, so you cannot bring your own beat AND your own vocal.
  2. The `drop` field is VISIBLE on `/add` even when you pick "vocal", so it reads as being asked
     for something irrelevant. (The code only ENFORCED it for beats — Discord shows every option
     regardless of which choice you made. Platform behaviour, not a broken check, and the fix is
     therefore to stop it being a command option at all.)
  3. Uploading is a separate command from grinding, so one job takes two places.

THE PLATFORM WALL, because it shapes everything here. Discord does NOT let a button or a select
menu open a file picker, and a modal accepts text inputs only. A bot can receive a file in exactly
two ways: as a slash-command ATTACHMENT option, or from a message posted in a channel — and the
second needs the privileged MESSAGE_CONTENT intent AND would make somebody's unreleased track
publicly visible, straight against the founder's own rule. So the files must ride on the command.

THE LESSON THIS RE-OPENS, ON PURPOSE. `grind_cmd` used to carry optional `beat`/`vocal` options and
they were deliberately removed: "a first-timer reading two blanks cannot tell that leaving them
empty is the right move." That warning is respected, not ignored — the difference is that those
options DUPLICATED the picker, whereas these do the one thing the picker cannot do at all. They are
named `my_beat`/`my_vocal` so they read as yours-and-optional rather than as a form to fill in, and
the no-attachment path is pinned below to behave exactly as it does today.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot as botmod  # noqa: E402


# --- fakes ------------------------------------------------------------------------------------

class _Att:
    """Just enough of a discord.Attachment. `size` is Discord's own figure and costs no fetch."""

    def __init__(self, filename="song.mp3", size=2_000_000, data=b"audio"):
        self.filename, self.size, self._data = filename, size, data

    async def read(self):
        return self._data


class _Resp:
    def __init__(self, sink):
        self.sink = sink

    async def send_message(self, content=None, *, embed=None, view=None, ephemeral=False, **_k):
        self.sink.update({"said": content, "embed": embed, "view": view, "ephemeral": ephemeral})

    async def send_modal(self, modal):
        self.sink["modal"] = modal

    async def defer(self, **k):
        self.sink["deferred"] = k

    async def edit_message(self, **_k):
        self.sink["edited"] = True


class _Interaction:
    def __init__(self, sink, uid=111):
        self.user = type("U", (), {"id": uid, "name": "someone", "display_name": "Someone"})()
        self.channel = type("C", (), {"id": 1, "category": None, "category_id": None})()
        self.guild = None
        self.response = _Resp(sink)
        self.followup = type("F", (), {"send": self._fu})()
        self.sink = sink

    async def _fu(self, *a, **k):
        self.sink.setdefault("followups", []).append((a, k))
        return type("M", (), {"edit": self._noop})()

    async def _noop(self, **_k):
        return None


@pytest.fixture(autouse=True)
def _open_everything(monkeypatch):
    """The door and the room rules are tested elsewhere; hold them open so these tests are about
    the journey only."""
    monkeypatch.setattr(botmod.door, "blocked_reason", lambda _i: None)
    monkeypatch.setattr(botmod, "_grinding_allowed_here", lambda _i: None)
    botmod._my_uploads.clear()
    yield
    botmod._my_uploads.clear()


def _stock_catalogue():
    from api_client import Song
    botmod.bot.songs = [
        Song(id="b" * 64, name="Levels", role_hint="beat", language="english", featured=True),
        Song(id="v" * 64, name="Location", role_hint="vocals", language="english", featured=True),
    ]
    botmod.bot.beats = [s for s in botmod.bot.songs if s.role_hint == "beat"]
    botmod.bot.vocals = [s for s in botmod.bot.songs if s.role_hint == "vocals"]


# --- the plan: what happens before anything is spent -------------------------------------------

def test_no_attachments_is_the_journey_that_already_works():
    plan = botmod.plan_uploads(None, None)
    assert plan.refusal is None
    assert plan.ask_for_drop is False
    assert plan.uploads == []


def test_a_beat_is_asked_where_the_drop_hits():
    """The app's own drop finder measured ~36% precision (7 found on a song with 2), and a Suno
    master is exactly the input it is worst on. The person made the song; they know."""
    plan = botmod.plan_uploads(_Att("mybeat.mp3"), None)
    assert plan.refusal is None
    assert plan.ask_for_drop is True


def test_a_vocal_is_never_asked_for_a_drop():
    """THE FOUNDER'S COMPLAINT, PINNED. 'For vocal also it is asking me to mark the drop.'"""
    plan = botmod.plan_uploads(None, _Att("myvocal.mp3"))
    assert plan.refusal is None
    assert plan.ask_for_drop is False, "a vocal was asked for a drop it has no use for"


def test_both_sides_can_be_your_own_songs():
    """THE OTHER FOUNDER COMPLAINT: 'I can only add either vocal or beat but I want to add both.'"""
    plan = botmod.plan_uploads(_Att("mybeat.mp3"), _Att("myvocal.mp3"))
    assert plan.refusal is None
    assert [role for role, _ in plan.uploads] == ["beat", "vocals"]
    assert plan.ask_for_drop is True, "the beat still needs its drop"


def test_only_the_beat_is_asked_even_when_both_are_uploaded():
    plan = botmod.plan_uploads(_Att("mybeat.mp3"), _Att("myvocal.mp3"))
    assert sum(1 for role, _ in plan.uploads if role == "beat") == 1


# --- refusing for free, before a modal and before a byte is fetched ----------------------------

def test_an_oversized_file_is_refused_without_asking_for_a_drop():
    """Asking for the drop and THEN refusing the file wastes the one question we ask. Size is
    Discord's own figure, so this costs no fetch."""
    plan = botmod.plan_uploads(_Att("huge.mp3", size=40 * 1024 * 1024), None)
    assert plan.refusal is not None and "MB" in plan.refusal
    assert plan.ask_for_drop is False, "it asked for a drop on a file it was about to refuse"


def test_a_file_that_is_not_audio_is_refused():
    plan = botmod.plan_uploads(None, _Att("holiday.png"))
    assert plan.refusal is not None
    assert "MP3" in plan.refusal or "M4A" in plan.refusal


def test_the_same_file_in_both_slots_is_refused():
    """A mix is two songs. The engine would dedupe them to one id and quietly mix a song with
    itself, which is not a thing anybody meant to ask for."""
    same = _Att("one.mp3", size=123456)
    plan = botmod.plan_uploads(same, _Att("one.mp3", size=123456))
    assert plan.refusal is not None
    assert plan.ask_for_drop is False


def test_the_size_limit_matches_the_engines_own_cap():
    assert botmod.MAX_UPLOAD_BYTES == 30 * 1024 * 1024


def test_the_refusal_quotes_the_limit_everything_else_quotes():
    """It said "the limit is 31 MB" — because it divided by a million while the cap counts in
    1024s. The engine's own refusal says 30 MB, so the app was quoting a ceiling that matched
    nothing else it says. Found by walking the journey; no test would have noticed."""
    plan = botmod.plan_uploads(_Att("huge.mp3", size=40 * 1024 * 1024), None)
    assert "30 MB" in plan.refusal, f"quoted the wrong limit: {plan.refusal}"
    assert "40 MB" in plan.refusal, f"quoted the wrong file size: {plan.refusal}"


# --- the drop, read the way the engine reads it ------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("1:24", 84.0),
    ("84", 84.0),
    ("1:24.5", 84.5),
    ("0:30", 30.0),
    ("  1:24  ", 84.0),
])
def test_a_drop_a_person_would_type_is_understood(raw, expected):
    assert botmod.parse_drop(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "soon", "1:75", "-5", "0:nan", "0:inf", "nan"])
def test_a_drop_that_is_not_a_time_is_rejected(raw):
    """`0:nan` is not hypothetical — it reached the engine from Discord and wrote a literal NaN
    into the manifest that indexes every song, found in the 2026-08-17 security review. The bot
    now refuses it a round trip earlier."""
    assert botmod.parse_drop(raw) is None


# --- the command itself -------------------------------------------------------------------------

def test_grind_with_nothing_attached_opens_todays_picker():
    """THE REGRESSION GUARD. `/grind` is the single path the whole product runs on; a break here
    is a total outage. Typing it with no files must be exactly what it has always been."""
    _stock_catalogue()
    sink = {}
    asyncio.run(botmod.grind_cmd.callback(_Interaction(sink)))
    assert sink.get("modal") is None, "an empty /grind asked a question it never used to ask"
    assert isinstance(sink.get("view"), botmod.GrindBuilderView)
    assert sink.get("ephemeral") is True, "the picker stopped being private"


def test_grind_with_a_beat_pops_the_drop_question():
    _stock_catalogue()
    sink = {}
    asyncio.run(botmod.grind_cmd.callback(_Interaction(sink), my_beat=_Att("mybeat.mp3")))
    assert sink.get("modal") is not None, "a beat was taken without ever asking where the drop is"
    assert sink.get("view") is None, "it opened the picker as well as asking"


def test_grind_with_only_a_vocal_asks_nothing_at_all(monkeypatch):
    """Attach a vocal and the next thing you see is your song going in — no question, no form."""
    _stock_catalogue()
    got = {}

    async def fake_ingest(interaction, plan, drop):
        got["drop"] = drop
        got["roles"] = [r for r, _ in plan.uploads]

    monkeypatch.setattr(botmod, "_ingest_uploads", fake_ingest)
    sink = {}
    asyncio.run(botmod.grind_cmd.callback(_Interaction(sink), my_vocal=_Att("myvocal.mp3")))
    assert sink.get("modal") is None, "a vocal was asked for a drop"
    assert got["roles"] == ["vocals"]
    assert got["drop"] == ""


def test_an_oversized_upload_is_refused_in_plain_words(monkeypatch):
    _stock_catalogue()
    sink = {}
    asyncio.run(botmod.grind_cmd.callback(
        _Interaction(sink), my_vocal=_Att("huge.mp3", size=40 * 1024 * 1024)))
    assert sink.get("said") and "MB" in sink["said"]
    assert sink.get("modal") is None and sink.get("view") is None


def test_the_door_is_still_checked_before_anything_is_read(monkeypatch):
    """An upload must not be fetched off Discord for somebody who is not allowed to grind."""
    monkeypatch.setattr(botmod.door, "blocked_reason", lambda _i: "You are not in yet.")
    sink = {}
    asyncio.run(botmod.grind_cmd.callback(_Interaction(sink), my_beat=_Att("mybeat.mp3")))
    assert sink.get("said") == "You are not in yet."
    assert sink.get("modal") is None, "a blocked person was asked for a drop"


# --- the modal ----------------------------------------------------------------------------------

def test_the_drop_question_only_ever_appears_for_a_beat():
    """Structural, not incidental: the modal is constructed from a plan that says a beat is
    present, so there is no path that shows it for a vocal."""
    plan = botmod.plan_uploads(None, _Att("v.mp3"))
    assert plan.ask_for_drop is False
    plan2 = botmod.plan_uploads(_Att("b.mp3"), _Att("v.mp3"))
    assert plan2.ask_for_drop is True


def test_a_nonsense_drop_asks_again_instead_of_losing_the_upload(monkeypatch):
    """Refusing outright would cost them the file and make them re-attach it. The attachment is
    still valid (its CDN url outlives the interaction), so the question is simply asked again."""
    plan = botmod.plan_uploads(_Att("b.mp3"), None)
    modal = botmod.DropModal(plan)
    modal.drop._value = "whenever"
    sink = {}
    asyncio.run(modal.on_submit(_Interaction(sink)))
    assert sink.get("modal") is not None, "a mistyped time threw the upload away"
    assert sink["modal"].error, "it asked again but did not say what was wrong"


def test_a_good_drop_goes_through_to_the_ingest(monkeypatch):
    got = {}

    async def fake_ingest(interaction, plan, drop):
        got["drop"] = drop

    monkeypatch.setattr(botmod, "_ingest_uploads", fake_ingest)
    plan = botmod.plan_uploads(_Att("b.mp3"), None)
    modal = botmod.DropModal(plan)
    modal.drop._value = "1:24"
    asyncio.run(modal.on_submit(_Interaction({})))
    assert got["drop"] == "1:24"


# --- a drop that goes nowhere is said out loud ---------------------------------------------------

def test_a_drop_typed_for_a_song_already_here_is_admitted_not_swallowed():
    """`POST /songs/add` returns early on a duplicate, BEFORE it writes `main_drop`. So somebody
    who re-attaches a song they already uploaded is asked for the drop, answers, and the answer is
    binned with nothing on screen saying so.

    IT BITES THE FOUNDER FIRST: both of their own uploads are stored as `vocals` with no drop,
    because until tonight declaring a beat forced you to supply one and declaring a vocal did not.
    Re-attaching one as `my_beat` is exactly this path."""
    got_in = [("beat", "b" * 64, "My Beat", True)]        # True = it was already here
    assert botmod._drop_went_nowhere(got_in, "1:24") is True


def test_a_drop_on_a_brand_new_beat_is_not_flagged():
    got_in = [("beat", "b" * 64, "My Beat", False)]
    assert botmod._drop_went_nowhere(got_in, "1:24") is False


def test_a_vocal_that_was_already_here_raises_nothing():
    """A vocal is never asked for a drop, so there is no answer to lose."""
    got_in = [("vocals", "v" * 64, "My Vocal", True)]
    assert botmod._drop_went_nowhere(got_in, "") is False
    assert botmod._drop_went_nowhere(got_in, "1:24") is False


def test_the_warning_says_no_money_was_taken():
    """The person is being told something went wrong. The very next thing they will wonder is
    whether it cost them, so it is answered in the same breath."""
    assert "charged" in botmod._OLD_DROP_NOTE or "cost" in botmod._OLD_DROP_NOTE
    assert "not saved" in botmod._OLD_DROP_NOTE


# --- the old door is closed ---------------------------------------------------------------------

def test_add_is_no_longer_a_command():
    """The founder's first complaint was having to go to `/add` at all. Leaving it registered
    would leave the second door standing next to the sign saying there is only one."""
    assert botmod.bot.tree.get_command("add") is None, "/add is still registered"


def test_mine_survives_because_it_answers_a_different_question():
    """`/mine` is not a second door — it is how you find songs you already added."""
    assert botmod.bot.tree.get_command("mine") is not None


def test_grind_is_still_registered_and_still_says_what_it_does():
    cmd = botmod.bot.tree.get_command("grind")
    assert cmd is not None and cmd.description
