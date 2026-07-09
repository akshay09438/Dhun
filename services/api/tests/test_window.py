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
