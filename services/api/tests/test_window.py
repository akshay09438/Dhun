from app.models import Section, TrackAnalysis
from app.planner.window import window_analysis


def _grid():
    # 0..120s: a downbeat every 2s (61 bars), energy per bar, a phrase every 8 bars.
    downs = [round(2.0 * i, 3) for i in range(61)]
    return TrackAnalysis(
        song_id="s", status="ready", bpm=120.0,
        beats=[round(1.0 * i, 3) for i in range(121)],
        downbeats=downs,
        phrase_starts=downs[::8],
        energy_curve=[0.2 + 0.01 * i for i in range(61)],
        sections=[Section(start=0.0, end=60.0, label="verse"),
                  Section(start=60.0, end=120.0, label="chorus")],
        vocal_regions=[(10.0, 20.0), (70.0, 95.0)],
    )


def test_window_analysis_crops_and_rebases_to_zero():
    a = window_analysis(_grid(), 40.0, 100.0)
    assert a.downbeats[0] == 0.0                      # rebased so window starts at 0
    assert max(a.downbeats) <= 60.0 + 1e-6            # nothing past the 60s span
    assert min(a.beats) >= 0.0
    assert a.beats[-1] <= 60.0 + 1e-6
    # energy_curve stays aligned with the kept downbeats (same count)
    assert len(a.energy_curve) == len(a.downbeats)
    # sections clipped to the window and rebased
    assert a.sections[0].start == 0.0 and a.sections[-1].end <= 60.0 + 1e-6
    # vocal region (70,95) -> (30,55); the (10,20) one is fully before the window and dropped
    assert (30.0, 55.0) in [(round(s, 1), round(e, 1)) for s, e in a.vocal_regions]
    assert all(e <= 60.0 + 1e-6 for _s, e in a.vocal_regions)
    assert a.bpm == 120.0                             # tempo untouched


def test_window_analysis_stays_aligned_when_energy_curve_is_shorter():
    """energy_curve can come back shorter than downbeats (Handbook 9.4 fallback data); downbeats
    and energy_curve must still be filtered by the SAME kept-index set, so they stay the same
    length after windowing (not just within the crop window separately)."""
    a = _grid().model_copy(update={"energy_curve": _grid().energy_curve[:45]})  # shorter than downbeats
    windowed = window_analysis(a, 40.0, 100.0)
    assert len(windowed.energy_curve) == len(windowed.downbeats)


from app.planner.window import choose_window


def test_choose_window_targets_90s_ending_after_the_main_drop():
    a = _grid()                       # energy rises with time -> the latest drop is the biggest
    drops = [16.0, 48.0, 96.0]        # onsets; 96.0 sits on the highest-energy bar
    win = choose_window(a, drops)
    assert win is not None
    start, end = win
    assert end > 96.0                 # window ends AFTER the main drop (a resolve tail)
    assert 60.0 <= end - start <= 120.0   # ~90s, within the flexible band
    assert start >= 0.0
    assert 96.0 - start >= 16.0       # real run-up before the drop (build-up room)
    assert start in a.phrase_starts   # snapped to a clean phrase boundary


def test_choose_window_none_without_a_drop():
    assert choose_window(_grid(), []) is None


def test_choose_window_none_when_drop_has_no_runup():
    a = _grid()
    assert choose_window(a, [4.0]) is None   # drop at 4s -> < min run-up -> fall back to full track


def _grid_with_breakdown():
    # 0..240s, downbeat every 2s (121 bars), phrase every 8 bars (every 16s). Mostly mid-energy,
    # with a real BREAKDOWN (low density) at the phrase starting 112s and the main drop from 196s.
    downs = [round(2.0 * i, 3) for i in range(121)]
    energy = [0.5] * 121
    for i, d in enumerate(downs):
        if 112.0 <= d < 128.0:
            energy[i] = 0.1        # the breakdown -> the best cue point to start on
        if d >= 196.0:
            energy[i] = 0.95       # the main drop region (highest energy)
    return TrackAnalysis(
        song_id="s", status="ready", bpm=120.0,
        beats=[round(1.0 * i, 3) for i in range(241)],
        downbeats=downs, phrase_starts=downs[::8], energy_curve=energy,
        sections=[Section(start=0.0, end=240.0, label="verse")], vocal_regions=[],
    )


def test_choose_window_starts_on_the_low_density_cue_point():
    a = _grid_with_breakdown()
    win = choose_window(a, [200.0])          # main drop ~200s
    assert win is not None
    start, end = win
    assert start == 112.0                    # starts on the breakdown cue, not a louder phrase
    assert 60.0 <= end - start <= 120.0


from app.planner.fence import energy_drops
from app.planner.window import _TAIL_SECS, _drop_intensity


