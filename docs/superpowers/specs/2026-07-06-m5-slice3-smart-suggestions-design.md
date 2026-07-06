# M5 Slice 3 — AI smart-suggestion buttons + "fade away" (design)

_Approved by the founder 2026-07-06. The third slice of M5 (lean live control): as the mix plays, surface 1–3 **context-aware suggestion chips** that change with the song's sections, each applying an on-beat move; plus the **"fade away"** energy move. Builds on Slice 2 (four tappable parts, on-beat ramps). Scope decision: the AI shows up **only as suggestions** — the user's own taps/typed commands stay predictable; and "beat up" is deferred to a small follow-up (its musical meaning needs its own definition)._

## Goal (acceptance)

Press play → the live player shows **1–3 tappable suggestion chips** for the current part of the song (e.g. "Bring the vocal in", "Drop to just the beat", "Fade it out"). As the playhead crosses into the next section (verse → chorus → …), the chips **change** to suit it. Tapping a chip lands its move **on the next beat** (reusing Slice 2's scheduler). **"Fade it out"** (or typing "fade away") ramps the whole mix down to silence over ~4 bars; "bring it all back" restores it. The user's own four part controls and typed commands are unchanged and predictable.

## The core idea

The M4 arranger already points Claude at a song's structure to make **offline** decisions among rule-vetted options, with a deterministic fallback (see `planner/plan.py`). Slice 3 reuses that exact pattern for the **live** moment: point the brain at Song 1's **section timeline** and ask, per section, for 1–3 good moves — but the brain only ever picks from a **closed set of moves we already support** (mute/unmute a part, drop-to-the-beat, bring-it-all-back, fade away). It never invents audio, never sets a partial volume, never runs per-beat. One call per mix, cached.

**Why per-section, pre-computed (not per-beat):** a live AI call every beat would be slow, costly, and jittery. Sections are the natural granularity of a DJ decision ("the chorus is coming — bring the vocal in"), they're already in the analysis, and one cached call keeps it instant and cheap. Rejected alternative: live per-beat AI (latency + cost + non-determinism, no upside at this scale).

**Invariants (unchanged):** the user stays in control (chips only _suggest_; taps/commands do exactly what they say); every move lands on the next bar boundary; the music never fully stops (fade ramps gain toward 0, playback continues).

## Scope

IN:

- **Suggestion brain** (`app/planner/suggest.py`, new — NOT dangerous): one Claude call per mix returns, for each of Song 1's sections, 1–3 chips drawn from a **closed move vocabulary**; a deterministic fallback maps section labels → sensible chips so it works with no AI/key. Cached per `mix_id`. Same LLM-plans-JSON / rules-fallback pattern as `plan.py` — never touches audio.
- **Route** (`app/routes/live.py`, additive): `GET /live/suggestions/{mix_id}` → `{sections: [{start, end, label, chips: [{text, op, targets}]}]}`. Computed **synchronously on first request** (one fast LLM call, instant fallback) and cached to `{mix_id}.suggestions.json`. Derived from the cached `MixPlan` (→ `song1_id`) + Song 1's analysis sections. 404 bad id, 409 if the mix plan / analysis isn't ready.
- **The "fade away" move** — a new `LiveOp` op kind `"fade"` (targets = all buses), ramped over ~4 bars. Added to the typed parser ("fade away"/"fade it out"/"fade out") **and** available as a chip. Additive to `LiveOp`/scheduler.
- **Web — suggestions in the player**: fetch suggestions when a mix exists; a light playhead poll picks the **current section's chips**; render them as tappable chips; tapping applies the chip's op via the shared on-beat path. `applyOp`/`schedule` learn the multi-bar `"fade"`.

OUT (later):

- **"beat up"** (raise energy) — deferred; define its sound first (drums-up vs a short build) in a small follow-up.
- **Live-state-aware suggestions** (chips that know exactly what's currently muted) — V1 chips are per-section only; tapping an already-active move is a gentle no-op.
- **Partial-volume "depth"** on direct commands — the user chose "I stay in control"; chips use only full mute/unmute/fade moves, no new gain machinery.
- Live tempo/BPM change (V2, non-goal).

## The closed move vocabulary (what a chip can be)

Every chip maps to a move Slice 1–3 already execute, so the brain never invents audio:

| Chip text             | op     | targets                      |
| --------------------- | ------ | ---------------------------- |
| Bring the vocal in    | unmute | [vocals]                     |
| Take the vocal out    | mute   | [vocals]                     |
| Take the bass out     | mute   | [bass]                       |
| Drop to just the beat | mute   | [bass, other, vocals]        |
| Bring it all back     | unmute | [drums, bass, other, vocals] |
| Fade it out           | fade   | [drums, bass, other, vocals] |

The AI picks 1–3 of these per section (it may not invent others; unknown chips are dropped on parse, like the arranger clamps anchors). The deterministic fallback assigns by label, e.g.: intro → {Bring the vocal in, Drop to just the beat}; verse → {Take the bass out, Drop to just the beat}; chorus → {Bring the vocal in, Bring it all back}; bridge/break → {Drop to just the beat, Take the vocal out}; outro → {Fade it out}; default → {Drop to just the beat, Bring it all back}.

## Components

**Backend:**

- `app/models.py` (additive): a `LiveChip` model — `text: str`, `op: str`, `targets: list[str]`; and a `SectionSuggestions` model — `start: float`, `end: float`, `label: str`, `chips: list[LiveChip]`. `LiveOp.op` gains the documented value `"fade"` (no structural change — it's already a free string; the parser/DTO handle it).
- `app/planner/suggest.py` (new, not dangerous): `suggest_moves(a1: TrackAnalysis, prompt: str = "") -> list[SectionSuggestions]` — deterministic label→chips fallback + an `_ai_suggest` path (one `claude-sonnet-5` call, closed-vocabulary, JSON-only) that returns None on any failure so the fallback runs. Mirrors `plan.py`'s structure (system prompt, `_extract_json`, try/except → None).
- `app/planner/live.py` (additive): `parse_command` recognizes "fade away"/"fade it out"/"fade out" → `LiveOp(op="fade", targets=[all])`. Existing commands unchanged.
- `app/routes/live.py` (additive): `GET /live/suggestions/{mix_id}` — hex-guarded; loads the cached `MixPlan` (→ `song1_id`) + Song 1's analysis; calls `suggest_moves`; caches JSON; serves it. Sync (one fast call; no new async-job copy).

**Frontend:**

- `src/lib/api.ts` (additive): `LiveChipDTO`, `SectionSuggestionsDTO`, `getSuggestions(mixId) -> {sections}`. `LiveOpDTO.op` already a string (accepts `"fade"`).
- `src/lib/liveSchedule.ts` (additive): `applyOp` treats `"fade"` as "all named buses off" (bus state reflects the fade); `currentChips(sections, songTime) -> LiveChip[]` picks the section the playhead is in (last section whose `start <= songTime`).
- `src/lib/liveAudio.ts` (additive): `schedule` handles `op.op === "fade"` — ramp every named bus to 0 over `FADE_BARS` (~4) bars starting on the next bar (a longer ramp than the 1-bar mute). Reuses the next-bar math.
- `src/components/Live/LiveMix.tsx` (additive): when `mixId` exists, `getSuggestions`; a light interval (~250 ms, only while playing) reads `player.songTime()` and updates the current section; render `currentChips(...)` as tappable chips; tapping builds the chip's `LiveOpDTO` and calls the shared `runOp` (on-beat). Chips sit alongside the four part buttons; built as a **clean, swappable component** so the later UI design pass is a re-skin.

## Data flow

mix ready → `LiveMix` has `mixId` → `getSuggestions(mixId)` → `GET /live/suggestions/{mix_id}` → (cache miss) route loads plan + Song 1 analysis → `suggest_moves` (AI or fallback) → per-section chips, cached → player stores them → on Play, the ~250 ms poll reads `songTime()`, `currentChips` picks the section → chips render → user taps "Drop to just the beat" → `runOp({op:"mute", targets:["bass","other","vocals"]})` → on-beat ramp + bus state update. Section changes → chips swap.

## Error / edge handling

- **No mix yet** → no chips (live player beat-only, as today).
- **No AI/key** → deterministic label→chips fallback (never blocks).
- **Analysis has no/thin sections** → one default chip set ({Drop to just the beat, Bring it all back, Fade it out}) covering the whole track.
- **Tapping an already-active move** → gentle no-op (per-section chips aren't live-state-aware; the reducer/scheduler already no-op cleanly).
- **Suggestions fetch fails** → the four part buttons + typed commands still work; chips just don't show (log, don't crash).
- **Beatgrid missing** → moves still fire on the next 2-second boundary (Slice 1 fallback); fade uses the same grid.

## Reuse, scale, boundaries

- **Same brain pattern, no new architecture:** `suggest.py` mirrors `plan.py` (LLM-plans / rules-fallback); no new AI-orchestration shape. It reads analysis + the cached plan; it never touches audio.
- **One cached call, not per-beat:** cost/latency bounded; suggestions cached to disk per `mix_id` (joins the same cache-eviction backlog as the mix WAV + vocal bus — logged, do before the ~50-user test).
- **Closed vocabulary = safe AI:** the brain can only pick moves the engine already supports; an evil/garbled response degrades to the fallback or drops unknown chips. No way for a suggestion to produce an unsupported audio action.
- **Additive contracts:** new models + a new `"fade"` op value; existing `LiveOp`/`LiveOpDTO`/parser/player behavior unchanged.

## Not a dangerous surface (except web tests)

New files (`planner/suggest.py`) + additive edits to `models.py`, `planner/live.py`, `routes/live.py`, and the web `lib/*` + `components/Live/*`. **`render.py`, `validate.py`, `storage.py`, `songs.py`, config untouched.** Only the web `*.test.ts`/`*.test.tsx` files (test-harness guard) need confirm-and-apply, as in Slices 1–2. Heavy chiefly because it brings the LLM into the live path (a new subsystem) — hence this design + a plan first.

## Testing

- **Backend:** `suggest_moves` fallback maps each section label to the right chips and always returns ≥1 chip per section; the AI path (mocked) returns closed-vocabulary chips and drops unknown ones; `parse_command("fade away")` → `op="fade"`, all targets. Route: `/live/suggestions` 404 bad id, 409 no plan/analysis, returns sections+chips when ready (chips drawn only from the vocabulary).
- **Frontend (protected — confirm-and-apply):** `currentChips(sections, songTime)` picks the right section at boundaries; `applyOp` with a `"fade"` op sets all buses off; the fade ramp params (all buses, `FADE_BARS`) are computed from the pure helpers; `LiveMix` renders the current section's chips.
- **Acceptance (founder, on the running app):** chips show, change per section, land on the beat when tapped, and "fade it out" fades the mix away.

## Open, non-blocking follow-ups (logged, not in this slice)

- "beat up" energy move (define its sound, then a small slice).
- Live-state-aware suggestions (chip hidden/greyed when its move is already active).
- Suggestions JSON joins the mix-WAV + vocal-bus cache-eviction sweep (before the ~50-user test).
- The playhead poll is a simple interval; if more live-timeline UI arrives, consider a shared playhead hook.
