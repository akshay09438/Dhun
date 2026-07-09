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