def _grid_two_drops():
    # 0..318s: a DRAMATIC drop at ~240s (near-silent breakdown, then a big hit) and a flatter,
    # sustained-loud stretch at ~120s. The dramatic drop must rank HARDEST despite the quiet run-up.
    downs = [round(2.0 * i, 3) for i in range(160)]
    energy = [0.4] * 160
    for i, d in enumerate(downs):
        if 120.0 <= d < 160.0:
            energy[i] = 0.72       # a flatter, sustained-loud section
        if 236.0 <= d < 240.0:
            energy[i] = 0.05       # a near-silent breakdown right before the big drop
        if 240.0 <= d < 268.0:
            energy[i] = 0.95       # the hard hit
    return TrackAnalysis(
        song_id="b", status="ready", bpm=120.0, bpm_confidence=0.9,
        beats=[round(1.0 * i, 3) for i in range(320)], downbeats=downs,
        phrase_starts=downs[::8], energy_curve=energy,
        sections=[Section(start=0.0, end=downs[-1], label="verse")], vocal_regions=[],
    )


def test_choose_window_ranks_drops_by_the_hit_not_the_phrase_average():
    """A dramatic drop (near-silent breakdown, then a loud hit) must OUTRANK a flatter sustained-loud
    section. A phrase average would bury it under its own quiet run-up (founder ear-test: Father
    Ocean's 3:56 main drop scored low that way). take=1's window lands on the hard hit."""
    a = _grid_two_drops()
    drops = energy_drops(a.energy_curve, a.downbeats)
    ranked = sorted(drops, key=lambda d: _drop_intensity(a, d), reverse=True)
    assert 238.0 <= ranked[0] <= 242.0                 # the hard hit, not the flat 120-160 stretch
    win = choose_window(a, drops, take=1)
    assert win is not None and abs((win[1] - _TAIL_SECS) - 240.0) <= 24.0  # window built on the hit


def test_choose_window_varies_the_drop_by_take():
    """Different takes land the window on different strong drops — variation, never the same mix."""
    a = _grid_two_drops()
    drops = energy_drops(a.energy_curve, a.downbeats)
    w1 = choose_window(a, drops, take=1)
    w2 = choose_window(a, drops, take=2)
    assert w1 and w2 and w1 != w2                       # the window moved to a different strong drop


from app.planner import fence
from app.planner.window import windowed_options


def test_windowed_options_regrids_onto_the_window():
    a1 = _grid()
    a2 = TrackAnalysis(song_id="v", status="ready", bpm=120.0,
                       beats=[round(0.5 * i, 3) for i in range(240)],
                       downbeats=[round(2.0 * i, 3) for i in range(60)],
                       vocal_regions=[(4.0, 30.0)])
    opts = fence.arrangement_options(a1, a2)
    assert opts["mixable"]
    w = windowed_options(opts, 40.0, 100.0)
    assert w["track_end"] <= 60.0 + 1e-6                 # canvas is the 60s window, not 120s
    assert all(0.0 <= x <= 60.0 + 1e-6 for x in w["anchors_ranked"])
    assert all(0.0 <= d <= 60.0 + 1e-6 for d in w["drops"])
    assert w["vocal_stretch"] == opts["vocal_stretch"]   # Song-2 fields untouched
    assert w["a1_grid"].downbeats[0] == 0.0              # rebased grid


def _late_drop_grid(track_secs: float = 240.0) -> TrackAnalysis:
    # low energy early, a clear low->high rise near the end (a real, late main drop)
    downs = [round(2.0 * i, 3) for i in range(int(track_secs // 2) + 1)]
    energy = [0.2] * len(downs)
    for i, d in enumerate(downs):
        if d >= 196.0:
            energy[i] = 0.9
    return TrackAnalysis(song_id="beat", status="ready", bpm=120.0,
                         beats=[round(1.0 * i, 3) for i in range(int(track_secs) + 1)],
                         downbeats=downs, phrase_starts=downs[::8], energy_curve=energy,
                         sections=[Section(start=0.0, end=track_secs, label="verse")],
                         vocal_regions=[])


def _compatible_vocal_song() -> TrackAnalysis:
    return TrackAnalysis(song_id="voc", status="ready", bpm=120.0,
                         beats=[round(0.5 * i, 3) for i in range(480)],
                         downbeats=[round(2.0 * i, 3) for i in range(120)],
                         vocal_regions=[(20.0, 60.0), (120.0, 150.0)])


def test_main_drop_survives_windowing():
    """The drop choose_window anchors on must still be present in windowed_options's recomputed
    drops -- otherwise the hook it was chosen for no longer lands on a drop after the crop."""
    a1 = _late_drop_grid()
    a2 = _compatible_vocal_song()
    opts = fence.arrangement_options(a1, a2)
    assert opts["mixable"]
    win = choose_window(opts["a1_grid"], opts["drops"])
    assert win is not None
    w = windowed_options(opts, *win)
    assert w["drops"]                                             # the payoff drop survived the crop
    assert any(d >= w["track_end"] * 0.5 for d in w["drops"])      # and sits in the LATE portion


def test_choose_window_handles_drop_near_end():
    """A drop within a few seconds of the track's end must never crash or return an
    inverted/empty window -- either a valid (possibly clamped) window, or a clean None."""
    a = _grid()                                   # 120s track
    drop = a.beats[-1] - 4.0                      # a drop just before the very end
    win = choose_window(a, [drop])
    if win is not None:
        start, end = win
        assert start < end
        assert end <= a.beats[-1] + 1e-6
        assert 60.0 <= end - start <= 120.0 + 1e-6
        assert drop - start >= 16.0 - 1e-6         # real run-up preserved, even this close to the end
