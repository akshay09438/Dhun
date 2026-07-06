# Prompt-DJ — Technical Spec (V1)

_How it is built. Starts as the intended design (from the PRD + discovery deltas); becomes as-built as code lands. Living document — if code and this doc disagree, the code wins and this doc is corrected. Full background: [reference/PRD.md](reference/PRD.md)._

## The one architectural principle (do not violate)

**The language model plans. The audio engine executes. They never mix.** The LLM turns (analysis + request) into a structured `MixPlan` (Feature 1) or a `LiveOp` (Feature 2). A deterministic render/playback engine executes those objects with DSP. The LLM never touches audio samples. This buys: editability, near-zero LLM cost, no hallucinated audio, and full debuggability.

## Stack (right-sized for validation scale; audio toolchain kept best-in-class)

| Layer                | Choice                                                             | Notes                                                                                           |
| -------------------- | ------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------- |
| Frontend             | React + Vite + TypeScript, wavesurfer.js, Web Audio + Tone.js      | upload, arrangement view, stem-bus player, live prompt bar                                      |
| Backend              | Python 3.11 + FastAPI + Pydantic v2                                | Pydantic schemas = data source of truth                                                         |
| Jobs                 | **In-process background tasks** (not separate Redis + workers yet) | upgrade to Redis/RQ when past validation scale                                                  |
| DB                   | **SQLite** to start                                                | upgrade to Postgres when it grows; no audio-quality impact                                      |
| Storage              | **Local disk** (`data/`, gitignored) to start                      | upgrade to Cloudflare R2 / S3 later                                                             |
| Stems                | **AudioShake / Music.ai API** (or self-host Demucs on Modal later) | 🎯 quality-critical — best-in-class                                                             |
| Analysis (MIR)       | librosa + madmom + Essentia + allin1                               | BPM/beatgrid/downbeats/key/sections/energy/vocal regions                                        |
| Time-stretch / pitch | **SoundTouch (free)** for V1 by choice                             | kept swappable to Rubber Band (paid, better on big stretches) in one file; keep stretches small |
| Mux / encode         | FFmpeg (LGPL build) + numpy                                        |                                                                                                 |
| LLM                  | Anthropic Claude API (structured output)                           | `MixPlan` + `LiveOp` only                                                                       |

**Why simplified vs. the PRD:** the PRD pins Postgres + Redis + separate workers + object store for scale. For ~50 users we run a single FastAPI app + SQLite + local storage + in-process jobs. This is _plumbing only_ — it has zero effect on how the mix sounds, and each piece upgrades independently without touching the audio engine.

## Core data models (Pydantic — the source of truth)

`TrackAnalysis` (per song, cached by content hash) · `StemSet` (per song, cached) · `MixPlan` (Feature 1 spine: bed + topline + sync + arrangement[] + fx) · `LiveState` + `LiveOp` (Feature 2). See PRD §5 for full schemas.

## Feature 1 pipeline (stage by stage)

Ingest (FFmpeg normalize) → Analysis (cached, with per-field confidence) → Stem separation (cached) → Arrangement planning (Claude + deterministic helpers + validator) → Tempo lock (SoundTouch) → Key lock → Beat alignment → Render/mixdown (flat file + stems-preserved live bundle) → Post (loudness normalize + limiter). See PRD §6.

## The judgment layer (the moat)

Deterministic helpers the LLM calls (never guesses): `snap_to_phrase`, `camelot_fit`, `stretch_ratio`, `vocal_regions`, `section_windows`. The LLM picks taste among _legal_ options; a validator enforces the hard rules (R1 one vocal at a time, R2 one bassline, R3 boundaries on downbeats, R4 key-clash guard, R5 ≥2 distinct vocal placements, R6 no clipping). Full rulebook: [reference/DJ-Judgment-Handbook.md](reference/DJ-Judgment-Handbook.md) (Parts 1–8 craft, Part 9 confidence/fallback, Part 10 live orchestration).

## Feature 2 (live, lean)

Playback holds separately-addressable stem buses (`s1.drums, s1.bass, s1.other, s1.vocals, s2.vocals`). Commands become on-beat `LiveOp`s (energy/element moves only in V1). Scheduler uses Song 1's grid as the master clock (Tone.js Transport / server-authoritative to start). Two invariants: music never stops; nothing fires off-grid. **Live BPM change is out of V1** (V2 stretch goal).

