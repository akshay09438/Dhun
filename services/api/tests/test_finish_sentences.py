"""Phrase-safe slice ends: a vocal line's slice END is extended to the singer's next breath
(a2.vocal_pauses) so a sung line finishes its sentence instead of cutting mid-word — bounded so
it never runs into the next line. Tests the planner logic `plan._finish_sentences` directly."""
from app.models import Placement, TrackAnalysis
from app.planner.plan import (_finish_sentences, _SENTENCE_FINISH_MAX_S,
                              _SENTENCE_FINISH_MARGIN_S)


def _a2(pauses):
    return TrackAnalysis(song_id="b" * 64, status="ready", vocal_pauses=pauses)


def test_extends_the_slice_end_to_the_next_breath():
    # slice ends at src 40.0 (mid-phrase); the singer's next breath is at 42.0 -> finish the sentence
    p = Placement(anchor=100.0, vocal_src=(2.0, 40.0))
    out = _finish_sentences([p], _a2([10.0, 42.0, 60.0]), stretch=1.0)
    assert out[0].vocal_src == (2.0, 42.0)


def test_never_extends_more_than_the_cap():
    # the next breath is far away (30s); the extension is capped so a line can't balloon
    p = Placement(anchor=100.0, vocal_src=(2.0, 40.0))
    out = _finish_sentences([p], _a2([80.0]), stretch=1.0)
    assert out[0].vocal_src[1] == 40.0 + _SENTENCE_FINISH_MAX_S


def test_is_bounded_by_the_next_line_so_it_never_overlaps():
    # breath at 42.0, but the next line starts soon after -> extension is clamped short of it.
    # room_rendered = next.anchor - margin - anchor = 141 - 2 - 100 = 39 ; max end = 2 + 39 = 41 < 42
    p1 = Placement(anchor=100.0, vocal_src=(2.0, 40.0))
    p2 = Placement(anchor=141.0, vocal_src=(0.0, 5.0))
    out = _finish_sentences([p1, p2], _a2([42.0]), stretch=1.0)
    end = out[0].vocal_src[1]
    assert end == 41.0
    # and the extended vocal ends before the next line begins (one voice at a time)
    assert 100.0 + (end - 2.0) / 1.0 <= 141.0 - _SENTENCE_FINISH_MARGIN_S + 1e-6


def test_no_extension_when_there_is_no_room():
    # next line is right after this one -> no room to finish; the slice is left unchanged (not shrunk)
    p1 = Placement(anchor=100.0, vocal_src=(2.0, 40.0))
    p2 = Placement(anchor=110.0, vocal_src=(0.0, 5.0))
    out = _finish_sentences([p1, p2], _a2([42.0]), stretch=1.0)
    assert out[0].vocal_src == (2.0, 40.0)


def test_noop_without_vocal_pauses():
    # older cached analysis (no vocal_pauses) -> the prior fixed-length behaviour, unchanged
    p = Placement(anchor=100.0, vocal_src=(2.0, 40.0))
    out = _finish_sentences([p], _a2([]), stretch=1.0)
    assert out[0].vocal_src == (2.0, 40.0)


def test_respects_the_stretch_when_converting_room_to_source_time():
    # with stretch 0.5 the vocal plays LONGER (rendered = source/stretch), so less source fits the gap.
    # room_rendered = 130 - 2 - 100 = 28 rendered secs ; max source len = 28 * 0.5 = 14 -> max end = 2 + 14 = 16
    p1 = Placement(anchor=100.0, vocal_src=(2.0, 12.0))
    p2 = Placement(anchor=130.0, vocal_src=(0.0, 5.0))
    out = _finish_sentences([p1, p2], _a2([40.0]), stretch=0.5)
    assert out[0].vocal_src[1] == 16.0
