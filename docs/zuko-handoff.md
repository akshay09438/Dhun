# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. `/handoff` rewrites this at the end of a session; `/start` and the SessionStart hook replay it at the beginning. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-07-06 (big session — M5 Slices 2 + 3 built, then 3 founder-ear-test bugs fixed; **both V1 features now done + founder-confirmed**)

## Where things stand (one breath)

**Both V1 features are DONE and founder-confirmed.** Feature 1 (the offline DJ mix) was already "perfect." This session finished **Feature 2 (live steering)**: the mix screen's **live player** now plays the whole mix and you reshape it live — tap/type any of four parts (**Beat · Bass · Melody · Vocals**) on the beat, use combos (**"drop everything but the beat"**, "bring it all back"), **"fade away"**, and tap **AI suggestion chips that change with the part of the song**. The founder tested it and said it "works perfectly." Along the way, an ear-test surfaced **three real bugs, all fixed with reproducing tests**: (1) **the AI was silently never running** — newer models return a _thinking_ block first, so `content[0].text` threw and both the arrangement and the suggestions always fell back to rules; now genuinely AI-driven (live-verified). (2) **"bring the vocal in" did nothing** between placements — the live Vocals part was the _sparse arranged_ vocal; it's now Song 2's **continuous** vocal (bring in anywhere she sings). (3) **chips felt static** — now consecutive same-chip sections merge and a **"▶ now playing: <part> · m:ss"** tag shows which part the live playhead is in. All on branch `feat/m5-live-control`, pushed to GitHub. **188 tests green (162 backend + 26 web), typecheck + lint clean.**

## In flight

- **Nothing half-done.** Working tree clean. Every piece committed on `feat/m5-live-control` and pushed to `origin`. Suite green (evidence below).
- **No open acceptance** — the founder live-confirmed the full live feature this session ("everything works perfectly").
- **Servers left running** on the current code: backend :8000 (restarted after the fixes — serves `/live/suggestions` + the continuous-vocal `/live/vocal-bus`), web :5173 → http://localhost:5173.
- **`main` is still at the M4 tip** (no PR flow in use; branches are backup). `feat/m5-live-control` now holds all founder-confirmed M5 work — a candidate to fast-forward `main` onto next session **if the founder wants** (merging to the protected branch is a deliberate step — ask first).

## Do first next session

