"""Tests for the fence — the deterministic 'legal, safe options' layer.

Pure arithmetic over a TrackAnalysis, so no audio, no network: fast and exact.
"""

from app.models import KeyInfo, Placement, Section, TrackAnalysis
from app.planner import fence


def make_analysis(bpm=120.0, n_bars=32, key="8A", vocal_regions=None,
                  energy=None, sections=None):
    beat = 60.0 / bpm
    n_beats = n_bars * 4
    beats = [round(i * beat, 3) for i in range(n_beats)]
    downbeats = beats[::4]
    phrase_starts = downbeats[::8]
    energy_curve = energy if energy is not None else [0.5] * len(downbeats)
    return TrackAnalysis(
        song_id="x" * 64, status="ready", bpm=bpm, beats=beats,
        downbeats=downbeats, phrase_starts=phrase_starts,
        key=KeyInfo(camelot=key, tonic="A", mode="minor", confidence=0.7),
        sections=sections or [], energy_curve=energy_curve,
        vocal_regions=vocal_regions or [],
    )


def test_best_stretch_safe_band():
    ratio, safe = fence.best_stretch(120.0, 122.0)
    assert 0.97 < ratio < 1.0 and safe


def test_best_stretch_too_far_is_unsafe():
    ratio, safe = fence.best_stretch(120.0, 150.0)
    assert not safe and ratio < fence.SAFE_STRETCH_LO


def test_best_stretch_folds_half_time():
    # a source the analyzer read at half tempo (61) still matches 122-ish cleanly
    ratio, safe = fence.best_stretch(120.0, 61.0)
    assert safe and 0.95 < ratio < 1.0


def test_best_stretch_guards_zero():
    assert fence.best_stretch(120.0, 0.0) == (1.0, False)


def test_candidate_drops_ranks_by_energy():
    energy = [0.3] * 32
    for i in range(8, 16):  # the second phrase (bars 8..15) is the loudest
        energy[i] = 0.9
    a1 = make_analysis(bpm=120.0, n_bars=32, energy=energy)
    drops = fence.candidate_drops(a1, need_secs=4.0)
    assert drops[0] == 16.0  # phrase 2 starts at bar 8 -> 16.0s, highest energy


def test_candidate_drops_respects_runway():
    a1 = make_analysis(bpm=120.0, n_bars=32)  # track ends ~62s
    drops = fence.candidate_drops(a1, need_secs=40.0)
    assert 32.0 not in drops and 48.0 not in drops  # no room for a 40s vocal there
    assert all(t + 40.0 <= a1.beats[-1] + 1e-6 for t in drops)


def test_candidate_drops_falls_back_to_downbeats():
    a1 = make_analysis()
    a1.phrase_starts = []  # phrases untrusted -> anchor on any downbeat
    drops = fence.candidate_drops(a1, need_secs=4.0)
    assert drops and set(drops) <= set(a1.downbeats)


def test_best_vocal_slice_picks_longest_and_snaps():
    a2 = make_analysis(vocal_regions=[(3.1, 9.0), (20.0, 40.0)])
    start, end = fence.best_vocal_slice(a2)
    assert start == 20.0 and end == 40.0  # longest region, already on a downbeat


def test_best_vocal_slice_caps_length():
    a2 = make_analysis(vocal_regions=[(10.0, 100.0)])
    start, end = fence.best_vocal_slice(a2)
    assert end - start <= fence.MAX_VOCAL_SECS + 1e-6


def test_best_vocal_slice_falls_back_to_chorus():
    a2 = make_analysis(vocal_regions=[], sections=[Section(start=8.0, end=24.0, label="chorus")])
    start, end = fence.best_vocal_slice(a2)
    assert start == 8.0 and end == 24.0


def test_camelot_fit():
    assert fence.camelot_fit("8A", "8A")
    assert fence.camelot_fit("8A", "9A")   # +1
    assert fence.camelot_fit("8A", "10A")  # +2
    assert fence.camelot_fit("8A", "8B")   # relative major/minor
    assert fence.camelot_fit("1A", "12A")  # wraps the clock
    assert not fence.camelot_fit("8A", "11A")  # +3 is a clash
    assert not fence.camelot_fit("8A", "3B")


def test_legal_options_happy_path():
    a1 = make_analysis(bpm=120.0)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(16.0, 40.0)])
    opts = fence.legal_options(a1, a2)
    assert opts["mixable"]
    assert opts["master_bpm"] == 120.0
    assert 0.97 < opts["vocal_stretch"] < 1.05
    assert opts["drops"] and opts["vocal_src"][1] > opts["vocal_src"][0]


