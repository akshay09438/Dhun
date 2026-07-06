# M4 Slice A — Living Arrangement + Regenerate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn M3's single vocal drop into a full DJ arrangement (the vocal weaving in/out across ≥2 sections, energy shaped like a set, a real one-bar beat-breath) plus a "give me another take" Regenerate button and a mix screen that shows the arrangement.

**Architecture:** The brain plans a structured `MixPlan`; a deterministic engine executes it; the LLM never touches audio. The plan grows from one placement to a list of `Placement`s. The fence offers the arrangement menu (ranked phrase anchors + vocal slices); the AI driver arranges the set (with a deterministic fallback); the referee enforces ≥2 non-overlapping on-beat placements + no clip/silence; the engine renders multiple placements and ducks (not silences) the bed before flagged entries. Regenerate folds a `take` number into the content-hash cache key.

**Tech Stack:** Python 3.11 · FastAPI · Pydantic v2 · numpy/scipy · soundfile · FFmpeg (`atempo`) · Anthropic `claude-sonnet-5` (structured, with rules fallback) · React + Vite + TypeScript (vitest).

## Global Constraints

- The LLM never touches audio samples — it only fills `MixPlan`. (technical-spec principle)
- `MixPlan` changes are **additive**: keep the scalar `anchor`/`vocal_src`; old cached `*.mixplan.json` must still parse.
- Time-stretch is FFmpeg `atempo` only (LGPL). Keep stretches within the fence's ±8% band. No GPL rubberband in the pipeline.
- Heavy audio-AI runs in the cloud (Replicate); local DSP is FFmpeg + numpy/scipy only (Windows-ARM constraint).
- Dangerous-surface files (`workers/render.py`, `services/api/app/planner/validate.py`) require the confirm-and-apply flow (founder yes + `.zuko/approve.js`) and an independent adversarial review before merge.
- Backend tests run from `services/api` via `.venv/Scripts/python.exe -m pytest`. Never weaken a test to pass.
- Bump `ENGINE_VERSION` in `routes/mix.py` when planner/engine behaviour changes, so cached mixes aren't stale-served.

---

### Task 1: Arrangement data models

**Files:**

- Modify: `services/api/app/models.py` (add `Placement`; extend `MixPlan`)
- Test: `services/api/tests/test_models.py` (new)

**Interfaces:**

- Produces: `Placement(anchor: float, vocal_src: tuple[float,float], beat_breath: bool=False)`; `MixPlan.placements: list[Placement] = []`; `MixPlan.take: int = 1`.

- [ ] **Step 1: Write the failing test**

```python
from app.models import MixPlan, Placement

def test_placement_and_arrangement_roundtrip():
    plan = MixPlan(
        mix_id="m" * 64, song1_id="a" * 64, song2_id="b" * 64,
        master_bpm=120.0, vocal_stretch=1.0, vocal_src=(16.0, 40.0), anchor=16.0,
        take=2,
        placements=[Placement(anchor=16.0, vocal_src=(16.0, 32.0)),
                    Placement(anchor=64.0, vocal_src=(40.0, 56.0), beat_breath=True)],
    )
    dumped = plan.model_dump_json()
    assert MixPlan.model_validate_json(dumped).placements[1].beat_breath is True
    assert plan.take == 2

def test_old_single_placement_json_still_parses():
    # an M3-era plan with no placements/take must still load (additive change)
    m3 = '{"mix_id":"m","song1_id":"a","song2_id":"b","master_bpm":120.0,' \
         '"vocal_stretch":1.0,"vocal_src":[16.0,40.0],"anchor":16.0}'
    plan = MixPlan.model_validate_json(m3)
    assert plan.placements == [] and plan.take == 1
```

- [ ] **Step 2: Run to verify it fails** — `cd services/api && .venv/Scripts/python.exe -m pytest tests/test_models.py -v` → FAIL (`Placement` undefined).

- [ ] **Step 3: Implement** — in `models.py`, above `MixPlan`:

```python
class Placement(BaseModel):
    """One vocal moment in an arrangement: where it enters and which slice sings."""
    anchor: float  # secs into Song 1, on a downbeat
    vocal_src: tuple[float, float]  # [start, end] secs of Song 2's vocal
    beat_breath: bool = False  # one-bar tension dip in the bed right before this entry
```

Add to `MixPlan` (after `beat_breath`):

