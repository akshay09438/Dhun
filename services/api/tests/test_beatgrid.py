"""Beat-grid health checks — the 'are the beat sensors reading cleanly?' guard (pure, no audio)."""
from app.planner import beatgrid


def _grid(bpm: float, bars: int, beats_per_bar: int = 4, start: float = 0.25) -> list[float]:
    bar = beats_per_bar * 60.0 / bpm
    return [round(start + i * bar, 4) for i in range(bars)]


def test_regular_grid_is_healthy():
    db = _grid(120, 40)                       # clean 4/4 at 120
    h = beatgrid.grid_health(120.0, db)
    assert h["ok"]
    assert h["regularity"] > 0.98
    assert h["bpm_agreement"] > 0.98


def test_irregular_grid_flags_unhealthy():
    db = _grid(120, 40)
    db[10] += 0.9                             # a dropped/added beat -> a big gap spike
    db[25] -= 0.7
    h = beatgrid.grid_health(120.0, db)
    assert not h["ok"]
    assert h["regularity"] < 0.9


def test_bpm_disagreeing_with_grid_flags_unhealthy():
    db = _grid(120, 40)                       # grid is actually 120
    h = beatgrid.grid_health(90.0, db)        # but BPM was mis-detected as 90 (a 33% error, no clean multiple)
    assert h["bpm_agreement"] < 0.8
    assert not h["ok"]


def test_half_bar_convention_still_agrees():
    # A grid marked every 2 beats (half-bar) at 120 should still AGREE with bpm=120 (tolerated multiple).
    db = _grid(120, 40, beats_per_bar=2)
    h = beatgrid.grid_health(120.0, db)
    assert h["bpm_agreement"] > 0.98


def test_too_few_downbeats_is_zero():
    assert beatgrid.grid_health(120.0, [0.25, 2.25])["health"] == 0.0
    assert beatgrid.grid_health(120.0, [])["health"] == 0.0
