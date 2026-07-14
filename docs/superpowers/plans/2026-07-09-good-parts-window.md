# Good-parts Window Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build each mix on the beat song's best ~90-second window (the run-up into its main drop) instead of the whole track, so mixes are tight, dense, and free of long empty stretches.

**Architecture:** Carve a ~90s window anchored on Song 1's main (highest-energy) drop, crop-and-rebase Song 1's analysis grid to that window so it starts at 0, then run the **existing** arrangement engine unchanged on that windowed grid. The render crops Song 1's decoded stems to the same window. If no confident main drop is found, fall back to today's full-track path — never worse than now.

**Tech Stack:** Python 3.11, Pydantic v2, FastAPI, numpy/scipy, FFmpeg, pytest. Backend lives in `services/api`; the render worker in `workers/`.

## Global Constraints

- **Never let the LLM touch audio.** All new logic is deterministic arithmetic over `TrackAnalysis`. (CLAUDE.md stack gotcha.)
- **The confidence/fallback ladder is load-bearing.** Windowing only engages on a confident grid with a real detected drop; otherwise the full-track path renders exactly as today. (DJ Handbook Part 9.)
- **Never weaken the hard-rule validator** (single vocal, single bassline, no clipping). It re-checks the real render. (`services/api/app/planner/validate.py`.)
- **A no-window plan must render byte-for-behaviour identical to today** (`plan.window is None`). This is the regression invariant.
- **Tests run from `services/api`** via `.venv/Scripts/python -m pytest -q`. Typecheck from repo root: `npm run typecheck`.
- **All times in a windowed plan are window-relative (start at 0).** `plan.window = (win_start, win_end)` (in Song 1's retimed-grid seconds) is the ONLY absolute reference, used solely by the render to crop.
- Engine version comment bumps `m5o.0 → m5p.0` where an engine version string is emitted (search for `m5o`).
- Dangerous surfaces (`workers/render.py`, `services/api/app/planner/validate.py`) require the heavy safety path: independent test-author + adversarial-safety-reviewer quorum + founder confirm-and-apply BEFORE edits are written.

---

### Task 1: `MixPlan.window` field (additive model change)

**Files:**

- Modify: `services/api/app/models.py` (the `MixPlan` class, after `source`)
- Test: `services/api/tests/test_models.py`

**Interfaces:**

- Produces: `MixPlan.window: tuple[float, float] | None = None` — the Song-1 retimed-grid span `[win_start, win_end]` the bed is cropped to; `None` = full track (back-compat).

- [ ] **Step 1: Write the failing test**

```python
# services/api/tests/test_models.py
from app.models import MixPlan

def test_mixplan_window_defaults_none_and_roundtrips():
    base = dict(mix_id="m", song1_id="a", song2_id="b", master_bpm=122.0,
                vocal_stretch=1.0, vocal_src=(0.0, 8.0), anchor=4.0)
    assert MixPlan(**base).window is None                      # additive default
    p = MixPlan(**base, window=(30.0, 120.0))
    assert p.window == (30.0, 120.0)
    assert MixPlan.model_validate(p.model_dump()).window == (30.0, 120.0)  # JSON round-trip
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_models.py::test_mixplan_window_defaults_none_and_roundtrips -v`
Expected: FAIL — `MixPlan` has no field `window` (Pydantic `unexpected keyword argument`).

- [ ] **Step 3: Add the field**

In `services/api/app/models.py`, in `class MixPlan`, immediately after the `source: str = "rules"` line:

```python
    window: tuple[float, float] | None = None  # good-parts: Song-1 retimed-grid span the bed is cropped to; None = full track
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/models.py services/api/tests/test_models.py
git commit -m "feat(models): add optional MixPlan.window for good-parts render crop"
```

---

### Task 2: `window_analysis` — crop + rebase a grid to the window

**Files:**

- Create: `services/api/app/planner/window.py`
- Test: `services/api/tests/test_window.py` (create)

**Interfaces:**

- Produces: `window_analysis(a1: TrackAnalysis, win_start: float, win_end: float) -> TrackAnalysis` — a copy of `a1` whose `beats/downbeats/phrase_starts/energy_curve/sections/vocal_regions` are restricted to `[win_start, win_end]` and shifted so the window starts at 0.0; `bpm` and confidences unchanged.

- [ ] **Step 1: Write the failing test**

```python
# services/api/tests/test_window.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_window.py::test_window_analysis_crops_and_rebases_to_zero -v`
Expected: FAIL — `ModuleNotFoundError: app.planner.window`.

- [ ] **Step 3: Create `window.py` with `window_analysis`**

```python
# services/api/app/planner/window.py
"""Good-parts window: pick the beat song's best ~90s stretch (the run-up into its main
drop) and crop the analysis grid to it, so the existing arrangement engine runs on a tight
window instead of the whole track. Pure arithmetic over TrackAnalysis — no AI, no audio.
Mirrors fence.retimed_analysis: everything here is a testable copy-and-rescale of the grid.
"""
from __future__ import annotations

from app.models import TrackAnalysis

_BARS_PER_PHRASE = 8


def window_analysis(a1: TrackAnalysis, win_start: float, win_end: float) -> TrackAnalysis:
    """Copy `a1` with its grid restricted to [win_start, win_end] and shifted to start at 0.

    Downbeats and the per-bar energy_curve are filtered by the SAME in-window index set so they
    stay aligned (the energy_curve is one value per downbeat-bar). Sections and vocal regions are
    clipped to the window then rebased. bpm/keys/confidences are unchanged.
    """
    lo, hi = win_start - 1e-6, win_end + 1e-6

    def shift(times: list[float]) -> list[float]:
        return [round(t - win_start, 4) for t in times if lo <= t <= hi]

    kept = [i for i, d in enumerate(a1.downbeats) if lo <= d <= hi]
    energy = [a1.energy_curve[i] for i in kept if i < len(a1.energy_curve)]
    sections = [
        s.model_copy(update={"start": round(max(s.start, win_start) - win_start, 4),
                             "end": round(min(s.end, win_end) - win_start, 4)})
        for s in a1.sections if s.end > win_start and s.start < win_end
    ]
    vocal_regions = [
        (round(max(s, win_start) - win_start, 4), round(min(e, win_end) - win_start, 4))
        for s, e in a1.vocal_regions if e > win_start and s < win_end
    ]
    return a1.model_copy(update={
        "beats": shift(a1.beats),
        "downbeats": [round(a1.downbeats[i] - win_start, 4) for i in kept],
        "phrase_starts": shift(a1.phrase_starts),
        "energy_curve": energy,
        "sections": sections,
        "vocal_regions": vocal_regions,
    })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_window.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/planner/window.py services/api/tests/test_window.py
git commit -m "feat(planner): window_analysis -- crop + rebase a grid to the good-parts window"
```

---

### Task 3: `choose_window` — pick the ~90s window on the main drop

**Files:**

- Modify: `services/api/app/planner/window.py`
- Test: `services/api/tests/test_window.py`

**Interfaces:**

- Consumes: `_grid()` helper from Task 2's test; `TrackAnalysis`.
- Produces: `choose_window(a1: TrackAnalysis, drops: list[float]) -> tuple[float, float] | None` — the `(win_start, win_end)` (in `a1`'s own seconds) whose end is a short tail after the highest-energy drop and whose start is the lowest-density phrase-boundary CUE POINT in range (60-120s span, real run-up preserved); `None` when there is no drop, no legal cue with run-up, or the track is too short to window.

- [ ] **Step 1: Write the failing test**

```python
# add to services/api/tests/test_window.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_window.py -k choose_window -v`
Expected: FAIL — `choose_window` not defined.

- [ ] **Step 3: Add `choose_window` (and helpers) to `window.py`**

```python
# append to services/api/app/planner/window.py

_TARGET_SECS = 90.0      # the window we aim for
_MIN_SECS = 60.0         # ...flexible down to here
_MAX_SECS = 120.0        # ...and up to here
_TAIL_SECS = 12.0        # how long the window rings on AFTER the main drop (the resolve)
_MIN_RUNUP_SECS = 16.0   # need at least this much build-up before the drop, else no window


def _phrase_energy_at(a1: TrackAnalysis, t: float) -> float:
    """Average energy of the phrase (8 bars) nearest time t; 0 without an energy grid."""
    if not (a1.downbeats and a1.energy_curve):
        return 0.0
    idx = min(range(len(a1.downbeats)), key=lambda i: abs(a1.downbeats[i] - t))
    start = (idx // _BARS_PER_PHRASE) * _BARS_PER_PHRASE
    window = a1.energy_curve[start:start + _BARS_PER_PHRASE]
    return sum(window) / len(window) if window else 0.0


def _snap(anchors: list[float], t: float) -> float:
    """Nearest phrase/downbeat anchor to t (t itself if there are no anchors)."""
    return min(anchors, key=lambda a: abs(a - t)) if anchors else t


def choose_window(a1: TrackAnalysis, drops: list[float]) -> tuple[float, float] | None:
    """The ~90s good-part window anchored on the MAIN drop (the highest-energy drop = the payoff).

    Ends a short tail AFTER the main drop (snapped to a phrase, clamped to the track). Starts on
    the best CUE POINT: the lowest-density (lowest-energy) phrase boundary that keeps the span in
    the 60-120s band and leaves real run-up before the drop — so the mix eases in where a DJ would
    (a breakdown/quiet spot), not mid-chorus. Returns None when there is no drop, no legal cue with
    run-up, or the track is too short — in every None case the caller keeps today's full-track mix.
    """
    if not drops or not a1.beats:
        return None
    track_end = a1.beats[-1]
    main = max(drops, key=lambda d: _phrase_energy_at(a1, d))  # the biggest drop is the payoff
    phrases = a1.phrase_starts or a1.downbeats or a1.beats

    win_end = min(track_end, _snap(phrases, main + _TAIL_SECS))
    if win_end <= main:                                   # drop at the very end -> tiny tail, no snap
        win_end = min(track_end, main + _TAIL_SECS)

    # Start on the best CUE POINT: among the phrase boundaries that keep the span in the 60-120s
    # band AND leave real run-up before the drop, pick the LOWEST-density (lowest-energy) one — a
    # breakdown/quiet spot, where a DJ starts bringing a track in, never mid-chorus. Ties break
    # toward a ~90s window. (Founder craft note 2026-07-09: cue/switch points sit on phrase
    # boundaries at points of lower musical density, e.g. right as a breakdown starts.)
    earliest = max(0.0, win_end - _MAX_SECS)
    latest = min(win_end - _MIN_SECS, main - _MIN_RUNUP_SECS)
    if latest < earliest:                                 # no legal start with run-up -> fall back
        return None
    cues = [p for p in phrases if earliest - 1e-6 <= p <= latest + 1e-6]
    if not cues:                                          # no phrase boundary in band -> fall back
        return None
    win_start = min(cues, key=lambda p: (round(_phrase_energy_at(a1, p), 3),
                                         abs((win_end - p) - _TARGET_SECS)))
    return (round(win_start, 3), round(win_end, 3))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_window.py -v`
Expected: PASS (all Task 2 + Task 3 tests).

- [ ] **Step 5: Commit**

```bash
git add services/api/app/planner/window.py services/api/tests/test_window.py
git commit -m "feat(planner): choose_window -- ~90s good-part window on the main drop"
```

---

### Task 4: `windowed_options` — re-derive the arrangement menu on the windowed grid

**Files:**

- Modify: `services/api/app/planner/window.py`
- Test: `services/api/tests/test_window.py`

**Interfaces:**

- Consumes: `fence.candidate_drops`, `fence.energy_drops`; an `opts` dict from `fence.arrangement_options` (keys `a1_grid`, `vocal_slices`, `vocal_stretch`, `drops`, ...).
- Produces: `windowed_options(opts: dict, win_start: float, win_end: float) -> dict` — a copy of `opts` whose grid-derived fields (`a1_grid`, `anchors_ranked`, `drops`, `track_end`, `sections`) are recomputed on the windowed, 0-based grid; Song-2 fields (`vocal_slices`, `vocal_peaks`, `vocal_stretch`, tempo) pass through unchanged.

- [ ] **Step 1: Write the failing test**

```python
# add to services/api/tests/test_window.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_window.py::test_windowed_options_regrids_onto_the_window -v`
Expected: FAIL — `windowed_options` not defined.

- [ ] **Step 3: Add `windowed_options` to `window.py`**

```python
# append to services/api/app/planner/window.py — import fence lazily to avoid a cycle
def windowed_options(opts: dict, win_start: float, win_end: float) -> dict:
    """Re-derive the arrangement menu on the windowed grid, keeping every Song-2/tempo field.

    The whole downstream engine (plan.build_mix_plan) reads these opts + a1_grid, so recomputing
    just the grid-derived fields on the 0-based windowed grid makes the existing arrangement run
    on the window with no other change.
    """
    from app.planner import fence  # local import: window.py <- plan.py <- fence.py cycle guard

    a1w = window_analysis(opts["a1_grid"], win_start, win_end)
    need = min(e - s for s, e in opts["vocal_slices"]) * opts["vocal_stretch"]
    anchors = fence.candidate_drops(a1w, need)
    track_end = a1w.beats[-1] if a1w.beats else (max(anchors) + need if anchors else need)
    return {
        **opts,
        "a1_grid": a1w,
        "anchors_ranked": anchors,
        "drops": fence.energy_drops(a1w.energy_curve, a1w.downbeats),
        "track_end": track_end,
        "sections": [(s.start, s.label) for s in a1w.sections],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_window.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/planner/window.py services/api/tests/test_window.py
git commit -m "feat(planner): windowed_options -- re-grid the arrangement menu onto the window"
```

---

### Task 5: Wire the window into `build_mix_plan` (safe surface)

**Files:**

- Modify: `services/api/app/planner/plan.py` (imports; `build_mix_plan`)
- Test: `services/api/tests/test_plan.py`

**Interfaces:**

- Consumes: `window.choose_window`, `window.windowed_options`; existing `_confident`, `fence.arrangement_options`.
- Produces: a `MixPlan` whose `window` is set (window-relative placements) when a confident main-drop window exists; otherwise today's full-track plan with `window is None`.

- [ ] **Step 1: Write the failing tests**

```python
# add to services/api/tests/test_plan.py
from app.models import Section, TrackAnalysis
from app.planner import plan as planmod


def _beat_song(track_secs=240.0):
    downs = [round(2.0 * i, 3) for i in range(int(track_secs // 2) + 1)]
    # energy low early, a clear high onset near ~200s (the main drop), so a window exists
    energy = [0.2] * len(downs)
    for i, d in enumerate(downs):
        if d >= 196.0:
            energy[i] = 0.9
    return TrackAnalysis(song_id="beat", status="ready", bpm=120.0, bpm_confidence=0.9,
                         beats=[round(1.0 * i, 3) for i in range(int(track_secs) + 1)],
                         downbeats=downs, phrase_starts=downs[::8], energy_curve=energy,
                         sections=[Section(start=0.0, end=track_secs, label="verse")],
                         vocal_regions=[])


def _vocal_song():
    return TrackAnalysis(song_id="voc", status="ready", bpm=120.0, bpm_confidence=0.9,
                         beats=[round(0.5 * i, 3) for i in range(480)],
                         downbeats=[round(2.0 * i, 3) for i in range(120)],
                         vocal_regions=[(20.0, 60.0), (120.0, 150.0)])


def test_build_mix_plan_windows_a_long_song(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)     # force the deterministic path
    p = planmod.build_mix_plan("m1", _beat_song(240.0), _vocal_song())
    assert p.window is not None
    ws, we = p.window
    assert 60.0 <= we - ws <= 120.0                            # ~90s good part, not 4 minutes
    assert all(pl.anchor <= (we - ws) + 1e-6 for pl in p.placements)  # window-relative anchors


def test_build_mix_plan_falls_back_full_track_without_a_drop(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    flat = _beat_song(240.0)
    flat = flat.model_copy(update={"energy_curve": [0.2] * len(flat.downbeats)})  # no drop
    p = planmod.build_mix_plan("m2", flat, _vocal_song())
    assert p.window is None                                    # today's full-track behaviour
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_plan.py -k window -v`
Expected: FAIL — `MixPlan.window` is always None (wiring absent); the first test fails on `p.window is not None`.

- [ ] **Step 3: Wire `build_mix_plan`**

In `services/api/app/planner/plan.py`:

1. Extend the import:

```python
from app.planner import fence, hooks, llm, window
```

2. Immediately after the `a1g = opts.get("a1_grid", a1)` line (just before `placements = _ai_arrange(...)`), insert:

```python
    # Good-parts window: build the mix on the beat's best ~90s (the run-up into its main drop)
    # instead of the whole track. Only on a confident grid with a real drop; else keep the full
    # track (today's behaviour). windowed_options re-grids the menu onto the 0-based window, so the
    # entire arrangement below runs unchanged on the window.
    window_span = window.choose_window(a1g, opts.get("drops", [])) if _confident(a1g) else None
    if window_span:
        opts = window.windowed_options(opts, *window_span)
        a1g = opts["a1_grid"]
```

3. In the `return MixPlan(` call, add `window=window_span,` (e.g. next to `take=take,`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_plan.py -v`
Expected: PASS (new window tests + existing plan tests unchanged).

- [ ] **Step 5: Full backend regression (proves the fallback invariant)**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all existing backend tests still PASS (no window on the existing test fixtures → today's plans reproduced).

- [ ] **Step 6: Commit**

```bash
git add services/api/app/planner/plan.py services/api/tests/test_plan.py
git commit -m "feat(planner): build_mix_plan builds on the good-parts window (fallback-safe)"
```

---

### Task 6: Render crops the bed to the window — DANGEROUS (`workers/render.py`)

> **Heavy safety path REQUIRED before this task's edits are written:** spawn the `test-author` subagent to write the render tests below independently, and an `adversarial-safety-reviewer` quorum (correctness / clip-safety / blast-radius) that must ALL return `safe`; then run the confirm-and-apply flow (`/zuko:build` §3c) for the founder's explicit yes and `node .zuko/approve.js` on `workers/render.py`. Do NOT hand-edit around the guard.

**Files:**

- Modify: `workers/render.py` (`render_mix`)
- Test: `services/api/tests/test_render.py`

**Interfaces:**

- Consumes: `plan.window` (from Task 1).
- Produces: when `plan.window` is set, a WAV built only from `[win_start, win_end]` of Song 1's (retimed) stems; placements/stem_moves (already 0-based) lay over the cropped bed; Song 1's own vocal (`s1_vocal_regions`) is seeked at `s + win_start`. When `plan.window is None`, byte-for-behaviour identical to today.

- [ ] **Step 1: Write the failing test**

The independent test-author has ALREADY written the core render tests into `services/api/tests/test_render.py` (in the working tree, uncommitted), using a `_long_stems(tmp_path, secs=120.0)` fixture that mirrors the file's existing `_stems()` helper:

- `test_render_window_crops_output_to_window_length` — 120s stems, `window=(30.0,120.0)` → duration 88–96s and `< 110s` (crops).
- `test_render_no_window_is_unchanged_full_length` — `window=None` → duration `>= 118s` (the safety invariant; passes today, must keep passing).
- `test_render_window_never_clips` — windowed render peak `<= _CEILING`.
- `test_render_window_places_vocal_within_the_cropped_output` — a window-relative placement at 85.0s inside a `(20.0,110.0)` window renders `<= 96s` (not stranded past the window).

**ADD these two REQUIRED safety tests (from the adversarial review) before the render edit lands:**

- `test_render_malformed_window_fails_loud` — a plan with `window=(120.0, 30.0)` (reversed → empty crop) must raise `render.RenderError`, NOT silently produce a beat-less WAV. This is the exact silent-bad-mix gap the guard closes. `with pytest.raises(render.RenderError): render.render_mix(plan, stems, vocal, out)`.
- `test_render_window_with_bed_stretch` — a windowed plan with `bed_stretch != 1.0` (e.g. `1.05`) still renders to ≈ the window length and stays clip-safe (proves the crop indexes the post-stretch decoded bed correctly on the movable-master path — the reviewer noted this combo was previously uncovered).

> Note (test-author): pure-tone fixtures prove the crop LENGTH, not that it starts at exactly `win_start`. Crop-start correctness is verified live in Task 9's founder ear-test on real pairs (a mis-started window would obviously not build into the hook).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_render.py -k window -v`
Expected: FAIL — the windowed render is still full-length (crop not implemented), so `test_render_window_crops_bed_to_the_window` fails the duration assertion.

- [ ] **Step 3: Implement the crop (after confirm-and-apply approval)**

In `workers/render.py`, inside `render_mix`, after:

```python
        decoded = {name: _decode(song1_stems[name]) for name in _BED_STEMS}
```

insert:

```python
        # Good-parts window: crop the (already retimed) bed to [win_start, win_end]. The plan's
        # anchors/stem_moves are window-relative (start at 0), so cropping the decoded stems here
        # aligns everything with sample 0 = win_start. window is on the SAME retimed grid the bed
        # is on (bed_stretch already applied above), so win*SR indexes the decoded arrays directly.
        # FAIL LOUD on a malformed window (w1<=w0 -> an EMPTY bed -> a beat-less mix the render
        # would otherwise ship silently, since validate_render's silence check still sees the vocal).
        # Mirrors this file's own convention (master_bpm<=0, bed_stretch range) — a bad plan is a
        # loud error, never a quiet bad mix. w1 is clamped to the bed length so a legit window that
        # ends a hair past the last sample (float/atempo rounding) is fine, not an error.
        window = getattr(plan, "window", None)
        if window:
            dec_len = max(len(a) for a in decoded.values())
            w0, w1 = int(window[0] * SR), min(int(window[1] * SR), dec_len)
            if not (0 <= w0 < w1):
                raise RenderError(f"plan.window {window} is malformed (empty or reversed crop)")
            decoded = {name: arr[w0:w1] for name, arr in decoded.items()}
```

Then, in the `s1_vocal_regions` loop, change the seek to add the window offset. Replace:

```python
            take = _edge_fade(_vocal_take(s1_vocals, s, max(e - s, 0.0), 1.0))
```

with:

```python
            off = window[0] if window else 0.0   # s1 regions are window-relative; the file is not cropped
            take = _edge_fade(_vocal_take(s1_vocals, s + off, max(e - s, 0.0), 1.0))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_render.py -v`
Expected: PASS (windowed + full-length + all existing render tests).

- [ ] **Step 5: Commit**

```bash
git add workers/render.py services/api/tests/test_render.py
git commit -m "feat(render): crop the bed to plan.window (good-parts); full-track path unchanged"
```

---

### Task 7: Verify the validator on a windowed plan — DANGEROUS (`validate.py`, verify-only)

> Read `services/api/app/planner/validate.py` first. The plan is internally consistent and window-relative, so the invariants (single vocal, one bassline, no clipping, on-beat) should hold with NO code change. Only if a check assumes the bed length equals the full song does it need a (heavy-path, confirm-and-apply) fix. **Default expectation: a test is added, no production edit.**

**Files:**

- Test: `services/api/tests/test_validate.py`
- Modify (only if the test proves it necessary): `services/api/app/planner/validate.py`

**Interfaces:**

- Consumes: `validate_plan` / `validate_render` (existing signatures — read the file for exact names/args).

- [ ] **Step 1: Write the test — a windowed plan validates clean**

```python
# add to services/api/tests/test_validate.py — mirror this file's existing validate_plan usage.
# Build a small windowed MixPlan (window set, window-relative placements) and assert validate_plan
# returns no violations, exactly as an equivalent non-windowed plan does. (Copy the construction
# style already used by the other tests in this file.)
```

- [ ] **Step 2: Run it**

Run: `.venv/Scripts/python -m pytest tests/test_validate.py -v`
Expected: PASS with no production change. If it FAILS, a validator check wrongly assumes full-track length — stop, route the fix through the confirm-and-apply flow (§3c) on `validate.py`, then re-run.

- [ ] **Step 3: Commit**

```bash
git add services/api/tests/test_validate.py
git commit -m "test(validate): a windowed plan validates clean (single vocal, no clip)"
```

---

### Task 8: Update the living docs (safe surface)

**Files:**

- Modify: `docs/functional-spec.md`, `docs/technical-spec.md`, `docs/implementation-plan.md`, `docs/mix-recipe.md`

- [ ] **Step 1: functional-spec.md** — in the "What the app does TODAY" section, add that mixes are now the ~90s "good part" that builds up to the main drop (hook-on-drop), and mark the old "full-length mix is the hero output" line (Open assumption #3) as **superseded 2026-07-09**: tighter, best-parts mixes are the target.

- [ ] **Step 2: technical-spec.md** — add the good-parts window: the new `app/planner/window.py` (`choose_window`, `window_analysis`, `windowed_options`), the "windowed grid becomes the canvas" flow, `MixPlan.window`, and the render bed-crop.

- [ ] **Step 3: implementation-plan.md** — mark the good-parts window feature done; add a drift-log entry dated 2026-07-09 describing the windowed-canvas approach and the fallback-to-full-track invariant.

- [ ] **Step 4: mix-recipe.md** — add the good-window rule: anchor on the main drop, start on a low-density **cue point** (a phrase boundary at a breakdown/quiet spot, never mid-chorus), build up to the drop, aim ~90s (60-120s), fall back to the full track when no confident drop.

- [ ] **Step 5: Commit**

```bash
git add docs/functional-spec.md docs/technical-spec.md docs/implementation-plan.md docs/mix-recipe.md
git commit -m "docs: good-parts window -- specs + recipe + drift log"
```

---

### Task 9: Full verification + founder ear-test render

**Files:** none (verification only)

- [ ] **Step 1: Full suite + typecheck**

Run (from `services/api`): `.venv/Scripts/python -m pytest -q` — expect **≥ 302 + new tests** green.
Run (from repo root): `npm run typecheck` — expect clean; `npm test` — expect web green (39, unchanged).

- [ ] **Step 2: Founder ear-test render (no cloud cost — cache present)**

Render a real windowed pair via the deterministic path (pop `ANTHROPIC_API_KEY`, `build_mix_plan` → `render_mix`) on Father Ocean × {Dil Ye Bekarar, Maula Mere} and a long pair (Anchor Point / Innerbloom). Save to `Desktop/DJAI SONGS` under a **fresh distinct filename** (avoid same-name OS/OneDrive cache). Confirm: ~90s length, builds up to the hook-on-drop, no dead air; `validate_plan`/`validate_render` CLEAN. This is the founder's keep/discard confirmation.

---

## Self-Review

**Spec coverage:** window selection (Task 3), crop+rebase grid (Task 2), re-grid the menu (Task 4), plan wiring + fallback (Task 5), render crop + s1-vocal offset (Task 6), validator verify (Task 7), model field (Task 1), docs (Task 8), verification incl. movable-master covered by full regression + ear-test (Task 9). Edge states from the spec: no-drop/low-confidence → Task 5 fallback test; drop-at-start (no run-up) → Task 3 test; short track → `choose_window` degenerate guard; movable master → decoded stems are post-`bed_stretch` on the same retimed grid the window uses (Task 6 comment) and are exercised by the existing movable-master render/plan tests under full regression.

**Placeholder scan:** Task 6/7 test bodies intentionally defer to the file's existing fixture style (the test-author writes them against the real fixtures) — flagged inline, not a hidden TODO. All new production code (`window.py`, the `plan.py` insert, the `render.py` insert) is given in full.

**Type consistency:** `choose_window(a1, drops) -> tuple|None`, `window_analysis(a1, win_start, win_end) -> TrackAnalysis`, `windowed_options(opts, win_start, win_end) -> dict`, `MixPlan.window: tuple|None` — names/signatures match across Tasks 1-6.
