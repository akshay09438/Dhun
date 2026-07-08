# Movable-Master Tempo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unblock tempo-declined pairs (Father Ocean × Tere Bina) by nudging the house track the minimum amount to a shared tempo, so the guest vocal's remaining stretch falls back inside the safe band — protecting the house's drive.

**Architecture:** The brain (`fence`/`plan`) computes a house-protective shared tempo, retimes Song 1's analysis onto it, and plans as usual on that retimed grid. The engine (`render.py`) pre-stretches Song 1's stems by the same ratio, then runs the existing render verbatim. The referee (`validate.py`) rescales Song 1's grid by the plan's own `bed_stretch` so on-beat checks hold. The LLM never touches audio.

**Tech Stack:** Python 3.11, Pydantic v2, numpy, soundfile, FFmpeg `atempo` (already used), pytest.

## Global Constraints

- **Additive only.** `MixPlan.bed_stretch: float = 1.0` defaults to today; every existing cached plan parses and renders **identically**. No existing field renamed or repurposed.
- **Only when needed.** `bed_stretch` stays `1.0` for any pair whose one-sided lock already fits `[SAFE_STRETCH_LO, SAFE_STRETCH_HI]` (= 0.89–1.11). Every current catalog pair is unchanged.
- **House-protective.** When engaged, the house moves the minimum, bounded to `HOUSE_SLOW_MAX = 0.04` (slow) / `HOUSE_SPEED_MAX = 0.08` (speed) — both new `fence` constants, tunable by ear. The vocal stays in `[SAFE_STRETCH_LO, SAFE_STRETCH_HI]`.
- **Single source of truth for the grid.** `fence.retimed_analysis(a1, master_bpm)` is the ONE function that rescales Song 1's timeline; both the planner and the referee call it, so they can never drift.
- **Dangerous surfaces:** `workers/render.py` (Task 7) and `services/api/app/planner/validate.py` (Task 6). Their failing tests are authored **independently** (test-author subagent); a fresh adversarial-safety panel must clear them; the founder gives an explicit yes; apply via `.zuko/approve.js`.
- **TDD, commit per task.** Run backend tests from `services/api` with `.venv/Scripts/python -m pytest`.

---

### Task 1: `MixPlan.bed_stretch` field (safe)

**Files:**

- Modify: `services/api/app/models.py` (the `MixPlan` class)
- Test: `services/api/tests/test_models.py`

**Interfaces:**

- Produces: `MixPlan.bed_stretch: float = 1.0` — the ratio Song 1's bed is time-stretched by (1.0 = native master).

- [ ] **Step 1: Write the failing test**

```python
# in services/api/tests/test_models.py
def test_bed_stretch_is_additive_and_defaults_to_one():
    plan = MixPlan(
        mix_id="m" * 64, song1_id="a" * 64, song2_id="b" * 64,
        master_bpm=128.16, vocal_stretch=0.89, vocal_src=(16.0, 40.0), anchor=16.0,
        bed_stretch=1.05,
    )
    assert MixPlan.model_validate_json(plan.model_dump_json()).bed_stretch == 1.05
    # an old plan with no bed_stretch still parses -> defaults to 1.0
    old = ('{"mix_id":"m","song1_id":"a","song2_id":"b","master_bpm":120.0,'
           '"vocal_stretch":1.0,"vocal_src":[16.0,40.0],"anchor":16.0}')
    assert MixPlan.model_validate_json(old).bed_stretch == 1.0
```

- [ ] **Step 2: Run it, verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_models.py::test_bed_stretch_is_additive_and_defaults_to_one -v`
Expected: FAIL (`bed_stretch` unknown / attribute error).

- [ ] **Step 3: Add the field**

```python
# services/api/app/models.py — in class MixPlan, next to vocal_stretch:
    bed_stretch: float = 1.0  # ratio Song 1's bed is time-stretched by (movable master); 1.0 = native
```

- [ ] **Step 4: Run it, verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_models.py -v` → PASS (all model tests).

- [ ] **Step 5: Commit**

```bash
git add services/api/app/models.py services/api/tests/test_models.py
git commit -m "feat(models): additive MixPlan.bed_stretch for the movable master"
```

---

### Task 2: `fence.tempo_plan` — house-protective shared tempo (safe)

**Files:**

- Modify: `services/api/app/planner/fence.py`
- Test: `services/api/tests/test_fence.py`

**Interfaces:**

