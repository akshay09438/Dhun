# M5 Slice 2 — The full mix, live, all parts controllable (design)

_Approved by the founder 2026-07-06. The second slice of M5 (lean live control): make the live player play the **whole** mix (Song 1's parts + Song 2's arranged vocal) and let **every** part mute/unmute on the beat. Builds directly on Slice 1 (`2026-07-06-m5-slice1-live-control-design.md`), which proved the on-beat live-steering engine with one command._

## Goal (acceptance)

Press play → hear the **full mix** playing live in the browser: Song 1's beat/bass/melody **and** Song 2's arranged vocal, in sync from t=0 → tap **Vocals** off (or type "remove the vocals") → the singing fades out over one bar, on the beat, the groove keeps going → type **"drop everything but the beat"** → everything but the drums fades out on the next bar → **"bring it all back"** → the full mix returns on the beat. Each part (Beat / Bass / Melody / Vocals) is independently switchable, on the beat, by tap or by typed command. The app replies in DJ language.

## The core architectural decision (settled last session)

The M4 mix is a **pre-rendered WAV** — a baked master; you cannot un-bake a part out of it to control it live. Slice 1 solved this for Song 1 by playing its already-served **stems** (drums/bass/other) in sync and ramping one bus's gain on a bar boundary. Slice 2 extends the same idea to the **vocal**.

**Chosen approach — the backend exports an "arranged-vocal bus"; the browser plays it as a fourth live part.** Do **not** rebuild the M4 arrangement (placements, per-bar warp, contrast answer, sweep, beat-breath) in the browser — that would duplicate the trusted engine in JS and risk not matching the approved render. Instead, a new backend module renders **just the arranged vocal on silence** using the _same_ engine helpers that build the Download, so the warp + fades + contrast are baked by the trusted code. The browser loads that one WAV as the **Vocals** bus alongside Song 1's stems, starts them all at the same `AudioContext` time (sample-accurate sync), and ramps any bus's gain on the beat — exactly the Slice-1 mechanism, now applied to any part.

**The live player is a steerable _approximation_, not a byte-copy of the Download (founder-approved).** Because the parts play at steady gain, the live mix omits two Download-only polish touches that are applied to the _bed_ during the single-file render: the filter **sweep** and the one-bar **beat-breath** duck before a big entry. The live player is the steering room; the **Download stays the polished master**. This is an honest, already-established divergence (Slice 1 design), not a regression.

