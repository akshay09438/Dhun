# Phrasing Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every change in a mix land on a musical phrase boundary — vocal entries and the drop on the 8-bar grid, the auto beat moves (cut / beat-up / breakdown) on the 4-bar grid — so nothing lands abruptly mid-phrase.

**Architecture:** One shared `snap_to_phrase(t, downbeats, bars)` helper in `fence.py` (the "phrasing ruler"), applied at each place a position is decided. Phrase boundaries are a subset of downbeats, so the referee (`validate.py`) already accepts them — this stays entirely on safe surfaces (`fence.py` / `plan.py`), no `render.py`/`validate.py` edits.

**Tech Stack:** Python 3.11, pytest. Pure arithmetic over `TrackAnalysis` (no audio, no network in the unit tests).

## Global Constraints

- Grid sizes: **8-bar** = `downbeats[::8]` (`fence._BARS_PER_PHRASE = 8`, exists); **4-bar** = `downbeats[::4]` (add `fence._BARS_PER_SUBPHRASE = 4`).
- Use the **retimed grid** on the movable-master path: callers pass `a1g.downbeats` (already threaded as `opts["a1_grid"]` / the `a1_downbeats` args).
- Graceful: missing/thin grid → snapping is a no-op; never crash, never decline a mix over phrasing.
- Do **not** touch `services/api/app/planner/validate.py` or `workers/render.py` (dangerous files). If a task seems to need them, stop.
- Run the backend suite from `services/api` with `.venv/Scripts/python -m pytest -q`. Never weaken a test to pass.
- Every task ends with a commit. Branch: `feat/house-bollywood-energy-sync` (do not merge to main).

---

### Task 1: The phrasing ruler — `snap_to_phrase`

**Files:**
- Modify: `services/api/app/planner/fence.py` (add constant + function near line 55, after `_BARS_PER_PHRASE`)
- Test: `services/api/tests/test_fence.py`

**Interfaces:**
- Produces: `fence.snap_to_phrase(t: float, downbeats: list[float], bars: int) -> float` and `fence._BARS_PER_SUBPHRASE = 4`.

- [ ] **Step 1: Write the failing tests** (append to `test_fence.py`; uses the existing `make_analysis`)

```python
def test_snap_to_phrase_snaps_to_nearest_8bar_line():
    a = make_analysis(bpm=120.0, n_bars=32)  # downbeats every 2.0s; 8-bar line every 16.0s
    db = a.downbeats
    assert fence.snap_to_phrase(15.0, db, 8) == db[8]   # 16.0s
    assert fence.snap_to_phrase(17.5, db, 8) == db[8]
    assert fence.snap_to_phrase(db[8], db, 8) == db[8]  # idempotent

def test_snap_to_phrase_4bar_grid():
    db = make_analysis(bpm=120.0, n_bars=32).downbeats
    assert fence.snap_to_phrase(7.0, db, 4) == db[4]    # 8.0s
    assert fence.snap_to_phrase(9.0, db, 4) == db[4]

def test_snap_to_phrase_empty_grid_returns_input():
    assert fence.snap_to_phrase(5.0, [], 8) == 5.0
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_fence.py -k snap_to_phrase -q`
Expected: FAIL (`module 'fence' has no attribute 'snap_to_phrase'`)

- [ ] **Step 3: Implement** (in `fence.py`, right after `_BARS_PER_PHRASE = 8`)

```python
_BARS_PER_SUBPHRASE = 4  # the finer 4-bar grid for smaller moves (8-bar = _BARS_PER_PHRASE)


def snap_to_phrase(t: float, downbeats: list[float], bars: int) -> float:
    """Snap time `t` to the nearest phrase boundary on the `bars`-bar grid — the nearest of
    `downbeats[::bars]` (every `bars`-th downbeat). Returns `t` unchanged if there is no such grid
    (missing/thin analysis), so a mix is never blocked over phrasing. bars=8 → the 8-bar 'turn of
    phrase'; bars=4 → the finer 4-bar grid."""
    grid = downbeats[::bars] if bars > 0 else downbeats
    if not grid:
        return t
    return min(grid, key=lambda d: abs(d - t))
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_fence.py -k snap_to_phrase -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add services/api/app/planner/fence.py services/api/tests/test_fence.py
git commit -m "feat(fence): snap_to_phrase helper (the phrasing ruler)"
```

---

### Task 2: Vocal entries land on the 8-bar grid

**Files:**
- Modify: `services/api/app/planner/fence.py:313-332` (`energy_drops` — snap + dedupe)
- Modify: `services/api/app/planner/plan.py:205` (`_default_arrangement` — belt re-snap of chosen anchors)
- Test: `services/api/tests/test_fence.py`, `services/api/tests/test_plan.py`