- Consumes: `SAFE_STRETCH_LO`, `SAFE_STRETCH_HI` (existing).
- Produces:
  - `HOUSE_SLOW_MAX = 0.04`, `HOUSE_SPEED_MAX = 0.08` (module constants).
  - `_fold_source(master_bpm, source_bpm) -> float`
  - `tempo_plan(master_bpm, source_bpm, lo=SAFE_STRETCH_LO, hi=SAFE_STRETCH_HI, slow_max=HOUSE_SLOW_MAX, speed_max=HOUSE_SPEED_MAX) -> tuple[float, float, float, bool]` returning `(master_bpm_out, bed_stretch, vocal_stretch, safe)`.

- [ ] **Step 1: Write the failing tests**

```python
# in services/api/tests/test_fence.py
def test_tempo_plan_in_band_keeps_house_native():
    m, bed, voc, safe = fence.tempo_plan(122.0, 111.0)  # +9.9% one-sided, in band
    assert safe and bed == 1.0 and m == 122.0 and 1.08 < voc < 1.11

def test_tempo_plan_protects_house_for_a_fast_guest():
    # 122 house x 144 guest (Tere Bina): house moves the MINIMUM and only UP; vocal to band edge.
    m, bed, voc, safe = fence.tempo_plan(122.0, 144.0)
    assert safe
    assert 1.0 < bed <= 1.0 + fence.HOUSE_SPEED_MAX + 1e-9   # house sped up, within its cap
    assert abs(voc - fence.SAFE_STRETCH_LO) < 1e-3            # vocal parked at its slow edge
    assert abs(m - bed * 122.0) < 0.05                        # master == house_bpm * bed_stretch

def test_tempo_plan_octave_folds_a_half_counted_ballad():
    # a 72-BPM ballad read as 72 folds to 144 (nearest 122) -> same result as 144
    assert fence.tempo_plan(122.0, 72.0) == fence.tempo_plan(122.0, 144.0)

def test_tempo_plan_declines_when_house_would_move_too_far():
    # 120 x 150: house would need > +8% to reach the vocal's band -> declined (house protected)
    _m, _bed, _voc, safe = fence.tempo_plan(120.0, 150.0)
    assert not safe

def test_tempo_plan_guards_zero():
    assert fence.tempo_plan(122.0, 0.0)[3] is False
```

- [ ] **Step 2: Run them, verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_fence.py -k tempo_plan -v`
Expected: FAIL (`tempo_plan` not defined).

- [ ] **Step 3: Implement**

```python
# services/api/app/planner/fence.py — near SAFE_STRETCH_LO/HI:
# The house/EDM track is the anchor: slowing it kills its drive. When a pair needs the
# movable master, the house moves the MINIMUM and is bounded here (tunable by ear); the
# guest vocal absorbs the rest of the stretch (recipe §1.5, founder call 2026-07-08).
HOUSE_SLOW_MAX = 0.04   # the house may slow at most 4%
HOUSE_SPEED_MAX = 0.08  # ...and speed at most 8%


def _fold_source(master_bpm: float, source_bpm: float) -> float:
    """Octave-fold the source BPM to the multiple (x0.5 / x1 / x2) nearest the master."""
    return min((source_bpm, source_bpm * 2, source_bpm / 2), key=lambda b: abs(b - master_bpm))


def tempo_plan(master_bpm: float, source_bpm: float,
               lo: float = SAFE_STRETCH_LO, hi: float = SAFE_STRETCH_HI,
               slow_max: float = HOUSE_SLOW_MAX, speed_max: float = HOUSE_SPEED_MAX
               ) -> tuple[float, float, float, bool]:
    """Choose the shared tempo for the pair, protecting the house track.

    Returns (master_bpm_out, bed_stretch, vocal_stretch, safe):
      - one-sided lock (house fixed) already in band -> native master (bed_stretch == 1.0),
        exactly today's behaviour; else
      - move the house the MINIMUM to bring the vocal back into band, bounded to
        [1-slow_max, 1+speed_max]. The vocal absorbs the rest and sits at its band edge.
    `safe` is False (decline) when the house would have to move beyond its bounds.
    """
    if master_bpm <= 0 or source_bpm <= 0:
        return master_bpm, 1.0, 1.0, False
    src = _fold_source(master_bpm, source_bpm)
    one_sided = master_bpm / src
    if lo <= one_sided <= hi:
        return master_bpm, 1.0, round(one_sided, 4), True         # native master (today)
    t = min(max(master_bpm, lo * src), hi * src)                  # vocal-legal tempo nearest the house
    bed, voc = t / master_bpm, t / src
    safe = (1.0 - slow_max) - 1e-9 <= bed <= (1.0 + speed_max) + 1e-9
    return round(t, 3), round(bed, 4), round(voc, 4), safe
