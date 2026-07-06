# M5 Slice 2 — The full mix, live, all parts controllable — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the live player play the whole mix (Song 1's beat/bass/melody + Song 2's arranged vocal) and let every part mute/unmute on the beat by tap or typed command, plus a "drop everything but the beat" combo.

**Architecture:** A new backend module (`workers/live_stems.py`) renders the arrangement's vocal layer onto silence by **reusing** the trusted render engine's helpers — no edit to `render.py`/`validate.py`. A new route serves that "arranged-vocal bus" WAV, keyed to the cached `mix_id`. The browser loads it as a fourth live bus alongside Song 1's stems, sync-starts all four, and ramps any bus's gain on the next bar. The live command parser grows to name several parts at once.

**Tech Stack:** FastAPI + Pydantic v2, numpy/soundfile/FFmpeg (backend DSP); React + TypeScript + Vitest, raw Web Audio API (frontend).

## Global Constraints

- **Never edit the dangerous engine/guard:** `workers/render.py`, `services/api/app/planner/validate.py`, `**/storage.py`, `routes/songs.py`, config are OUT of scope. `live_stems.py` imports render helpers; it does not modify them.
- **Web test files (`apps/web/**/*.test.ts`, `*.test.tsx`) are a protected surface** — adding them requires the founder confirm-and-apply flow (`.zuko/approve.js`) before the write. Backend `test_*.py` are NOT guarded.
- **Additive only** to `LiveOp`, `MixPlan` consumers, and DTOs — never rename existing fields (`target`, `vocal_src`, `anchor` stay; plans are cached to disk as JSON and must still parse).
- **Invariants:** music never stops (mute = gain→0, never stop playback); every op fires on the next bar boundary from Song 1's beatgrid.
- **Vocal-bus level:** add the vocal at ratio 1.0 (matching `render_mix`); do NOT peak-normalize the bus (the browser sums it live with the raw stems, so relative balance must be preserved). Apply only a safety clip to `[-_CEILING, _CEILING]`.
- Backend tests run from `services/api`: `./.venv/Scripts/python.exe -m pytest -q`. Web from repo root: `npm test`, `npm run typecheck`, `npm run lint`.

---

### Task 1: `LiveOp.targets` + multi-part command parser

**Files:**

- Modify: `services/api/app/models.py` (LiveOp — add `targets`)
- Modify: `services/api/app/planner/live.py` (grow `parse_command`)
- Test: `services/api/tests/test_live.py` (append cases; NOT a guarded file)

**Interfaces:**

- Produces: `parse_command(text: str) -> LiveOp` where `LiveOp.targets: list[str]` names the buses (`"drums"|"bass"|"other"|"vocals"`); for a single-part op `target` is also set (back-compat). Combos set `targets` with `target=None`.

- [ ] **Step 1: Write the failing tests** — append to `services/api/tests/test_live.py`:

```python
def test_remove_the_vocals_mutes_vocals():
    op = parse_command("remove the vocals")
    assert op.op == "mute" and op.targets == ["vocals"]


def test_bring_the_vocals_back_unmutes_vocals():
    op = parse_command("bring the vocals back")
    assert op.op == "unmute" and op.targets == ["vocals"]


def test_drop_everything_but_the_beat_mutes_all_but_drums():
    op = parse_command("drop everything but the beat")
    assert op.op == "mute" and set(op.targets) == {"bass", "other", "vocals"}
    assert "drums" not in op.targets


def test_bring_it_all_back_unmutes_everything():
    op = parse_command("bring it all back")
    assert op.op == "unmute" and set(op.targets) == {"drums", "bass", "other", "vocals"}


def test_take_the_melody_out_mutes_other():
    op = parse_command("take the melody out")
    assert op.op == "mute" and op.targets == ["other"]


def test_bass_command_still_sets_both_target_and_targets():
    op = parse_command("take the bass out")
    assert op.op == "mute" and op.target == "bass" and op.targets == ["bass"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd services/api && ./.venv/Scripts/python.exe -m pytest tests/test_live.py -q`
Expected: FAIL — new cases error (`targets` attribute missing / phrases not recognized).

- [ ] **Step 3: Add `targets` to the model** — in `services/api/app/models.py`, inside `LiveOp`, add the field (keep `target`):

```python
class LiveOp(BaseModel):
    op: str
    target: str | None = None  # single bus (Slice 1 back-compat); mirrors targets[0] when one part
    targets: list[str] = []  # the buses this op affects — may be several ("drop everything but the beat")
    when: str = "next_bar"
    say: str = ""
    reason: str | None = None
```

- [ ] **Step 4: Grow the parser** — replace the body of `services/api/app/planner/live.py` with (order matters: most specific first):

