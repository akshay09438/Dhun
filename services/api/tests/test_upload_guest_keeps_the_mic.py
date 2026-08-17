"""When somebody uploads their own vocal, THEY are what the mix is for.

MEASURED 2026-08-17, across the 216 real mix plans on disk. A catalog "beat" is very often a full
vocal song, so the arrangement's both-songs-trade flourish gives the beat's own singer a large share
of the mix. Averaged per beat, the guest's share of the singing runs 27%-59%; on the pair the
founder reported (Anchor Point x Location) the guest got 33s against the host's 135s - TWENTY PER
CENT. Eight of thirty beats leave the guest under half.

For the catalog that is a taste question, and it is answered by ear, one beat at a time, in
`beat_guest_verse.GUEST_VERSE`. For an UPLOAD it is not a taste question at all: somebody who
uploads their own track and waits for a render wants to hear THEIR track. A beat that sings 80% of
their mix reads as the feature being broken, which is exactly what the founder predicted would
happen to all three testers.

So when Song 2 is an upload, Song 1's own vocal is not placed. The guest carries the whole mix.
This reuses the instrumental-only path that already exists for Merrygo and Rapture - the same
outcome, reached for a different and explicit reason.

WHAT THIS MUST NOT DO: change a single catalog mix. The flag defaults to False, so every existing
pair plans exactly as before - asserted below, because a silent change to the catalog's arrangements
would be far worse than the bug being fixed.
"""

import pytest

from app.planner import plan as planner
from tests.test_fence import make_analysis


def _pair():
    """A vocal-RICH beat (it sings across the track) plus a guest with plenty to sing."""
    a1 = make_analysis(bpm=120.0, n_bars=64,
                       vocal_regions=[(8.0, 24.0), (40.0, 60.0), (72.0, 96.0)])
    a1.song_id = "beat" + "a" * 60
    a2 = make_analysis(bpm=120.0, n_bars=64,
                       vocal_regions=[(0.0, 16.0), (20.0, 40.0), (44.0, 64.0)])
    a2.song_id = "upl" + "b" * 61
    return a1, a2


def _plan(guest_is_upload):
    a1, a2 = _pair()
    return planner.build_mix_plan("m", a1, a2, "", take=1, guest_is_upload=guest_is_upload)


def test_a_catalog_beat_still_trades_its_own_vocal_in():
    """The existing behaviour, pinned. If this stops being true the test below proves nothing."""
    p = _plan(guest_is_upload=False)
    assert p.s1_vocal_regions, (
        "the fixture beat no longer trades its vocal in, so the upload test has nothing to prove")


def test_an_upload_gets_the_whole_mix_to_itself():
    """THE FIX. Song 1's own singer stands down when the guest is somebody's upload."""
    p = _plan(guest_is_upload=True)
    assert p.s1_vocal_regions == [], (
        "the beat is still singing over an uploaded vocal - the uploader hears someone else's song")


def test_the_upload_still_gets_a_real_arrangement():
    """Silencing the host must not cost the guest its placements - it should gain, not lose."""
    catalog = _plan(guest_is_upload=False)
    upload = _plan(guest_is_upload=True)
    assert upload.placements, "the upload got no vocal placements at all"
    assert len(upload.placements) >= len(catalog.placements), (
        "silencing the beat reduced the guest's own placements")


def test_the_flag_defaults_to_off():
    """Every existing caller - routes/mix.py, sanity_check.py, every cached plan - must be untouched."""
    a1, a2 = _pair()
    explicit = planner.build_mix_plan("m", a1, a2, "", take=1, guest_is_upload=False)
    default = planner.build_mix_plan("m", a1, a2, "", take=1)
    assert default.s1_vocal_regions == explicit.s1_vocal_regions
    assert default.model_dump() == explicit.model_dump(), (
        "the default path is no longer byte-identical to the pre-change plan")


def test_a_hand_marked_instrumental_beat_is_unaffected(monkeypatch):
    """The existing hand-list keeps working on its own terms, upload or not."""
    from app.planner import instrumental_beats
    a1, a2 = _pair()
    monkeypatch.setattr(instrumental_beats, "INSTRUMENTAL_ONLY_BEATS", frozenset({a1.song_id}))
    p = planner.build_mix_plan("m", a1, a2, "", take=1)
    assert p.s1_vocal_regions == [], "the instrumental-only hand-list stopped being honoured"
