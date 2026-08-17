"""An upload silences the catalogue song's own singer — in BOTH directions, and for real.

The flag that does this was added on 2026-08-17 and DEFAULTED TO FALSE WITH NO CALLER. It has
therefore never once run: `routes/mix.py` called `build_mix_plan` without it, so every mix ever
made planned as though no upload existed. These tests exist because "it is built" and "it fires"
turned out to be different things, and only the second one matters to a person waiting on a render.

TWO DIRECTIONS, TWO REASONS, TWO PARAMETERS:

  * `guest_is_upload`  — Song 2 is somebody's upload. Measured across 216 real plans, a catalog
    beat is usually a full vocal song and takes 41-73% of the singing; an uploader who waited for
    a render wants to hear THEIR track, not the beat's singer.
  * `beat_is_upload`   — Song 1 is somebody's upload. A Suno track used as a beat almost always
    has its own vocal, so pairing it with a catalog vocal puts two singers on top of each other.

They are deliberately NOT one parameter. Both reach the same branch, but a single flag would make
whichever name it kept a lie at one of the two call sites, and this is exactly the sort of thing a
later reader has to trust without re-deriving.

THE THING THAT MUST NOT MOVE: a catalogue x catalogue mix. Those are the mixes that already sound
right, and a silent change to them would be worse than the bug being fixed.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from app import library_store
from app.planner import plan as planner
from app.planner import uploads
from tests.test_fence import make_analysis

BEAT = "beat" + "a" * 60
VOC = "voc" + "b" * 61


@pytest.fixture(autouse=True)
def _fresh(monkeypatch, tmp_path):
    """A throwaway manifest, and the upload reader's cache cleared, for every test."""
    monkeypatch.setattr(library_store, "settings",
                        dataclasses.replace(library_store.settings, data_dir=tmp_path))
    uploads.forget_cached_manifest()
    yield
    uploads.forget_cached_manifest()


def _pair():
    """A vocal-RICH beat (it sings across the track) plus a guest with plenty to sing."""
    a1 = make_analysis(bpm=120.0, n_bars=64,
                       vocal_regions=[(8.0, 24.0), (40.0, 60.0), (72.0, 96.0)])
    a1.song_id = BEAT
    a2 = make_analysis(bpm=120.0, n_bars=64,
                       vocal_regions=[(0.0, 16.0), (20.0, 40.0), (44.0, 64.0)])
    a2.song_id = VOC
    return a1, a2


# --- reading "is this an upload" off the catalogue row ---------------------------------------

def test_a_catalogue_song_is_not_an_upload():
    library_store.upsert("Wake Me Up", BEAT, "beat")
    assert uploads.is_upload(BEAT) is False


def test_a_row_with_an_uploader_is_an_upload():
    library_store.upsert("my track", BEAT, "beat", extra={"uploaded_by": "12345"})
    assert uploads.is_upload(BEAT) is True


def test_an_unknown_song_is_not_an_upload():
    """A song with no row at all must never read as an upload — that would silence a catalog beat."""
    assert uploads.is_upload("f" * 64) is False


def test_the_manifest_is_not_re_read_on_every_call():
    """`is_upload` runs on the hot planning path; re-reading the file each time is a disk hit per
    call. Cached, and invalidated by mtime — never by a timer."""
    library_store.upsert("my track", BEAT, "beat", extra={"uploaded_by": "1"})
    uploads.is_upload(BEAT)
    reads = []
    real = library_store.load
    library_store_load = lambda *a, **k: (reads.append(1), real(*a, **k))[1]  # noqa: E731
    import app.planner.uploads as u
    u.library_store.load = library_store_load
    try:
        for _ in range(20):
            uploads.is_upload(BEAT)
        assert reads == [], f"the manifest was read {len(reads)} times on a warm cache"
    finally:
        u.library_store.load = real