**Invariants (unchanged, from the tech spec):** the music never stops (a "mute" ramps gain toward 0, never stops playback); nothing fires off-grid (every op schedules to the next bar boundary from Song 1's beatgrid).

## What counts as "Vocals" (decided)

The M4 arrangement has **two** singing voices that the referee already guarantees never overlap: Song 2's arranged vocal (the star) and Song 1's **own** vocal answering in a beat-only gap (the contrast move). The live **Vocals** bus contains **both** — so "Vocals" means _all the singing_, and "remove the vocals" yields a clean instrumental with nobody left singing. This is faithful (the two never overlap, by construction) and gives the user one clean mental model instead of a confusing 5th control.

## Slice 2 scope

IN:

- **Backend arranged-vocal bus.** A new module `workers/live_stems.py` (NOT a dangerous surface) renders the arrangement's vocal layer — Song 2's placed/warped/edge-faded vocal + Song 1's contrast-vocal regions — onto a **silent** buffer of the mix's full length, **reusing** `render.py`'s helpers (`_vocal_take`, `_vocal_take_warped`, `_edge_fade`, `_placements_of`, `SR`) via import. No peak-normalize-to-the-master, no sweep, no beat-breath duck (those are bed effects). Written to `data/` and cached, keyed to the mix's content id (same `mix_id` as the finished mix, so it always matches the current take).
- **Backend route** to serve it: `GET /live/vocal-bus/{mix_id}` → the WAV (async start-then-poll if it must render; served from cache once built). Derived from the **already-cached MixPlan** for that `mix_id` — no re-planning, no AI call.
- **Four live buses in the browser:** `drums` (Beat), `bass`, `other` (Melody), `vocals` (Song 2 arranged + Song 1 contrast). The `LivePlayer` loads the vocal-bus WAV in addition to the three stems and sync-starts all four.
- **Every part switchable on the beat**, by **tap** (the on/off dots become buttons) or by **typed command**, each a 1-bar equal-power gain ramp (reusing Slice-1's `schedule`).
- **Grown command set** (deterministic parser, LLM path still deferred behind the same fallback): remove/bring-back vocals; mute/unmute drums & melody; the **combo** "drop everything but the beat" (mute bass+other+vocals, keep drums) and "bring it all back" (unmute all). A LiveOp can now carry **multiple targets**.
- **DJ-language replies** for each, plus the existing out-of-scope decline.
- **Regenerate tie-in:** the live player reloads the current take's vocal bus, so what you steer matches what's shown.

OUT (later slices):

- The AI **judgment** layer: AI-decided mute _depth_ + context-aware suggestion buttons that change as the song plays (Slice 3, the founder's favorite).
- The remaining **energy** moves ("beat up", "fade away") — Slice 3.
- Live tempo/BPM change (V2, non-goal).
- Reproducing the sweep / beat-breath live (deliberately Download-only).

## Components

**Backend (`services/api` + `workers`):**

- `workers/live_stems.py` **(new, not dangerous)** — `render_vocal_bus(plan, song1_stems, song2_vocal, out_path) -> Path`: builds the arranged vocal layer on silence. Mirrors the vocal half of `render_mix` (same placement loop, warp branch, contrast loop, edge fades) but starts from `np.zeros` and skips the bed sum / normalize / sweep / breath. Imports the shared helpers from `workers.render` — does **not** edit `render.py`.
- `app/routes/live.py` **(additive)** — add `GET /live/vocal-bus/{mix_id}`: validates the hex id, loads the cached `MixPlan` + stem paths, calls `render_vocal_bus` (async start-then-poll, mirroring `mix.py`'s `_jobs` pattern; cache by a `.vocalbus.wav` sibling of the mix). 404/409 with plain-language preconditions if the plan/stems aren't ready.
- `app/models.py` **(additive)** — extend `LiveOp` with `targets: list[str] = []` (a command that names several parts). `target` stays for back-compat with Slice 1; the parser sets `targets` and, when it's a single part, `target` too.
- `app/planner/live.py` **(additive)** — extend `parse_command` to recognize the vocals / drums / melody / combo phrases and return multi-target ops. Keep the bass phrases and the decline. Still deterministic; LLM path deferred.

**Frontend (`apps/web`):**

- `src/lib/liveSchedule.ts` **(additive)** — add `"vocals"` to `BusName`; make `applyOp` handle `targets` (fold a multi-target op into the bus-state reducer); keep the pure next-bar / ramp math.
- `src/lib/liveAudio.ts` **(additive)** — `LivePlayer.load` also fetches the vocal-bus WAV for a given `mix_id`; `schedule` handles multi-target ops (ramp each named bus). Sync-start already covers any number of buses.
- `src/lib/api.ts` **(additive)** — a client helper + polling for the vocal-bus endpoint; extend `LiveOpDTO` with `targets`.
- `src/components/Live/LiveMix.tsx` **(additive)** — accept the current `mix_id` (or the song+prompt+take to derive it) so it loads the right take's vocals; render four **tappable** part buttons (Beat/Bass/Melody/Vocals) that fire the same on-beat ramp; reload the vocal bus when the take changes. Falls back to beat-only when no mix is ready.

## Data flow

mix ready (take N) → LiveMix knows `mix_id` → `LivePlayer.load` fetches Song 1's `drums/bass/other` stems **and** `GET /live/vocal-bus/{mix_id}` → all four buffers decoded → play → sync-start all four at one `ctx.currentTime` → user taps **Vocals** off (or types "remove the vocals") → (tap: local op; type: `POST /live/command` → `LiveOp{op:"mute", targets:["vocals"], say:"pulling the vocal on the next bar"}`) → `LivePlayer.schedule` computes the next downbeat and ramps the `vocals` gain 1→0 over one bar → status line shows the reply → the Vocals button flips off. "drop everything but the beat" → `targets:["bass","other","vocals"]` → three ramps on the same bar.

## Error / edge handling

- **No mix ready yet** → live player loads Song 1's stems only and runs beat-only (today's behavior); Vocals control is disabled with a hint until a mix exists.
- **Vocal-bus render not ready** → poll like the mix route; show "getting the vocal ready…" then enable Vocals.
- **Already in the asked state** ("remove the vocals" when they're already muted) → no-op with a plain reply (Slice-1 statelessness noted below).
- **Out-of-scope** ("add a third song", "make it faster") → decline, no audio change.
- **Beatgrid missing** → fall back to the next 2-second boundary (music never stops), as Slice 1.
- **No Web Audio / test DOM** → the whole live player degrades to "not ready" (Slice-1 try/catch guard), never crashes the page.

## Reuse, scale, and boundaries

- **No duplicated DSP.** `live_stems.py` imports the engine's helpers rather than re-implementing the warp/fade math — the single source of truth for "how a vocal is placed" stays in `render.py`. If a future change to the vocal path must touch `render.py` itself, that is the confirm-and-apply heavy path; this slice is designed to avoid it.
- **Cache the bus, don't recompute.** The vocal bus is keyed to `mix_id`, so it renders once per take and is served from disk after (mirrors the mix WAV). It joins the same **cache-eviction** backlog item as the mix WAVs (logged; the ~50-user-test sweep in `storage.py` will cover both) — noted so it isn't a surprise.
- **Additive contracts.** `LiveOp.targets` and the new `BusName` value extend, never rename — Slice-1 single-target ops still parse and behave.

## Not a dangerous surface (except the web tests)

New files (`workers/live_stems.py`) and **additive** edits to `models.py`, `planner/live.py`, `routes/live.py`, and the web `lib/*`, `components/Live/*`. **`render.py`, `validate.py`, `storage.py`, `songs.py`, config are NOT touched.** The one protected surface in play is the web `*.test.ts`/`*.test.tsx` files (test-harness guard) — adding Slice-2 tests needs founder confirm-and-apply, exactly as in Slice 1. It's "heavy" chiefly because it's a new architectural piece (a second live bus source + multi-target ops), so it gets this design + a plan before code.

## Testing

- **Backend:** `render_vocal_bus` produces a full-length buffer that is **silent outside** the plan's placements/contrast regions and **non-silent inside** them; honors warp vs global-stretch; never sums the bed. `parse_command`: "remove the vocals"/"bring the vocals back" → vocals mute/unmute; "drop everything but the beat" → mute [bass,other,vocals]; "bring it all back" → unmute all; drums/melody phrases; bass phrases still work; out-of-scope still declines. Route: vocal-bus 404 on bad id, 409 when the plan/stems aren't ready, serves the WAV when built.
- **Frontend (protected — confirm-and-apply):** pure pieces — `applyOp` with multi-target ops flips all named buses; `BusName` includes vocals; the next-bar/ramp math unchanged. `LiveMix` renders four tappable parts and reflects state (jsdom, no real Web Audio).
- **Acceptance (founder, on the running app):** the full-mix play + the taps/commands land on the beat and sound right.

## Open, non-blocking follow-ups (logged, not in this slice)

- Slice-1's stateless-parser quirk persists (a redundant "bring it back" still replies) — harmless; the AI layer in Slice 3 gives it live state.
- `liveAudio.schedule` snapshots instantaneous gain on rapid consecutive commands (inaudible one-at-a-time) — carried from Slice 1.
- Vocal-bus WAVs add to the mix-WAV cache-eviction debt — bundle into the pre-user-test `storage.py` sweep.