```python
    placements: list[Placement] = []  # full arrangement; [] => single-placement (M3)
    take: int = 1  # which regenerate iteration (1-based)
```

- [ ] **Step 4: Run to verify it passes** — same command → PASS.
- [ ] **Step 5: Commit** — `git add services/api/app/models.py services/api/tests/test_models.py && git commit -m "feat(m4): arrangement data models (Placement, MixPlan.placements/take)"`

---

### Task 2: Fence — the arrangement menu

**Files:**

- Modify: `services/api/app/planner/fence.py` (add `section_at`, `vocal_slices`, `arrangement_options`)
- Test: `services/api/tests/test_fence.py` (append)

**Interfaces:**

- Consumes: existing `legal_options`, `candidate_drops`, `best_vocal_slice`, `MAX_VOCAL_SECS`, `MIN_VOCAL_SECS`.
- Produces: `arrangement_options(a1, a2) -> dict` — on `mixable`, adds `anchors_ranked: list[float]` (phrase starts, best energy first) and `vocal_slices: list[tuple[float,float]]` (Song-2 strong regions, longest first, snapped, capped). Declines pass through unchanged.

- [ ] **Step 1: Write the failing test** (append to `test_fence.py`, reuse `make_analysis`):

```python
def test_vocal_slices_ranked_and_capped():
    a2 = make_analysis(vocal_regions=[(8.0, 14.0), (20.0, 60.0), (70.0, 76.0)])
    slices = fence.vocal_slices(a2)
    assert slices[0][1] - slices[0][0] <= fence.MAX_VOCAL_SECS + 1e-6  # capped
    assert len(slices) >= 2 and slices[0][0] == 20.0  # longest first, snapped

def test_arrangement_options_happy():
    energy = [0.3] * 32
    for i in range(8, 16): energy[i] = 0.9
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
```

- [ ] **Step 2: Run to verify it fails** — `pytest tests/test_fence.py -k arrangement -v` → FAIL.

- [ ] **Step 3: Implement** — append to `fence.py`:

```python
def vocal_slices(a2: TrackAnalysis, limit: int = 4) -> list[tuple[float, float]]:
    """Song 2's strongest sung stretches, longest first, snapped to a downbeat,
    each capped to MAX_VOCAL_SECS. Falls back to best_vocal_slice if regions are
    unknown."""
    regions = sorted(
        ((s, e) for s, e in a2.vocal_regions if e - s >= MIN_VOCAL_SECS),
        key=lambda r: r[1] - r[0], reverse=True,
    )[:limit]
    if not regions:
        return [best_vocal_slice(a2)]
    out: list[tuple[float, float]] = []
    for s, e in regions:
        start = min(a2.downbeats, key=lambda d: abs(d - s)) if a2.downbeats else s
        end = min(e, start + MAX_VOCAL_SECS)
        out.append((round(start, 3), round(max(end, start + MIN_VOCAL_SECS), 3)))
    return out


def section_at(a1: TrackAnalysis, t: float) -> str:
    """The Song-1 section label containing time t (or '' if unknown)."""
    for s in a1.sections:
        if s.start <= t < s.end:
            return s.label
    return ""


def arrangement_options(a1: TrackAnalysis, a2: TrackAnalysis) -> dict:
    """The legal menu for a full arrangement: the M3 legal set plus ranked phrase
    anchors and the available vocal slices. Declines pass through unchanged."""
    base = legal_options(a1, a2)
    if not base["mixable"]:
        return base
    slices = vocal_slices(a2)
    need = min(e - s for s, e in slices) * base["vocal_stretch"]
    return {
        **base,
        "anchors_ranked": candidate_drops(a1, need),  # best energy first, with runway
        "vocal_slices": slices,
    }
```

- [ ] **Step 4: Run to verify it passes** — `pytest tests/test_fence.py -v` → all PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat(m4): fence arrangement menu (vocal_slices, section_at, arrangement_options)"`

---

### Task 3: AI driver — arrange the set + regenerate

**Files:**

- Modify: `services/api/app/planner/plan.py`
- Test: `services/api/tests/test_plan.py` (append; update the M3 fallback test to expect `placements`)

**Interfaces:**