```

- [ ] **Step 4: Run them, verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_fence.py -k tempo_plan -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/planner/fence.py services/api/tests/test_fence.py
git commit -m "feat(fence): tempo_plan — house-protective shared tempo (movable master)"
```

---

### Task 3: `fence.retimed_analysis` — rescale Song 1's grid (safe)

**Files:**

- Modify: `services/api/app/planner/fence.py`
- Test: `services/api/tests/test_fence.py`

**Interfaces:**

- Consumes: `TrackAnalysis`, `Section` (from `app.models`).
- Produces: `retimed_analysis(a1: TrackAnalysis, target_bpm: float) -> TrackAnalysis` — a copy whose every time field is scaled by `a1.bpm / target_bpm` (= `1/bed_stretch`) and whose `bpm == target_bpm`. `energy_curve` values are unchanged (per-bar; re-timestamped via the scaled downbeats).

- [ ] **Step 1: Write the failing test**

```python
# in services/api/tests/test_fence.py
def test_retimed_analysis_scales_grid_to_target_tempo():
    a1 = make_analysis(bpm=122.0, n_bars=16, vocal_regions=[(10.0, 20.0)],
                       sections=[Section(start=0.0, end=8.0, label="intro")])
    r = fence.retimed_analysis(a1, 128.16)          # house sped up (bed_stretch ~1.05)
    f = 122.0 / 128.16
    assert r.bpm == 128.16
    assert abs(r.downbeats[1] - a1.downbeats[1] * f) < 1e-3   # every downbeat pulled in
    assert abs(r.vocal_regions[0][0] - 10.0 * f) < 1e-3
    assert abs(r.sections[0].end - 8.0 * f) < 1e-3
    assert r.energy_curve == a1.energy_curve         # per-bar values unchanged
    assert a1.downbeats[1] != r.downbeats[1]          # original left untouched (a copy)
```

- [ ] **Step 2: Run it, verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_fence.py::test_retimed_analysis_scales_grid_to_target_tempo -v` → FAIL.

- [ ] **Step 3: Implement**

```python
# services/api/app/planner/fence.py — add near tempo_plan:
def retimed_analysis(a1: TrackAnalysis, target_bpm: float) -> TrackAnalysis:
    """Return a copy of a1 whose timeline is scaled to target_bpm (for the movable master:
    the house bed is stretched to target_bpm, so its grid must move with it). Pure arithmetic;
    energy_curve is per-bar and unchanged. No-op if either bpm is missing."""
    if not a1.bpm or a1.bpm <= 0 or target_bpm <= 0:
        return a1
    f = a1.bpm / target_bpm
    return a1.model_copy(update={
        "bpm": target_bpm,
        "beats": [round(t * f, 4) for t in a1.beats],
        "downbeats": [round(t * f, 4) for t in a1.downbeats],
        "phrase_starts": [round(t * f, 4) for t in a1.phrase_starts],
        "sections": [s.model_copy(update={"start": round(s.start * f, 4), "end": round(s.end * f, 4)})
                     for s in a1.sections],
        "vocal_regions": [(round(s * f, 4), round(e * f, 4)) for s, e in a1.vocal_regions],
    })
```

- [ ] **Step 4: Run it, verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_fence.py::test_retimed_analysis_scales_grid_to_target_tempo -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/planner/fence.py services/api/tests/test_fence.py
git commit -m "feat(fence): retimed_analysis — the single grid-rescale for the movable master"
```

---

### Task 4: Wire `tempo_plan` + retime into `legal_options` / `arrangement_options` (safe)

**Files:**

- Modify: `services/api/app/planner/fence.py` (`legal_options`, `arrangement_options`)
- Test: `services/api/tests/test_fence.py`

**Interfaces:**

- Produces: `legal_options` / `arrangement_options` dicts now also carry `"bed_stretch": float` and `"a1_grid": TrackAnalysis` (the retimed grid to plan/warp against; equals the original when `bed_stretch == 1.0`). `master_bpm` is now the shared tempo `T` when engaged. All existing keys keep their meaning.

- [ ] **Step 1: Write the failing tests**

