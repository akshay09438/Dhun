# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. `/handoff` rewrites this at the end of a session; `/start` and the SessionStart hook replay it at the beginning. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-07-15 (**BEST-PARTS RESEARCH — still 100% in the experiment clone `C:\Dhun-Experiment`, NOT the official app. No official product code changed (only pre-existing LF↔CRLF line-ending noise, not edited).** Big realization this session: the CURRENT live mixer is ALREADY hook+touches+arc, and the "best-parts" idea is a length-selection WINDOW that sits ON TOP — and that window is already BUILT in the engine, just switched OFF by a flag. **The multi-set PR from 2026-07-14 is STILL OPEN — not merged.**)

## Where things stand (one breath)

Two threads:

- **(A) Multi-set UI — still pending merge (unchanged since 2026-07-14).** Built + verified on `feat/multiset-ui` (`319d507`, pushed); PR one click from opening; NOT merged. Untouched this session.
- **(B) Best-parts research (sandbox `C:\Dhun-Experiment`, no GitHub remote).** Proved find→cut→combine, then discovered most of it is already in the live engine. Latest sandbox commit `ce1ac5e`. Research/measurement only — nothing here is promoted into the official app.

## THE BIG REALIZATION (read this first next session)

Reading the live engine (`services/api/app/planner/plan.py`, `window.py`, `render.py`) showed the current mix method is **already richer than the "V3" we were rebuilding**:

- **Full songs today** — the good-parts crop is disabled: `plan.py:32  _GOOD_PARTS_WINDOW_ENABLED = False` (founder decision 2026-07-09 to remix full songs). The window machinery (`window.py`) is kept "dormant + tested", a one-line revert.
- **Vocal = hook + surrounding phrases** — hand-marked hook on the drop + the vocal's other phrases as "setup" (`plan.py:205-284`, `hooks.py`).
- **Beat = full track, shaped** by builds / beat-up / breakdown / bass slams (`stem_moves`).
- **Both songs' vocals trade** — Song 1's own vocals answer in the gaps + lick into the drop (`fence.lead_sections` / `predrop_licks`, `plan.py:101-103`), firing on confident grids.
- `window.py:choose_window` already picks the MAIN drop by post-onset hit-intensity (it even fixed the "energy-average buries the drop" bug, `window.py:85-91`), a clean cue-in, a 30s tail, and take-rotation.

**So the climb-finder is NOT a replacement mixer — it's a LENGTH-SELECTION layer on top.** Flipping the window ON turns the live method into the best-parts short automatically. The only genuinely NEW work the experiments surfaced: (a) **melodic-drop detection** (Innerbloom's drop is a synth swell, no drums — the detector may miss it), and (b) the **mid-word pickup fix** (a hook with a lead-in enters mid-word because the beat-lock starts on the downbeat).

## In flight - done vs left

### (A) Multi-set (carry over — re-verify, don't trust the sentence)

- On `feat/multiset-ui` (`319d507`), pushed. Suite was **415 backend + 49 web green** _as of 2026-07-14_ — a CLAIM to re-run before merge, not re-verified this session.
- Left: founder ear-listen to a two-set join, then open + merge the PR; then the owed `storage.py` set-WAV cache eviction.

### (B) Best-parts research — DONE this session (all sandbox)

- **Exp 3 mid-word pickup fix + LOCKED 3 pairs, all founder-ear-confirmed:**
  - Father Ocean × Der Lagi (`exp3/V3_LOCKED_FatherOcean_x_DerLagi.wav`, `exp3_bestparts.py`) — the mid-word fix that clinched it: prepend the hook's half-bar pickup + pull the anchor back so the line sings INTO the drop. (A 4-bar delay was tried first, sounded worse, reverted.)
  - I Adore You × Tujhe (`exp3/V3_LOCKED_IAdoreYou_x_Tujhe.wav`, `exp3_pair2.py`) — tempo slow-down; same pickup fix generalized.
  - Innerbloom × Dooriyan (`exp3/LOCKED_Innerbloom_x_Dooriyan_SHORT.wav` + `_FULL`, `exp3_innerbloom_dooriyan.py`) — **both songs newly loaded** into the sandbox catalog (Replicate stem-split; catalog now 9 songs). Perfect tempo (122=122); key flagged incompatible (6B vs 7A) but founder said it sounds good. Short windowed around the founder-chosen MAIN drop (~5:54) — which is a MELODIC swell (drums out), so the "loudest bar" missed it (lesson: main drop ≠ energy argmax).
