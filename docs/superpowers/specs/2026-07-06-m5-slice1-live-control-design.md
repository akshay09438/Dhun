# M5 Slice 1 — Live control foundation (design)

_Approved by the founder 2026-07-06. The first slice of M5 (lean live control): make the playing mix steerable with words, proven with one command. Product scope was settled in conversation; this is the technical + UX design._

## Goal (acceptance)

Press play → hear Song 1's groove playing **live** in the browser → type **"take the bass out"** → the bass fades out over **one bar, on the beat**, everything else keeps playing → type **"bring it back"** → the bass swells back in on the beat. The app replies in DJ language ("dropping the bass on the next bar"). This proves the whole live-steering engine.

## The core architectural decision

The M4 mix is a **pre-rendered WAV** — a baked file; you cannot mute a part out of it. Live control requires playing the song's **separate parts in sync** and adjusting one part's volume on the beat.

**Chosen approach: play the ready-made stems in the browser** (not rebuild the arrangement in JS). Song 1's stems (drums/bass/other) already exist and are already served (M2a). The browser decodes them, starts them at the same `AudioContext` time (sample-accurate sync), routes each through its own `GainNode`, and ramps a bus's gain on a beat boundary to mute/unmute. Rejected alternative: reconstructing the full M4 arrangement (placements, per-bar warp, contrast, sweep) live in the browser — far more complex, and risks not matching the approved M4 render. Layering Song 2's _arranged_ vocal comes in a later slice (produced by the trusted backend engine as a pre-arranged vocal bus, so the browser never re-implements the warp).

**Invariants (from the tech spec):** the music never stops (a "mute" ramps gain toward 0, it never stops playback); nothing fires off-grid (every op is scheduled to the next bar boundary using Song 1's beatgrid).

## Slice 1 scope (deliberately minimal, honest)

IN:

- Browser **live stem player** for Song 1's instrumental buses: `drums`, `bass`, `other`, summed live = the groove.
- **On-beat scheduler** locked to Song 1's downbeats (from the cached analysis) — schedules an op to fire on the next bar.
- **One command pair**: "take the bass out" / "bring it back" (+ obvious synonyms), applied as a **1-bar equal-power fade** on the `bass` bus.
- **DJ-language reply** shown in a status line.
- **Part indicators** (small on/off dots per bus) so the muted part is visible.
- A backend **LiveOp** contract + `/live` route: plain-language command → structured op `{op: "mute"|"unmute", target: "bass", when: "next_bar"}`, with an **out-of-scope decline** for anything V1 can't do. The LLM plans the op (never touches audio); a deterministic keyword parser is the fallback and covers Slice 1's fixed commands offline.

OUT (later slices):

- Song 2's arranged vocal layered into the live player (Slice 1b / next) — via a backend "arranged vocal bus" export, not a browser rebuild.
- The other moves (drop-everything-but-the-beat, remove vocals, beat up, fade away).
- The AI **judgment** layer: AI-decided mute depth + the context-aware suggestion buttons (Slice 2).
- Live tempo/BPM change (V2, non-goal).

## Components

**Backend (`services/api`):**

- `app/models.py` — add `LiveOp` (Pydantic): `op` ("mute" | "unmute" | "decline"), `target` (bus name | null), `when` ("next_bar"), `say` (DJ-language reply string), `reason` (for a decline). Additive; no change to existing models.
- `app/planner/live.py` (new, not a dangerous surface) — `parse_command(text, context) -> LiveOp`: deterministic keyword parser for the lean command set + an out-of-scope decline; the LLM path (structured `LiveOp`) is layered behind it with the same deterministic fallback pattern as `plan.py`. Slice 1 wires only bass mute/unmute + decline.
- `app/routes/live.py` (new, not dangerous) — `POST /live/command {song1_id, song2_id, text}` → `LiveOp`. Stateless; the browser holds live playback state. Validates ids (hex) like the other routes.

**Frontend (`apps/web`):**

- `src/lib/liveAudio.ts` — the Web Audio engine: load+decode Song 1 stems, a per-bus `GainNode` graph, `play()/pause()`, `scheduleOp(op, beatgrid)` that computes the next bar time and ramps the target bus's gain over one bar (equal-power). Pure-ish, unit-testable (next-bar math + ramp params extracted).
- `src/components/Live/LiveMix.tsx` — the mix screen: play/pause, the command text box, the status line (DJ reply), the per-bus on/off indicators. Calls `/live/command`, then `liveAudio.scheduleOp`.
- Reuse the existing stems/analysis API client helpers.

## Data flow

play → `liveAudio` starts all Song 1 buses in sync → user types "take the bass out" → `POST /live/command` → `LiveOp{op:"mute",target:"bass",when:"next_bar",say:"dropping the bass on the next bar"}` → `liveAudio.scheduleOp` computes the next downbeat from the beatgrid and ramps `bass` gain 1→0 over one bar → status line shows the reply → the `bass` indicator flips off.

## Error / edge handling

- **Out-of-scope command** (e.g. "add a third song", "make it faster") → `LiveOp{op:"decline", say:"I can't do that in this version — try 'take the bass out' or 'bring it back'."}`. No audio change.
- **Command with no clean runway / already in that state** ("bring it back" when bass is on) → no-op with a plain reply.
- **Missing stems/analysis** → the screen says what's needed (mirrors the mix route's plain-language preconditions).
- **AI/LLM unavailable** → deterministic parser still handles the lean set (never blocks).
- **Beatgrid missing** → fall back to firing on the next 2-second boundary (music never stops; still not jarring).

## Testing

- Backend: `parse_command` tests — "take the bass out"/"drop the bass" → mute bass; "bring it back" → unmute; out-of-scope → decline; route returns the op for valid ids, 404 on bad ids.
- Frontend: unit-test the pure pieces of `liveAudio` — next-bar time from a beatgrid + current time; the equal-power ramp values; the reducer that flips bus on/off state. (The raw Web Audio playback is verified by ear in the founder acceptance, not unit-tested.)
- Acceptance (founder, on the running app): the bass drops on the beat and returns, smoothly.

## Not a dangerous surface

New files (`routes/live.py`, `planner/live.py`, `lib/liveAudio.ts`, `components/Live/*`) and an additive `LiveOp` model. No edit to `render.py`, `validate.py`, `storage.py`, `songs.py`, or config. Standard light-ish build with tests; heavy only in that it's a new architectural subsystem (real-time browser audio), so it gets a design (this doc) + a plan before code.
