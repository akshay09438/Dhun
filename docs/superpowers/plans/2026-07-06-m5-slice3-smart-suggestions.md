# M5 Slice 3 — AI smart-suggestion buttons + "fade away" — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** As the mix plays, show 1–3 context-aware suggestion chips that change with the song's sections and apply on the beat when tapped; plus the "fade away" move.

**Architecture:** A new backend module (`planner/suggest.py`) asks Claude — with a deterministic label→chip fallback — for 1–3 moves per Song-1 section, drawn only from a **closed vocabulary** the live engine already executes; served (cached) by a new route. The browser fetches them, tracks the playhead, shows the current section's chips, and applies a tapped chip through Slice 2's on-beat path. A new `"fade"` op ramps all parts to silence over ~4 bars.

**Tech Stack:** FastAPI + Pydantic v2, Anthropic SDK (pure-Python; same pattern as `planner/plan.py`); React + TypeScript + Vitest, raw Web Audio API.

## Global Constraints

- **Never edit the dangerous engine/guard:** `workers/render.py`, `workers/live_stems.py`(reused, not edited), `services/api/app/planner/validate.py`, `**/storage.py`, `routes/songs.py`, config are OUT of scope.
- **Web test files (`apps/web/**/*.test.ts`) are protected** — adding them needs the founder confirm-and-apply flow (`.zuko/approve.js`). Backend `test_*.py` are NOT guarded. This slice edits **two** protected files: `liveSchedule.test.ts` (Task 4), `api.test.ts` (Task 5). `LiveMix.test.tsx` is NOT edited (its existing test stays a regression).
- **Closed vocabulary (verbatim chip text → op/targets):** `Bring the vocal in`→unmute[vocals]; `Take the vocal out`→mute[vocals]; `Take the bass out`→mute[bass]; `Drop to just the beat`→mute[bass,other,vocals]; `Bring it all back`→unmute[drums,bass,other,vocals]; `Fade it out`→fade[drums,bass,other,vocals]. The AI may pick ONLY these; unknown chips are dropped.
- **The AI never touches audio** and runs **once per mix, cached** — never per-beat. Any AI failure → deterministic fallback. Mirrors `planner/plan.py`.
- **User stays in control:** chips only suggest; the four part buttons + typed commands are unchanged. No partial-volume machinery — chips use only full mute/unmute/fade.
- **Additive only:** new models + a new `"fade"` op value; existing `LiveOp`/`LiveOpDTO`/parser/player/`applyOp` behavior unchanged for existing ops.
- **Invariants:** every move fires on the next bar; the music never fully stops (fade ramps toward 0, playback continues).
- Backend tests: from `services/api`, `./.venv/Scripts/python.exe -m pytest -q`. Web: from repo root, `npm test`, `npm run typecheck`, `npm run lint`.
- **Tests must never call the real Anthropic API:** monkeypatch `app.planner.suggest._ai_suggest` (return None for fallback tests, a dict for AI tests). Never rely on the ambient `ANTHROPIC_API_KEY`.

---

### Task 1: `LiveChip`/`SectionSuggestions` models + "fade away" parser

**Files:**

- Modify: `services/api/app/models.py` (add two models)
- Modify: `services/api/app/planner/live.py` (add the fade branch)
- Test: `services/api/tests/test_live.py` (append; NOT guarded)

**Interfaces:**

- Produces: `LiveChip{text:str, op:str, targets:list[str]}`, `SectionSuggestions{start:float, end:float, label:str, chips:list[LiveChip]}`; `parse_command("fade away") -> LiveOp(op="fade", targets=[all four])`.

- [ ] **Step 1: Write the failing test** — append to `services/api/tests/test_live.py`:

```python
def test_fade_away_is_a_fade_of_everything():
    op = parse_command("fade away")
    assert op.op == "fade" and set(op.targets) == {"drums", "bass", "other", "vocals"}


def test_fade_it_out_synonym():
    assert parse_command("fade it out").op == "fade"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd services/api && ./.venv/Scripts/python.exe -m pytest tests/test_live.py -q`
Expected: FAIL — "fade away" currently hits the out-of-scope decline.

- [ ] **Step 3: Add the models** — append to `services/api/app/models.py`:

```python
class LiveChip(BaseModel):
    """One tappable live suggestion: display text + the move it applies (from the closed
    vocabulary). op is "mute" | "unmute" | "fade"; targets are bus names."""

    text: str
    op: str
    targets: list[str] = []


class SectionSuggestions(BaseModel):
    """The 1-3 suggested moves for one section of Song 1's timeline."""

    start: float
    end: float
    label: str
    chips: list[LiveChip] = []
```