```python
# in services/api/tests/test_fence.py
def test_arrangement_options_engages_movable_master_for_tere_bina_shape():
    a1 = make_analysis(bpm=122.0, n_bars=64, vocal_regions=[(20.0, 40.0)])
    a2 = make_analysis(bpm=144.0, n_bars=64, vocal_regions=[(16.0, 40.0)])
    opts = fence.arrangement_options(a1, a2)
    assert opts["mixable"]
    assert opts["bed_stretch"] > 1.0                      # house nudged up (never slowed)
    assert opts["master_bpm"] > 122.0                     # shared tempo above the house's own
    assert opts["a1_grid"].bpm == opts["master_bpm"]      # planning grid is the retimed one
    assert opts["anchors_ranked"] and opts["anchors_ranked"][0] < a1.beats[-1] * 122.0 / opts["master_bpm"] + 1e-6

def test_arrangement_options_in_band_pair_stays_native():
    a1 = make_analysis(bpm=122.0, n_bars=64, vocal_regions=[(20.0, 40.0)])
    a2 = make_analysis(bpm=118.0, n_bars=64, vocal_regions=[(16.0, 40.0)])
    opts = fence.arrangement_options(a1, a2)
    assert opts["bed_stretch"] == 1.0 and opts["master_bpm"] == 122.0
    assert opts["a1_grid"] is a1                          # untouched grid, today's path
```

- [ ] **Step 2: Run them, verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_fence.py -k "movable_master or stays_native" -v` → FAIL (`bed_stretch`/`a1_grid` keys missing).

- [ ] **Step 3: Implement** (replace the tempo block in `legal_options`, and the grid source in `arrangement_options`)

```python
# services/api/app/planner/fence.py — legal_options, replacing the best_stretch block:
def legal_options(a1: TrackAnalysis, a2: TrackAnalysis) -> dict:
    if not a1.bpm or not a2.bpm or not (a1.phrase_starts or a1.downbeats or a1.beats):
        return {"mixable": False, "reason": "One track has no reliable beat to lock to."}

    master_bpm, bed_stretch, vocal_stretch, safe = tempo_plan(a1.bpm, a2.bpm)
    if not safe:
        pct = round(abs(a1.bpm / _fold_source(a1.bpm, a2.bpm) - 1) * 100)
        return {"mixable": False,
                "reason": f"These two songs are too far apart in tempo (~{pct}% stretch) to blend cleanly."}

    a1g = retimed_analysis(a1, master_bpm) if abs(bed_stretch - 1.0) >= 1e-6 else a1
    vocal_src = best_vocal_slice(a2)
    need = (vocal_src[1] - vocal_src[0]) * vocal_stretch
    drops = candidate_drops(a1g, need)
    if not drops:
        return {"mixable": False, "reason": "Couldn't find a spot in Song 1 with room for the vocal."}

    key_fit = camelot_fit(a1.key.camelot, a2.key.camelot) if (a1.key and a2.key) else None
    return {"mixable": True, "master_bpm": master_bpm, "bed_stretch": bed_stretch,
            "vocal_stretch": vocal_stretch, "vocal_src": vocal_src, "drops": drops,
            "key_fit": key_fit, "a1_grid": a1g}
```

```python
# services/api/app/planner/fence.py — arrangement_options, use a1g everywhere it read a1:
def arrangement_options(a1: TrackAnalysis, a2: TrackAnalysis) -> dict:
    base = legal_options(a1, a2)
    if not base["mixable"]:
        return base
    a1g = base["a1_grid"]
    slices = vocal_slices(a2)
    need = min(e - s for s, e in slices) * base["vocal_stretch"]
    anchors_ranked = candidate_drops(a1g, need)
    track_end = (a1g.beats[-1] if a1g.beats
                 else (max(anchors_ranked) + need if anchors_ranked else need))
    return {
        **base,
        "anchors_ranked": anchors_ranked,
        "vocal_slices": slices,
        "vocal_peaks": vocal_peaks(a2),
        "drops": energy_drops(a1g.energy_curve, a1g.downbeats),
        "track_end": track_end,
        "sections": [(s.start, s.label) for s in a1g.sections],
    }
```

- [ ] **Step 4: Run the whole fence suite** (existing tests must still pass — in-band pairs unchanged)

Run: `.venv/Scripts/python -m pytest tests/test_fence.py -v`
Expected: PASS, including the existing `test_legal_options_happy_path` (master_bpm 120, in band) and `test_legal_options_declines_far_tempo`.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/planner/fence.py services/api/tests/test_fence.py
git commit -m "feat(fence): legal/arrangement options carry bed_stretch + the retimed grid"
```

---