**Interfaces:**
- Consumes: `fence.snap_to_phrase`, `fence._BARS_PER_PHRASE` (Task 1).
- Produces: `energy_drops` now returns only phrase-aligned (8-bar) drop times; every `Placement.anchor` from `_default_arrangement` sits on the 8-bar grid.

- [ ] **Step 1: Write the failing tests**

`test_fence.py`:
```python
def test_energy_drops_land_on_phrase_lines():
    energy = [0.2] * 32
    for i in range(10, 16):
        energy[i] = 0.9  # a rise starting at bar 10 (a NON-phrase downbeat, 20.0s)
    a = make_analysis(bpm=120.0, n_bars=32, energy=energy)
    drops = fence.energy_drops(a.energy_curve, a.downbeats)
    phrase = a.downbeats[::8]
    assert drops and all(d in phrase for d in drops)  # snapped to an 8-bar line (16.0s)
```

`test_plan.py` (uses that file's `make_analysis` + `planner`):
```python
def test_vocal_anchors_land_on_8bar_phrase_lines(monkeypatch):
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)  # force the rules path
    energy = [0.3] * 96
    for i in range(26, 34):
        energy[i] = 0.95   # a drop starting on a non-phrase bar (26)
    for i in range(66, 74):
        energy[i] = 0.98
    a1 = make_analysis(bpm=120.0, n_bars=96, energy=energy)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 20.0), (40.0, 70.0)])
    plan = planner.build_mix_plan("m" * 64, a1, a2, take=1)
    phrase = a1.downbeats[::8]
    assert plan.placements
    assert all(any(abs(p.anchor - ps) <= 0.06 for ps in phrase) for p in plan.placements)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_fence.py::test_energy_drops_land_on_phrase_lines tests/test_plan.py::test_vocal_anchors_land_on_8bar_phrase_lines -q`
Expected: FAIL (drops/anchors land on non-phrase downbeats)

- [ ] **Step 3: Implement**

In `fence.energy_drops`, replace the final `return drops` (line 332) with:
```python
    # Phrasing: a drop IS the turn of phrase, so pin each to the nearest 8-bar phrase line (phrase
    # wins over a slightly-off detected downbeat). Dedupe drops that snap to the same line.
    snapped: list[float] = []
    for d in drops:
        s = snap_to_phrase(d, downbeats, _BARS_PER_PHRASE)
        if s not in snapped:
            snapped.append(s)
    return snapped
```

In `plan._default_arrangement`, right after `chosen = fence.synced_anchors(...)` (line 205), add the belt re-snap:
```python
    # Phrasing belt-and-suspenders: guarantee every anchor sits on an 8-bar phrase line, even on the
    # thin-analysis fallback path where synced_anchors could return a raw downbeat.
    _db = opts["a1_grid"].downbeats
    chosen = sorted({fence.snap_to_phrase(t, _db, fence._BARS_PER_PHRASE) for t in chosen})
```

- [ ] **Step 4: Run to verify they pass, then the full suite**

Run: `.venv/Scripts/python -m pytest tests/test_fence.py tests/test_plan.py -q`
Expected: PASS (including the two new tests). Fix any pre-existing test that assumed a raw-downbeat anchor by updating its expectation to the phrase-aligned value (NEVER weaken an assertion — recompute the correct expected phrase line).

- [ ] **Step 5: Commit**

```bash
git add services/api/app/planner/fence.py services/api/app/planner/plan.py services/api/tests/test_fence.py services/api/tests/test_plan.py
git commit -m "feat(fence/plan): vocal entries + drops snap to the 8-bar phrase grid"
```

---

### Task 3: Beat-up & breakdown windows land on the 4-bar grid

**Files:**
- Modify: `services/api/app/planner/fence.py:717` (`_best_energy_window` — restrict window starts to the 4-bar grid)
- Test: `services/api/tests/test_fence.py`

**Interfaces:**
- Consumes: `fence._BARS_PER_SUBPHRASE` (Task 1).
- Produces: `_best_energy_window` (and thus `beat_up_moves` / `breakdown_moves`) only returns windows whose start downbeat index is a multiple of 4; since widths are 4 and 8, both edges sit on the 4-bar grid.

- [ ] **Step 1: Write the failing test**

```python
def test_best_energy_window_starts_on_4bar_grid():
    # one loud 4-bar run STARTING at a non-grid bar (index 9) must be rejected for a 4-grid start
    energy = [0.5] * 48
    for i in range(9, 13):
        energy[i] = 0.99
    a = make_analysis(bpm=120.0, n_bars=48, energy=energy)
    lead = Placement(anchor=a.downbeats[2], vocal_src=(0.0, 3.0))  # a placement early, leaving a big gap after
    win = fence._best_energy_window(a, [lead], [], [], 1.0, 4, 0.3)
    assert win is not None
    start_i = a.downbeats.index(win[0])
    assert start_i % fence._BARS_PER_SUBPHRASE == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_fence.py::test_best_energy_window_starts_on_4bar_grid -q`
Expected: FAIL (window starts at index 9)

- [ ] **Step 3: Implement**

In `_best_energy_window`, inside `for j in range(len(idxs) - bars):` (line 717), add as the FIRST line of the loop body:
```python
            if idxs[j] % _BARS_PER_SUBPHRASE != 0:  # phrasing: window start must sit on the 4-bar grid
                continue
```

- [ ] **Step 4: Run to verify it passes, then the beat-up/breakdown tests**

Run: `.venv/Scripts/python -m pytest tests/test_fence.py -k "best_energy_window or beat_up or breakdown" -q`
Expected: PASS. If an existing beat-up/breakdown test asserted a specific non-grid window, recompute its expected (grid-aligned) window — do not weaken it.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/planner/fence.py services/api/tests/test_fence.py
git commit -m "feat(fence): beat-up & breakdown windows land on the 4-bar grid"
```

---

### Task 4: "Drop to just the beat" cut window lands on the 4-bar grid

**Files:**
- Modify: `services/api/app/planner/fence.py:657-685` (`stem_moves_for_drops` — snap cut/melody boundary indices to the 4-bar grid, preserving the existing clamps)
- Test: `services/api/tests/test_fence.py`

**Interfaces:**
- Consumes: `fence._BARS_PER_SUBPHRASE` (Task 1).
- Produces: every emitted `StemMove` from `stem_moves_for_drops` has `start` on the 4-bar grid; the bass move still ends at the (8-bar) anchor.

- [ ] **Step 1: Write the failing test**

```python
def test_stem_moves_for_drops_start_on_4bar_grid():
    a = make_analysis(bpm=120.0, n_bars=48)
    db = a.downbeats
    # a produced drop whose anchor is an 8-bar line; build_bars forces cut/build back onto odd bars
    p = Placement(anchor=db[16], vocal_src=(0.0, 4.0), build_bars=3)
    moves = fence.stem_moves_for_drops([p], db, 1.0, [])
    assert moves
    for m in moves:
        start_i = min(range(len(db)), key=lambda k: abs(db[k] - m.start))
        assert start_i % fence._BARS_PER_SUBPHRASE == 0, f"{m.stem} start not on 4-bar grid"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_fence.py::test_stem_moves_for_drops_start_on_4bar_grid -q`
Expected: FAIL (cut_start on `anchor - (build+recovery+cut)` = a non-grid bar)

- [ ] **Step 3: Implement**

In `stem_moves_for_drops`, after the previous-vocal clamp `while` loop (line 672) and before `cut_start = a1_downbeats[cut_start_i]` (line 673), snap the boundary INDICES to the 4-bar grid — round the start UP (never earlier than the clamp) and the melody end DOWN (never past the build boundary):
```python
        sub = _BARS_PER_SUBPHRASE
        cut_start_i = ((cut_start_i + sub - 1) // sub) * sub    # round UP to the 4-bar grid
        other_end_i = (other_end_i // sub) * sub                # round DOWN to the 4-bar grid
        if cut_start_i >= anchor_i:                             # snapped past the slam — no runway, skip
            continue
```
The existing lines that read `a1_downbeats[cut_start_i]` / `a1_downbeats[other_end_i]` and the `if cut_start_i < other_end_i:` melody guard (line 683) then hold: the bass move covers `[a1_downbeats[cut_start_i], anchor]` and the melody move only emits when real 4-grid cut room remains. No other change needed.

- [ ] **Step 4: Run to verify it passes, then the stem-move tests**

Run: `.venv/Scripts/python -m pytest tests/test_fence.py -k "stem_moves" -q`
Expected: PASS. Recompute (never weaken) any existing stem-move test that asserted specific non-grid boundaries.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/planner/fence.py services/api/tests/test_fence.py
git commit -m "feat(fence): drop-to-just-the-beat cut window lands on the 4-bar grid"
```

---

### Task 5: Integration guard, engine version bump, docs, and re-render

**Files:**
- Modify: `services/api/app/routes/mix.py` (`ENGINE_VERSION` bump + comment — NOT a dangerous file)
- Test: `services/api/tests/test_plan.py` (whole-plan phrasing guard)
- Modify: `docs/implementation-plan.md`, `docs/technical-spec.md`, `docs/functional-spec.md`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the integration test** (`test_plan.py`)

```python
def test_all_changes_land_on_the_phrase_grid(monkeypatch):
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    energy = [0.3] * 96
    for i in range(26, 34):
        energy[i] = 0.95
    for i in range(58, 66):
        energy[i] = 0.9
    a1 = make_analysis(bpm=120.0, n_bars=96, energy=energy)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 20.0), (40.0, 70.0)])
    plan = planner.build_mix_plan("m" * 64, a1, a2, take=1)
    db = a1.downbeats
    eight = db[::8]
    for p in plan.placements:                       # entries on the 8-bar grid
        assert any(abs(p.anchor - ps) <= 0.06 for ps in eight)
    for m in getattr(plan, "stem_moves", []):        # every move edge on the 4-bar grid
        for t in (m.start, m.end):
            i = min(range(len(db)), key=lambda k: abs(db[k] - t))
            assert i % 4 == 0, f"{m.stem} edge {t} not on 4-bar grid"
```

- [ ] **Step 2: Run to verify it passes** (the feature is already built by Tasks 1-4)

Run: `.venv/Scripts/python -m pytest tests/test_plan.py::test_all_changes_land_on_the_phrase_grid -q`
Expected: PASS. If it fails, a leak remains — fix the offending site (still on safe surfaces), don't weaken the test.

- [ ] **Step 3: Bump `ENGINE_VERSION`** in `routes/mix.py`

Add a comment line above `ENGINE_VERSION = "m5n.0"` and change the value:
```python
# m5o.0: PHRASING — every change lands on the phrase grid. Vocal entries + drops snap to the 8-bar
#        grid (fence.energy_drops / plan._default_arrangement); the auto beat moves (cut, beat-up,
#        breakdown) snap to the 4-bar grid (fence.stem_moves_for_drops / _best_energy_window).
#        Planner-only via fence.snap_to_phrase; render.py/validate.py UNCHANGED (phrase lines are
#        downbeats, already accepted by R3). Re-renders differ where a change was previously mid-phrase.
ENGINE_VERSION = "m5o.0"
```

- [ ] **Step 4: Run the full backend suite + typecheck + web tests**

Run: `.venv/Scripts/python -m pytest -q` (from `services/api`), then from repo root `npm run typecheck` and `npm test`.
Expected: all green (backend was 300 before this build; add the new tests).

- [ ] **Step 5: Update the living docs**

- `docs/implementation-plan.md`: append a drift-log entry — phrasing built (8-bar entries/drops, 4-bar moves), planner-only/safe surface, the render.py build-ramp deliberately left (a gradual ramp into the 8-bar drop), engine `m5o.0`.
- `docs/technical-spec.md`: add phrasing to the "how it's built" arrangement section.
- `docs/functional-spec.md`: note that changes now land on musical phrase lines (no abrupt mid-phrase moves).

- [ ] **Step 6: Commit**

```bash
git add services/api/app/routes/mix.py services/api/tests/test_plan.py docs/implementation-plan.md docs/technical-spec.md docs/functional-spec.md
git commit -m "feat(engine): phrasing alignment integration guard + m5o.0 + docs"
```

- [ ] **Step 7: Verification re-render (local, cached — no cloud cost)**

Re-render the three Anchor Point pairs (05 Dil Ye Bekarar, 09 Jee Karda, 10 Maula Mere) with the deterministic pipeline (reuse the goodnight batch scripts in the scratchpad; `ANTHROPIC_API_KEY` popped). For each rendered plan, assert (in the script) every placement anchor is on the 8-bar grid and every stem-move edge on the 4-bar grid, and `validate_plan`/`validate_render` are CLEAN. Then re-render the full goodnight batch to `Desktop/DJAI SONGS` for the founder's ear-test — confirm the four Father Ocean mixes still validate clean. This step is the "did it help" check; its output is evidence for the founder, not a committed test.

---

## Self-review notes

- **Spec coverage:** Task 1 = the ruler; Task 2 = 8-bar vocal entries/drops (spec items 1-2); Task 3 = 4-bar beat-up/breakdown (spec item 4); Task 4 = 4-bar cut window (spec item 3); Task 5 = integration guard + version + docs + re-render (acceptance criteria). The deliberately-not-snapped build ramp (spec "Not snapped") is respected — no task touches it or `render.py`.
- **Type consistency:** `snap_to_phrase(t, downbeats, bars)` and `_BARS_PER_SUBPHRASE` are used identically across Tasks 2-4. `_BARS_PER_PHRASE` is the existing `8`.
- **Safe surface:** only `fence.py`, `plan.py`, `routes/mix.py`, tests, docs — no `validate.py` / `render.py`. No dangerous-file ceremony required.
- **No placeholders:** every code and test step is concrete. Where an existing test may assert an old non-grid value, the instruction is to recompute the correct phrase-aligned expectation, never to weaken.