- [ ] **Step 4: Add the fade branch** — in `services/api/app/planner/live.py`, add the phrase tuple near the other tuples (after `_UNMUTE_GENERIC`):

```python
_FADE = ("fade away", "fade it out", "fade out", "fade the mix out", "fade the music out")
```

Then, inside `parse_command`, add this branch immediately after the empty-text check (before the combos), so "fade" is handled first:

```python
    if any(p in t for p in _FADE):
        return LiveOp(op="fade", targets=list(_ALL), say="fading the whole mix out")
```

(`_ALL = ["drums", "bass", "other", "vocals"]` already exists at module top.)

- [ ] **Step 5: Run to verify it passes**

Run: `cd services/api && ./.venv/Scripts/python.exe -m pytest tests/test_live.py -q`
Expected: PASS (all prior live-parser cases + the 2 new). The models import cleanly (a quick `./.venv/Scripts/python.exe -c "from app.models import LiveChip, SectionSuggestions"` should exit 0).

- [ ] **Step 6: Commit**

```bash
git add services/api/app/models.py services/api/app/planner/live.py services/api/tests/test_live.py
git commit -m "feat(m5): LiveChip/SectionSuggestions models + 'fade away' parser"
```

---

### Task 2: `suggest_moves` — per-section chips (AI + deterministic fallback)

**Files:**

- Create: `services/api/app/planner/suggest.py`
- Test: `services/api/tests/test_suggest.py` (NOT guarded)

**Interfaces:**

- Consumes: `LiveChip`, `SectionSuggestions`, `TrackAnalysis` (Task 1 + existing).
- Produces: `suggest_moves(a1: TrackAnalysis, prompt: str = "") -> list[SectionSuggestions]`; module-level `_ai_suggest(sections, prompt) -> dict[int, list[str]] | None` (monkeypatch target in tests); `_VOCAB` mapping.

- [ ] **Step 1: Write the failing test** — create `services/api/tests/test_suggest.py`:

```python
from app.models import Section, TrackAnalysis
from app.planner import suggest
from app.planner.suggest import suggest_moves


def _analysis(labels):
    secs = [Section(start=float(i * 30), end=float((i + 1) * 30), label=lbl)
            for i, lbl in enumerate(labels)]
    return TrackAnalysis(song_id="a" * 64, status="ready", sections=secs)


def test_fallback_maps_labels_to_vocabulary_chips(monkeypatch):
    monkeypatch.setattr(suggest, "_ai_suggest", lambda *a, **k: None)  # no AI -> fallback
    out = suggest_moves(_analysis(["intro", "chorus", "verse", "outro"]))
    assert [s.label for s in out] == ["intro", "chorus", "verse", "outro"]
    # every chip is from the closed vocabulary, 1-3 per section
    for s in out:
        assert 1 <= len(s.chips) <= 3
        for c in s.chips:
            assert c.text in suggest._VOCAB
            assert (c.op, c.targets) == (suggest._VOCAB[c.text][0], list(suggest._VOCAB[c.text][1]))
    # outro suggests the fade
    assert any(c.op == "fade" for c in out[-1].chips)
    # chorus suggests bringing the vocal in
    assert any(c.text == "Bring the vocal in" for c in out[1].chips)


def test_no_sections_gives_one_default_section(monkeypatch):
    monkeypatch.setattr(suggest, "_ai_suggest", lambda *a, **k: None)
    out = suggest_moves(TrackAnalysis(song_id="a" * 64, status="ready", sections=[]))
    assert len(out) == 1 and out[0].chips  # a single default section with default chips


def test_ai_chips_used_and_unknown_dropped(monkeypatch):
    # AI returns a good chip for section 0 and an off-menu chip that must be dropped.
    monkeypatch.setattr(suggest, "_ai_suggest",
                        lambda *a, **k: {0: ["Bring the vocal in", "Teleport the drums"]})
    out = suggest_moves(_analysis(["intro", "outro"]))
    texts0 = [c.text for c in out[0].chips]
    assert "Bring the vocal in" in texts0 and "Teleport the drums" not in texts0
    assert out[1].chips  # section 1 (no AI entry) falls back, still non-empty
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd services/api && ./.venv/Scripts/python.exe -m pytest tests/test_suggest.py -q`
Expected: FAIL — `ModuleNotFoundError: app.planner.suggest`.

- [ ] **Step 3: Create `services/api/app/planner/suggest.py`**