### Task 5: Plan on the retimed grid + set `bed_stretch` (safe)

**Files:**

- Modify: `services/api/app/planner/plan.py` (`build_mix_plan`)
- Test: `services/api/tests/test_plan.py`

**Interfaces:**

- Consumes: `opts["a1_grid"]`, `opts["bed_stretch"]`, `opts["master_bpm"]` from `fence.arrangement_options`.
- Produces: `MixPlan.bed_stretch` set from `opts`; all placement/warp/flourish planning runs against `a1g` (the retimed grid).

- [ ] **Step 1: Write the failing test**

```python
# in services/api/tests/test_plan.py  (use the module's existing analysis helpers/fixtures)
def test_build_mix_plan_sets_bed_stretch_and_plans_on_retimed_grid():
    from tests.test_fence import make_analysis
    a1 = make_analysis(bpm=122.0, n_bars=64, vocal_regions=[(20.0, 40.0)])
    a2 = make_analysis(bpm=144.0, n_bars=64, vocal_regions=[(16.0, 40.0)])
    plan = build_mix_plan("id", a1, a2)
    assert plan.bed_stretch > 1.0 and plan.master_bpm > 122.0
    # every anchor lands on a downbeat of the RETIMED grid (what the audio will play at)
    from app.planner import fence
    dg = fence.retimed_analysis(a1, plan.master_bpm).downbeats
    for p in plan.placements:
        assert min(abs(p.anchor - d) for d in dg) <= 0.06

def test_build_mix_plan_in_band_pair_has_unit_bed_stretch():
    from tests.test_fence import make_analysis
    a1 = make_analysis(bpm=122.0, n_bars=64, vocal_regions=[(20.0, 40.0)])
    a2 = make_analysis(bpm=118.0, n_bars=64, vocal_regions=[(16.0, 40.0)])
    assert build_mix_plan("id", a1, a2).bed_stretch == 1.0
```

- [ ] **Step 2: Run them, verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_plan.py -k bed_stretch -v` → FAIL (`bed_stretch` 1.0 / attribute).

- [ ] **Step 3: Implement** — in `build_mix_plan`, bind `a1g` and thread it through:

```python
# services/api/app/planner/plan.py — build_mix_plan:
    opts = fence.arrangement_options(a1, a2)
    if not opts["mixable"]:
        raise MixDeclined(opts["reason"])
    a1g = opts.get("a1_grid", a1)  # the retimed grid to plan + warp + validate-flourishes against

    placements = _ai_arrange(opts, prompt, take)
    source = "ai" if placements else "rules"
    if not placements:
        placements = _default_arrangement(opts, take)
    placements = _attach_warp(placements, a1g, a2, opts["vocal_stretch"])
    placements = _dedupe_nonoverlapping(placements, opts["vocal_stretch"])
    if not _spans_song(placements, opts.get("track_end", 0.0)):
        rebuilt = _attach_warp(_default_arrangement(opts, take), a1g, a2, opts["vocal_stretch"])
        placements = _dedupe_nonoverlapping(rebuilt, opts["vocal_stretch"])
        source = "rules"
    placements, s1_regions = _apply_flourishes(a1g, placements, opts["vocal_stretch"])
    if _confident(a1g):
        placements = _produce_drops(placements, opts.get("drops", []), s1_regions,
                                    opts["vocal_stretch"], opts["master_bpm"])
    first = placements[0]
    return MixPlan(
        mix_id=mix_id, song1_id=a1.song_id, song2_id=a2.song_id,
        master_bpm=opts["master_bpm"], vocal_stretch=opts["vocal_stretch"],
        bed_stretch=opts.get("bed_stretch", 1.0),
        vocal_src=first.vocal_src, anchor=first.anchor,
        placements=placements, s1_vocal_regions=s1_regions, take=take,
        notes=_describe_arrangement(placements, s1_regions),
        confidence=0.75 if source == "ai" else 0.6, source=source,
    )