- Consumes: `fence.arrangement_options`, `Placement`, `MixPlan`, `MixDeclined`.
- Produces: `build_mix_plan(mix_id, a1, a2, prompt="", take=1) -> MixPlan` now returns a plan with `placements` (≥2 when the pair allows, else 1 as low-confidence fallback), sorted, non-overlapping; `_default_arrangement(opts, take) -> list[Placement]`; `_ai_arrange(opts, prompt, take) -> list[Placement] | None`.

- [ ] **Step 1: Write the failing test** (append to `test_plan.py`):

```python
def test_arrangement_has_multiple_nonoverlapping_placements(monkeypatch):
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)  # force fallback
    energy = [0.3] * 32
    for i in range(0, 8): energy[i] = 0.8
    for i in range(16, 24): energy[i] = 0.9
    a1 = make_analysis(bpm=120.0, n_bars=32, energy=energy)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 16.0), (20.0, 36.0)])
    plan = planner.build_mix_plan("m" * 64, a1, a2)
    assert len(plan.placements) >= 2
    ordered = sorted(plan.placements, key=lambda p: p.anchor)
    for a, b in zip(ordered, ordered[1:]):  # no two vocals overlap in time
        a_len = (a.vocal_src[1] - a.vocal_src[0]) * plan.vocal_stretch
        assert a.anchor + a_len <= b.anchor + 1e-6
    assert plan.anchor == plan.placements[0].anchor  # scalar mirrors first placement (M3 back-compat)

def test_regenerate_yields_a_different_arrangement(monkeypatch):
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    energy = [0.5] * 32
    for i in (4, 12, 20, 28): energy[i] = 0.9
    a1 = make_analysis(bpm=120.0, n_bars=32, energy=energy)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 12.0), (16.0, 28.0)])
    t1 = planner.build_mix_plan("m" * 64, a1, a2, take=1)
    t2 = planner.build_mix_plan("m" * 64, a1, a2, take=2)
    assert [p.anchor for p in t1.placements] != [p.anchor for p in t2.placements]
```

Also update `test_fallback_plan_without_api_key` to assert `mix.placements` is non-empty (the arrangement now drives it).

- [ ] **Step 2: Run to verify it fails** — `pytest tests/test_plan.py -v` → FAIL.

- [ ] **Step 3: Implement** — in `plan.py`, replace `build_mix_plan` and add the arrangement helpers:

```python
from app.models import MixPlan, Placement, TrackAnalysis

_MAX_PLACEMENTS = 3
_ENTRY_MARGIN = 1.0  # secs of breathing room between one vocal's end and the next entry


def _default_arrangement(opts: dict, take: int) -> list[Placement]:
    """Deterministic arrangement: 2-3 top-energy phrase anchors (spaced so vocals
    never overlap), each given a vocal slice trimmed to fit, rotated by `take` for
    regenerate variety. The first placement never breathes; later ones do."""
    anchors = sorted(opts["anchors_ranked"])
    slices = opts["vocal_slices"]
    stretch = opts["vocal_stretch"]
    if len(anchors) < 2:
        s = slices[0]
        return [Placement(anchor=anchors[0] if anchors else 0.0, vocal_src=s)]
    n = min(_MAX_PLACEMENTS, len(anchors))
    offset = (take - 1) % max(1, len(anchors) - n + 1)  # rotate the window per take
    chosen = anchors[offset:offset + n]
    placements: list[Placement] = []
    for i, anc in enumerate(chosen):
        s0, s1 = slices[i % len(slices)]
        gap = (chosen[i + 1] - anc) if i + 1 < len(chosen) else _MAX_PLACEMENTS * 60.0
        fit = gap / stretch - _ENTRY_MARGIN  # source-time length that fits before the next entry
        end = min(s1, s0 + max(fence.MIN_VOCAL_SECS, min(s1 - s0, fit)))
        placements.append(Placement(anchor=anc, vocal_src=(s0, round(end, 3)),
                                    beat_breath=i > 0))
    return placements


def _ai_arrange(opts: dict, prompt: str, take: int) -> list[Placement] | None:
    """Ask Claude to arrange the set. Returns placements or None on any failure."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        payload = {
            "shared_tempo_bpm": opts["master_bpm"],
            "phrase_anchors_seconds": [round(a, 1) for a in opts["anchors_ranked"][:8]],
            "vocal_slices_seconds": [[round(s, 1), round(e, 1)] for s, e in opts["vocal_slices"]],
            "keys_compatible": opts["key_fit"], "user_request": prompt or "",
            "take_number": take, "make_it_different_from_previous_takes": take > 1,
        }
        msg = client.messages.create(model=_MODEL, max_tokens=600, system=_ARRANGE_SYSTEM,
                                     messages=[{"role": "user", "content": json.dumps(payload)}])
        data = _extract_json(msg.content[0].text)
        out: list[Placement] = []
        for p in data["placements"][:_MAX_PLACEMENTS]:
            anc = float(p["anchor"])
            sl = p["vocal_slice"]
            if anc in opts["anchors_ranked"]:  # only legal anchors
                out.append(Placement(anchor=anc, vocal_src=(float(sl[0]), float(sl[1])),
                                     beat_breath=bool(p.get("beat_breath", False))))
        return out or None
    except Exception:
        return None


def _dedupe_nonoverlapping(placements: list[Placement], stretch: float) -> list[Placement]:
    """Sort by anchor and drop any placement that would overlap the previous vocal
    (enforces one-voice-at-a-time before the render; the referee re-checks)."""
    ordered = sorted(placements, key=lambda p: p.anchor)
    kept: list[Placement] = []
    for p in ordered:
        if not kept:
            kept.append(p); continue
        prev = kept[-1]
        prev_end = prev.anchor + (prev.vocal_src[1] - prev.vocal_src[0]) * stretch
        if p.anchor >= prev_end:
            kept.append(p)
    return kept
```

