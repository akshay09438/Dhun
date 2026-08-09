"""The BEAT song's own vocal (Song 1) also finishes its phrase at the hand-off: each s1_vocal_region's
END is extended to the beat singer's next breath (a1.vocal_pauses), bounded so it never rings past the
R1 crossfade allowance of the Song-2 entry it hands into. Tests `plan._finish_beat_vocal_phrases`."""
from app.models import Placement, TrackAnalysis
from app.planner import fence
from app.planner.plan import _finish_beat_vocal_phrases, _BEAT_FINISH_MAX_S


def _a1(pauses):
    return TrackAnalysis(song_id="a" * 64, status="ready", vocal_pauses=pauses)


def test_extends_the_beat_vocal_to_its_next_breath():
    # region ends 40.0 (mid-word); the beat singer's next breath is 42.0; the Song-2 entry is far away
    out = _finish_beat_vocal_phrases([(10.0, 40.0)], _a1([42.0, 80.0]),
                                     [Placement(anchor=100.0, vocal_src=(0.0, 5.0))])
    assert out == [(10.0, 42.0)]


def test_is_bounded_by_the_r1_crossfade_allowance_of_the_next_entry():
    # breath is at 43.0, but a Song-2 entry starts at 41.0 -> the beat vocal may ring only
    # LEAD_XFADE_SECS (1.2s) past it, so it is clamped to 42.2, not 43.0 (stays a legal crossfade)
    out = _finish_beat_vocal_phrases([(10.0, 40.0)], _a1([43.0]),
                                     [Placement(anchor=41.0, vocal_src=(0.0, 5.0))])
    assert out[0][1] == round(41.0 + fence.LEAD_XFADE_SECS, 3)


def test_never_extends_more_than_the_cap():
    out = _finish_beat_vocal_phrases([(10.0, 40.0)], _a1([80.0]),
                                     [Placement(anchor=200.0, vocal_src=(0.0, 5.0))])
    assert out[0][1] == 40.0 + _BEAT_FINISH_MAX_S


def test_noop_without_vocal_pauses():
    assert _finish_beat_vocal_phrases([(10.0, 40.0)], _a1([]), []) == [(10.0, 40.0)]


def test_leaves_a_region_alone_when_no_later_breath():
    # the last phrase already ends at the singer's final breath -> nothing to extend to
    assert _finish_beat_vocal_phrases([(10.0, 40.0)], _a1([5.0, 20.0]), []) == [(10.0, 40.0)]