```

- [ ] **Step 4: Run the plan suite**

Run: `.venv/Scripts/python -m pytest tests/test_plan.py -v` → PASS (new + existing).

- [ ] **Step 5: Commit**

```bash
git add services/api/app/planner/plan.py services/api/tests/test_plan.py
git commit -m "feat(plan): plan on the retimed grid and record bed_stretch"
```

---

### Task 6: Referee — rescale the grid + guard `bed_stretch` (🔒 PROTECTED `validate.py`)

> **Dangerous surface.** Failing tests authored independently (test-author subagent). Fresh adversarial-safety panel must clear it. Founder's explicit yes, then apply via `.zuko/approve.js --files "services/api/app/planner/validate.py,services/api/tests/test_validate.py" ...`.

**Files:**

- Modify: `services/api/app/planner/validate.py`
- Test: `services/api/tests/test_validate.py`

**Interfaces:**

- Consumes: `fence.retimed_analysis`, `fence.HOUSE_SLOW_MAX`, `fence.HOUSE_SPEED_MAX`.
- Produces: `validate_plan` rescales `a1` by the plan's own `bed_stretch` (via `retimed_analysis(a1, plan.master_bpm)`) before the on-beat/warp checks, and flags an out-of-bounds `bed_stretch` (B3).

- [ ] **Step 1 (independent test-author): Write the failing tests**

```python
# in services/api/tests/test_validate.py
def test_validate_flags_out_of_bounds_bed_stretch():
    a1, a2 = make_analysis(bpm=122.0), make_analysis()
    plan = make_arrangement_plan([Placement(anchor=16.0, vocal_src=(0.0, 8.0))])
    plan.master_bpm, plan.bed_stretch = 122.0 * 1.20, 1.20  # house sped 20% — past HOUSE_SPEED_MAX
    assert any("B3" in m for m in validate.validate_plan(plan, a1, a2))

def test_validate_on_the_retimed_grid_accepts_a_movable_master_plan():
    # Song 1 at 122; the plan runs at a stretched tempo. Anchors on the RETIMED downbeats must pass.
    from app.planner import fence
    a1 = make_analysis(bpm=122.0, n_bars=64)
    target = 128.16
    dg = fence.retimed_analysis(a1, target).downbeats
    p = [Placement(anchor=dg[8], vocal_src=(0.0, 6.0)), Placement(anchor=dg[24], vocal_src=(0.0, 6.0))]
    plan = make_arrangement_plan(p, stretch=0.89)
    plan.master_bpm, plan.bed_stretch = target, round(target / 122.0, 4)
    assert validate.validate_plan(plan, a1, make_analysis()) == []

def test_validate_retimed_grid_still_catches_a_real_offbeat_entry():
    from app.planner import fence
    a1 = make_analysis(bpm=122.0, n_bars=64)
    target = 128.16
    dg = fence.retimed_analysis(a1, target).downbeats
    p = [Placement(anchor=dg[8] + 0.3, vocal_src=(0.0, 6.0))]  # 300 ms off the retimed grid
    plan = make_arrangement_plan(p, stretch=0.89)
    plan.master_bpm, plan.bed_stretch = target, round(target / 122.0, 4)
    assert any("R3" in m for m in validate.validate_plan(plan, a1, make_analysis()))

def test_validate_old_plan_unaffected_by_the_rescale():
    a1, a2 = make_analysis(), make_analysis()      # bed_stretch defaults 1.0
    assert validate.validate_plan(make_plan(anchor=16.0), a1, a2) == []
```

- [ ] **Step 2: Run them, verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_validate.py -k "bed_stretch or retimed or unaffected" -v` → FAIL.

- [ ] **Step 3: Implement**

```python
# services/api/app/planner/validate.py — imports:
from app.planner.fence import (HOUSE_SLOW_MAX, HOUSE_SPEED_MAX, LEAD_XFADE_SECS,
                               SAFE_STRETCH_HI, SAFE_STRETCH_LO, placement_end, retimed_analysis)

# validate_plan — at the very top of the function body:
def validate_plan(plan: MixPlan, a1: TrackAnalysis, a2: TrackAnalysis) -> list[str]:
    violations: list[str] = []
    bed_stretch = getattr(plan, "bed_stretch", 1.0) or 1.0
    if abs(bed_stretch - 1.0) >= 1e-6:
        if not (1.0 - HOUSE_SLOW_MAX - 1e-6 <= bed_stretch <= 1.0 + HOUSE_SPEED_MAX + 1e-6):
            violations.append("the house tempo stretch is outside the safe band (B3)")
        # validate against the stretched grid the audio actually plays at (single source of
        # truth: the same retime the planner used, keyed off the plan's own master_bpm)
        a1 = retimed_analysis(a1, plan.master_bpm)
    if not SAFE_STRETCH_LO <= plan.vocal_stretch <= SAFE_STRETCH_HI:
        violations.append("tempo stretch is outside the safe band (B3)")
    # ... the rest of the existing function is UNCHANGED (it now reads the rescaled a1) ...
```

- [ ] **Step 4: Run the validate suite**