1. **Recommended next build: the one-click "Studying your songs" screen** (functional-spec Screen 2). Today the user presses **Split** + **Analyze** on each song by hand before "Make my mix" — this is the exact friction that confused the founder mid-session. Replace it with one automatic step (auto split + analyze, then mix). Highest-impact UX fix; makes the app demo-ready for the ~50-creator test.
2. **Then, the rest of the road to the validation test (rough order):**
   - **"Beat up"** — the last live command; decide its _sound_ first (drums-up vs a short build), then a small slice.
   - **Live-vocal beat-lock (deferred M5 polish)** — the continuous live vocal uses a single global stretch, so it drifts slightly off the beat over minutes; beat-lock it bar-by-bar like the Download (reuse `fence.warp_map` + `render._vocal_take_warped`). Founder flagged it; agreed to defer to M6 polish.
   - **Cache-eviction sweep (before the ~50-user test)** — mix WAVs + the new `.livevocal.wav` + `.suggestions.json` all pile up in `data/` with no eviction; add a keep-newest/age sweep. Belongs in `storage.py` — a **dangerous** surface, so gate it (confirm-and-apply).
   - **The UI design pass** — the founder has designs; apply them across all screens at once (deliberately deferred to the end so it's one coherent pass; the live chips/parts were built as swappable pieces for this).
3. **M6:** loudness master (limiter) + short-clip (15–30s) export + the ~50-creator validation test.
4. **Before any public exposure (M1 security list, still open):** sandbox/resource-limit FFmpeg on untrusted input, proxy rate/body limits, HTTP traversal/oversize tests, a duration cap at upload.

## Verification evidence (which checks ran, what they returned)

Ran at handoff time, 2026-07-06:

- Backend: `./.venv/Scripts/python -m pytest -q` in `services/api` → **162 passed** (was 149 at the start of the M5-Slice-2/3 work; +Slice 2, +Slice 3, +the 3 fix tests: llm/first_text, section-merge, full-vocal-continuous).
- Web: `npm test` (vitest) → **26 passed** (5 files); `npm run typecheck` → **clean**; `npm run lint` → **clean**.
- **AI fix live-verified this session:** loaded the real key and called `suggest._ai_suggest` → returned real per-section picks (intro→"Bring the vocal in", chorus→"Bring it all back", break→"Take the bass out"/"Drop to just the beat", outro→"Fade it out"), where before it silently returned `None`. Confirmed model `claude-sonnet-5` fails (`ThinkingBlock` has no `.text`) and `claude-sonnet-4-5` works.
- **Founder ear-test:** live steering "works perfectly"; the only remaining nit (live-vocal not perfectly on the beat) is the logged deferred polish.

## Open escalations

- **None blocking.** No red suite, no work waiting on a human decision.
- **Cost note (NEW — flag to the founder):** the AI is **now genuinely on** (it never actually ran before). Each **new mix** and each **first suggestions fetch per mix** now makes real Anthropic calls (small cost). The deterministic rules remain the automatic fallback if the key is absent or the call fails. Old cached mixes are rules-made — **regenerate a take** to get an AI mix.
- **CLAIMS to re-verify (not settled facts):**
  - No dangerous-surface _code_ was changed this session (`render.py`, `validate.py`, `storage.py`, `songs.py`, `config.py` all untouched — the fixes live in `plan.py`/`suggest.py`/`live.py`/`live_stems.py`/`models.py`, none of which are on the danger list). The only dangerous surface touched was the web `*.test.ts` files (test-harness guard), via confirm-and-apply (founder approved; approvals cleared). **Re-run the full suite next session** before building further.
  - **`workers/render_vocal_bus` is now unused by the app** (the live Vocals part switched to `render_full_vocal`). It's kept + still tested. Backlog: remove or repurpose it.
  - **Live-vocal sync is a known approximation:** single global stretch drifts slightly off-beat over minutes (deferred to M6 beat-lock). Not a bug — a logged tradeoff of the founder's "continuous vocal" choice.
- **Backlog (logged, deliberate — not blockers at validation scale):** cache eviction (mix WAV + `.livevocal.wav` + `.suggestions.json`), before the user test; the async start/poll/serve pattern is in 4 routes (extract a shared `async_job` helper next time it's touched); `render_vocal_bus` cleanup; the two-players UX (live vs finished-mix player) is a design-pass clarity item.
- **Keys / cost:** `REPLICATE_API_TOKEN` + `ANTHROPIC_API_KEY` in the gitignored root `.env` (loaded by `app/main.py`). Replicate powers split/analyze of NEW songs (the cached demo pair needs neither). Anthropic now powers the live arrangement + suggestions (was silently off until this session's fix).
- **Environment truths (unchanged):** PyTorch/librosa/madmom can't run on this Windows-ARM machine — heavy audio via Replicate; local DSP is FFmpeg + numpy/scipy only. The machine is memory-constrained — **work lean/sequential** (few concurrent background jobs); the founder flagged the laptop getting stuck under heavy parallelism, so this session's execution switched to inline, one-task-at-a-time.

## How to run the app

See README.md. Quick: backend `.venv/Scripts/python -m uvicorn app.main:app --port 8000` (from `services/api`), web `npm run dev` (from root), open http://localhost:5173. Or the `.claude/launch.json` configs (`backend`, `web`). Both are currently running on the latest code. Live player: make a mix (**"Make my mix"**, or **"Give me another take"** for a fresh AI one), press **Play**, then tap parts/chips or type commands (`take the bass out`, `drop everything but the beat`, `fade away`, `bring it all back`).