```python
"""Per-section live suggestion chips.

For each of Song 1's sections, propose 1-3 live moves that fit that part of the song —
chosen ONLY from a closed vocabulary the live engine already executes (mute/unmute a part,
drop-to-the-beat, bring-it-all-back, fade). Claude picks; a deterministic label->chips
fallback runs on any AI failure, so suggestions work with no API key. One call per mix
(the route caches the result). Never touches audio — mirrors planner.plan's LLM-plans /
rules-fallback shape.
"""

from __future__ import annotations

import json
import os

from app.models import LiveChip, SectionSuggestions, TrackAnalysis

_MODEL = "claude-sonnet-5"
_MAX_CHIPS = 3

# The closed vocabulary: chip text -> (op, targets). The brain may pick ONLY these.
_VOCAB: dict[str, tuple[str, list[str]]] = {
    "Bring the vocal in": ("unmute", ["vocals"]),
    "Take the vocal out": ("mute", ["vocals"]),
    "Take the bass out": ("mute", ["bass"]),
    "Drop to just the beat": ("mute", ["bass", "other", "vocals"]),
    "Bring it all back": ("unmute", ["drums", "bass", "other", "vocals"]),
    "Fade it out": ("fade", ["drums", "bass", "other", "vocals"]),
}
_DEFAULT_TEXTS = ["Drop to just the beat", "Bring it all back", "Fade it out"]

_SUGGEST_SYSTEM = (
    "You are a DJ suggesting live moves for a playing mix, section by section. For EACH "
    "section index, choose 1-3 moves that fit that part of the song, using ONLY this exact "
    "menu (copy the text verbatim): 'Bring the vocal in', 'Take the vocal out', 'Take the "
    "bass out', 'Drop to just the beat', 'Bring it all back', 'Fade it out'. Suit the move "
    "to the part: introduce/build in intros and choruses, strip back in breakdowns, fade in "
    "the outro. STRICT JSON only, nothing else: "
    '{"sections":{"<index>":["<move text>", ...]}}'
)


def _chip(text: str) -> LiveChip:
    op, targets = _VOCAB[text]
    return LiveChip(text=text, op=op, targets=list(targets))


def _fallback_texts(label: str) -> list[str]:
    """Deterministic label -> chip texts (the fallback, and the AI's menu framing)."""
    l = label.lower()
    if "intro" in l or "start" in l:
        return ["Bring the vocal in", "Drop to just the beat"]
    if "chorus" in l:
        return ["Bring the vocal in", "Bring it all back"]
    if "verse" in l:
        return ["Take the bass out", "Drop to just the beat"]
    if "bridge" in l or "break" in l:
        return ["Drop to just the beat", "Take the vocal out"]
    if "outro" in l or "end" in l:
        return ["Fade it out", "Bring it all back"]
    return ["Drop to just the beat", "Bring it all back"]


def _sections_of(a1: TrackAnalysis) -> list[tuple[float, float, str]]:
    secs = [(float(s.start), float(s.end), s.label) for s in a1.sections]
    if not secs:  # thin/absent structure -> one default section spanning the track
        return [(0.0, 1.0e9, "track")]
    return secs


def _extract_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model output")
    return json.loads(text[start : end + 1])


def _ai_suggest(sections: list[tuple[float, float, str]], prompt: str) -> dict[int, list[str]] | None:
    """Ask Claude for per-section chip texts. Returns {section_index: [text, ...]} with only
    known-vocabulary texts kept, or None on any failure (caller then uses the fallback)."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=key)
        payload = {
            "sections": [{"index": i, "label": lbl, "start": round(s0, 1)}
                         for i, (s0, _s1, lbl) in enumerate(sections)],
            "menu": list(_VOCAB.keys()),
            "user_request": prompt or "",
        }
        msg = client.messages.create(
            model=_MODEL, max_tokens=600, system=_SUGGEST_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload)}],
        )
        raw = _extract_json(msg.content[0].text).get("sections", {})
        result: dict[int, list[str]] = {}
        for k, texts in raw.items():
            try:
                idx = int(k)
            except (TypeError, ValueError):
                continue
            kept = [t for t in texts if t in _VOCAB][:_MAX_CHIPS]
            if kept:
                result[idx] = kept
        return result or None
    except Exception:
        return None


def suggest_moves(a1: TrackAnalysis, prompt: str = "") -> list[SectionSuggestions]:
    """1-3 suggestion chips per Song-1 section, AI-picked with a deterministic fallback."""
    sections = _sections_of(a1)
    ai = _ai_suggest(sections, prompt) or {}
    out: list[SectionSuggestions] = []
    for i, (s0, s1, label) in enumerate(sections):
        texts = ai.get(i) or (_fallback_texts(label) if a1.sections else _DEFAULT_TEXTS)
        chips = [_chip(t) for t in texts if t in _VOCAB][:_MAX_CHIPS]
        if not chips:  # guard: never emit an empty section
            chips = [_chip(t) for t in _fallback_texts(label)][:_MAX_CHIPS]
        out.append(SectionSuggestions(start=s0, end=s1, label=label, chips=chips))
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd services/api && ./.venv/Scripts/python.exe -m pytest tests/test_suggest.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add services/api/app/planner/suggest.py services/api/tests/test_suggest.py
git commit -m "feat(m5): suggest_moves — per-section live chips (AI + deterministic fallback)"
```