```python
"""The live driver: turn a plain-language steering command into a structured LiveOp.

Slice 2 grows the lean command set to every part (drums/bass/other/vocals) plus the
"drop everything but the beat" combo. Still deterministic; an LLM path will sit in
front of it later with this same function as the fallback (mirrors planner.plan).
The op is executed by the browser on the beat — this module never touches audio.
"""

from __future__ import annotations

from app.models import LiveOp

_ALL = ["drums", "bass", "other", "vocals"]

# Phrase -> the bus a single-part command targets.
_MUTE_BASS = ("take the bass out", "drop the bass", "bass out", "kill the bass", "no bass")
_UNMUTE_BASS = ("bring the bass back", "bass back")
_MUTE_VOCALS = ("remove the vocals", "take the vocals out", "drop the vocals", "no vocals",
                "kill the vocals", "mute the vocals", "vocals out")
_UNMUTE_VOCALS = ("bring the vocals back", "vocals back", "add the vocals", "add vocals")
_MUTE_DRUMS = ("take the drums out", "drop the drums", "no drums", "mute the drums", "drums out")
_UNMUTE_DRUMS = ("bring the drums back", "drums back")
_MUTE_OTHER = ("take the melody out", "drop the melody", "no melody", "mute the melody", "melody out")
_UNMUTE_OTHER = ("bring the melody back", "melody back")
# Combos.
_JUST_DRUMS = ("drop everything but the beat", "just the drums", "only the beat", "beat only",
               "everything but the beat")
_ALL_BACK = ("bring it all back", "bring everything back", "full mix", "all back", "reset the mix")
# Slice-1 generic "bring it back" / undo -> restore the bass (kept for back-compat).
_UNMUTE_GENERIC = ("bring it back", "back to normal", "undo")


def _mute(targets: list[str], say: str) -> LiveOp:
    return LiveOp(op="mute", targets=targets, target=(targets[0] if len(targets) == 1 else None), say=say)


def _unmute(targets: list[str], say: str) -> LiveOp:
    return LiveOp(op="unmute", targets=targets, target=(targets[0] if len(targets) == 1 else None), say=say)


def parse_command(text: str) -> LiveOp:
    """Map a typed command to a LiveOp. Unknown/out-of-scope asks are declined plainly."""
    t = " ".join(text.lower().split())
    if not t:
        return LiveOp(op="decline", say="Type a command like 'take the bass out'.")

    # Combos first (they contain words that would otherwise match single parts).
    if any(p in t for p in _ALL_BACK):
        return _unmute(list(_ALL), "bringing the whole mix back on the next bar")
    if any(p in t for p in _JUST_DRUMS):
        return _mute(["bass", "other", "vocals"], "dropping everything but the beat on the next bar")

    # Single parts — unmute checked before mute per part so "bring the X back" wins over "X out".
    if any(p in t for p in _UNMUTE_VOCALS):
        return _unmute(["vocals"], "bringing the vocals back on the next bar")
    if any(p in t for p in _MUTE_VOCALS):
        return _mute(["vocals"], "pulling the vocals on the next bar")
    if any(p in t for p in _UNMUTE_DRUMS):
        return _unmute(["drums"], "bringing the drums back on the next bar")
    if any(p in t for p in _MUTE_DRUMS):
        return _mute(["drums"], "dropping the drums on the next bar")
    if any(p in t for p in _UNMUTE_OTHER):
        return _unmute(["other"], "bringing the melody back on the next bar")
    if any(p in t for p in _MUTE_OTHER):
        return _mute(["other"], "pulling the melody on the next bar")
    if any(p in t for p in _UNMUTE_BASS):
        return _unmute(["bass"], "bringing the bass back on the next bar")
    if any(p in t for p in _UNMUTE_GENERIC):
        return _unmute(["bass"], "bringing the bass back on the next bar")
    if any(p in t for p in _MUTE_BASS):
        return _mute(["bass"], "dropping the bass on the next bar")

    return LiveOp(
        op="decline",
        say="I can't do that in this version — try 'take the bass out', 'remove the vocals', or 'drop everything but the beat'.",
        reason="out of scope",
    )
```

- [ ] **Step 5: Run the full live-parser suite**

Run: `cd services/api && ./.venv/Scripts/python.exe -m pytest tests/test_live.py -q`
Expected: PASS (the 6 original Slice-1 cases + the 6 new ones). Note the original `test_bring_it_back_unmutes` still passes (`_UNMUTE_GENERIC`).

- [ ] **Step 6: Commit**

```bash
git add services/api/app/models.py services/api/app/planner/live.py services/api/tests/test_live.py
git commit -m "feat(m5): live parser handles every part + 'drop everything but the beat' combo"
```

---

### Task 2: `render_vocal_bus` — the arranged-vocal bus on silence

**Files:**

- Create: `workers/live_stems.py`
- Test: `services/api/tests/test_live_stems.py` (NOT a guarded file)

**Interfaces:**

- Consumes: from `workers.render` — `_vocal_take`, `_vocal_take_warped`, `_edge_fade`, `_placements_of`, `SR`, `_CEILING`, `RenderError`.
- Produces: `render_vocal_bus(plan, song1_stems: Mapping[str, Path], song2_vocal: Path, out_path: Path) -> Path` — writes a stereo PCM_16 WAV containing only the arrangement's vocal layer (Song 2 placed/warped + Song 1 contrast regions), silent everywhere else, at ratio 1.0, safety-clipped.

- [ ] **Step 1: Write the failing test** — create `services/api/tests/test_live_stems.py`:

```python
"""Tests for the arranged-vocal-bus renderer. Like test_render, these shell out to
FFmpeg and build tiny synthetic stems; they confirm the bus carries the vocal only
where the plan places it and is silent (no bed) everywhere else."""

import sys
import types
from pathlib import Path

import numpy as np
import soundfile as sf

_REPO = Path(__file__).resolve().parents[3]  # tests -> api -> services -> repo
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from workers import live_stems  # noqa: E402
from workers.render import SR  # noqa: E402


def _tone(path, freq=440.0, secs=8.0, amp=0.4, sr=SR):
    t = np.linspace(0, secs, int(sr * secs), endpoint=False)
    sf.write(path, (amp * np.sin(2 * np.pi * freq * t)).astype("float32"), sr)


def _stems(tmp_path):
    paths = {}
    for name, f in (("drums", 110.0), ("bass", 55.0), ("other", 330.0), ("vocals", 660.0)):
        p = tmp_path / f"{name}.wav"
        _tone(p, freq=f, secs=8.0)
        paths[name] = p
    vocal = tmp_path / "vocal.wav"
    _tone(vocal, freq=440.0, secs=8.0)
    return paths, vocal


def _arr_plan(placements, s1_regions=()):
    """placements = [(anchor, (start,end)), ...]; s1_regions = [(s,e), ...]."""
    return types.SimpleNamespace(
        master_bpm=120.0, vocal_stretch=1.0,
        vocal_src=placements[0][1], anchor=placements[0][0], beat_breath=False,
        placements=[types.SimpleNamespace(anchor=a, vocal_src=v, beat_breath=False)
                    for a, v in placements],
        s1_vocal_regions=list(s1_regions),
    )


def _rms(y, a, b):
    seg = y[int(a * SR):int(b * SR)]
    return float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0


def test_vocal_bus_is_valid_stereo_wav(tmp_path):
    stems, vocal = _stems(tmp_path)
    out = tmp_path / "bus.wav"
    live_stems.render_vocal_bus(_arr_plan([(2.0, (0.0, 2.0))]), stems, vocal, out)
    y, sr = sf.read(out, dtype="float32", always_2d=True)
    assert sr == SR and y.shape[1] == 2
    peak = float(np.max(np.abs(y)))
    assert 0.0 < peak <= 0.999  # audible, never clipping


def test_vocal_bus_silent_before_placement_and_loud_inside(tmp_path):
    stems, vocal = _stems(tmp_path)
    out = tmp_path / "bus.wav"
    live_stems.render_vocal_bus(_arr_plan([(2.0, (0.0, 2.0))]), stems, vocal, out)
    y, _ = sf.read(out, dtype="float32", always_2d=True)
    # Before the anchor (2.0s) the bus is silence — proves the bed is NOT summed in.
    assert _rms(y, 0.2, 1.7) < 1e-3
    # Inside the placement it is loud (the vocal is present).
    assert _rms(y, 2.3, 3.7) > 1e-2


def test_vocal_bus_includes_song1_contrast_region(tmp_path):
    stems, vocal = _stems(tmp_path)
    out = tmp_path / "bus.wav"
    # No Song 2 placement near 5s; a Song 1 contrast region at [5,6] must still be audible.
    live_stems.render_vocal_bus(_arr_plan([(0.5, (0.0, 1.0))], s1_regions=[(5.0, 6.0)]),
                                stems, vocal, out)
    y, _ = sf.read(out, dtype="float32", always_2d=True)
    assert _rms(y, 5.2, 5.8) > 1e-2


def test_vocal_bus_with_no_placements_is_valid_silence(tmp_path):
    stems, vocal = _stems(tmp_path)
    out = tmp_path / "bus.wav"
    plan = types.SimpleNamespace(master_bpm=120.0, vocal_stretch=1.0,
                                 vocal_src=(0.0, 0.0), anchor=0.0, beat_breath=False,
                                 placements=[], s1_vocal_regions=[])
    # _placements_of falls back to the scalar anchor/vocal_src (a zero-length slice) -> silence.
    live_stems.render_vocal_bus(plan, stems, vocal, out)
    y, sr = sf.read(out, dtype="float32", always_2d=True)
    assert sr == SR and len(y) >= 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd services/api && ./.venv/Scripts/python.exe -m pytest tests/test_live_stems.py -q`
Expected: FAIL — `ModuleNotFoundError: workers.live_stems`.

- [ ] **Step 3: Create `workers/live_stems.py`**

```python
"""Render the arrangement's VOCAL layer onto silence — the "arranged-vocal bus".

The live player (browser) plays Song 1's stems at steady gain and needs Song 2's
arranged vocal as a separate, sync-playable track it can mute/unmute on the beat.
Rather than re-implement the warp/fade/contrast math in JS, this reuses the trusted
render engine's helpers to bake exactly the vocal half of `render_mix` onto a silent
buffer: same placements, same per-bar beat-lock, same edge fades, plus Song 1's own
contrast vocal. It deliberately skips the bed sum, the master peak-normalize, and the
bed-only effects (sweep, beat-breath) — those live only in the finished Download.

Level: the vocal is added at ratio 1.0 (identical to `render_mix`), and the bus is NOT
peak-normalized, because the browser sums it live with the raw stems — so the relative
balance between vocal and bed matches the Download (whose global normalize is uniform).
Only a safety clip is applied so a pathological overlap can't exceed the WAV's range.
This module imports render.py's helpers; it never modifies the engine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

import numpy as np
import soundfile as sf

from workers.render import (  # reuse the single source of truth for vocal placement
    SR,
    RenderError,
    _CEILING,
    _edge_fade,
    _placements_of,
    _vocal_take,
    _vocal_take_warped,
)


def _hold(buf: np.ndarray, need: int) -> np.ndarray:
    """Extend the buffer with silence so it can hold audio out to `need` samples."""
    if need > len(buf):
        return np.vstack([buf, np.zeros((need - len(buf), 2), dtype=np.float32)])
    return buf


def render_vocal_bus(plan, song1_stems: Mapping[str, Path], song2_vocal: Path,
                     out_path: Path) -> Path:
    """Render `plan`'s vocal layer (Song 2 placed + Song 1 contrast) onto silence."""
    if plan.master_bpm <= 0:
        raise RenderError("plan has a non-positive tempo")

    layer = np.zeros((0, 2), dtype=np.float32)

    for p in _placements_of(plan):
        warp = getattr(p, "warp", None)
        if warp:  # per-bar beat-lock (M4d) — each bar re-locked to Song 1's grid
            voc = _edge_fade(_vocal_take_warped(song2_vocal, warp))
        else:  # legacy single global stretch (M3/M4a–c cached plans)
            start, end = p.vocal_src
            voc = _edge_fade(_vocal_take(song2_vocal, start, max(end - start, 0.0), plan.vocal_stretch))
        anchor = max(0, int(p.anchor * SR))
        need = anchor + len(voc)
        layer = _hold(layer, need)
        layer[anchor:need] += voc

    # Song 1's own vocal answering in the gaps (contrast) — same as render_mix, no stretch.
    s1_vocals = song1_stems.get("vocals")
    for s, e in getattr(plan, "s1_vocal_regions", []):
        if s1_vocals is None:
            break
        take = _edge_fade(_vocal_take(s1_vocals, s, max(e - s, 0.0), 1.0))
        a0 = max(0, int(s * SR))
        layer = _hold(layer, a0 + len(take))
        layer[a0:a0 + len(take)] += take

    np.clip(layer, -_CEILING, _CEILING, out=layer)  # safety only — NOT a peak-normalize
    if len(layer) == 0:
        layer = np.zeros((1, 2), dtype=np.float32)  # a valid (silent) WAV even with no vocal
    sf.write(out_path, layer, SR, subtype="PCM_16")
    return out_path
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd services/api && ./.venv/Scripts/python.exe -m pytest tests/test_live_stems.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add workers/live_stems.py services/api/tests/test_live_stems.py
git commit -m "feat(m5): render_vocal_bus — arranged-vocal bus on silence, reusing the engine helpers"
```