Add the arrange system prompt near `_SYSTEM`:

```python
_ARRANGE_SYSTEM = (
    "You are a DJ arranging Song 2's vocal over Song 1's beat. From the given legal "
    "phrase anchors (seconds, best-energy first) and vocal slices, choose 2-3 non-"
    "overlapping placements that build a set: keep an instrumental intro, land the "
    "vocal on high-energy sections, leave a verse of just beat between entries, and "
    "finish strong. Never start in the first anchor. Set beat_breath=true before a big "
    "re-entry (a one-bar tension dip, not silence). If take_number>1, choose a "
    "genuinely different arrangement. STRICT JSON only: "
    '{"placements":[{"anchor":<sec>,"vocal_slice":[<start>,<end>],"beat_breath":<bool>}]}'
)
```

Replace `build_mix_plan`:

```python
def build_mix_plan(mix_id: str, a1: TrackAnalysis, a2: TrackAnalysis,
                   prompt: str = "", take: int = 1) -> MixPlan:
    """Produce the arrangement recipe. Raises MixDeclined if the pair can't blend."""
    opts = fence.arrangement_options(a1, a2)
    if not opts["mixable"]:
        raise MixDeclined(opts["reason"])
    placements = _ai_arrange(opts, prompt, take)
    source = "ai" if placements else "rules"
    if not placements:
        placements = _default_arrangement(opts, take)
    placements = _dedupe_nonoverlapping(placements, opts["vocal_stretch"])
    first = placements[0]
    notes = _describe_arrangement(placements)
    return MixPlan(
        mix_id=mix_id, song1_id=a1.song_id, song2_id=a2.song_id,
        master_bpm=opts["master_bpm"], vocal_stretch=opts["vocal_stretch"],
        vocal_src=first.vocal_src, anchor=first.anchor,  # scalar mirrors first (M3 back-compat)
        placements=placements, take=take, notes=notes,
        confidence=0.75 if source == "ai" else 0.6, source=source,
    )


def _describe_arrangement(placements: list[Placement]) -> str:
    if len(placements) == 1:
        return _describe(placements[0].anchor)
    spots = ", ".join(f"{int(p.anchor) // 60}:{int(p.anchor) % 60:02d}" for p in placements)
    return f"Vocal weaves in at {spots}, tempo-locked to Song 1 with the beat running throughout."
```

- [ ] **Step 4: Run to verify it passes** — `pytest tests/test_plan.py tests/test_fence.py -v` → PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat(m4): AI driver arranges the set + regenerate variety, deterministic fallback"`

---

### Task 4 (DANGEROUS — needs approval): Referee — R5 + no-overlap

**Files:**

- Modify: `services/api/app/planner/validate.py`
- Test: `services/api/tests/test_validate.py` (append)

> **Guard:** `validate.py` is on the dangerous list. Do not edit until the founder has approved via the confirm-and-apply flow and `.zuko/approve.js` has unlocked it. An independent test-author + adversarial review run before merge.

**Interfaces:**