---

### Task 3: `GET /live/suggestions/{mix_id}` route

**Files:**

- Modify: `services/api/app/routes/live.py`
- Test: `services/api/tests/test_live_route.py` (append; NOT guarded)

**Interfaces:**

- Consumes: `suggest_moves` (Task 2); `MixPlan`, `TrackAnalysis`; `analysis_path`; `settings.data_dir`.
- Produces: `GET /live/suggestions/{mix_id}` → `{"sections": [ {start,end,label,chips:[{text,op,targets}]} ]}`; cached to `{mix_id}.suggestions.json`. 404 bad id; 409 if the mix plan or Song-1 analysis isn't ready.

- [ ] **Step 1: Write the failing tests** — append to `services/api/tests/test_live_route.py` (this file already has `_use_live_tmp`, `HEX`, `client` from the vocal-bus tests):

```python
from app.models import MixPlan
from app.planner import suggest as suggest_mod


def _seed_plan_and_sections(tmp_path, monkeypatch):
    monkeypatch.setattr(suggest_mod, "_ai_suggest", lambda *a, **k: None)  # force fallback, no AI
    plan = MixPlan(mix_id=HEX, song1_id=HEX, song2_id=HEX, master_bpm=120.0,
                   vocal_stretch=1.0, vocal_src=(0.0, 2.0), anchor=1.0)
    (tmp_path / f"{HEX}.mixplan.json").write_text(plan.model_dump_json())
    analysis_path(HEX).write_text(json.dumps(
        {"song_id": HEX, "bpm": 120.0, "downbeats": [], "beats": [], "phrase_starts": [],
         "sections": [{"start": 0.0, "end": 30.0, "label": "intro"},
                      {"start": 30.0, "end": 60.0, "label": "chorus"}],
         "energy_curve": [], "vocal_regions": []}))


def test_suggestions_bad_id_is_404():
    assert client.get("/live/suggestions/nothex").status_code == 404


def test_suggestions_without_a_plan_is_409(monkeypatch, tmp_path):
    _use_live_tmp(monkeypatch, tmp_path)
    assert client.get(f"/live/suggestions/{HEX}").status_code == 409


def test_suggestions_returns_sections_with_vocabulary_chips(monkeypatch, tmp_path):
    _use_live_tmp(monkeypatch, tmp_path)
    _seed_plan_and_sections(tmp_path, monkeypatch)
    r = client.get(f"/live/suggestions/{HEX}")
    assert r.status_code == 200
    secs = r.json()["sections"]
    assert [s["label"] for s in secs] == ["intro", "chorus"]
    known = {"Bring the vocal in", "Take the vocal out", "Take the bass out",
             "Drop to just the beat", "Bring it all back", "Fade it out"}
    for s in secs:
        assert s["chips"] and all(c["text"] in known for c in s["chips"])
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd services/api && ./.venv/Scripts/python.exe -m pytest tests/test_live_route.py -q`
Expected: FAIL — no `/live/suggestions` route.

- [ ] **Step 3: Extend `services/api/app/routes/live.py`** — add `TrackAnalysis` to the models import and import `suggest_moves`:

Change the models import line to:

```python
from app.models import LiveOp, MixPlan, TrackAnalysis
```

Add after the `render_vocal_bus` import block:

```python
from app.planner.suggest import suggest_moves
```

Then add the path helper and route at the end of the file:

```python
def _suggestions_path(mix_id: str):
    return settings.data_dir / f"{mix_id}.suggestions.json"


@router.get("/live/suggestions/{mix_id}")
def live_suggestions(mix_id: str):
    """Per-section suggestion chips for a finished mix. One AI call (cached), fallback-safe."""
    if not _HEX_ID.fullmatch(mix_id):
        raise HTTPException(404, "Not found.")
    cache = _suggestions_path(mix_id)
    if cache.exists():
        return {"sections": json.loads(cache.read_text())}
    plan_file = _mixplan_path(mix_id)
    if not plan_file.exists():
        raise HTTPException(409, "Make the mix first so I can suggest moves.")
    plan = MixPlan(**json.loads(plan_file.read_text()))
    a1p = analysis_path(plan.song1_id)
    if not a1p.exists():
        raise HTTPException(409, "Song 1 hasn't been analyzed yet.")
    a1 = TrackAnalysis(status="ready", **json.loads(a1p.read_text()))
    data = [s.model_dump() for s in suggest_moves(a1)]
    cache.write_text(json.dumps(data))
    return {"sections": data}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd services/api && ./.venv/Scripts/python.exe -m pytest tests/test_live_route.py -q`
Expected: PASS (prior vocal-bus/context/command tests + 3 new).

- [ ] **Step 5: Run the FULL backend suite**

Run: `cd services/api && ./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS — 149 prior + 2 (Task 1) + 3 (Task 2) + 3 (Task 3) = **157 passed**.

- [ ] **Step 6: Commit**

```bash
git add services/api/app/routes/live.py services/api/tests/test_live_route.py
git commit -m "feat(m5): GET /live/suggestions/{mix_id} — per-section chips (cached, fallback-safe)"
```

---

### Task 4: Frontend state — `fade` op + current-section chip picker

**Files:**

- Modify: `apps/web/src/lib/liveSchedule.ts`
- Test: `apps/web/src/lib/liveSchedule.test.ts` — **PROTECTED (confirm-and-apply)**

**Interfaces:**

- Produces: `applyOp` treats `"fade"` as all-named-buses-off; `Chip`/`Section` types; `currentChips(sections, songTime) -> Chip[]`.

- [ ] **Step 1: (Protected write) Add the failing tests** — append to `apps/web/src/lib/liveSchedule.test.ts`:

```typescript
import { currentChips, type Section } from "./liveSchedule";

test("applyOp treats a fade as all named buses off", () => {
  const s = { drums: true, bass: true, other: true, vocals: true };
  const r = applyOp(s, {
    op: "fade",
    target: null,
    targets: ["drums", "bass", "other", "vocals"],
  });
  expect(r).toEqual({ drums: false, bass: false, other: false, vocals: false });
});

test("currentChips picks the section the playhead is in", () => {
  const sections: Section[] = [
    {
      start: 0,
      end: 30,
      label: "intro",
      chips: [{ text: "A", op: "mute", targets: ["bass"] }],
    },
    {
      start: 30,
      end: 60,
      label: "chorus",
      chips: [{ text: "B", op: "unmute", targets: ["vocals"] }],
    },
  ];
  expect(currentChips(sections, 5).map((c) => c.text)).toEqual(["A"]);
  expect(currentChips(sections, 45).map((c) => c.text)).toEqual(["B"]);
  expect(currentChips(sections, 30).map((c) => c.text)).toEqual(["B"]); // boundary belongs to the new section
});

