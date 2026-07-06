# M5 Slice 1 — Live Control Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Play Song 1's stems live in the browser and make "take the bass out / bring it back" land on the beat with a smooth 1-bar fade, replying in DJ language — proving the live-steering engine.

**Architecture:** The browser plays Song 1's already-served stems (drums/bass/other) through the raw Web Audio API — one `AudioBufferSourceNode` + `GainNode` per bus, all started at the same `AudioContext` time so they stay sample-accurate in sync. A typed command hits a new backend `/live/command` route that returns a structured `LiveOp` (LLM plans; deterministic keyword parser is the fallback and covers Slice 1 offline). The browser schedules the op on the next downbeat (from the cached beatgrid) by ramping the target bus's gain over one bar. The music never stops (mute = gain→0, never a stop); nothing fires off-grid.

**Tech Stack:** Backend FastAPI + Pydantic v2 (pytest). Frontend React 18 + Vite + TypeScript, **raw Web Audio API — no Tone.js/wavesurfer** (not installed; not needed for this slice) (vitest).

## Global Constraints

- No dangerous-surface files are touched: only new files (`app/planner/live.py`, `app/routes/live.py`, `apps/web/src/lib/liveAudio.ts`, `apps/web/src/components/Live/*`) and an additive `LiveOp` model in `app/models.py`. Do NOT edit `render.py`, `validate.py`, `storage.py`, `routes/songs.py`, or config.
- LLM never touches audio; it only fills a structured `LiveOp`. Every command path has a deterministic fallback so live control never blocks on the AI (mirror the pattern in `services/api/app/planner/plan.py`).
- Song 1 buses this slice: `drums`, `bass`, `other` (the instrumental bed). Stems are served at `GET /songs/{id}/stems/{stem}` (see `app/routes/stems.py`).
- One bar = `60 / bpm * 4` seconds (4/4, as everywhere else in the app).
- Route id validation: reuse the hex-id guard pattern (`[0-9a-f]{64}`) used in `routes/mix.py`.
- Backend tests: `services/api/.venv/Scripts/python -m pytest`. Web tests: `npm test` (from repo root) or `npm -w apps/web run test`.

---

### Task 1: `LiveOp` model + deterministic command parser

**Files:**

- Modify: `services/api/app/models.py` (append `LiveOp`)
- Create: `services/api/app/planner/live.py`
- Test: `services/api/tests/test_live.py`

**Interfaces:**

- Produces: `LiveOp` pydantic model with fields `op: str` ("mute" | "unmute" | "decline"), `target: str | None`, `when: str = "next_bar"`, `say: str = ""`, `reason: str | None = None`. `parse_command(text: str) -> LiveOp`.

- [ ] **Step 1: Write the failing test**

```python
# services/api/tests/test_live.py
from app.planner.live import parse_command


def test_take_the_bass_out_mutes_bass():
    op = parse_command("take the bass out")
    assert op.op == "mute" and op.target == "bass" and op.when == "next_bar"
    assert "bass" in op.say.lower()


def test_drop_the_bass_is_also_a_mute():
    assert parse_command("drop the bass").op == "mute"


def test_bring_it_back_unmutes():
    op = parse_command("bring it back")
    assert op.op == "unmute" and op.target == "bass"


def test_out_of_scope_is_declined_plainly():
    op = parse_command("add a third song")
    assert op.op == "decline" and op.target is None
    assert op.say  # a plain-language message pointing at what V1 can do


def test_empty_command_declines():
    assert parse_command("   ").op == "decline"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `services/api/.venv/Scripts/python -m pytest tests/test_live.py -v` (from `services/api`)
Expected: FAIL — `ModuleNotFoundError: app.planner.live`.

- [ ] **Step 3: Write minimal implementation**

Append to `services/api/app/models.py`:

```python
class LiveOp(BaseModel):
    """One live steering instruction the browser executes on the beat.

    The brain (deterministic parser now; the LLM later) turns a typed command into
    this structured op; the browser schedules it on the next bar. The LLM never
    touches audio — it only fills this. op is "mute" | "unmute" | "decline".
    """

    op: str
    target: str | None = None  # which bus: "bass" | "drums" | "other" | ...
    when: str = "next_bar"
    say: str = ""  # DJ-language reply shown to the user
    reason: str | None = None  # why a command was declined (out of scope)