---

### Task 3: `GET /live/vocal-bus/{mix_id}` route

**Files:**

- Modify: `services/api/app/routes/live.py`
- Test: `services/api/tests/test_live_route.py` (append; NOT guarded)

**Interfaces:**

- Consumes: `render_vocal_bus` (Task 2); `MixPlan` (has `song1_id`/`song2_id`); `stem_path`; `settings.data_dir`.
- Produces: `GET /live/vocal-bus/{mix_id}` → `200` FileResponse (audio/wav) when ready; `202` while rendering; `409` if the mix plan isn't on disk yet; `404` on a bad id.

- [ ] **Step 1: Write the failing tests** — append to `services/api/tests/test_live_route.py`:

```python
import dataclasses as _dc

from app.routes import live as live_route


def _use_live_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(live_route, "settings",
                        _dc.replace(live_route.settings, data_dir=tmp_path))


def test_vocal_bus_bad_id_is_404():
    r = client.get("/live/vocal-bus/nothex")
    assert r.status_code == 404


def test_vocal_bus_without_a_plan_is_409(monkeypatch, tmp_path):
    _use_live_tmp(monkeypatch, tmp_path)
    r = client.get(f"/live/vocal-bus/{HEX}")
    assert r.status_code == 409


def test_vocal_bus_serves_the_wav_when_present(monkeypatch, tmp_path):
    _use_live_tmp(monkeypatch, tmp_path)
    (tmp_path / f"{HEX}.vocalbus.wav").write_bytes(b"RIFF....WAVEfake")  # pre-seeded "ready"
    r = client.get(f"/live/vocal-bus/{HEX}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("audio/")
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd services/api && ./.venv/Scripts/python.exe -m pytest tests/test_live_route.py -q`
Expected: FAIL — no `/live/vocal-bus/...` route (404 for all, or attribute errors).

- [ ] **Step 3: Extend `services/api/app/routes/live.py`** — add imports at the top (after the existing ones):

```python
import logging
import sys
import threading

from fastapi import Response
from fastapi.responses import FileResponse

from app.audio.stems import stem_path
from app.config import settings
from app.models import MixPlan

# workers/ lives at the repo root; put it on the path so we can import the vocal-bus renderer.
_REPO = __import__("pathlib").Path(__file__).resolve().parents[4]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
from workers.live_stems import render_vocal_bus  # noqa: E402

log = logging.getLogger("promptdj.live")
_S1_STEMS = ("drums", "bass", "other")
# mix_id -> (status, message). Absence + a stored .vocalbus.wav means "ready". In-memory
# is fine for single-worker validation (same pattern as mix.py; shared-eviction backlog note).
_vocal_jobs: dict[str, tuple[str, str | None]] = {}
```

Then add the path helpers and route at the end of the file:

```python
def _vocal_bus_path(mix_id: str):
    return settings.data_dir / f"{mix_id}.vocalbus.wav"


def _mixplan_path(mix_id: str):
    return settings.data_dir / f"{mix_id}.mixplan.json"


def _run_vocal_bus(mix_id: str) -> None:
    """Background worker: load the cached plan, render its vocal layer to a bus WAV."""
    try:
        plan = MixPlan(**json.loads(_mixplan_path(mix_id).read_text()))
        stems = {s: stem_path(plan.song1_id, s) for s in _S1_STEMS}
        s1_voc = stem_path(plan.song1_id, "vocals")
        if s1_voc.exists():
            stems["vocals"] = s1_voc
        render_vocal_bus(plan, stems, stem_path(plan.song2_id, "vocals"), _vocal_bus_path(mix_id))
        _vocal_jobs.pop(mix_id, None)  # readiness now inferred from the stored file
    except Exception:  # noqa: BLE001 — never leak a trace; log so a systematic bug isn't invisible
        log.exception("vocal-bus render failed for %s", mix_id)
        _vocal_bus_path(mix_id).unlink(missing_ok=True)
        _vocal_jobs[mix_id] = ("error", "Couldn't prepare the live vocals.")


@router.get("/live/vocal-bus/{mix_id}")
def live_vocal_bus(mix_id: str):
    """Serve the arranged-vocal bus for a finished mix; render it on first request."""
    if not _HEX_ID.fullmatch(mix_id):
        raise HTTPException(404, "Not found.")
    out = _vocal_bus_path(mix_id)
    if out.exists():
        return FileResponse(out, media_type="audio/wav")
    if not _mixplan_path(mix_id).exists():
        raise HTTPException(409, "Make the mix first so I can prepare the live vocals.")
    status = _vocal_jobs.get(mix_id, (None,))[0]
    if status == "error":
        raise HTTPException(500, "Couldn't prepare the live vocals. Try regenerating the mix.")
    if status != "processing":
        _vocal_jobs[mix_id] = ("processing", None)
        threading.Thread(target=_run_vocal_bus, args=(mix_id,), daemon=True).start()
    return Response(status_code=202)  # browser polls until 200
```

