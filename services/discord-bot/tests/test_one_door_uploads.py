"""One door, one field: `/grind` takes a song of your own, and it joins BOTH your lists.

WHY THIS EXISTS. The founder used `/add` for real and reported the JOURNEY, not the sound: "I like
the mixes they are making but this is the issue and the experience is the issue." Then, after the
first rebuild, they hit the next wall immediately:

    "when I click on one of them, the 'Add my' thing disappears"

The first rebuild gave `/grind` TWO optional file fields, `my_beat` and `my_vocal`. Whether Discord
keeps offering the second field once the first is filled is its client's behaviour and nothing this
code can reach - so the design stopped depending on it. There is now ONE field. A song goes in
without being asked which side it is, and appears under **Pick a beat** AND **Pick a vocal**; the
choice is made at mixing time, where it belongs.

THAT IS SAFE RATHER THAN SLOPPY. `role_hint` was only ever a menu filter - this project measured a
song tagged `vocals` working fine as the beat, for ~2.5x more workable pairs at zero cost.

THE PLATFORM WALL, because it shapes all of it. Discord does NOT let a button or a select menu open
a file picker, and a modal accepts text inputs only. A bot receives a file in exactly two ways: as
a slash-command ATTACHMENT option, or from a message posted in a channel - and the second needs the
privileged MESSAGE_CONTENT intent AND would make somebody's unreleased track publicly visible,
straight against the founder's own rule. So the file must ride on the command.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot as botmod  # noqa: E402
from api_client import Song  # noqa: E402


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


def _song(sid, name, role="vocals", featured=True, language="english"):
    return Song(id=sid, name=name, role_hint=role, language=language, featured=featured)


def _stock_catalogue():
    botmod.bot.songs = [
        _song("b" * 64, "Levels", role="beat"),
        _song("v" * 64, "Location", role="vocals"),
    ]
    botmod.bot.beats = [s for s in botmod.bot.songs if s.role_hint == "beat"]
    botmod.bot.vocals = [s for s in botmod.bot.songs if s.role_hint == "vocals"]


def _mine(uid, *songs):
    botmod._my_uploads[str(uid)] = list(songs)


# --- the plan: what happens before anything is spent -------------------------------------------

def test_no_attachment_is_the_journey_that_already_works():
    plan = botmod.plan_upload(None)
    assert plan.refusal is None
    assert plan.ask_for_drop is False
    assert plan.attachment is None


def test_a_song_is_asked_where_the_drop_hits():
    """Asked ONCE, for every upload, because the song can now be picked as the beat at any time.

    This is NOT the thing the founder complained about. Then, a song was pinned to one side, so
    asking a VOCAL where its drop hits was asking about something that could never be used. Now an
    upload appears under both headings, so the answer is always live."""
    plan = botmod.plan_upload(_Att("mysong.mp3"))
    assert plan.refusal is None
    assert plan.ask_for_drop is True


def test_an_oversized_file_is_refused_without_asking_for_a_drop():
    """Asking and THEN refusing wastes the one question this journey gets."""
    plan = botmod.plan_upload(_Att("huge.mp3", size=40 * 1024 * 1024))
    assert plan.refusal is not None and "MB" in plan.refusal
    assert plan.ask_for_drop is False, "it asked about a file it was about to refuse"


def test_a_file_that_is_not_audio_is_refused():
    plan = botmod.plan_upload(_Att("holiday.png"))
    assert plan.refusal is not None
    assert "MP3" in plan.refusal or "M4A" in plan.refusal


def test_the_size_limit_matches_the_engines_own_cap():
    assert botmod.MAX_UPLOAD_BYTES == 30 * 1024 * 1024


def test_the_refusal_quotes_the_limit_everything_else_quotes():
    """It said "the limit is 31 MB" - it divided by a million while the cap counts in 1024s, so the
    app quoted a ceiling matching nothing else it says. Found by walking the journey, not by a
    test."""
    plan = botmod.plan_upload(_Att("huge.mp3", size=40 * 1024 * 1024))
    assert "30 MB" in plan.refusal and "40 MB" in plan.refusal


# --- the drop, read the way the engine reads it ------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("1:24", 84.0), ("84", 84.0), ("1:24.5", 84.5), ("0:30", 30.0), ("  1:24  ", 84.0)])
def test_a_drop_a_person_would_type_is_understood(raw, expected):
    assert botmod.parse_drop(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "soon", "1:75", "-5", "0:nan", "0:inf", "nan"])
def test_a_drop_that_is_not_a_time_is_rejected(raw):
    """`0:nan` is not hypothetical - it reached the engine from Discord and wrote a literal NaN
    into the manifest that indexes every song, found in the 2026-08-17 security review."""
    assert botmod.parse_drop(raw) is None


# --- YOUR songs are in YOUR picker, under both headings ----------------------------------------

def test_your_own_song_appears_under_both_headings():
    """THE FOUNDER'S ASK, 2026-08-18: "under Choose the Beat, their song name is also shown. Under
    Choose Vocal, the song is also shown, and they can choose whatever they like." """
    _stock_catalogue()
    _mine(111, _song("m" * 64, "My Own Song"))
    v = botmod.GrindBuilderView(111)
    assert "My Own Song" in [o.label for o in v.beat_select.options], "not offered as a beat"
    assert "My Own Song" in [o.label for o in v.vocal_select.options], "not offered as a vocal"