def test_legal_options_declines_far_tempo():
    a1 = make_analysis(bpm=120.0)
    a2 = make_analysis(bpm=150.0, vocal_regions=[(16.0, 40.0)])
    opts = fence.legal_options(a1, a2)
    assert not opts["mixable"] and "tempo" in opts["reason"].lower()


def test_legal_options_declines_no_beat():
    a1 = make_analysis()
    a1.bpm, a1.beats, a1.downbeats, a1.phrase_starts = 0.0, [], [], []
    a2 = make_analysis(vocal_regions=[(16.0, 40.0)])
    opts = fence.legal_options(a1, a2)
    assert not opts["mixable"] and "beat" in opts["reason"].lower()


def test_vocal_slices_ranked_and_capped():
    a2 = make_analysis(vocal_regions=[(8.0, 14.0), (20.0, 60.0), (70.0, 76.0)])
    slices = fence.vocal_slices(a2)
    assert slices[0][1] - slices[0][0] <= fence.MAX_VOCAL_SECS + 1e-6  # capped
    assert len(slices) >= 2 and slices[0][0] == 20.0  # longest first, snapped to a downbeat


def test_arrangement_options_happy():
    energy = [0.3] * 32
    for i in range(8, 16):
        energy[i] = 0.9
    a1 = make_analysis(bpm=120.0, n_bars=32, energy=energy)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(16.0, 40.0), (60.0, 80.0)])
    opts = fence.arrangement_options(a1, a2)
    assert opts["mixable"]
    assert opts["anchors_ranked"] and opts["anchors_ranked"][0] == 16.0
    assert len(opts["vocal_slices"]) >= 1


def test_arrangement_options_declines_far_tempo():
    a1 = make_analysis(bpm=120.0)
    a2 = make_analysis(bpm=150.0, vocal_regions=[(16.0, 40.0)])
    assert not fence.arrangement_options(a1, a2)["mixable"]


def test_contrast_windows_finds_gap_where_s1_sings():
    a1 = make_analysis(bpm=120.0, n_bars=64, vocal_regions=[(50.0, 80.0)])  # S1 sings 50-80
    placements = [Placement(anchor=16.0, vocal_src=(0.0, 12.0)),   # ends 28
                  Placement(anchor=90.0, vocal_src=(0.0, 12.0))]   # gap 28-90
    wins = fence.contrast_windows(a1, placements, stretch=1.0)
    assert wins and all(s >= 28.0 and e <= 90.0 for s, e in wins)  # inside the gap
    assert wins[0][0] >= 50.0 and wins[0][1] <= 80.0               # where S1 actually sings


def test_contrast_windows_empty_when_s1_silent_in_gaps():
    a1 = make_analysis(bpm=120.0, n_bars=64, vocal_regions=[(0.0, 10.0)])  # S1 sings only early
    placements = [Placement(anchor=16.0, vocal_src=(0.0, 12.0)),
                  Placement(anchor=90.0, vocal_src=(0.0, 12.0))]
    assert fence.contrast_windows(a1, placements, stretch=1.0) == []


def test_arc_anchors_spreads_across_thirds():
    # anchors evenly across a 240s track -> the arc must take one per third, so the
    # vocal reaches the whole song (a strong entry near the end), never clustered.
    anchors = [float(t) for t in range(0, 240, 16)]  # 0,16,...,224
    picks = fence.arc_anchors(anchors, track_end=240.0, count=3)
    assert len(picks) == 3
    assert picks[0] < 80.0             # first third
    assert 80.0 <= picks[1] < 160.0    # middle third
    assert picks[2] >= 160.0           # final third — the strong finish


def test_arc_anchors_rotates_with_take_for_variety():
    anchors = [0.0, 20.0, 100.0, 200.0]  # first band [0,80) has two options to rotate
    a = fence.arc_anchors(anchors, track_end=240.0, count=3, take=1)
    b = fence.arc_anchors(anchors, track_end=240.0, count=3, take=2)
    assert a != b  # Regenerate gets a genuinely different pick within a band


def test_arc_anchors_falls_back_when_too_few():
    # fewer anchors than placements -> just use what's there (short songs are limited)
    assert fence.arc_anchors([10.0, 20.0], track_end=240.0, count=3) == [10.0, 20.0]
