# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-08-06 — **This session shipped NOTHING to the codebase — it was throwaway prototyping for Rule 3 (chop-and-repeat), which is now PARKED pending a real-DJ consult.** The last real shipped achievement remains **Rule 4 (the echo + reverb), LIVE on `main`** — re-verified today, still live and intact. Rule 3 stays a Desktop listening experiment only; the repo is byte-for-byte unchanged (`git status` clean).

## Where things stand (one breath)

- **Rule 4 (echo + reverb) is LIVE on `main` and re-verified today** — `rule4_enabled() = True`, `_RULE4_ENABLED = True`, `_DELAY_ECHO_WET = 1.10` (the founder-chosen boldest level), `ENGINE_VERSION = m6.11+m8echo`. Every mix renders with the tempo-synced delay echo + reverb bed. Fully reversible (flip `_RULE4_ENABLED` to `False` → back to `m6.11`, byte-identical). **This is the session-before-last's work and it is DONE.**
- **Rule 3 (chop-and-repeat) — EXPLORED via throwaway scripts only, then PARKED.** Nothing in the real codebase (no `render.py`, no `validate.py`, no tests, no docs, no ceremony — the `prototype-sound-before-ceremony` rule). Two listening rounds were rendered to dated Desktop folders on one pair (**I Adore You** beat × **Tujhe Bhula Diya** vocal).
- **The blocker (founder's call): the founder is consulting a real DJ tomorrow on how chop-and-repeat should actually be done** ("I also know how this will actually sound"). Do NOT build further until that input lands — it will set the target.

## The Rule 3 learning so far (this is the valuable part — don't lose it)

- **Round 1 (WRONG approach):** sliced the vocal on the BAR/BEAT grid and repeated whatever bar had energy → cut _through_ words, repeated a meaningless scrap. Founder feedback: that is not chop-and-repeat.
- **The correction (founder):** chop-and-repeat = take ONE whole, recognizable, HAND-PICKED line — the hook — and repeat _that intact line_, playing with it; sometimes bring in a second line. For this pair the hook line is **"tujhe bhula diya ho"**, hand-located by the founder at **0:58–1:12 of Tujhe Bhula Diya**; a second line ("kyun teri yaadon mein") sometimes trades with it.
- **Round 2 (RIGHT approach, awaiting the founder's ear + DJ input):** cut the WHOLE sung lines out of the 0:58–1:12 window at the pauses (envelope method, intact — not grid-sliced), and repeated the whole line over the beat five ways (straight / with-breath / per-bar / two-lines-trading / playful-pitch). Also exported the 4 isolated dry lines from that window so the founder can confirm exactly which one is "tujhe bhula diya ho" (best guess = LINE-0 @ 0:58.7; LINE-1 @ 1:02.3 likely "kyun teri yaadon mein").
- **Pitch shifting WORKED on this machine this session** — `rubberband` did NOT throw the earlier `std::bad_alloc`; the pitched variation rendered for real. (If it fails again, the scripts skip pitch and say so.) Reverse + time-stretch both work.
- **Reusable engine pieces confirmed for when Rule 3 is really built:** `workers/rule3_parked.py :: punchy_bar()` carries the breath-safe VOICED_FLOOR (never re-fire a breath — the Father Ocean 3:56 defect); `workers/render.py :: _phrase_ends()` is the reliable envelope line-splitter; `_vocal_take()` handles tempo-locked slicing; the echo-harness pattern (`scripts/echo_reverb_harness.py`) is the throwaway template.

## Stage 2 (hook detection) — feasibility REPORTED, nothing built

- **Question:** is "the hook = the most-repeated phrase" computable from the vocal stem using the reliable envelope approach (the one that found line-ends across 36 stems, median 28), NOT `vocal_regions`?
- **Answer: yes, low research risk.** Step 1 = cut the vocal into whole phrases with the existing envelope splitter (`_phrase_ends`). Step 2 = fingerprint each phrase and score how many other phrases it closely matches (self-similarity); the most-recurring phrase is the hook. Standard "chorus/thumbnail via self-similarity matrix" — no lyrics, no meaning, no AI. **`librosa` is NOT installed and is NOT needed** — scipy + numpy suffice; one-time, cacheable, on-machine, no cloud. Only real work later = ear-tuning the "alike enough" threshold (Indian vocals ornament heavily). This is effectively the hand-pick that Rule 3 currently does by ear.

## In flight — honest state

- **Nothing in flight in the codebase.** Repo is clean (`git status` empty), on `main`. No production files changed this session.
- **Rule 3 is parked, not in progress** — waiting on the founder's DJ consult. When it resumes, the next micro-step is a listening decision, not a build (see "Do first").

## Do first next session

1. **Wait for / capture the founder's DJ input on how chop-and-repeat should sound** — that sets the target. Then continue the throwaway listening loop (still no ceremony) from the Round-2 folder.
2. **Founder to confirm the hook line** in the Round-2 folder: which `LINE-N` clip is "tujhe bhula diya ho" (best guess LINE-0), and which chop-feel (1–5) is closest — or "still not it." Swap the line / retune in minutes.
3. Only once the SOUND is founder-approved does Rule 3 earn a real build (render.py + validator + tests + the two adversarial ceremonies), exactly like Rule 4.

## Verification evidence

- **Repo clean, no code touched:** `git status --short` → empty; branch = `main`. All prototype scripts live in the session scratchpad; all audio + READMEs live in gitignored Desktop folders. **Nothing to review, nothing to merge for Rule 3.**
- **Rule 4 LIVE re-verified today (2026-08-06):** `python -c "... from app.planner import plan; from app.routes import mix"` →
  - `plan.rule4_enabled()` = **True**
  - `plan._RULE4_ENABLED` = **True**
  - `render._DELAY_ECHO_WET` = **1.10**
  - `mixroute.ENGINE_VERSION` = **`m6.11+m8echo`**
- **Full test suite NOT re-run this session** — deliberately, because zero production code changed. The last real run (prior session, 2026-08-05) was **499 passed / 1 failed**, the 1 failure being the known pre-existing `test_cache_sweep.py` order-dependent flake (unrelated to any feature). That number stands unchanged; re-run before any real Rule 3 build.

## Prototype artefacts (throwaway, on the founder's Desktop — safe to delete anytime)

- `Prompt-DJ Rule3 chop-and-repeat PROTOTYPE (2026-08-05)` — Round 1 (grid-sliced, the WRONG approach) + a README + Stage-2 report.
- `Prompt-DJ Rule3 chop-and-repeat R2 (2026-08-05)` — Round 2 (whole-line, the RIGHT approach): `chop1..5` + `LINE-0..3` dry hook-line clips.

## Open escalations / re-verify next session (claims, not facts)

- **Rule 4 LIVE state (dangerous surface) — re-verify next session as a claim:** confirm `_RULE4_ENABLED is True`, `_DELAY_ECHO_WET == 1.10`, `ENGINE_VERSION == "m6.11+m8echo"`, and the golden byte-identical-OFF gate still passes (the one-line OFF fallback intact). Verified true TODAY, but treat as a claim next time.
- **Pre-existing flaky test (NOT any feature):** the full suite can intermittently fail ONE `test_cache_sweep.py` test — proven cross-file state pollution from `test_mix_route.py` (each passes in isolation). Has its own task chip. Still open.
- **Founder decision pending:** whether to delete the dormant, now-superseded effect-pool subsystem (Rule 4 pre-empts it).
- **Older open item (carried, re-verify):** the Export screen "Download full mix" defect from the 2026-07-21 handoff — diagnosed (the fetched file is discarded ~2 ms after download, and the link is never attached to the page), NOT fixed; the fix also needs the dangerous-surface `ExportScreen.test.tsx` strengthened, so it waits on a founder go-ahead. Status unchanged this session.
- **Rule 3 is parked pending the founder's real-DJ consult** — do not build until that input sets the target sound.