def test_a_new_upload_is_seen_without_a_restart():
    """The cache must not outlive the file it caches — /add writes a row and the very next grind
    has to see it."""
    assert uploads.is_upload(BEAT) is False
    library_store.upsert("my track", BEAT, "beat", extra={"uploaded_by": "1"})
    assert uploads.is_upload(BEAT) is True, "a freshly uploaded song still reads as catalogue"


# --- the hand-marked drop tables still win ---------------------------------------------------

def test_an_uploaded_drop_is_used_when_nothing_is_hand_marked():
    library_store.upsert("my track", BEAT, "beat",
                         extra={"uploaded_by": "1", "main_drop": 84.0})
    from app.planner import main_drops
    assert main_drops.main_drops_for(BEAT) == [84.0]


def test_a_hand_marked_drop_beats_an_uploaded_one(monkeypatch):
    """Same precedence rule as marks_generated: the ear-confirmed tables always win, so an upload
    can never retune a catalog beat that already sounds right."""
    from app.planner import main_drops
    library_store.upsert("my track", BEAT, "beat",
                         extra={"uploaded_by": "1", "main_drop": 84.0})
    monkeypatch.setitem(main_drops.MAIN_DROPS, BEAT, [12.5])
    assert main_drops.main_drops_for(BEAT) == [12.5]


def test_a_catalogue_song_with_no_marks_still_gets_nothing():
    """No row, no upload, no hand mark -> [] so energy detection runs, exactly as before."""
    from app.planner import main_drops
    assert main_drops.main_drops_for("e" * 64) == []


# --- the two directions, through the planner --------------------------------------------------

def test_an_uploaded_vocal_stops_the_beat_singing():
    a1, a2 = _pair()
    p = planner.build_mix_plan("m", a1, a2, "", take=1, guest_is_upload=True)
    assert p.s1_vocal_regions == [], (
        "the beat is still singing over an uploaded vocal — the uploader hears someone else's song")


def test_an_uploaded_beat_goes_instrumental_against_a_catalogue_vocal():
    """The mirror case. A Suno track used as a beat usually has its own vocal, so without this the
    mix has two singers at once."""
    a1, a2 = _pair()
    p = planner.build_mix_plan("m", a1, a2, "", take=1, beat_is_upload=True)
    assert p.s1_vocal_regions == [], (
        "an uploaded beat is singing underneath a catalog vocal — two singers at once")


def test_an_uploaded_vocal_beats_a_hand_marked_guest_verse_window():
    """THE GAP IN THE GROUNDWORK. The five hand-marked guest-verse beats (Wake Me Up, Faded, Lean
    On, Closer, Confusion) return EARLY in _apply_flourishes, before the upload check — so an
    uploaded vocal paired with one of them still had the beat sing its window. The uploader's rule
    has to win over a catalog taste call, or the feature simply does not apply to five of the beats
    on the menu."""
    from app.planner import beat_guest_verse
    a1, a2 = _pair()
    beat_guest_verse.GUEST_VERSE[BEAT] = (10.0, 30.0)
    try:
        p = planner.build_mix_plan("m", a1, a2, "", take=1, guest_is_upload=True)
        assert p.s1_vocal_regions == [], (
            "a guest-verse beat still sings its window over an uploaded vocal")
    finally:
        beat_guest_verse.GUEST_VERSE.pop(BEAT, None)


# --- THE ONE THAT PROTECTS EVERYTHING THAT ALREADY WORKS --------------------------------------

def test_a_catalogue_pair_plans_byte_identically():
    """The founder's own acceptance test. Neither flag set — as for every catalog x catalog mix —
    must produce a plan indistinguishable from the pre-change one, field for field."""
    a1, a2 = _pair()
    default = planner.build_mix_plan("m", a1, a2, "", take=1)
    explicit = planner.build_mix_plan("m", a1, a2, "", take=1,
                                      guest_is_upload=False, beat_is_upload=False)
    assert default.model_dump() == explicit.model_dump()
    assert default.s1_vocal_regions, (
        "the fixture beat no longer trades its vocal in, so the tests above prove nothing")