def test_your_own_song_comes_first_in_both_lists():
    """Invisible unless it is in front of you - a Discord dropdown holds 25 and the catalogue
    fills it."""
    _stock_catalogue()
    _mine(111, _song("m" * 64, "My Own Song"))
    v = botmod.GrindBuilderView(111)
    assert v.beat_select.options[0].label == "My Own Song"
    assert v.vocal_select.options[0].label == "My Own Song"


def test_the_role_it_was_stored_under_does_not_decide_where_it_shows():
    """`role_hint` was only ever a menu filter - a song tagged `vocals` was measured working fine
    as the beat. An upload is no longer asked which side it is, so nothing may read that tag to
    decide where it appears."""
    _stock_catalogue()
    _mine(111, _song("m" * 64, "Tagged A Vocal", role="vocals"))
    v = botmod.GrindBuilderView(111)
    assert "Tagged A Vocal" in [o.label for o in v.beat_select.options]


def test_a_stranger_never_sees_your_songs():
    """An unreleased track must not be reachable by somebody who merely knows the person exists."""
    _stock_catalogue()
    _mine(111, _song("m" * 64, "My Own Song"))
    v = botmod.GrindBuilderView(222)
    assert "My Own Song" not in [o.label for o in v.beat_select.options]
    assert "My Own Song" not in [o.label for o in v.vocal_select.options]


def test_your_own_song_survives_the_language_filter():
    """An upload's language is a default nobody was asked for, and a language tag once hid 103
    songs. Doing that to somebody's own track, in their own picker, is the same bug smaller."""
    _stock_catalogue()
    _mine(111, _song("m" * 64, "My Own Song", language="hindi"))
    v = botmod.GrindBuilderView(111)          # the picker defaults to english
    assert "My Own Song" in [o.label for o in v.vocal_select.options]


# --- the command itself -------------------------------------------------------------------------

def test_grind_with_nothing_attached_opens_todays_picker():
    """THE REGRESSION GUARD. `/grind` is the single path the whole product runs on, so a break here
    is a total outage. Typing it with no file must be what it has always been."""
    _stock_catalogue()
    sink = {}
    asyncio.run(botmod.grind_cmd.callback(_Interaction(sink)))
    assert sink.get("modal") is None, "an empty /grind asked a question it never used to ask"
    assert isinstance(sink.get("view"), botmod.GrindBuilderView)
    assert sink.get("ephemeral") is True, "the picker stopped being private"


def test_grind_with_a_song_pops_the_drop_question():
    _stock_catalogue()
    sink = {}
    asyncio.run(botmod.grind_cmd.callback(_Interaction(sink), my_song=_Att("mysong.mp3")))
    assert sink.get("modal") is not None, "a song was taken without asking where the drop is"
    assert sink.get("view") is None, "it opened the picker as well as asking"


def test_there_is_exactly_one_upload_field():
    """It was TWO, `my_beat` and `my_vocal`, and the founder hit the problem at once: "when I click
    on one of them, the 'Add my' thing disappears". Whether Discord keeps offering the second field
    is its client's behaviour, so the design stopped depending on it."""
    import discord as _d
    cmd = botmod.bot.tree.get_command("grind")
    params = list(getattr(cmd, "parameters", []))
    assert [p.name for p in params] == ["my_song"], "the upload field count changed"
    assert not params[0].required, "typing /grind on its own must still work"
    assert params[0].type is _d.AppCommandOptionType.attachment, \
        "a song CHOICE belongs to the picker, not to the command"