Run: `.venv/Scripts/python -m pytest tests/test_validate.py -v` → PASS (new + all existing).

- [ ] **Step 5: Adversarial panel + founder yes + apply + commit** (see the process gate at the top). After approval:

```bash
git add services/api/app/planner/validate.py services/api/tests/test_validate.py
git commit -m "feat(validate): rescale the grid by bed_stretch + guard the house stretch band"
```

---

### Task 7: Engine — pre-stretch Song 1's stems (🔒 PROTECTED `render.py`)

> **Dangerous surface.** Failing tests authored independently. Fresh adversarial-safety panel must clear it (could the bed & vocal drift apart? clip? an old mix change?). Founder's explicit yes, then apply via `.zuko/approve.js --files "workers/render.py,services/api/tests/test_render.py" ...`.

**Files:**

- Modify: `workers/render.py`
- Test: `services/api/tests/test_render.py`

**Interfaces:**

- Consumes: `plan.bed_stretch` (defaults 1.0).
- Produces: `_atempo_file(src, ratio, out) -> Path`; `render_mix` pre-stretches Song 1's stems by `bed_stretch` when `!= 1.0`, then runs the existing render verbatim.

- [ ] **Step 1 (independent test-author): Write the failing tests**

```python
# in services/api/tests/test_render.py
def _arr_plan_bed(placements, bed_stretch, master_bpm=120.0):
    p = _arr_plan(placements)
    p.bed_stretch = bed_stretch
    p.master_bpm = master_bpm
    return p

def test_render_bed_stretch_one_is_identical_to_today(tmp_path):
    """Old-mixes-still-work: bed_stretch == 1.0 must byte-match the pre-change render."""
    stems, vocal = _stems(tmp_path)
    a = tmp_path / "a.wav"; b = tmp_path / "b.wav"
    render.render_mix(_arr_plan([(1.0, (0.0, 1.5), False)]), stems, vocal, a)
    plan = _arr_plan([(1.0, (0.0, 1.5), False)]); plan.bed_stretch = 1.0
    render.render_mix(plan, stems, vocal, b)
    ya, _ = sf.read(a, dtype="float32", always_2d=True)
    yb, _ = sf.read(b, dtype="float32", always_2d=True)
    assert ya.shape == yb.shape and float(np.max(np.abs(ya - yb))) < 1e-6

def test_render_bed_stretch_shrinks_the_bed_and_stays_clean(tmp_path):
    """A sped-up house bed (bed_stretch>1) is shorter, on-grid, and never clips."""
    stems, vocal = _stems(tmp_path)  # 8s tones
    out = tmp_path / "mix.wav"
    plan = _arr_plan_bed([(1.0, (0.0, 1.0), False)], bed_stretch=1.05)
    render.render_mix(plan, stems, vocal, out)
    y, sr = sf.read(out, dtype="float32", always_2d=True)
    assert 0.0 < float(np.max(np.abs(y))) <= render._CEILING     # audible, no clip
    # bed drums were 8s -> at 1.05x they are ~7.62s; the mix length tracks the stretched bed
    assert 7.0 < len(y) / sr < 7.9

def test_atempo_file_changes_duration(tmp_path):
    src = tmp_path / "s.wav"; _tone(src, secs=4.0)
    out = render._atempo_file(src, 1.05, tmp_path / "o.wav")
    y, sr = sf.read(out, dtype="float32", always_2d=True)
    assert 3.6 < len(y) / sr < 3.95  # 4s / 1.05 ~= 3.81s
```

- [ ] **Step 2: Run them, verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_render.py -k "bed_stretch or atempo_file" -v` → FAIL.

- [ ] **Step 3: Implement**

```python
# workers/render.py — add a helper near _decode:
def _atempo_file(src: Path, ratio: float, out: Path) -> Path:
    """Time-stretch a whole audio file by `ratio` (pitch-preserved atempo) to a WAV at `out`."""
    _run_ffmpeg(["ffmpeg", "-y", "-i", str(src), "-ar", str(SR), "-ac", "2",
                 "-filter:a", f"atempo={ratio:.6f}", str(out)])
    return out