## The dangerous 5% (mirrors `.zuko/config.json`)

Secrets/keys · the upload handler (untrusted input) · storage deletes (irreversible) · the render pipeline + quality validator · CI/test harness. No real auth or payments in V1.

## As-built (M1)

- `services/api/app/`: `config.py` (limits), `audio/normalize.py` (FFmpeg two-pass peak-normalize → 44.1k/stereo/16-bit, with a subprocess timeout), `storage.py` (content-hash save/serve, hex-id validation), `routes/songs.py` (streaming size-capped upload + serve), `main.py`. 10 pytest tests.
- `apps/web/`: React+Vite+TS upload screen (`components/Uploader`), `lib/api.ts` client. 5 vitest tests.
- Time-stretch not yet wired (arrives with mixing in M3); SoundTouch chosen for then.

## As-built (M2a — stem splitting)

- **Runs in the cloud, not locally.** PyTorch/Demucs can't run on the founder's Windows-ARM machine (proven), so separation calls **Replicate** (`ryan5453/demucs`, htdemucs) over HTTP. The `replicate` client is pure-Python and runs fine locally.
- `services/api/app/audio/stems.py`: `separate_stems(song_id, wav)` → 4 stems, **cached by content id** (no repeat API cost). `app/routes/stems.py` is **asynchronous** (a ~2min cloud job can't be held on one request — long songs timed out): `POST /songs/{id}/stems` starts a background thread and returns `202 processing`; `GET /songs/{id}/stems` reports status (processing/ready/error); `GET /songs/{id}/stems/{stem}` serves a part (id+stem validated). In-memory `_jobs` registry (single-worker validation; persisted table when hosted). `StemSet` = {song_id, status, stems}. 8 tests (mocked Replicate).
- `apps/web`: each song card gets a "Split into parts" button → 4 stem players. +1 test. 6 web tests total.
- **Keys:** `REPLICATE_API_TOKEN` (+ `ANTHROPIC_API_KEY` for M3) in a gitignored root `.env`, loaded at startup via `python-dotenv` in `main.py`.
- **Cost:** ~2–6¢ per song, cached; validated live end-to-end.

## As-built (M2b — analysis)

- **Hybrid cloud + local math.** Rhythm/structure from Replicate `sakemin/all-in-one-music-structure-analyzer` (allin1): BPM, beats, downbeats, sections. Local pure-numpy (`app/audio/analysis.py`): key (FFT chromagram + Krumhansl–Kessler profiles → Camelot, confidence = winner margin), energy curve (RMS/bar), vocal regions (RMS of the split vocal stem/bar), phrase starts (every 8th downbeat), bpm confidence (beat-interval regularity). librosa/madmom/essentia cannot install on this ARM machine (numba/llvmlite lack wheels) — hence pure numpy.
- `app/routes/analysis.py`: async start-then-poll like stems; result cached as `{id}.analysis.json`. `TrackAnalysis` model carries per-field confidence (sections pinned at 0.6 — the known weak link the planner must distrust).
- `apps/web`: "Analyze track" per song → BPM chip, Camelot key chip (confidence on hover), proportional section-timeline bar.
- Verified live: Father Ocean → 122 BPM (correct), 925 beats / 232 bars / 29 phrases, full section map, 11 vocal regions.

## As-built (M3 — the basic mix)

The first mix implements the one principle literally: **the brain plans a `MixPlan`, the engine executes it; the LLM never touches audio.** Four small, independently-tested units:

- **The fence** (`app/planner/fence.py`, deterministic): reads both songs' `TrackAnalysis` and returns the legal, safe options — phrase-aligned high-energy drop points (with a runway check), a safe tempo stretch (`best_stretch` folds half/double-time and holds ±8%), a capped vocal slice snapped to a downbeat, and Camelot key-fit (informational). Falls back down the ladder (phrase→downbeat→beat) when data is shaky, and declines a pair in plain language when tempos are too far apart or there's no beat. Pure arithmetic — no AI, no audio.
- **The AI driver** (`app/planner/plan.py`): Claude (`claude-sonnet-5`) picks the drop + a one-bar beat-breath among the fence's options; on any failure (no `ANTHROPIC_API_KEY`, network, bad output, out-of-range index) it falls back to the deterministic "best drop" pick, so a mix never blocks on the AI. Raises `MixDeclined` (with a reason) when the pair is unmixable.
- **The referee** (`app/planner/validate.py`, dangerous surface): `validate_plan` (R3 vocal on a downbeat, B3 safe stretch, non-empty slice) and `validate_render` (R6 no clip ≥0.999, and **not silent or near-silent** — at least 2% of samples above an audible floor, so a mostly-silent render with a stray blip is caught, not just exact-zero). R1 single-vocal / R2 single-bassline are guaranteed **by construction** — the bed is only S1's drums+bass+other and the only vocal added is S2's single slice. `assert_*` raise `ValidationError`.
- **The engine** (`workers/render.py`, dangerous surface): FFmpeg + numpy only, decoupled (takes plain file paths, no app/db coupling — imported by the API via a `sys.path` bootstrap). Sums S1 drums+bass+other into the bed; slices S2's vocal then `atempo`-stretches it to S1's tempo (pitch preserved); fades both edges (~8 ms) to kill clicks; optional one-bar beat-breath silences the bed before entry; peak-normalizes to −1 dBFS with a 0.999 brickwall so the master never clips. Renders 44.1 kHz stereo WAV. Guards: decoded audio is capped at 12 min so a tiny-but-hours-long low-bitrate file can't balloon memory (the upload cap is on bytes, not duration); non-positive tempo is rejected and a negative anchor is clamped.

Route (`app/routes/mix.py`, async — mirrors stems/analysis): `POST /mix {song1_id, song2_id, prompt?}` starts a background job and returns `202` (or the cached result); `GET /mix/{mix_id}` polls; `GET /mix/{mix_id}/audio` serves the WAV. `mix_id` = SHA-256 of `(song1, song2, prompt)` → identical requests are free; preconditions (both uploaded + analyzed + split) are reported in plain language (409). Models: `MixPlan` (the recipe) and `Mix` (the job/result). Web: a `MixMaker` card (`apps/web/src/components/Mix/`) → poll → play + download + DJ-language note.

**Time-stretch:** FFmpeg `atempo` (pitch-preserved, LGPL-core, already installed) — the as-built realization of the spec's SoundTouch choice, kept small (±8%). GPL `librubberband` exists in the dev FFmpeg but the pipeline does not depend on it.

## As-built (M4 Slice A — the living arrangement + regenerate)

M3's single drop grows into a full arrangement; the brain still plans a `MixPlan`, the engine executes it, the LLM never touches audio.

- **Models** (`app/models.py`): `Placement(anchor, vocal_src, beat_breath)`; `MixPlan.placements: list[Placement]` + `take: int` — **additive** (the scalar `anchor`/`vocal_src` stay, so M3-era cached `*.mixplan.json` still parse).
- **The fence** (`planner/fence.py`): `arrangement_options` returns the M3 legal set plus ranked phrase anchors and the available vocal slices; `rendered_vocal_secs`/`placement_end` are the **single source of truth** for a placed vocal's real length (`source / stretch` — see the atempo note).
- **The driver** (`planner/plan.py`): Claude arranges 2–3 non-overlapping placements building an energy arc, with a deterministic fallback; `take` rotates the arrangement for Regenerate; `_dedupe_nonoverlapping` guards one-vocal-at-a-time before render. AI slices re-clamped to `MAX_VOCAL_SECS`.
- **The referee** (`planner/validate.py`, dangerous): now checks **no overlap across placements** (R1, via the shared `placement_end`) + each entry on a downbeat (R3), plus M3's B3/R6. R1 source-single holds by construction.
- **The engine** (`workers/render.py`, dangerous): loops placements, laying each vocal on the continuous bed; `beat_breath` **ducks the bed to 35%** for one bar (never silence — the M3 dead-air fix stays). Windows temp-cleanup made race-safe.
- **Route** (`routes/mix.py`): `/mix` takes an optional `take`; `mix_id` folds in `take` + `ENGINE_VERSION` (`m4a.2`) so each take is a distinct cached render. **Web:** a two-lane arrangement timeline + "Give me another take" + Download.

**The atempo length contract (a fixed bug worth remembering):** FFmpeg `atempo=stretch` outputs `source_duration / stretch`, **not** `* stretch`. For `stretch < 1` (a faster vocal, ~half of compatible pairs) the vocal plays _longer_; an early M4 cut used the inverted `* stretch` in the driver and referee, so vocals could overlap (two voices) past the checks. Caught by the adversarial review; fixed by routing both through `fence.placement_end`.

## As-built (M4 Slice B — contrast + subtle FX + confidence fallbacks)

Additive on Slice A; the two-voices rule now spans both songs.

- **Models:** `Placement.fx: str | None` (`"sweep_in"`), `MixPlan.s1_vocal_regions: list[tuple[float,float]]` — both additive (M3/M4a plans still parse). `fx` is left a bare string on purpose (an enum would make cached plans more brittle); the referee typo-guards it instead.
- **Fence:** `contrast_windows` — the beat-only gaps between Song-2 placements (via the shared `placement_end`) intersected with where Song 1 itself sings, margin-protected (2 s) so a contrast never touches a Song-2 vocal or the next duck/sweep bar.
- **Driver** (`_apply_flourishes`, `_confident`): on a confident Song 1 → one contrast window + one `sweep_in` on the final entry; on a shaky Song 1 (`bpm_confidence < 0.5`) → play safe (≤2 placements, no contrast/fx/breath). The AI's picks are stripped/gated after it runs, so a misbehaving model can't force fancy moves on bad data.
- **Referee** (dangerous): R1 now holds **across both songs** — every `s1_vocal_regions` span is checked against every Song-2 placement window (`placement_end`); overlap → violation. Also typo-guards unknown `fx`. Verified by an adversarial review that could not defeat the two-voices guarantee (straddles, sub-unity stretch, unsorted plans, evil-AI injection).
- **Engine** (dangerous): applies `_sweep_bed` (a rising low-pass crossfade, eased at the leading edge so it can't click; overshoot folded into the −1 dBFS normalize + clip guard) before a `sweep_in` entry; mixes Song 1's own vocal stem into each contrast span at ratio 1.0 (it is already Song 1's tempo). Degrades gracefully if the Song-1 vocal stem is missing.
- **Route:** passes Song 1's `vocals` stem; `ENGINE_VERSION m4b.1`. **Web:** the timeline shows Song 1's vocal in a distinct color + a sweep mark, with a legend.

## As-built (M4 Slice C — the energy arc: vocal spans the whole song)

The prior arrangement ranked anchors by **energy only**, so on a long song (e.g. a real 7:52 pair) the 2–3 placements clustered where the song is loudest (the middle), leaving the first half and the ending empty. This layer makes the arrangement follow an energy **arc** across the whole song — straight from the DJ Handbook (H1 shape-an-arc, H2 think-in-thirds, H5 don't-peak-early, H6 waves). Same placement count (no render-cost change); only _where_ they land moves. Purely in the planning code — the referee and engine are untouched.

- **Fence** (`planner/fence.py`): `arc_anchors(anchors_ranked, track_end, count, take)` — splits the timeline into `count` equal bands and takes the best-energy anchor in each, so one vocal moment lands in every third and the final band gives a strong late entry; `take` rotates the within-band pick for Regenerate variety; falls back to what exists when anchors are too few. `arrangement_options` now also returns `track_end` (the whole canvas) and `sections` (Song 1's shape, for the AI).
- **Driver** (`planner/plan.py`): `_default_arrangement` selects via `arc_anchors` (spread) instead of a sliding window of consecutive anchors. A new **arc guard** — `_spans_song` — rebuilds any plan (a clustering AI, or thin analysis) as the deterministic arc when it fails to reach both the first half and the final third; the guard makes the founder's acceptance test true **by construction**, regardless of how the plan was produced. The AI prompt + payload now include `track_length_seconds`, `song1_sections`, and a `recommended_spread_anchors`, and instruct it to spread across the thirds with a strong finish.
- **Route** (`routes/mix.py`): `ENGINE_VERSION m4c.1` so cached clustered mixes aren't re-served.
- **Verified end-to-end (no cloud cost)** on the real cached 122-BPM 7:52 beat + 125-BPM vocal: Take 1 vocal at 1:52 / 5:01 / 5:32 (+ Song 1's own vocal answering at 2:41, sweep on the last entry); Take 2 at 1:36 / 4:29 / 6:51 — both span first-half→final-third, takes differ, render passed the referee. 96 backend tests (was 91) + 10 web green.
- **Known limit (deliberate, next layer):** still 2–3 vocal moments, so a very long song can feel a touch sparse between entries. Adding _more_ vocal returns touches `workers/render.py` (a dangerous surface) and is the explicitly-deferred next layer, gated on the founder finding it too sparse by ear.

## As-built (M4 Slice D — per-bar beat-lock: the vocal stops drifting)

Slice C spread the vocal across the whole song, which exposed a pre-existing drift: a single global `atempo` ratio can't hold a long vocal on the beat, because real tempos wobble and BPM detection is imperfect. Measured on the real 122/125 BPM 7:52 pair, a 40 s vocal drifted **+315 ms** off the beat by its end. Slice D re-locks every bar.

- **Fence** (`planner/fence.py`): `warp_map(anchor, vocal_src, a1_downbeats, a2_downbeats, global_ratio)` maps each Song-2 bar in the slice onto the matching Song-1 bar and emits `(src_start, src_end, out_secs)` per bar, where `out_secs` is the Song-1 bar length — so every bar boundary lands on a Song-1 downbeat and drift resets each bar (~0 ms). It **starts on Song 2's first downbeat** in the slice (drops any mid-bar lead-in rather than emit a grid-shifting leading partial), keeps a trailing partial for the vocal's own tail, and **returns `[]` (legacy global stretch) on a genuine grid glitch** (a bar whose ratio is out of the safe band) rather than a half-locked map. `placement_end(..., warp=None)` returns `anchor + sum(out_secs)` when warped, so the driver and referee still measure a placed vocal's real end identically.
- **Models** (`app/models.py`): `Placement.warp: list[tuple] = []` — additive; empty ⇒ the legacy single-atempo path (M3/M4a–c cached plans still parse and render unchanged).
- **Driver** (`planner/plan.py`): `_attach_warp` gives each Song-2 placement a warp map; dedupe + contrast use the warp-aware `placement_end`.
- **Engine** (`workers/render.py`, dangerous): `_vocal_take_warped` stretches each bar to its `out_secs` and lays the bars at their locked offsets, joined by short equal-power crossfades (each bar rendered a hair long so the seam crossfades without moving the downbeat). Raises `RenderError` if a bar ratio is ever outside atempo's [0.5, 2.0] (defense-in-depth; unreachable for real plans). Legacy `warp=[]` path is byte-identical to before.
- **Referee** (`planner/validate.py`, dangerous): R1 no-overlap (both S2↔S2 and S1-contrast↔S2) now measures with the warp-aware `placement_end`; new **R7** — a warped placement's per-bar ratios must be in the safe band and its interior bar boundaries must land on Song-1 downbeats. `assert_plan` runs before render.
- **Route** (`routes/mix.py`): `ENGINE_VERSION m4d.1`.
- **Reviews:** independent test-author (21 acceptance tests, hollow-test-hardened), + a 3-lens adversarial/scalability quorum. Scalability **ship**; DSP **safe**; the safety-guarantee lens **caught a real must-fix** (R7 falsely rejected ~29% of mid-bar-start plans by shifting the grid on a leading partial) — **fixed** (start-on-downbeat + glitch→`[]`) and the re-review confirmed **safe** (29% → 0.2%, 0 overlaps). **Verified end-to-end (no cloud cost)** on the real 7:52 pair: boundary drift **315/236/180 ms → 0/0/0 ms**, R7+R1+R6 pass, valid render. 127 backend + 10 web tests green.
- **Known residual (logged, low-severity, non-blocking):** a ~0.2% _loud_ R7 decline on band-edge pairs — `warp_map` band-checks the unrounded `out_secs` while R7 recomputes from the 4-dp-rounded value, so a trailing partial at the ~±8% edge can tip just past R7's tolerance. Never a silent bad mix or overlap; the user regenerates. Fix when next in `validate.py`: give R7's band check a rounding-aware tolerance (~2–5e-3), or have `warp_map` drop a trailing partial whose stored ratio would fail R7.
- **Perf follow-up (logged):** per-bar rendering spawns ~1 FFmpeg process per bar (~60 for a 7-min mix, ~+10 s, invisible behind stem separation at validation scale). Collapse to a single per-placement filtergraph when next in `render.py` — bundle with the mix-WAV eviction work (both share "Regenerate is the multiplier").
- **AI-path nicety (logged):** `_ai_arrange` doesn't snap a slice start to a Song-2 downbeat, so an AI placement drops up to ~1 bar of lead-in (warp_map starts on the downbeat). Correct and on-beat, just slightly less vocal; snap `s0` when convenient.

## As-built (M5 Slice 1 — live control foundation)

The first "steer the mix with words" slice. The M4 mix is a baked WAV (can't un-mute a part), so live control plays the **separate stems** in the browser and rides one part's gain on the beat. LLM plans (a `LiveOp`); the browser executes; nothing off-grid; the music never stops.

- **Models** (`app/models.py`): `LiveOp` (additive) — `op` ("mute" | "unmute" | "decline"), `target`, `when="next_bar"`, `say` (DJ-language reply), `reason`.
- **Live driver** (`app/planner/live.py`, not dangerous): `parse_command(text) -> LiveOp` — deterministic keyword parser for the lean set (Slice 1: bass mute/unmute) + an out-of-scope decline. An LLM path will sit in front later with this as the fallback (same pattern as `planner.plan`). Never touches audio.
- **Routes** (`app/routes/live.py`, not dangerous): `POST /live/command {song1_id, song2_id, text}` → `LiveOp`; `GET /live/context/{song1_id}` → `{bpm, downbeats}` (from the cached analysis — the grid the browser schedules on). Stateless; hex-id guarded.
- **Web — pure logic** (`apps/web/src/lib/liveSchedule.ts`, unit-tested): `barSeconds`, `nextBarTime(downbeats, songTime, bpm)` (next real downbeat, else next bar on the bpm grid), `applyOp` (bus on/off reducer), `rampTarget`. All the scheduling decisions live here so they're testable without Web Audio.
- **Web — audio engine** (`apps/web/src/lib/liveAudio.ts`, ear-verified not unit-tested): `LivePlayer` — decodes Song 1's `drums/bass/other` stems, one `GainNode` per bus, starts all sources at the same `AudioContext` time (sample-accurate sync), and `schedule(op, ctx)` ramps the target bus over one bar starting on the next downbeat. `new AudioContext()` is wrapped in try/catch so an unsupported environment degrades to "not ready" rather than crashing.
- **Web — screen** (`apps/web/src/components/Live/LiveMix.tsx`): play/pause, a command text box, a DJ-language status line, per-bus on/off indicators. Wired **additively** into `Uploader.tsx` alongside the M4 `MixMaker` (same both-songs-ready gate); the M4 finished-mix player is untouched.
- **Tests:** `test_live.py`, `test_live_route.py` (pytest); `api.test.ts`, `liveSchedule.test.ts`, `LiveMix.test.tsx` (vitest). Raw Web Audio playback is verified by ear (founder acceptance), not in jsdom. 136 backend + 18 web green.
- **Stack note:** uses the **raw Web Audio API** — Tone.js/wavesurfer named in the stack table are NOT installed and were not needed for this slice.
- **Danger-surface note:** the web `*.test.ts`/`*.test.tsx` files ARE on the dangerous list (the test-harness guard) — adding new web tests goes through confirm-and-apply. (Python `test_*.py` are not guarded; only `conftest.py`/`pytest.ini`.)

## As-built (M5 Slice 2 — the full mix, live, all parts controllable)

Slice 1 played only Song 1's stems. Slice 2 layers in **Song 2's arranged vocal** and makes **every** part switchable on the beat — so the live player plays the _whole_ mix. The key move: don't rebuild the M4 arrangement in the browser — have the trusted engine bake the vocal layer onto silence and let the browser play it as a fourth bus.

- **Arranged-vocal bus** (`workers/live_stems.py`, new — NOT a dangerous surface): `render_vocal_bus(plan, song1_stems, song2_vocal, out_path)` renders the arrangement's vocal layer (Song 2's placed/warped/edge-faded vocal + Song 1's contrast regions) onto a **silent** buffer, by **importing** `render.py`'s helpers (`_vocal_take`, `_vocal_take_warped`, `_edge_fade`, `_placements_of`, `SR`, `_CEILING`). It skips the bed sum, the master peak-normalize, and the bed-only effects (sweep, beat-breath). Vocal added at **ratio 1.0, not normalized** — the browser sums it live with the raw stems, so the vocal-vs-bed balance matches the Download (whose global normalize is uniform); only a safety clip is applied. **`render.py`/`validate.py` are untouched.**
- **Route** (`app/routes/live.py`, additive): `GET /live/vocal-bus/{mix_id}` → 200 audio when ready, 202 while rendering (async start-then-poll, mirrors `mix.py`'s `_jobs`), 409 if no cached mix plan, 404 on a bad id. Derives everything from the cached `MixPlan` JSON (which carries `song1_id`/`song2_id`) — no re-planning, no AI. Cached as `{mix_id}.vocalbus.wav`.
- **Models** (`app/models.py`, additive): `LiveOp.targets: list[str]` — a command can name several buses at once ("drop everything but the beat"). `target` stays (Slice-1 back-compat; set when a single part).
- **Live driver** (`app/planner/live.py`): `parse_command` grows to the full lean set — remove/bring-back vocals, drums, melody (`other`); the combos "drop everything but the beat" (mute bass+other+vocals) and "bring it all back" (unmute all four); bass phrases unchanged. Order: combos → per-part unmute-before-mute → bass fallback. Still deterministic.
- **Web — pure logic** (`liveSchedule.ts`): `BusName` gains `"vocals"`; `busesOf(op)` returns the affected buses (prefers `targets`, else `target`, filters to valid names); `applyOp` flips every named bus. `barSeconds`/`nextBarTime`/`rampTarget` unchanged.
- **Web — audio engine** (`liveAudio.ts`): `load(song1Id, stemBuses, mixId?)` also fetches + decodes the vocal bus (via `fetchVocalBus`, which polls past 202) into a fourth bus when a mix exists; `schedule` computes the next-bar time once and ramps **every** bus in `busesOf(op)`. Sync-start unchanged (all four buses start at one ctx time).
- **Web — screen** (`LiveMix.tsx`): four **tappable** parts — **Beat**/Bass/**Melody**/Vocals (friendly labels over `drums`/`bass`/`other`/`vocals`). Tapping builds a local op and rides the same on-beat ramp (no server round-trip); typed commands still POST to the parser. Takes an optional `mixId`; the player **reloads** the vocal bus when the song or the take changes (Regenerate → live vocals follow). Vocals is disabled with a hint until a mix exists. `MixMaker` gained an optional `onMixReady(mix_id)`; `Uploader` lifts `mixId` and threads it to both.
- **The live player is a steerable _approximation_** (founder-approved): steady-gain parts, so it omits the Download-only sweep + beat-breath (bed effects). The **Download stays the polished master**; the live player is the steering room.
- **Tests:** `test_live_stems.py` (vocal-bus silent-outside/loud-inside, contrast region, no-placement silence), `test_live_route.py` (+vocal-bus 404/409/200), `test_live.py` (+multi-part/combo parsing); `api.test.ts` (+`fetchVocalBus` polling), `liveSchedule.test.ts` (+multi-target `applyOp`), `LiveMix.test.tsx` (four parts render). **149 backend + 22 web green.**
- **Danger-surface note:** only the web `*.test.ts`/`*.test.tsx` files were on the dangerous list (test-harness guard) — added via confirm-and-apply. `render.py`/`validate.py`/`storage.py`/`songs.py`/config untouched.

## Known follow-ups

- CI `verify` job is Node-only today; add a Python (pytest) job when a GitHub remote is set up. Also point the coverage job at `apps/web/coverage/` (or emit to repo-root `coverage/`).
- Non-Western (Indian/Bollywood/Punjabi) key + structure detection is weaker — hand-verify those demo pairs.
- Before any public exposure (per the M1 security review): sandbox/resource-limit FFmpeg on untrusted input, add rate-limiting + body-size limits at the proxy, and add HTTP-level traversal/oversize tests.