- **The read-only engine analysis** (above) — the session's most valuable output.

### (B) Best-parts — LEFT / IN FLIGHT (the next task, DESIGNED but NOT built — founder closed the session before rendering)

- **The A/B test (requested, not rendered):** on Father Ocean × Der Lagi, build **A = current method, full song** (baseline) vs **B = same mixer fed only each song's climb-finder best-part WINDOW** (same arranging logic, shorter input). Question: does cropping make it **tighter-and-better**, or **thinner** because it starved the arranger of touches?
- **Two risk-flags to surface BEFORE rendering B (founder asked for these explicitly):**
  1. **Vocal collision** — does the climb-finder's vocal anchor (loudest hook) AGREE with where the mixer places the vocal (on the drop)? If not, report the gap in seconds.
  2. **Starvation** — cropped to the window, does the arranger LOSE material it uses in A (predrop_licks, lead_sections, breakdown)? List full-song-available vs survives-in-window.
- **Two real build gaps** (only these, everything else is a flag flip): melodic-drop detection; the mid-word pickup fix.

### Parked (sandbox)

- **Rapture + Anchor Point** — half-loaded beat songs. Replicate read-timeouts hit repeatedly: **Rapture has stems (analysis missing), Anchor Point has neither** (only the normalized WAV). Song files + any stems on disk. Retry with the loop in `scratchpad/retry_beats.py` if wanted. (Innerbloom + Dooriyan loaded fine.)

## Do first next session

Ask the founder: run the **A/B test** (the designed-not-built task above), OR flip the window flag in a sandbox copy of the engine to test the "best-parts is a one-line switch" hypothesis directly, OR go ship multi-set. All three are teed up.

## Verification evidence (which checks ran, what they returned)

- **Official app: NO code changed, NO tests run this session** — nothing to verify. The 2026-07-14 suite result (415 backend + 49 web green, typecheck clean) is the last-known state; **re-run before any multi-set merge**, do not trust the sentence.
- **Sandbox (`C:\Dhun-Experiment`) — verified by render + measurement + the founder's ear, not a test suite (throwaway research):**
  - 3 mixes locked, each founder-confirmed by ear. Timing/drop diagnoses done with measured numbers (e.g. Father Ocean real slam 236.10s vs marked 235.1; Innerbloom main drop is a drumless swell ~5:54).
  - **REAL Replicate calls were made** loading Innerbloom + Dooriyan (paid; stem-split + structure). First attempt 401'd (no charge — token not loaded); fixed by `load_dotenv`. Rapture/Anchor Point incurred some timed-out split attempts (Replicate may charge for compute even on client read-timeout — a small, real cost).
  - Engine analysis is code-cited (plan.py:32/205-284, window.py:85-91/104), not guessed.
- **Git:** sandbox committed through `ce1ac5e` (scripts + README; audio + catalog data gitignored per "never commit mixes"). Official repo: only this handoff committed (docs branch), plus pre-existing line-ending noise.

## Open escalations / re-verify next session (claims, not settled facts)

- **Multi-set "green" is a 2026-07-14 CLAIM** — re-run `cd services/api && ./.venv/Scripts/python.exe -m pytest -q` and `npm run typecheck && npm test` before merging.
- **No dangerous-surface code was edited** (render.py / validate.py / config.py / storage.py / songs.py were READ, not changed; the sandbox used engine functions import-and-call only, incl. `separate_stems` which calls Replicate).
- **Best-parts is NOT in the official app** — it's sandbox research + a code-reading finding that the window is built-but-disabled. Turning it on is a founder decision + the 2 build gaps, not "done."
- **Sandbox catalog now has 9 songs** (added Innerbloom, Dooriyan). This is on-disk only (gitignored data), not version-controlled.