test("currentChips is empty for no sections", () => {
  expect(currentChips([], 10)).toEqual([]);
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npm test -- liveSchedule`
Expected: FAIL — `currentChips` not exported; `applyOp` ignores `"fade"`.

- [ ] **Step 3: Update `apps/web/src/lib/liveSchedule.ts`** — replace `applyOp` and append the chip types + picker:

Replace `applyOp` with:

```typescript
export function applyOp(state: BusState, op: OpLike): BusState {
  if (op.op !== "mute" && op.op !== "unmute" && op.op !== "fade") return state;
  const on = op.op === "unmute"; // mute and fade both settle a bus to off
  const next = { ...state };
  for (const b of busesOf(op)) next[b] = on;
  return next;
}
```

Append at the end of the file:

```typescript
export type Chip = { text: string; op: string; targets: string[] };
export type Section = {
  start: number;
  end: number;
  label: string;
  chips: Chip[];
};

/** The chips for the section the playhead is in: the last section whose start <= songTime
 *  (sections are sorted by start). Empty when there are no sections. */
export function currentChips(sections: Section[], songTime: number): Chip[] {
  let cur: Section | undefined;
  for (const s of sections) {
    if (s.start <= songTime + 1e-6) cur = s;
    else break;
  }
  return cur?.chips ?? [];
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `npm test -- liveSchedule` then `npm run typecheck`
Expected: both PASS (prior liveSchedule tests + 3 new). Existing mute/unmute tests still pass (the fade branch only adds a case).

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/lib/liveSchedule.ts apps/web/src/lib/liveSchedule.test.ts
git commit -m "feat(m5): fade op in applyOp + currentChips section picker"
```

---

### Task 5: Frontend — suggestions fetch + fade ramp in the player

**Files:**

- Modify: `apps/web/src/lib/api.ts` (DTOs + `getSuggestions`; widen `LiveOpDTO.op`)
- Modify: `apps/web/src/lib/liveAudio.ts` (`schedule` handles `"fade"`)
- Test: `apps/web/src/lib/api.test.ts` — **PROTECTED (confirm-and-apply)**

**Interfaces:**

- Consumes: `busesOf` (existing); `GET /live/suggestions/{mixId}` (Task 3).
- Produces: `LiveChipDTO`, `SectionSuggestionsDTO`, `getSuggestions(mixId) -> SectionSuggestionsDTO[]`; `LiveOpDTO.op` includes `"fade"`; `LivePlayer.schedule` ramps a `"fade"` over `FADE_BARS` bars.

- [ ] **Step 1: (Protected write) Add the failing test** — append to `apps/web/src/lib/api.test.ts`:

```typescript
import { getSuggestions } from "./api";

test("getSuggestions returns the sections array", async () => {
  const g = globalThis as unknown as { fetch: typeof fetch };
  const real = g.fetch;
  g.fetch = (async () =>
    new Response(
      JSON.stringify({
        sections: [
          {
            start: 0,
            end: 30,
            label: "intro",
            chips: [{ text: "A", op: "mute", targets: ["bass"] }],
          },
        ],
      }),
      { status: 200 },
    )) as typeof fetch;
  try {
    const secs = await getSuggestions("a".repeat(64));
    expect(secs).toHaveLength(1);
    expect(secs[0].chips[0].text).toBe("A");
  } finally {
    g.fetch = real;
  }
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npm test -- api`
Expected: FAIL — `getSuggestions` not exported.

- [ ] **Step 3: Extend `apps/web/src/lib/api.ts`** — widen the `LiveOpDTO.op` union and add the DTOs + fetch. Change the `LiveOpDTO` type's `op` field to include `"fade"`:

```typescript
export type LiveOpDTO = {
  op: "mute" | "unmute" | "decline" | "fade";
  target: string | null;
  targets?: string[];
  when: string;
  say: string;
  reason: string | null;
};
```

Add near the other live helpers:

```typescript
export type LiveChipDTO = { text: string; op: string; targets: string[] };
export type SectionSuggestionsDTO = {
  start: number;
  end: number;
  label: string;
  chips: LiveChipDTO[];
};

/** Per-section suggestion chips for a finished mix (one cached AI call server-side). */
export async function getSuggestions(
  mixId: string,
): Promise<SectionSuggestionsDTO[]> {
  const res = await fetch(`${API_BASE}/live/suggestions/${mixId}`);
  if (!res.ok) throw new Error("Couldn't load suggestions.");
  const data = await res.json();
  return data.sections ?? [];
}
```

- [ ] **Step 4: Update `apps/web/src/lib/liveAudio.ts`** — make `schedule` handle `"fade"` (longer ramp, all named buses to 0). Add a `FADE_BARS` constant at the top of the file (after the imports):

```typescript
const FADE_BARS = 4; // "fade away" ramps the whole mix out over four bars
```

Replace the `schedule` method with:

```typescript
  /** Schedule a mute/unmute/fade on the next bar, ramped over 1 bar (or FADE_BARS for a
   *  fade), for every named bus. */
  schedule(op: LiveOpDTO, ctx: LiveContextDTO): void {
    if (op.op !== "mute" && op.op !== "unmute" && op.op !== "fade") return;
    const bpm = ctx.bpm ?? 120;
    const barSong = nextBarTime(ctx.downbeats, this.songTime(), bpm);
    const startCtx = this.startCtxTime + barSong; // song time -> ctx time
    const target = op.op === "unmute" ? 1 : 0; // mute and fade both go to 0
    const bars = op.op === "fade" ? FADE_BARS : 1;
    for (const bus of busesOf(op)) {
      const g = this.gains.get(bus);
      if (!g) continue;
      g.gain.cancelScheduledValues(startCtx);
      g.gain.setValueAtTime(g.gain.value, startCtx);
      g.gain.linearRampToValueAtTime(target, startCtx + barSeconds(bpm) * bars);
    }
  }
```

(The `rampTarget` import may now be unused in this file — if `npm run lint` flags it, remove `rampTarget` from the import list in `liveAudio.ts`. Do not touch `liveSchedule.ts`'s `rampTarget` export.)

- [ ] **Step 5: Run to verify it passes**

Run: `npm test -- api` then `npm run typecheck` then `npm run lint`
Expected: all PASS. (The raw Web Audio fade is verified by ear in acceptance, per the design — only `getSuggestions` is unit-tested here.)

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/lib/api.ts apps/web/src/lib/liveAudio.ts apps/web/src/lib/api.test.ts
git commit -m "feat(m5): getSuggestions + fade ramp (4 bars) in the player"
```

---

### Task 6: `LiveMix` — show current-section chips, tap to apply

**Files:**

- Modify: `apps/web/src/components/Live/LiveMix.tsx`
- Modify: `apps/web/src/components/Live/LiveMix.module.css` (chip styles — additive)

_No test-file change: `LiveMix.test.tsx` stays as-is (its four-parts-render assertion is a regression guard; the pure chip logic is covered in Task 4, and the raw-audio UI is ear-verified, per the design)._

**Interfaces:**

- Consumes: `getSuggestions`, `SectionSuggestionsDTO` (Task 5); `currentChips` (Task 4); `LivePlayer.schedule`/`songTime` (Task 5); `applyOp`, `runOp`.

- [ ] **Step 1: Add the suggestions state + fetch + playhead poll** — in `apps/web/src/components/Live/LiveMix.tsx`, update the imports:

```tsx
import { useEffect, useRef, useState } from "react";
import { LivePlayer } from "../../lib/liveAudio";
import {
  postLiveCommand,
  getLiveContext,
  getSuggestions,
  type LiveContextDTO,
  type LiveOpDTO,
  type SectionSuggestionsDTO,
} from "../../lib/api";
import {
  applyOp,
  currentChips,
  type BusState,
  type BusName,
  type Chip,
} from "../../lib/liveSchedule";
import styles from "./LiveMix.module.css";
```

Add state (after the existing `useState` calls, near `const [text, setText]`):

```tsx
const [sections, setSections] = useState<SectionSuggestionsDTO[]>([]);
const [chips, setChips] = useState<Chip[]>([]);
```

Add a fetch effect (after the existing load `useEffect`):

```tsx
// Load the per-section suggestion chips for the current mix (once per take).
useEffect(() => {
  setSections([]);
  setChips([]);
  if (!mixId) return;
  getSuggestions(mixId)
    .then(setSections)
    .catch(() => setSections([])); // chips are optional — parts + typed commands still work
}, [mixId]);
```

Add a playhead poll effect that swaps chips as the song moves (only while playing):

```tsx
// While playing, follow the playhead and show the current section's chips.
useEffect(() => {
  if (!playing || sections.length === 0) {
    setChips([]);
    return;
  }
  const id = setInterval(() => {
    const t = playerRef.current?.songTime() ?? 0;
    setChips(currentChips(sections, t));
  }, 250);
  return () => clearInterval(id);
}, [playing, sections]);
```

- [ ] **Step 2: Extend `runOp` to handle fade, and add a chip-tap handler** — replace `runOp` with:

```tsx
/** Apply an op to the audio + the on/off state (shared by taps, chips, typed commands). */
function runOp(op: LiveOpDTO) {
  if (op.op === "mute" || op.op === "unmute" || op.op === "fade") {
    playerRef.current?.schedule(op, ctxRef.current);
    setBusState((s) => applyOp(s, op));
  }
}

function tapChip(chip: Chip) {
  const op: LiveOpDTO = {
    op: chip.op as LiveOpDTO["op"],
    target: chip.targets.length === 1 ? chip.targets[0] : null,
    targets: chip.targets,
    when: "next_bar",
    say: "",
    reason: null,
  };
  runOp(op);
  setStatus(`${chip.text.toLowerCase()} — on the next bar`);
}
```

- [ ] **Step 3: Render the chips** — in the returned JSX, add a suggestions row between the `buses` div and the command `form`:

```tsx
{
  chips.length > 0 && (
    <div className={styles.suggestions} aria-label="suggestions">
      <span className={styles.suggestLabel}>Try:</span>
      {chips.map((c) => (
        <button
          key={c.text}
          type="button"
          data-testid="suggestion-chip"
          className={styles.chip}
          onClick={() => tapChip(c)}
        >
          {c.text}
        </button>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Add chip styles** — append to `apps/web/src/components/Live/LiveMix.module.css`:

```css
.suggestions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin: 8px 0;
}
.suggestLabel {
  opacity: 0.6;
  font-size: 0.85em;
}
.chip {
  cursor: pointer;
  border: 1px solid #7c5cff;
  background: rgba(124, 92, 255, 0.12);
  color: inherit;
  border-radius: 999px;
  padding: 4px 12px;
  font: inherit;
}
.chip:hover {
  background: rgba(124, 92, 255, 0.24);
}
```

- [ ] **Step 5: Run the web checks**

Run: `npm test` then `npm run typecheck` then `npm run lint`
Expected: all PASS. `npm test` — the existing `LiveMix.test.tsx` (four parts render) still passes (no `mixId` in that test → no fetch, no poll). Web total unchanged from Task 5 + the Task 4 additions.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/components/Live/LiveMix.tsx apps/web/src/components/Live/LiveMix.module.css
git commit -m "feat(m5): LiveMix shows current-section suggestion chips, tap to apply on the beat"
```

---

### Task 7: Docs + full-suite verification

**Files:**

- Modify: `docs/functional-spec.md`, `docs/technical-spec.md`, `docs/implementation-plan.md`

- [ ] **Step 1: Update the living docs** — reflect Slice 3 as built:
  - **functional-spec.md** "What the app does TODAY": the live player now shows 1–3 suggestion chips that change with the song's parts and apply on the beat when tapped; "fade away" fades the whole mix out. Note chips are AI-suggested (once per mix) with a built-in fallback, and the user's own controls stay predictable.
  - **technical-spec.md**: add an "As-built (M5 Slice 3)" section — `planner/suggest.py` (closed vocabulary, AI + label fallback, mirrors `plan.py`), `GET /live/suggestions/{mix_id}` (sync, cached), the `"fade"` op (4-bar ramp), `currentChips` playhead picker, chips UI built as a swappable component.
  - **implementation-plan.md**: M5 row → "Slices 1–3 built"; append a 2026-07-06 drift-log entry summarizing Slice 3 + the logged non-blockers (suggestions JSON joins the cache-eviction sweep; "beat up" deferred; live-state-aware chips deferred).

- [ ] **Step 2: Run the FULL suites**

Run: `cd services/api && ./.venv/Scripts/python.exe -m pytest -q` then from repo root `npm test && npm run typecheck && npm run lint`
Expected: backend **157 passed**; web green (22 prior + 3 Task 4 + 1 Task 5 = **26**); typecheck + lint clean.

- [ ] **Step 3: Commit**

```bash
git add docs/functional-spec.md docs/technical-spec.md docs/implementation-plan.md
git commit -m "docs(m5): Slice 3 as-built — AI suggestion chips + fade away"
```

---

## Self-Review

**Spec coverage:** suggestion brain with closed vocabulary + AI + label fallback (Task 2) ✓; per-section, cached, one call (Task 2 + route caching Task 3) ✓; route (Task 3) ✓; `"fade"` op + parser (Task 1) + ramp (Task 5) + state (Task 4) ✓; chips change with the playhead (Task 4 `currentChips` + Task 6 poll) ✓; tap applies on the beat via shared path (Task 6) ✓; user controls unchanged (no edit to mute/unmute behavior) ✓; states: no-mix (Task 6 guards on `mixId`), no-AI (fallback Task 2), thin sections (default section Task 2), fetch-fail (Task 6 `.catch`) ✓; render.py/validate.py untouched (Global Constraints) ✓; chips built as a swappable component for the later UI pass (Task 6) ✓.

**Placeholder scan:** none — every code step is complete. The one conditional instruction (remove `rampTarget` import if lint flags it, Task 5) is a concrete either/or, not a TODO.

**Type consistency:** `Chip`/`Section` (liveSchedule, Task 4) vs `LiveChipDTO`/`SectionSuggestionsDTO` (api, Task 5) are distinct-but-compatible shapes (both `{text,op,targets}` / `{start,end,label,chips}`); `LiveMix` consumes the DTO from `getSuggestions` and the `Chip` type for `currentChips`/`tapChip` — `SectionSuggestionsDTO.chips` is structurally assignable to `Chip[]`. `LiveOpDTO.op` widened to include `"fade"` (Task 5) before `LiveMix` builds a fade op (Task 6). `_VOCAB` texts match verbatim across `suggest.py`, the route test, and the frontend `known` set. `suggest_moves` / `_ai_suggest` names match across module, tests, and route.

**Dangerous-surface note:** protected files touched: `liveSchedule.test.ts` (Task 4), `api.test.ts` (Task 5) — both via confirm-and-apply. `render.py`, `validate.py`, `live_stems.py`, `storage.py`, `songs.py`, config untouched. `LiveMix.test.tsx` not modified.