```

Create `services/api/app/planner/live.py`:

```python
"""The live driver: turn a plain-language steering command into a structured LiveOp.

Slice 1 is a deterministic keyword parser for the lean command set; an LLM path will
sit in front of it later with this same function as the fallback (mirrors planner.plan).
The op is executed by the browser on the beat — this module never touches audio.
"""

from __future__ import annotations

from app.models import LiveOp

# Phrases that mean "remove Song 1's bassline", and "restore it".
_MUTE_BASS = ("take the bass out", "drop the bass", "bass out", "kill the bass", "no bass")
_UNMUTE = ("bring it back", "bring the bass back", "bass back", "back to normal", "undo")


def parse_command(text: str) -> LiveOp:
    """Map a typed command to a LiveOp. Unknown/out-of-scope asks are declined plainly."""
    t = " ".join(text.lower().split())
    if not t:
        return LiveOp(op="decline", say="Type a command like 'take the bass out'.")
    if any(p in t for p in _UNMUTE):
        return LiveOp(op="unmute", target="bass", say="bringing the bass back on the next bar")
    if any(p in t for p in _MUTE_BASS):
        return LiveOp(op="mute", target="bass", say="dropping the bass on the next bar")
    return LiveOp(
        op="decline",
        say="I can't do that in this version — try 'take the bass out' or 'bring it back'.",
        reason="out of scope",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `services/api/.venv/Scripts/python -m pytest tests/test_live.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add services/api/app/models.py services/api/app/planner/live.py services/api/tests/test_live.py
git commit -m "feat(m5): LiveOp model + deterministic command parser (bass mute/unmute/decline)"
```

---

### Task 2: `/live` routes — command + timing context

**Files:**

- Create: `services/api/app/routes/live.py`
- Modify: `services/api/app/main.py` (register the router — follow how `mix`/`stems` routers are included)
- Test: `services/api/tests/test_live_route.py`

**Interfaces:**

- Consumes: `parse_command` (Task 1); `analysis_path` + cached analysis JSON (see `app/routes/mix.py::_load_analysis`).
- Produces: `POST /live/command {song1_id, song2_id, text}` → `LiveOp` JSON. `GET /live/context/{song1_id}` → `{"bpm": float, "downbeats": list[float]}` (from the cached analysis; the browser schedules on these).

- [ ] **Step 1: Write the failing test**

```python
# services/api/tests/test_live_route.py
import json
from fastapi.testclient import TestClient
from app.main import app
from app.audio.analysis import analysis_path

client = TestClient(app)
HEX = "a" * 64


def _seed_analysis(song_id, bpm=120.0, downbeats=(0.0, 2.0, 4.0)):
    analysis_path(song_id).write_text(json.dumps(
        {"song_id": song_id, "bpm": bpm, "downbeats": list(downbeats),
         "beats": [], "phrase_starts": [], "sections": [], "energy_curve": [],
         "vocal_regions": []}))


def test_command_returns_a_liveop():
    r = client.post("/live/command", json={"song1_id": HEX, "song2_id": HEX, "text": "take the bass out"})
    assert r.status_code == 200
    body = r.json()
    assert body["op"] == "mute" and body["target"] == "bass"


def test_command_declines_out_of_scope():
    r = client.post("/live/command", json={"song1_id": HEX, "song2_id": HEX, "text": "make it faster"})
    assert r.json()["op"] == "decline"


def test_bad_song_id_is_404():
    r = client.post("/live/command", json={"song1_id": "nothex", "song2_id": HEX, "text": "x"})
    assert r.status_code == 404


def test_context_returns_bpm_and_downbeats():
    _seed_analysis(HEX, bpm=124.0, downbeats=(0.5, 2.5, 4.5))
    r = client.get(f"/live/context/{HEX}")
    assert r.status_code == 200
    assert r.json()["bpm"] == 124.0 and r.json()["downbeats"][0] == 0.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `services/api/.venv/Scripts/python -m pytest tests/test_live_route.py -v`
Expected: FAIL — 404 on `/live/command` (route not registered).

- [ ] **Step 3: Write minimal implementation**

Create `services/api/app/routes/live.py`:

```python
"""Routes for live steering: turn a typed command into a LiveOp, and serve the beatgrid
the browser schedules on. Stateless — the browser holds live playback state."""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.audio.analysis import analysis_path
from app.models import LiveOp
from app.planner.live import parse_command

router = APIRouter()
_HEX_ID = re.compile(r"[0-9a-f]{64}")


class LiveCommand(BaseModel):
    song1_id: str
    song2_id: str
    text: str = ""


class LiveContext(BaseModel):
    bpm: float | None = None
    downbeats: list[float] = []


@router.post("/live/command")
def live_command(cmd: LiveCommand) -> LiveOp:
    for sid in (cmd.song1_id, cmd.song2_id):
        if not _HEX_ID.fullmatch(sid):
            raise HTTPException(404, "Song not found.")
    return parse_command(cmd.text)


@router.get("/live/context/{song1_id}")
def live_context(song1_id: str) -> LiveContext:
    if not _HEX_ID.fullmatch(song1_id):
        raise HTTPException(404, "Not found.")
    p = analysis_path(song1_id)
    if not p.exists():
        raise HTTPException(409, "Song 1 hasn't been analyzed yet.")
    a = json.loads(p.read_text())
    return LiveContext(bpm=a.get("bpm"), downbeats=a.get("downbeats", []))
```

Register in `services/api/app/main.py` (match the existing `include_router` calls):

```python
from app.routes import live  # noqa
app.include_router(live.router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `services/api/.venv/Scripts/python -m pytest tests/test_live_route.py -v`
Expected: PASS (4 passed). Then run the full backend suite to confirm no regression: `services/api/.venv/Scripts/python -m pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/routes/live.py services/api/app/main.py services/api/tests/test_live_route.py
git commit -m "feat(m5): /live/command (-> LiveOp) and /live/context (bpm + downbeats) routes"
```

---

### Task 3: Frontend API client — live command + context

**Files:**

- Modify: `apps/web/src/lib/api.ts` (append)
- Test: `apps/web/src/lib/api.test.ts` (append; follow the existing `fetch`-mock style)

**Interfaces:**

- Produces: `type LiveOpDTO = { op: "mute"|"unmute"|"decline"; target: string|null; when: string; say: string; reason: string|null }`. `type LiveContextDTO = { bpm: number|null; downbeats: number[] }`. `postLiveCommand(song1Id, song2Id, text): Promise<LiveOpDTO>`. `getLiveContext(song1Id): Promise<LiveContextDTO>`.

- [ ] **Step 1: Write the failing test** (append to `api.test.ts`)

```typescript
import { postLiveCommand, getLiveContext } from "./api";

test("postLiveCommand returns the parsed op", async () => {
  vi.spyOn(global, "fetch").mockResolvedValue({
    ok: true,
    json: async () => ({
      op: "mute",
      target: "bass",
      when: "next_bar",
      say: "dropping the bass",
      reason: null,
    }),
  } as Response);
  const op = await postLiveCommand(
    "a".repeat(64),
    "b".repeat(64),
    "take the bass out",
  );
  expect(op.op).toBe("mute");
  expect(op.target).toBe("bass");
});

test("getLiveContext returns bpm and downbeats", async () => {
  vi.spyOn(global, "fetch").mockResolvedValue({
    ok: true,
    json: async () => ({ bpm: 122, downbeats: [0, 2, 4] }),
  } as Response);
  const ctx = await getLiveContext("a".repeat(64));
  expect(ctx.bpm).toBe(122);
  expect(ctx.downbeats).toEqual([0, 2, 4]);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm -w apps/web run test -- api.test.ts`
Expected: FAIL — `postLiveCommand is not exported`.

- [ ] **Step 3: Write minimal implementation** (append to `api.ts`)

```typescript
export type LiveOpDTO = {
  op: "mute" | "unmute" | "decline";
  target: string | null;
  when: string;
  say: string;
  reason: string | null;
};

export type LiveContextDTO = { bpm: number | null; downbeats: number[] };

/** Turn a typed steering command into a structured op the player runs on the beat. */
export async function postLiveCommand(
  song1Id: string,
  song2Id: string,
  text: string,
): Promise<LiveOpDTO> {
  const res = await fetch(`${API_BASE}/live/command`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ song1_id: song1Id, song2_id: song2Id, text }),
  });
  if (!res.ok) throw new Error("Couldn't run that command.");
  return res.json();
}

/** The beatgrid the live player schedules on (Song 1's tempo + downbeats). */
export async function getLiveContext(song1Id: string): Promise<LiveContextDTO> {
  const res = await fetch(`${API_BASE}/live/context/${song1Id}`);
  if (!res.ok) throw new Error("Couldn't load the beat map.");
  return res.json();
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm -w apps/web run test -- api.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/lib/api.ts apps/web/src/lib/api.test.ts
git commit -m "feat(m5): web api client for /live/command and /live/context"
```

---

### Task 4: Pure live-scheduling logic (no Web Audio, fully unit-tested)

**Files:**

- Create: `apps/web/src/lib/liveSchedule.ts`
- Test: `apps/web/src/lib/liveSchedule.test.ts`

**Interfaces:**

- Produces:
  - `barSeconds(bpm: number): number` — `60/bpm*4`.
  - `nextBarTime(downbeats: number[], songTime: number, bpm: number): number` — the first downbeat strictly after `songTime`; if none/empty, `songTime` rounded up to the next `barSeconds` multiple.
  - `type BusName = "drums" | "bass" | "other"`.
  - `type BusState = Record<BusName, boolean>` (true = audible).
  - `applyOp(state: BusState, op: {op: string; target: string|null}): BusState` — pure reducer (mute→false, unmute→true; decline/unknown target → unchanged).
  - `rampTarget(op: {op: string}): number` — the gain a mute/unmute ramps toward (mute→0, unmute→1).

- [ ] **Step 1: Write the failing test**

```typescript
// apps/web/src/lib/liveSchedule.test.ts
import { barSeconds, nextBarTime, applyOp, rampTarget } from "./liveSchedule";

test("barSeconds is one 4/4 bar", () => {
  expect(barSeconds(120)).toBeCloseTo(2.0);
});

test("nextBarTime picks the next real downbeat", () => {
  expect(nextBarTime([0, 2, 4, 6], 2.3, 120)).toBe(4);
});

test("nextBarTime falls back to bpm grid when no downbeats", () => {
  expect(nextBarTime([], 2.3, 120)).toBeCloseTo(4.0); // next 2s multiple after 2.3
});

test("applyOp mutes and unmutes the target bus only", () => {
  const s = { drums: true, bass: true, other: true };
  expect(applyOp(s, { op: "mute", target: "bass" })).toEqual({
    drums: true,
    bass: false,
    other: true,
  });
  expect(
    applyOp({ ...s, bass: false }, { op: "unmute", target: "bass" }).bass,
  ).toBe(true);
  expect(applyOp(s, { op: "decline", target: null })).toEqual(s);
});

test("rampTarget is 0 for mute, 1 for unmute", () => {
  expect(rampTarget({ op: "mute" })).toBe(0);
  expect(rampTarget({ op: "unmute" })).toBe(1);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm -w apps/web run test -- liveSchedule.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

```typescript
// apps/web/src/lib/liveSchedule.ts
export type BusName = "drums" | "bass" | "other";
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

export function applyOp(
  state: BusState,
  op: { op: string; target: string | null },
): BusState {
  if (
    (op.op !== "mute" && op.op !== "unmute") ||
    !op.target ||
    !(op.target in state)
  )
    return state;
  return { ...state, [op.target as BusName]: op.op === "unmute" };
}

export function rampTarget(op: { op: string }): number {
  return op.op === "unmute" ? 1 : 0;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm -w apps/web run test -- liveSchedule.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/lib/liveSchedule.ts apps/web/src/lib/liveSchedule.test.ts
git commit -m "feat(m5): pure live-scheduling logic (next-bar time, bus reducer, ramp target)"
```

---

### Task 5: The Web Audio engine (`liveAudio.ts`) — wraps the pure logic

**Files:**

- Create: `apps/web/src/lib/liveAudio.ts`
- (No unit test — raw Web Audio isn't available in jsdom; verified by ear in the founder acceptance. All decision logic lives in the Task-4 pure module, which IS tested.)

**Interfaces:**

- Consumes: `barSeconds`, `nextBarTime`, `rampTarget` (Task 4); `API_BASE` (api.ts); stems at `${API_BASE}/songs/${song1Id}/stems/${bus}`.
- Produces: `class LivePlayer` with `load(song1Id, buses: BusName[]): Promise<void>`, `play(): void`, `pause(): void`, `songTime(): number`, `schedule(op: LiveOpDTO, ctx: LiveContextDTO): void`, `dispose(): void`.

- [ ] **Step 1: Implement** (no test-first; this is the thin, untestable Web Audio wrapper — keep ALL logic in Task 4)

```typescript
// apps/web/src/lib/liveAudio.ts
import { API_BASE, type LiveOpDTO, type LiveContextDTO } from "./api";
import {
  barSeconds,
  nextBarTime,
  rampTarget,
  type BusName,
} from "./liveSchedule";

export class LivePlayer {
  private ctx = new AudioContext();
  private buffers = new Map<BusName, AudioBuffer>();
  private gains = new Map<BusName, GainNode>();
  private sources = new Map<BusName, AudioBufferSourceNode>();
  private startCtxTime = 0; // ctx.currentTime when playback (song time 0) began
  private playing = false;

  async load(song1Id: string, buses: BusName[]): Promise<void> {
    await Promise.all(
      buses.map(async (bus) => {
        const res = await fetch(`${API_BASE}/songs/${song1Id}/stems/${bus}`);
        const buf = await this.ctx.decodeAudioData(await res.arrayBuffer());
        this.buffers.set(bus, buf);
        const g = this.ctx.createGain();
        g.gain.value = 1;
        g.connect(this.ctx.destination);
        this.gains.set(bus, g);
      }),
    );
  }

  play(): void {
    if (this.playing) return;
    this.startCtxTime = this.ctx.currentTime + 0.1; // small lead so all sources start together
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

  /** Schedule a mute/unmute on the next bar, ramped smoothly over one bar. */
  schedule(op: LiveOpDTO, ctx: LiveContextDTO): void {
    if ((op.op !== "mute" && op.op !== "unmute") || !op.target) return;
    const g = this.gains.get(op.target as BusName);
    if (!g) return;
    const bpm = ctx.bpm ?? 120;
    const barSong = nextBarTime(ctx.downbeats, this.songTime(), bpm);
    const startCtx = this.startCtxTime + barSong; // song time -> ctx time
    const target = rampTarget(op);
    g.gain.cancelScheduledValues(startCtx);
    g.gain.setValueAtTime(g.gain.value, startCtx);
    g.gain.linearRampToValueAtTime(target, startCtx + barSeconds(bpm)); // smooth 1-bar fade
  }

  dispose(): void {
    this.pause();
    this.ctx.close();
  }
}
```

- [ ] **Step 2: Typecheck**

Run: `npm -w apps/web run typecheck`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/lib/liveAudio.ts
git commit -m "feat(m5): LivePlayer Web Audio engine (sync stem playback + on-beat gain ramp)"
```

---

### Task 6: `LiveMix` screen + wire into the app

**Files:**

- Create: `apps/web/src/components/Live/LiveMix.tsx`
- Create: `apps/web/src/components/Live/LiveMix.module.css`
- Test: `apps/web/src/components/Live/LiveMix.test.tsx`
- Modify: `apps/web/src/App.tsx` (render `LiveMix` when both songs are analyzed+split — follow how `Mix` is currently rendered/gated)

**Interfaces:**

- Consumes: `LivePlayer` (Task 5), `postLiveCommand` + `getLiveContext` (Task 3), `applyOp` + `BusState` (Task 4).
- Props: `LiveMix({ song1Id, song2Id }: { song1Id: string; song2Id: string })`.
- The component keeps `busState: BusState`, a `status` string (the DJ reply), and a `LivePlayer` in a ref. On submit: `postLiveCommand` → set status to `op.say` → `player.schedule(op, ctx)` → `setBusState(applyOp(busState, op))`.

- [ ] **Step 1: Write the failing test** (mock the network + the player so the test is pure DOM behavior)

```typescript
// apps/web/src/components/Live/LiveMix.test.tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import LiveMix from "./LiveMix";
import * as api from "../../lib/api";

vi.mock("../../lib/liveAudio", () => ({
  LivePlayer: class {
    load = vi.fn().mockResolvedValue(undefined);
    play = vi.fn();
    pause = vi.fn();
    schedule = vi.fn();
    songTime = () => 0;
    dispose = vi.fn();
  },
}));

test("typing 'take the bass out' shows the DJ reply and flips the bass indicator off", async () => {
  vi.spyOn(api, "getLiveContext").mockResolvedValue({ bpm: 120, downbeats: [0, 2, 4] });
  vi.spyOn(api, "postLiveCommand").mockResolvedValue({
    op: "mute", target: "bass", when: "next_bar", say: "dropping the bass on the next bar", reason: null,
  });

  render(<LiveMix song1Id={"a".repeat(64)} song2Id={"b".repeat(64)} />);
  fireEvent.change(screen.getByPlaceholderText(/take the bass out/i), { target: { value: "take the bass out" } });
  fireEvent.submit(screen.getByRole("form", { name: /command/i }));

  await waitFor(() => expect(screen.getByText(/dropping the bass/i)).toBeInTheDocument());
  expect(screen.getByTestId("bus-bass").getAttribute("data-on")).toBe("false");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm -w apps/web run test -- LiveMix.test.tsx`
Expected: FAIL — `LiveMix` not found.

- [ ] **Step 3: Write minimal implementation**

```tsx
// apps/web/src/components/Live/LiveMix.tsx
import { useEffect, useRef, useState } from "react";
import { LivePlayer } from "../../lib/liveAudio";
import {
  postLiveCommand,
  getLiveContext,
  type LiveContextDTO,
} from "../../lib/api";
import { applyOp, type BusState, type BusName } from "../../lib/liveSchedule";
import styles from "./LiveMix.module.css";

const BUSES: BusName[] = ["drums", "bass", "other"];

export default function LiveMix({
  song1Id,
  song2Id,
}: {
  song1Id: string;
  song2Id: string;
}) {
  const playerRef = useRef<LivePlayer | null>(null);
  const ctxRef = useRef<LiveContextDTO>({ bpm: 120, downbeats: [] });
  const [ready, setReady] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [busState, setBusState] = useState<BusState>({
    drums: true,
    bass: true,
    other: true,
  });
  const [status, setStatus] = useState("");
  const [text, setText] = useState("");

  useEffect(() => {
    const p = new LivePlayer();
    playerRef.current = p;
    Promise.all([p.load(song1Id, BUSES), getLiveContext(song1Id)]).then(
      ([, ctx]) => {
        ctxRef.current = ctx;
        setReady(true);
      },
    );
    return () => p.dispose();
  }, [song1Id]);

  function togglePlay() {
    const p = playerRef.current!;
    if (playing) {
      p.pause();
      setPlaying(false);
    } else {
      p.play();
      setPlaying(true);
    }
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    const op = await postLiveCommand(song1Id, song2Id, text);
    setStatus(op.say);
    if (op.op === "mute" || op.op === "unmute") {
      playerRef.current!.schedule(op, ctxRef.current);
      setBusState((s) => applyOp(s, op));
    }
    setText("");
  }

  return (
    <div className={styles.live}>
      <button onClick={togglePlay} disabled={!ready}>
        {playing ? "Pause" : "Play"}
      </button>
      <div className={styles.buses}>
        {BUSES.map((b) => (
          <span
            key={b}
            data-testid={`bus-${b}`}
            data-on={busState[b]}
            className={busState[b] ? styles.on : styles.off}
          >
            {b}
          </span>
        ))}
      </div>
      <form aria-label="command" onSubmit={onSubmit}>
        <input
          placeholder="Try: take the bass out"
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

`LiveMix.module.css` (minimal; the design polish pass comes with the UI/UX skill in a later slice):

```css
.live {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.buses {
  display: flex;
  gap: 8px;
}
.on {
  opacity: 1;
  font-weight: 600;
}
.off {
  opacity: 0.35;
  text-decoration: line-through;
}
.status {
  min-height: 1.4em;
  color: #444;
}
```

Then render it in `App.tsx` where the mix is shown today (gate on both songs analyzed+split, same condition as the current `Mix`).

- [ ] **Step 4: Run test to verify it passes**

Run: `npm -w apps/web run test -- LiveMix.test.tsx`
Expected: PASS. Then `npm -w apps/web run typecheck` and `npm -w apps/web run lint` — both PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/components/Live apps/web/src/App.tsx
git commit -m "feat(m5): LiveMix screen — play, typed command, DJ reply, bus indicators"
```

---

### Task 7: Full-suite green + founder acceptance

- [ ] **Step 1:** Backend suite green: `services/api/.venv/Scripts/python -m pytest -q`.
- [ ] **Step 2:** Web green: `npm run typecheck && npm run lint && npm test` (from repo root).
- [ ] **Step 3:** Restart the backend (so `/live/*` is registered) and open the web app. Founder acceptance (test sheet):
  1. Load the two cached songs, make sure Song 1 is split + analyzed, open the live mix screen, press **Play** → you hear the groove.
  2. Type **"take the bass out"** → within a bar, the bass smoothly fades out on the beat, drums keep going; status shows "dropping the bass on the next bar"; the `bass` indicator dims.
  3. Type **"bring it back"** → the bass swells back in on the beat; indicator brightens.
  4. Type **"add a third song"** → polite decline, no audio change.
- [ ] **Step 4:** Update the living docs in the same PR: `docs/implementation-plan.md` (M5 Slice 1 done + drift-log note), `docs/technical-spec.md` (the live-control subsystem as-built), `docs/functional-spec.md` ("what the app does today" — the mix screen now takes live commands).

---

## Self-Review

- **Spec coverage:** live stem player (T5), on-beat scheduler (T4 `nextBarTime` + T5 `schedule`), one command pair (T1 parser, T6 wiring), DJ-language reply (T1 `say`, T6 status), part indicators (T6), LiveOp + `/live` route + out-of-scope decline (T1, T2), beatgrid context (T2, T3) — all covered. OUT-of-scope items (Song 2 vocal layering, other moves, AI judgment/buttons, tempo) are correctly deferred and not in any task.
- **Placeholder scan:** none — every code step is complete.
- **Type consistency:** `LiveOpDTO`/`LiveContextDTO` (T3) match the backend `LiveOp`/`LiveContext` (T1/T2); `BusName`/`BusState`/`applyOp` (T4) are consumed unchanged in T5/T6; `LivePlayer` method names (`load/play/pause/songTime/schedule/dispose`) match between T5 and the T6 mock + usage.