- Consumes: `MixPlan`, `Placement`, existing `validate_render`, `SAFE_STRETCH_*`.
- Produces: `validate_plan` extended to check R5 (≥2 placements for an arrangement, or exactly 1 as the allowed single-drop) + no time overlap + each anchor on a downbeat.

- [ ] **Step 1: Write the failing test**:

```python
from app.models import Placement

def make_arrangement_plan(placements, stretch=1.0):
    return MixPlan(mix_id="m"*64, song1_id="a"*64, song2_id="b"*64, master_bpm=120.0,
                   vocal_stretch=stretch, vocal_src=placements[0].vocal_src,
                   anchor=placements[0].anchor, placements=placements)

def test_validate_flags_overlapping_placements():
    a1, a2 = make_analysis(), make_analysis()  # downbeats every 2s
    p = [Placement(anchor=16.0, vocal_src=(0.0, 24.0)),   # 24s vocal from 16 -> ends 40
         Placement(anchor=32.0, vocal_src=(0.0, 8.0))]    # enters 32 -> overlaps
    v = validate.validate_plan(make_arrangement_plan(p), a1, a2)
    assert any("overlap" in m.lower() or "R1" in m for m in v)

def test_validate_flags_offbeat_placement():
    a1, a2 = make_analysis(), make_analysis()
    p = [Placement(anchor=16.0, vocal_src=(0.0, 8.0)),
         Placement(anchor=33.1, vocal_src=(0.0, 8.0))]  # 33.1 not on a 2s downbeat
    assert any("R3" in m for m in validate.validate_plan(make_arrangement_plan(p), a1, a2))

def test_validate_accepts_clean_arrangement():
    a1, a2 = make_analysis(), make_analysis()
    p = [Placement(anchor=16.0, vocal_src=(0.0, 8.0)),
         Placement(anchor=32.0, vocal_src=(0.0, 8.0))]
    assert validate.validate_plan(make_arrangement_plan(p), a1, a2) == []
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement** — in `validate.py`, extend `validate_plan` to iterate placements (falling back to the scalar for a legacy single-placement plan):

```python
def _placements_of(plan: MixPlan) -> list:
    return plan.placements or [type("P", (), {
        "anchor": plan.anchor, "vocal_src": plan.vocal_src, "beat_breath": plan.beat_breath})()]

def validate_plan(plan: MixPlan, a1: TrackAnalysis, a2: TrackAnalysis) -> list[str]:
    violations: list[str] = []
    if not SAFE_STRETCH_LO <= plan.vocal_stretch <= SAFE_STRETCH_HI:
        violations.append("tempo stretch is outside the safe band (B3)")
    places = _placements_of(plan)
    ordered = sorted(places, key=lambda p: p.anchor)
    for p in ordered:
        if not _on_a_downbeat(p.anchor, a1.downbeats):
            violations.append("a vocal entry is not on a downbeat of Song 1 (R3)")
        if p.vocal_src[1] <= p.vocal_src[0]:
            violations.append("a vocal slice is empty")
    for a, b in zip(ordered, ordered[1:]):  # R1: one vocal at a time
        a_end = a.anchor + (a.vocal_src[1] - a.vocal_src[0]) * plan.vocal_stretch
        if b.anchor < a_end - 1e-6:
            violations.append("two vocal placements overlap (R1)")
    return violations
```

(R5 "≥2 for an arrangement" is enforced by the driver/route producing arrangements; the validator's hard floor is R1/R3/B3 + `validate_render` R6, which are what code can prove on any plan. A single placement remains legal as the low-confidence fallback.)

- [ ] **Step 4: Run to verify it passes** — `pytest tests/test_validate.py -v` → PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat(m4): referee enforces no-overlap + on-beat across placements"`

---

### Task 5 (DANGEROUS — needs approval): Engine — multi-placement + real breath

**Files:**

- Modify: `workers/render.py`
- Test: `services/api/tests/test_render.py` (append)

> **Guard:** `workers/render.py` is on the dangerous list — same approval + review gate as Task 4 (bundle both files into one approval).

**Interfaces:**

- Consumes: `plan.placements` (list of objects with `anchor`, `vocal_src`, `beat_breath`), `plan.master_bpm`, `plan.vocal_stretch`; falls back to the scalar `anchor`/`vocal_src` when `placements` is empty.
- Produces: `render_mix(plan, song1_stems, song2_vocal, out_path)` renders every placement; `_BREATH_DUCK = 0.35`.