# render_mix — wrap the body in a tempdir and pre-stretch the stems when bed_stretch != 1.0:
def render_mix(plan, song1_stems, song2_vocal, out_path):
    if plan.master_bpm <= 0:
        raise RenderError("plan has a non-positive tempo")
    bed_stretch = float(getattr(plan, "bed_stretch", 1.0) or 1.0)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as _td:
        if abs(bed_stretch - 1.0) >= 1e-3:  # movable master: retime the WHOLE house bed to the target
            if not (_ATEMPO_MIN <= bed_stretch <= _ATEMPO_MAX):
                raise RenderError(f"bed stretch {bed_stretch:.3f} outside atempo range")
            song1_stems = {name: _atempo_file(p, bed_stretch, Path(_td) / f"{name}.wav")
                           for name, p in song1_stems.items()}
        bed = _sum_stems([song1_stems["drums"], song1_stems["bass"], song1_stems["other"]])
        # ... the ENTIRE existing body from here down is unchanged, only indented one level ...
        sf.write(out_path, bed, SR, subtype="PCM_16")
        return out_path
```

Note for the implementer: the change to `render_mix` is (a) the `bed_stretch` prelude and (b) indenting the existing body one level under the `with`. Do **not** alter any existing render logic; the stretched stems already sit on the retimed grid the plan's anchors/warp expect.

- [ ] **Step 4: Run the render suite**

Run: `.venv/Scripts/python -m pytest tests/test_render.py -v` → PASS (new + all existing, incl. `test_render_bed_stretch_one_is_identical_to_today`).

- [ ] **Step 5: Adversarial panel + founder yes + apply + commit.** After approval:

```bash
git add workers/render.py services/api/tests/test_render.py
git commit -m "feat(render): pre-stretch Song 1's stems for the movable master"
```

---

### Task 8: Route — bump `ENGINE_VERSION` (safe)

**Files:**

- Modify: `services/api/app/routes/mix.py`
- Test: `services/api/tests/test_mix_route.py`

**Interfaces:**

- Produces: a new `ENGINE_VERSION` so a pair now mixed at a shared tempo never serves a stale native-tempo cache.

- [ ] **Step 1: Write the failing test**

```python
# in services/api/tests/test_mix_route.py
def test_engine_version_is_movable_master():
    from app.routes.mix import ENGINE_VERSION
    assert ENGINE_VERSION == "m5h.1"
```

- [ ] **Step 2: Run it, verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_mix_route.py::test_engine_version_is_movable_master -v` → FAIL.

- [ ] **Step 3: Implement** — add a comment line and bump the constant:

```python
# services/api/app/routes/mix.py — extend the version log and bump:
# m5h.1: movable-master tempo — house-protective shared tempo for far-apart pairs (e.g. Tere Bina);
#        MixPlan.bed_stretch stretches Song 1's whole bed to the target; referee rescales the grid.
ENGINE_VERSION = "m5h.1"
```

- [ ] **Step 4: Run the route suite**

Run: `.venv/Scripts/python -m pytest tests/test_mix_route.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/routes/mix.py services/api/tests/test_mix_route.py
git commit -m "chore(mix): bump ENGINE_VERSION to m5h.1 (movable master)"
```

---

## Final verification (after all tasks)

- [ ] Full backend suite: from `services/api`, `.venv/Scripts/python -m pytest -q` → all green (was 212; expect ~212 + new).
- [ ] Typecheck (root): `npm run typecheck` → clean.
- [ ] **Founder ear-test (machinery proof, free/cached):** render Father Ocean × Tujhe Bhula Diya with a forced `bed_stretch` (nudge the house a few %) via the scratchpad pattern; confirm the house sounds clean, on-beat, click-free. Then, once Tere Bina is ingested, render the real pair and listen for vocal warble; tune `HOUSE_SLOW_MAX`/`HOUSE_SPEED_MAX` by ear.
- [ ] Update living docs: `docs/technical-spec.md` (the movable master + bed_stretch), `docs/implementation-plan.md` (mark this step; drift-log note that the roadmap put the movable master before Step 3 and chose house-protective over 50/50).

## Self-review notes

- **Spec coverage:** tempo math (T2), retime (T3), fence wiring (T4), plan (T5), referee rescale + B3 (T6), engine pre-stretch (T7), model field (T1), route (T8), old-mix identity proof (T7 test). All spec sections mapped.
- **Type consistency:** `tempo_plan` returns `(master_bpm, bed_stretch, vocal_stretch, safe)` everywhere; `retimed_analysis(a1, target_bpm)` used identically in plan and referee; `a1_grid`/`bed_stretch` keys added in T4 and consumed in T5.
- **Only-when-needed / additive:** `bed_stretch` defaults 1.0; in-band pairs keep `a1_grid is a1` and `bed_stretch == 1.0`; T7's identity test pins byte-equality.