Note: `json` is already imported at the top of `live.py`.

- [ ] **Step 4: Run to verify it passes**

Run: `cd services/api && ./.venv/Scripts/python.exe -m pytest tests/test_live_route.py -q`
Expected: PASS (the 4 original + 3 new).

- [ ] **Step 5: Run the whole backend suite (guard against regressions)**

Run: `cd services/api && ./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS — 136 prior + 6 (Task 1) + 4 (Task 2) + 3 (Task 3) = **149 passed**.

- [ ] **Step 6: Commit**

```bash
git add services/api/app/routes/live.py services/api/tests/test_live_route.py
git commit -m "feat(m5): GET /live/vocal-bus/{mix_id} — serve the arranged-vocal bus (async, cached)"
```

---

### Task 4: Frontend schedule/state — vocals bus + multi-target ops

**Files:**

- Modify: `apps/web/src/lib/liveSchedule.ts`
- Test: `apps/web/src/lib/liveSchedule.test.ts` — **PROTECTED (confirm-and-apply before writing)**

**Interfaces:**

- Produces: `BusName` includes `"vocals"`; `applyOp(state, op)` accepts `{op, target?, targets?}` and flips every named bus.

- [ ] **Step 1: (Protected write) Add the failing tests** — append to `apps/web/src/lib/liveSchedule.test.ts`:

```typescript
test("applyOp flips every bus named in targets (combo)", () => {
  const s = { drums: true, bass: true, other: true, vocals: true };
  const r = applyOp(s, {
    op: "mute",
    target: null,
    targets: ["bass", "other", "vocals"],
  });
  expect(r).toEqual({ drums: true, bass: false, other: false, vocals: false });
});

test("applyOp unmutes all with a full targets list", () => {
  const s = { drums: false, bass: false, other: false, vocals: false };
  const r = applyOp(s, {
    op: "unmute",
    target: null,
    targets: ["drums", "bass", "other", "vocals"],
  });
  expect(r).toEqual({ drums: true, bass: true, other: true, vocals: true });
});