def test_an_oversized_upload_is_refused_in_plain_words():
    _stock_catalogue()
    sink = {}
    asyncio.run(botmod.grind_cmd.callback(
        _Interaction(sink), my_song=_Att("huge.mp3", size=40 * 1024 * 1024)))
    assert sink.get("said") and "MB" in sink["said"]
    assert sink.get("modal") is None and sink.get("view") is None


def test_the_door_is_still_checked_before_anything_is_read(monkeypatch):
    """An upload must not be fetched off Discord for somebody who is not allowed to grind."""
    monkeypatch.setattr(botmod.door, "blocked_reason", lambda _i: "You are not in yet.")
    sink = {}
    asyncio.run(botmod.grind_cmd.callback(_Interaction(sink), my_song=_Att("mysong.mp3")))
    assert sink.get("said") == "You are not in yet."
    assert sink.get("modal") is None, "a blocked person was asked for a drop"


# --- the modal ----------------------------------------------------------------------------------

def test_a_nonsense_drop_asks_again_instead_of_losing_the_upload():
    """Refusing outright would cost them the file and make them find and re-attach it. The
    attachment's own url outlives the interaction, so the plan is still good and only the answer
    was wrong."""
    plan = botmod.plan_upload(_Att("s.mp3"))
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
    plan = botmod.plan_upload(_Att("s.mp3"))
    modal = botmod.DropModal(plan)
    modal.drop._value = "1:24"
    asyncio.run(modal.on_submit(_Interaction({})))
    assert got["drop"] == "1:24"


# --- a drop that goes nowhere is said out loud ---------------------------------------------------

def test_a_drop_typed_for_a_song_already_here_is_admitted_not_swallowed():
    """The engine used to return early on a duplicate BEFORE writing the drop, so the answer was
    binned in silence. Fixed engine-side; the bot says so either way rather than staying quiet."""
    assert botmod._drop_went_nowhere(True, "1:24") is True


def test_a_drop_on_a_brand_new_song_is_not_flagged():
    assert botmod._drop_went_nowhere(False, "1:24") is False


def test_no_drop_typed_means_nothing_to_warn_about():
    assert botmod._drop_went_nowhere(True, "") is False


def test_the_warning_says_no_money_was_taken():
    """They are being told something went wrong. The next thing they will wonder is whether it cost
    them, so it is answered in the same breath."""
    assert "charged" in botmod._OLD_DROP_NOTE or "cost" in botmod._OLD_DROP_NOTE
    assert "not saved" in botmod._OLD_DROP_NOTE


# --- the old door is closed ---------------------------------------------------------------------

def test_add_is_no_longer_a_command():
    """The founder's first complaint was having to go to `/add` at all."""
    assert botmod.bot.tree.get_command("add") is None, "/add is still registered"


def test_mine_survives_because_it_answers_a_different_question():
    assert botmod.bot.tree.get_command("mine") is not None


def test_grind_is_still_registered_and_still_says_what_it_does():
    cmd = botmod.bot.tree.get_command("grind")
    assert cmd is not None and cmd.description


# --- no copy may point at a command that does not exist -----------------------------------------

def test_no_message_sends_somebody_to_a_command_that_does_not_exist():
    """DELETING A COMMAND IS ONLY HALF THE JOB, and this project has learned it three times:
    `#read-this-first` advertised `/mix`, `/set` and `/songs` for two versions after they were
    removed; `/help` promised a `/grind beat: vocal:` form that did nothing; and removing `/add`
    left `/mine` saying "`/add` takes an MP3 or M4A" as the ONLY route it offered for adding a
    song. Nothing errored. It just sent people nowhere.

    So this walks every STRING the bot can actually say (docstrings and comments excluded, since
    those are for us) and fails if it names a slash command that is not registered."""
    import ast

    src_dir = Path(__file__).resolve().parents[1]
    registered = {c.name for c in botmod.bot.tree.get_commands()}

    offences = []
    for path in (src_dir / "bot.py", src_dir / "ui.py", src_dir / "door.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                first = node.body[0] if node.body else None
                if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                        and isinstance(first.value.value, str)):
                    docstrings.add(id(first.value))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if id(node) in docstrings:
                continue
            for named in re.findall(r"`/([a-z][a-z0-9_-]*)", node.value):
                if named not in registered:
                    offences.append(f"{path.name}:{node.lineno} -> /{named}")

    assert not offences, ("copy points at a command that is not registered:\n  "
                          + "\n  ".join(offences))