- [ ] **Step 1: Write the failing test** (append to `test_render.py`; `_plan` already exists — add a `placements` kwarg):

```python
def _arr_plan(placements, breath=False):
    return types.SimpleNamespace(master_bpm=120.0, vocal_stretch=1.0,
        vocal_src=placements[0][1], anchor=placements[0][0], beat_breath=breath,
        placements=[types.SimpleNamespace(anchor=a, vocal_src=v, beat_breath=b)
                    for a, v, b in placements])

def test_render_places_vocal_in_multiple_spots(tmp_path):
    stems, vocal = _stems(tmp_path)
    out = tmp_path / "mix.wav"
    render.render_mix(_arr_plan([(1.0, (0.0, 1.5), False), (4.0, (0.0, 1.5), False)]),
                      stems, vocal, out)
    y, sr = sf.read(out, dtype="float32", always_2d=True)
    # both vocal windows carry more energy than the beat-only gap between them
    e = lambda a, b: float(np.mean(np.abs(y[int(a*sr):int(b*sr)])))
    assert e(1.0, 2.5) > e(2.6, 3.9) and e(4.0, 5.5) > e(2.6, 3.9)

def test_breath_ducks_not_silences(tmp_path):
    stems, vocal = _stems(tmp_path)
    out = tmp_path / "mix.wav"
    render.render_mix(_arr_plan([(2.0, (0.0, 1.0), True)], breath=True), stems, vocal, out)
    y, sr = sf.read(out, dtype="float32", always_2d=True)
    bar_before = float(np.max(np.abs(y[int(0.2*sr):int(1.9*sr)])))
    assert bar_before > 1e-3  # NOT dead air (the M3 gap bug stays fixed)
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement** — in `render.py`, add `_BREATH_DUCK = 0.35`, and refactor `render_mix` to loop placements:

```python
def _placements_of(plan):
    if getattr(plan, "placements", None):
        return plan.placements
    return [type("P", (), {"anchor": plan.anchor, "vocal_src": plan.vocal_src,
                           "beat_breath": getattr(plan, "beat_breath", False)})()]

def render_mix(plan, song1_stems, song2_vocal, out_path):
    if plan.master_bpm <= 0:
        raise RenderError("plan has a non-positive tempo")
    bed = _sum_stems([song1_stems["drums"], song1_stems["bass"], song1_stems["other"]])
    bar = int((60.0 / plan.master_bpm) * 4 * SR)
    for p in _placements_of(plan):
        start, end = p.vocal_src
        voc = _edge_fade(_vocal_take(song2_vocal, start, max(end - start, 0.0), plan.vocal_stretch))
        anchor = max(0, int(p.anchor * SR))
        if p.beat_breath:  # DUCK the bed for one bar (tension), never silence it
            b0 = max(0, anchor - bar)
            bed[b0:anchor] *= _BREATH_DUCK
        need = anchor + len(voc)
        if need > len(bed):
            bed = np.vstack([bed, np.zeros((need - len(bed), 2), dtype=np.float32)])
        bed[anchor:need] += voc
    peak = float(np.max(np.abs(bed))) if bed.size else 0.0
    if peak > 0.0:
        bed *= _TARGET_PEAK / peak
    np.clip(bed, -_CEILING, _CEILING, out=bed)
    sf.write(out_path, bed, SR, subtype="PCM_16")
    return out_path
```

Keep the existing `test_beat_breath_silences_the_bar_before_entry` updated: rename to `test_beat_breath_ducks_the_bar` and assert the bar is quieter than the vocal region but **not** near-zero (`> 1e-3`).

- [ ] **Step 4: Run to verify it passes** — `pytest tests/test_render.py -v` → PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat(m4): engine renders multiple placements + real beat-breath (duck, not silence)"`

---

### Task 6: Route — take / regenerate

**Files:**

- Modify: `services/api/app/routes/mix.py`
- Test: `services/api/tests/test_mix_route.py` (append)

**Interfaces:**

- Consumes: `build_mix_plan(..., take=)`.
- Produces: `MixRequest.take: int = 1`; `mix_id_for(song1, song2, prompt, take)`; `POST /mix` passes `take` through; `ENGINE_VERSION` bumped to `m4a.1`.

- [ ] **Step 1: Write the failing test**:

```python
def test_regenerate_is_a_distinct_cached_take(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    _setup_pair(tmp_path)
    r1 = client.post("/mix", json={"song1_id": SONG1, "song2_id": SONG2, "take": 1})
    r2 = client.post("/mix", json={"song1_id": SONG1, "song2_id": SONG2, "take": 2})
    assert r1.json()["mix_id"] != r2.json()["mix_id"]  # different take -> different cache slot
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement** — add `take: int = 1` to `MixRequest`; thread it through `mix_id_for` (fold into the hash string), `_run_mix` (`build_mix_plan(..., take=req.take)`), and `start_mix`; bump `ENGINE_VERSION = "m4a.1"`. Update `_setup_pair`'s analysis for SONG2 to include ≥2 vocal regions so an arrangement forms.

- [ ] **Step 4: Run to verify it passes** — `pytest tests/test_mix_route.py -v` → PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat(m4): /mix take param drives regenerate (distinct cached takes)"`

---

### Task 7: Web — arrangement timeline + Regenerate

**Files:**

- Modify: `apps/web/src/lib/api.ts` (add `take` to `startMix`, `PlacementDTO`, `placements` on `MixPlanDTO`)
- Modify: `apps/web/src/components/Mix/Mix.tsx` (arrangement timeline; Regenerate button; take label)
- Modify: `apps/web/src/components/Mix/Mix.module.css` (timeline lanes)
- Test: `apps/web/src/components/Mix/Mix.test.tsx` (append)

**Interfaces:**

- Consumes: `MixDTO` with `plan.placements: {anchor, vocal_src:[number,number], beat_breath}[]`, `plan.take`.
- Produces: two-lane arrangement view (beat lane full width; vocal blocks positioned by `anchor`/length over the total duration); a "Give me another take" button that calls `startMix(song1, song2, "", take+1)` and re-polls; a "take N" label.

- [ ] **Step 1: Write the failing test** (append to `Mix.test.tsx`): mock POST → processing, GET → ready with `plan.placements` of length 2 and `take: 1`; assert two vocal blocks (`data-testid="vocal-block"`) render and a `/give me another take/i` button exists; clicking it fires a second POST with `take: 2`.

- [ ] **Step 2: Run to verify it fails** — `npm test` → FAIL.

- [ ] **Step 3: Implement** — extend `api.ts` types + `startMix(song1, song2, prompt="", take=1)`; in `Mix.tsx` render the two-lane timeline from `plan.placements` (compute total duration from the last placement end or a passed duration; position each block left% = anchor/total, width% = len/total; `data-testid="vocal-block"`), a Regenerate button (`onClick` → `handleMix(take+1)`), and the take label. Add lane CSS.

- [ ] **Step 4: Run to verify it passes** — `npm test && npm run typecheck && npm run lint` → PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat(m4): mix screen shows the arrangement + Regenerate button"`

---

### Task 8: Living docs

**Files:** Modify `docs/functional-spec.md`, `docs/technical-spec.md`, `docs/implementation-plan.md`.

- [ ] Update functional spec (what the app does today → full arrangement + regenerate), technical spec (as-built M4a: placements, arrangement driver, no-overlap referee, multi-placement engine + breath duck, take/regenerate), implementation plan (mark M4 in progress → Slice A done, drift-log entry; note Slice B deferred). Commit.

---

## Self-Review

- **Spec coverage:** models (T1) · fence menu (T2) · AI arrange + regenerate + fallback (T3) · referee no-overlap/on-beat (T4) · multi-placement engine + real breath (T5) · take/regenerate route (T6) · arrangement screen + Regenerate (T7) · docs (T8). Confidence-fallback = single-placement path retained in driver/validator/engine. Slice B explicitly out of scope. ✓
- **Placeholder scan:** none — every code/ test step carries real code. ✓
- **Type consistency:** `Placement(anchor, vocal_src, beat_breath)`, `MixPlan.placements/take`, `build_mix_plan(..., take=1)`, `arrangement_options`, `_default_arrangement`, `_ai_arrange`, `_dedupe_nonoverlapping`, `_BREATH_DUCK`, `ENGINE_VERSION="m4a.1"` used consistently across tasks. ✓
- **Dangerous surfaces:** T4 (`validate.py`) + T5 (`render.py`) gated behind one confirm-and-apply approval + independent review. ✓