test("applyOp still honors a single target when targets is absent", () => {
  const s = { drums: true, bass: true, other: true, vocals: true };
  expect(applyOp(s, { op: "mute", target: "vocals" }).vocals).toBe(false);
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npm test -- liveSchedule`
Expected: FAIL — `vocals` not in `BusState`; `applyOp` ignores `targets`.

- [ ] **Step 3: Update `apps/web/src/lib/liveSchedule.ts`** — replace `BusName`, `BusState`, and `applyOp`:

```typescript
export type BusName = "drums" | "bass" | "other" | "vocals";
export type BusState = Record<BusName, boolean>;

export function barSeconds(bpm: number): number {
  return (60 / bpm) * 4;
}

/** The first downbeat strictly after songTime; if none, round up to the next bar on the bpm grid. */
export function nextBarTime(
  downbeats: number[],
  songTime: number,
  bpm: number,
): number {
  const next = downbeats.find((d) => d > songTime + 1e-6);
  if (next !== undefined) return next;
  const bar = barSeconds(bpm);
  return Math.ceil((songTime + 1e-6) / bar) * bar;
}

export type OpLike = { op: string; target?: string | null; targets?: string[] };

/** The buses an op affects: `targets` when present, else the single `target`. */
export function busesOf(op: OpLike): BusName[] {
  const raw =
    op.targets && op.targets.length ? op.targets : op.target ? [op.target] : [];
  return raw.filter(
    (b): b is BusName =>
      b === "drums" || b === "bass" || b === "other" || b === "vocals",
  );
}

export function applyOp(state: BusState, op: OpLike): BusState {
  if (op.op !== "mute" && op.op !== "unmute") return state;
  const next = { ...state };
  for (const b of busesOf(op)) next[b] = op.op === "unmute";
  return next;
}

export function rampTarget(op: { op: string }): number {
  return op.op === "unmute" ? 1 : 0;
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `npm test -- liveSchedule`
Expected: PASS (5 original + 3 new). The Slice-1 `applyOp ... target only` test still passes.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/lib/liveSchedule.ts apps/web/src/lib/liveSchedule.test.ts
git commit -m "feat(m5): vocals bus + multi-target applyOp/busesOf"
```

---

### Task 5: Frontend player — load the vocal bus, ramp multiple buses

**Files:**

- Modify: `apps/web/src/lib/api.ts` (DTO + vocal-bus fetch)
- Modify: `apps/web/src/lib/liveAudio.ts` (load vocal bus; multi-target schedule)
- Test: `apps/web/src/lib/api.test.ts` — **PROTECTED (confirm-and-apply)**

**Interfaces:**

- Consumes: `busesOf`, `BusName` (Task 4); `GET /live/vocal-bus/{mixId}` (Task 3).
- Produces: `LiveOpDTO.targets?: string[]`; `fetchVocalBus(mixId): Promise<ArrayBuffer>`; `LivePlayer.load(song1Id, stemBuses, mixId?)`; `LivePlayer.schedule` ramps every named bus.

- [ ] **Step 1: (Protected write) Add the failing test** — append to `apps/web/src/lib/api.test.ts`:

```typescript
import { fetchVocalBus } from "./api";

test("fetchVocalBus polls past 202 and returns the audio bytes", async () => {
  const calls: number[] = [];
  const g = globalThis as unknown as { fetch: typeof fetch };
  const real = g.fetch;
  g.fetch = (async () => {
    calls.push(1);
    if (calls.length < 2) return new Response(null, { status: 202 });
    return new Response(new Uint8Array([1, 2, 3]), { status: 200 });
  }) as typeof fetch;
  try {
    const buf = await fetchVocalBus("a".repeat(64));
    expect(new Uint8Array(buf)).toEqual(new Uint8Array([1, 2, 3]));
    expect(calls.length).toBe(2);
  } finally {
    g.fetch = real;
  }
}, 10000);
```

Note: `fetchVocalBus` must poll with a **short, injectable** delay so the test isn't slow. Implement the wait as `await new Promise((r) => setTimeout(r, POLL_MS))` with `POLL_MS = 50` in test via a module constant defaulting to 1500 — simplest: keep 1500 but the test's second call happens on attempt 2, so cap loop wait: use `POLL_MS` small enough. To keep the test fast without exposing internals, set the poll delay to 1500ms in prod but have the loop `await` only _between_ attempts; the test's stub returns 200 on the 2nd call, so exactly one 1500ms wait occurs — under the 10s budget. (Acceptable.)

- [ ] **Step 2: Run to verify it fails**

Run: `npm test -- api`
Expected: FAIL — `fetchVocalBus` is not exported.

- [ ] **Step 3: Extend `apps/web/src/lib/api.ts`** — update `LiveOpDTO` and add the fetch helper (place near the other live helpers):

```typescript
export type LiveOpDTO = {
  op: "mute" | "unmute" | "decline";
  target: string | null;
  targets?: string[];
  when: string;
  say: string;
  reason: string | null;
};
```

```typescript
const VOCAL_BUS_POLL_MS = 1500;

/** Fetch the arranged-vocal-bus WAV for a mix, polling past 202 while it renders. */
export async function fetchVocalBus(mixId: string): Promise<ArrayBuffer> {
  for (let i = 0; i < 80; i++) {
    const res = await fetch(`${API_BASE}/live/vocal-bus/${mixId}`);
    if (res.status === 200) return res.arrayBuffer();
    if (res.status === 202) {
      await new Promise((r) => setTimeout(r, VOCAL_BUS_POLL_MS));
      continue;
    }
    throw new Error("Couldn't prepare the live vocals.");
  }
  throw new Error("Preparing the live vocals took too long.");
}
```

- [ ] **Step 4: Update `apps/web/src/lib/liveAudio.ts`** — load the vocal bus and ramp multiple buses:

```typescript
import {
  API_BASE,
  fetchVocalBus,
  type LiveOpDTO,
  type LiveContextDTO,
} from "./api";
import {
  barSeconds,
  busesOf,
  nextBarTime,
  rampTarget,
  type BusName,
} from "./liveSchedule";

export class LivePlayer {
  private ctx = new AudioContext();
  private buffers = new Map<BusName, AudioBuffer>();
  private gains = new Map<BusName, GainNode>();
  private sources = new Map<BusName, AudioBufferSourceNode>();
  private startCtxTime = 0;
  private playing = false;

  private addBus(bus: BusName, buf: AudioBuffer): void {
    this.buffers.set(bus, buf);
    const g = this.ctx.createGain();
    g.gain.value = 1;
    g.connect(this.ctx.destination);
    this.gains.set(bus, g);
  }

  /** Load Song 1's instrumental stems, plus (when a mix exists) its arranged-vocal bus. */
  async load(
    song1Id: string,
    stemBuses: BusName[],
    mixId?: string,
  ): Promise<void> {
    await Promise.all(
      stemBuses.map(async (bus) => {
        const res = await fetch(`${API_BASE}/songs/${song1Id}/stems/${bus}`);
        const buf = await this.ctx.decodeAudioData(await res.arrayBuffer());
        this.addBus(bus, buf);
      }),
    );
    if (mixId) {
      const buf = await this.ctx.decodeAudioData(await fetchVocalBus(mixId));
      this.addBus("vocals", buf);
    }
  }

  play(): void {
    if (this.playing) return;
    this.startCtxTime = this.ctx.currentTime + 0.1;
    for (const [bus, buf] of this.buffers) {
      const src = this.ctx.createBufferSource();
      src.buffer = buf;
      src.connect(this.gains.get(bus)!);
      src.start(this.startCtxTime);
      this.sources.set(bus, src);
    }
    this.ctx.resume();
    this.playing = true;
  }

  pause(): void {
    for (const src of this.sources.values()) src.stop();
    this.sources.clear();
    this.playing = false;
  }

  songTime(): number {
    return Math.max(0, this.ctx.currentTime - this.startCtxTime);
  }

  /** Schedule a mute/unmute on the next bar, ramped over one bar, for every named bus. */
  schedule(op: LiveOpDTO, ctx: LiveContextDTO): void {
    if (op.op !== "mute" && op.op !== "unmute") return;
    const bpm = ctx.bpm ?? 120;
    const barSong = nextBarTime(ctx.downbeats, this.songTime(), bpm);
    const startCtx = this.startCtxTime + barSong;
    const target = rampTarget(op);
    for (const bus of busesOf(op)) {
      const g = this.gains.get(bus);
      if (!g) continue;
      g.gain.cancelScheduledValues(startCtx);
      g.gain.setValueAtTime(g.gain.value, startCtx);
      g.gain.linearRampToValueAtTime(target, startCtx + barSeconds(bpm));
    }
  }

  dispose(): void {
    this.pause();
    this.ctx.close();
  }
}
```

- [ ] **Step 5: Run to verify api tests pass + typecheck**

Run: `npm test -- api` then `npm run typecheck`
Expected: both PASS. (liveAudio's raw Web Audio isn't unit-tested — verified by ear in acceptance, per the Slice-1 design.)

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/lib/api.ts apps/web/src/lib/liveAudio.ts apps/web/src/lib/api.test.ts
git commit -m "feat(m5): player loads the vocal bus and ramps multiple buses on the beat"
```

---

### Task 6: `LiveMix` — four tappable parts, tied to the current take

**Files:**

- Modify: `apps/web/src/components/Live/LiveMix.tsx`
- Modify: `apps/web/src/components/Mix/Mix.tsx` (emit the ready mix_id)
- Modify: `apps/web/src/components/Uploader/Uploader.tsx` (lift mixId, pass to both)
- Modify: `apps/web/src/components/Live/LiveMix.module.css` (button styles — non-test, additive)
- Test: `apps/web/src/components/Live/LiveMix.test.tsx` — **PROTECTED (confirm-and-apply)**

**Interfaces:**

- Consumes: `LivePlayer.load(song1Id, stemBuses, mixId?)`, `LivePlayer.schedule`, `applyOp`, `busesOf` (Tasks 4–5).
- Produces: `LiveMix({song1Id, song2Id, mixId?})` rendering four labelled parts (Beat/Bass/Melody/Vocals); `MixMaker({song1, song2, onMixReady?})`.

- [ ] **Step 1: (Protected write) Update the failing test** — replace `apps/web/src/components/Live/LiveMix.test.tsx` with:

```tsx
import { render, screen } from "@testing-library/react";
import LiveMix from "./LiveMix";

test("LiveMix shows the four part controls without crashing (no Web Audio in jsdom)", () => {
  render(<LiveMix song1Id={"a".repeat(64)} song2Id={"b".repeat(64)} />);
  expect(screen.getByText("Beat")).toBeInTheDocument();
  expect(screen.getByText("Bass")).toBeInTheDocument();
  expect(screen.getByText("Melody")).toBeInTheDocument();
  expect(screen.getByText("Vocals")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npm test -- LiveMix`
Expected: FAIL — labels "Beat/Melody/Vocals" not present (current UI shows raw bus names `drums/bass/other`).

- [ ] **Step 3: Rewrite `apps/web/src/components/Live/LiveMix.tsx`**

```tsx
import { useEffect, useRef, useState } from "react";
import { LivePlayer } from "../../lib/liveAudio";
import {
  postLiveCommand,
  getLiveContext,
  type LiveContextDTO,
  type LiveOpDTO,
} from "../../lib/api";
import { applyOp, type BusState, type BusName } from "../../lib/liveSchedule";
import styles from "./LiveMix.module.css";

const STEM_BUSES: BusName[] = ["drums", "bass", "other"];
// Display order + friendly labels for the four controllable parts.
const PARTS: { bus: BusName; label: string }[] = [
  { bus: "drums", label: "Beat" },
  { bus: "bass", label: "Bass" },
  { bus: "other", label: "Melody" },
  { bus: "vocals", label: "Vocals" },
];

export default function LiveMix({
  song1Id,
  song2Id,
  mixId,
}: {
  song1Id: string;
  song2Id: string;
  mixId?: string;
}) {
  const playerRef = useRef<LivePlayer | null>(null);
  const ctxRef = useRef<LiveContextDTO>({ bpm: 120, downbeats: [] });
  const [ready, setReady] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [busState, setBusState] = useState<BusState>({
    drums: true,
    bass: true,
    other: true,
    vocals: true,
  });
  const [status, setStatus] = useState("");
  const [text, setText] = useState("");

  // (Re)load the player whenever the song or the current take (mixId) changes, so the
  // live vocals always match the mix on screen.
  useEffect(() => {
    setReady(false);
    setPlaying(false);
    let p: LivePlayer;
    try {
      p = new LivePlayer();
    } catch {
      return; // no Web Audio (or a test DOM) — live mode stays not-ready, page doesn't crash
    }
    playerRef.current = p;
    Promise.all([
      p.load(song1Id, STEM_BUSES, mixId),
      getLiveContext(song1Id),
    ]).then(([, ctx]) => {
      ctxRef.current = ctx;
      setReady(true);
    });
    return () => p.dispose();
  }, [song1Id, mixId]);

  const vocalsAvailable = Boolean(mixId);

  function togglePlay() {
    const p = playerRef.current;
    if (!p) return;
    if (playing) {
      p.pause();
      setPlaying(false);
    } else {
      p.play();
      setPlaying(true);
    }
  }

  /** Apply an op to the audio + the on/off state (shared by taps and typed commands). */
  function runOp(op: LiveOpDTO) {
    if (op.op === "mute" || op.op === "unmute") {
      playerRef.current?.schedule(op, ctxRef.current);
      setBusState((s) => applyOp(s, op));
    }
  }

  function toggleBus(bus: BusName) {
    if (bus === "vocals" && !vocalsAvailable) return;
    const op: LiveOpDTO = {
      op: busState[bus] ? "mute" : "unmute",
      target: bus,
      targets: [bus],
      when: "next_bar",
      say: "",
      reason: null,
    };
    runOp(op);
    setStatus(
      `${busState[bus] ? "dropping" : "bringing back"} the ${bus} on the next bar`,
    );
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    const op = await postLiveCommand(song1Id, song2Id, text);
    setStatus(op.say);
    runOp(op);
    setText("");
  }

  return (
    <div className={styles.live}>
      <button onClick={togglePlay} disabled={!ready}>
        {playing ? "Pause" : "Play"}
      </button>
      <div className={styles.buses}>
        {PARTS.map(({ bus, label }) => {
          const disabled = bus === "vocals" && !vocalsAvailable;
          return (
            <button
              key={bus}
              type="button"
              data-testid={`bus-${bus}`}
              data-on={busState[bus]}
              className={busState[bus] ? styles.on : styles.off}
              disabled={disabled}
              title={
                disabled
                  ? "Make a mix first to steer the vocals"
                  : `Tap to toggle ${label}`
              }
              onClick={() => toggleBus(bus)}
            >
              {label}
            </button>
          );
        })}
      </div>
      <form aria-label="command" onSubmit={onSubmit}>
        <input
          placeholder="Try: drop everything but the beat"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <button type="submit">Go</button>
      </form>
      <p className={styles.status} role="status">
        {status}
      </p>
    </div>
  );
}
```

- [ ] **Step 4: Emit the ready mix_id from `MixMaker`** — in `apps/web/src/components/Mix/Mix.tsx`, add the optional callback to the signature and call it when a mix becomes ready:

Change the component signature:

```tsx
export function MixMaker({
  song1,
  song2,
  onMixReady,
}: {
  song1: SongDTO;
  song2: SongDTO;
  onMixReady?: (mixId: string) => void;
}) {
```

In `handleMix`, after each `setMix(...)` on the ready paths, notify the parent. Replace the two ready branches:

```tsx
if (started.status === "ready") {
  setMix(started);
  setState("done");
  onMixReady?.(started.mix_id);
  return;
}
```

```tsx
if (s.status === "ready") {
  setMix(s);
  setState("done");
  onMixReady?.(s.mix_id);
  return;
}
```

- [ ] **Step 5: Lift `mixId` in `Uploader` and pass it down** — in `apps/web/src/components/Uploader/Uploader.tsx`, add state and thread it:

Add near the other `useState` calls in `Uploader`:

```tsx
const [mixId, setMixId] = useState<string | undefined>(undefined);
```

Replace the two-song render block:

```tsx
{
  songs.length === 2 && (
    <MixMaker song1={songs[0]} song2={songs[1]} onMixReady={setMixId} />
  );
}
{
  songs.length === 2 && (
    <LiveMix song1Id={songs[0].id} song2Id={songs[1].id} mixId={mixId} />
  );
}
```

- [ ] **Step 6: Add the part-button styles** — append to `apps/web/src/components/Live/LiveMix.module.css` (non-test, additive; keep the existing `.on`/`.off` selectors working as buttons):

```css
.buses button {
  cursor: pointer;
  border: 1px solid #3d4a5c;
  border-radius: 999px;
  padding: 4px 12px;
  font: inherit;
}
.buses button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
```

(If `.on`/`.off` already set colors, they still apply — these rules only add shape/interactivity.)

- [ ] **Step 7: Run the web checks**

Run: `npm test -- LiveMix` then `npm test` then `npm run typecheck` then `npm run lint`
Expected: all PASS. Web tests: 18 prior + 3 (Task 4) + 1 (Task 5) = **22 passed**, with the LiveMix test updated (still 1 file, now asserting four parts).

- [ ] **Step 8: Commit**

```bash
git add apps/web/src/components/Live/LiveMix.tsx apps/web/src/components/Live/LiveMix.module.css apps/web/src/components/Mix/Mix.tsx apps/web/src/components/Uploader/Uploader.tsx apps/web/src/components/Live/LiveMix.test.tsx
git commit -m "feat(m5): LiveMix — four tappable parts tied to the current take"
```

---

### Task 7: Docs + full-suite verification

**Files:**

- Modify: `docs/functional-spec.md` (what the app does now)
- Modify: `docs/technical-spec.md` (how the live vocal bus works)
- Modify: `docs/implementation-plan.md` (M5 status + drift-log entry)

- [ ] **Step 1: Update the living docs** — in each, reflect Slice 2 as built:
  - **functional-spec.md** "What the app does TODAY": the live player now plays the full mix and every part (Beat/Bass/Melody/Vocals) toggles on the beat by tap or command, plus "drop everything but the beat"; the live player is a steerable approximation, the Download stays the polished master.
  - **technical-spec.md**: add the arranged-vocal-bus mechanism (`workers/live_stems.py` reuses render helpers; `/live/vocal-bus/{mix_id}`; browser loads it as a 4th bus; level = ratio 1.0, no normalize).
  - **implementation-plan.md**: M5 row → "Slices 1–2 built"; append a drift-log entry dated 2026-07-06 summarizing Slice 2 and the logged non-blockers (stateless parser; vocal-bus WAVs join the cache-eviction backlog; async-job pattern now in a 4th route).

- [ ] **Step 2: Run the FULL suites**

Run: `cd services/api && ./.venv/Scripts/python.exe -m pytest -q` then from repo root `npm test && npm run typecheck && npm run lint`
Expected: backend **149 passed**, web **22 passed**, typecheck + lint clean. (171 total.)

- [ ] **Step 3: Commit**

```bash
git add docs/functional-spec.md docs/technical-spec.md docs/implementation-plan.md
git commit -m "docs(m5): Slice 2 as-built — full live mix, all parts controllable"
```

---

## Self-Review

**Spec coverage:** backend vocal bus (Task 2) ✓; vocal-bus route (Task 3) ✓; four buses in browser (Tasks 5–6) ✓; every part switchable by tap + command (Task 6) ✓; multi-target ops + "drop everything but the beat"/"bring it all back" (Tasks 1,4) ✓; "Vocals" = Song 2 + Song 1 contrast (Task 2 contrast loop + test) ✓; regenerate tie-in (Task 6, mixId re-load) ✓; no-mix-yet graceful (Task 6, vocals disabled) ✓; approximation, not the sweep/breath (Task 2 skips bed effects; noted) ✓; render.py/validate.py untouched (Global Constraints) ✓; additive contracts ✓.

**Placeholder scan:** none — every code step shows full code. (The `fetchVocalBus` poll-delay note in Task 5 Step 1 is an explicit design choice, not a TODO.)

**Type consistency:** `BusName` gains `"vocals"` (Task 4) and is used consistently in `liveSchedule`, `liveAudio`, `LiveMix`. `LiveOp.targets`/`LiveOpDTO.targets` names match across backend + DTO. `render_vocal_bus` signature matches its route caller (Task 3) and tests (Task 2). `onMixReady`/`mixId` threading matches across Mix/Uploader/LiveMix.

**Dangerous-surface note:** the only protected files are the three web test files (Tasks 4–6, flagged **confirm-and-apply**). No edit to `render.py`, `validate.py`, `storage.py`, `songs.py`, config. Backend `test_*.py` and `.module.css` are not guarded.