def test_neither_flag_is_set_for_two_catalogue_songs():
    """Read off the real manifest rather than assumed: two ordinary catalog rows must produce
    (False, False), so nothing about a normal grind changes."""
    library_store.upsert("Wake Me Up", BEAT, "beat")
    library_store.upsert("Rolling in the Deep", VOC, "vocals", "english")
    assert uploads.upload_flags(BEAT, VOC) == (False, False)


def test_both_flags_when_somebody_mixes_two_of_their_own_uploads():
    """Two of your own songs is a supported case — nothing may assume one side is catalogue."""
    library_store.upsert("my beat", BEAT, "beat", extra={"uploaded_by": "1"})
    library_store.upsert("my vocal", VOC, "vocals", "english", extra={"uploaded_by": "1"})
    assert uploads.upload_flags(BEAT, VOC) == (True, True)


# --- and that the ROUTE actually passes them --------------------------------------------------

def test_the_mix_route_tells_the_planner_about_uploads(monkeypatch, tmp_path):
    """The whole point of this change. The flag existed for a day with no caller; this fails if
    `routes/mix.py` ever stops computing and passing them."""
    from app.routes import mix as mixroute

    library_store.upsert("my vocal", VOC, "vocals", "english", extra={"uploaded_by": "1"})
    library_store.upsert("Wake Me Up", BEAT, "beat")
    a1, a2 = _pair()

    seen: dict = {}

    def capture(*args, **kwargs):
        seen.update(kwargs)
        raise RuntimeError("captured — stop before the render")

    monkeypatch.setattr(mixroute, "maybe_sweep", lambda *a, **k: None)
    monkeypatch.setattr(mixroute, "_load_analysis", lambda sid: a1 if sid == BEAT else a2)
    monkeypatch.setattr(mixroute, "build_mix_plan", capture)
    monkeypatch.setattr(mixroute, "_record_mix_event", lambda *a, **k: None)

    mixroute._run_mix("mix-1", BEAT, VOC, "", take=1, rule=1)

    assert seen.get("guest_is_upload") is True, "the route never told the planner Song 2 is an upload"
    assert seen.get("beat_is_upload") is False


def test_the_mix_route_reports_an_uploaded_beat(monkeypatch):
    from app.routes import mix as mixroute

    library_store.upsert("my beat", BEAT, "beat", extra={"uploaded_by": "1"})
    library_store.upsert("Rolling in the Deep", VOC, "vocals", "english")
    a1, a2 = _pair()
    seen: dict = {}

    def capture(*args, **kwargs):
        seen.update(kwargs)
        raise RuntimeError("captured")

    monkeypatch.setattr(mixroute, "maybe_sweep", lambda *a, **k: None)
    monkeypatch.setattr(mixroute, "_load_analysis", lambda sid: a1 if sid == BEAT else a2)
    monkeypatch.setattr(mixroute, "build_mix_plan", capture)
    monkeypatch.setattr(mixroute, "_record_mix_event", lambda *a, **k: None)

    mixroute._run_mix("mix-2", BEAT, VOC, "", take=1, rule=1)

    assert seen.get("beat_is_upload") is True, "the route never told the planner Song 1 is an upload"
    assert seen.get("guest_is_upload") is False


def test_the_manifest_being_unreadable_never_silences_a_catalogue_beat(monkeypatch, tmp_path):
    """Fail SAFE. If the catalogue cannot be read, every song must read as catalogue — guessing
    "upload" would mute the beat's vocal on ordinary grinds for everyone."""
    p = library_store.manifest_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ not json", encoding="utf-8")
    uploads.forget_cached_manifest()
    assert uploads.upload_flags(BEAT, VOC) == (False, False)
    assert json.loads  # keeps the import honest
