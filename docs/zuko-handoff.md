# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-08-09 (session close) — **FIVE FIXES on branch `fix/download-and-abrupt-vocal-fade` — all committed + pushed to `origin` (akshay09438/Dhun), suites GREEN, app live on localhost, PR NOT merged yet (the founder merges it).** Compare link: https://github.com/akshay09438/Dhun/pull/new/fix/download-and-abrupt-vocal-fade. This branch was cut from `feat/vocal-rich-beat-rule` HEAD, so its PR ALSO carries the prior vocal-rich-beat-rule commits — all belong on `main` together. Branch is 6 commits ahead of `main` (5 this session + the vocal-rich feature).

**What shipped this session (each a `/zuko:fix`, in order):**

1. **`eff6bbf` Download button now saves the file** (`ExportScreen.tsx`, non-dangerous). It fetched the mix but never saved it — the `<a>` was never added to the DOM and the object URL was revoked in the same tick as the click. Fix: append the link; defer `revokeObjectURL`+`remove`. The protected `ExportScreen.test.tsx` was strengthened via confirm-and-apply (asserts the link is DOM-connected at click + the URL isn't revoked synchronously).
2. **`94d0cc7` Musical vocal exit-fade** (`workers/render.py` — DANGEROUS, confirm-and-apply). `Placement.exit_fade_ms` + `_exit_fade` — a length-preserving raised-cosine tail fade on Song-2 placements AND standalone Song-1 answers. Gated (0.0 default) so the golden byte-identity gate holds; `validate.py` UNTOUCHED. `ENGINE_VERSION +m14fade`.
3. **`f0326e7` Vocal-song lines finish their sentence** (analysis + planner, non-dangerous). `analysis._vocal_pauses` (breath detection, `TrackAnalysis.vocal_pauses`, `LOCAL_ANALYSIS_VERSION la1→la2`, catalog recomputed free); `plan._finish_sentences` extends each Song-2 slice to the next breath, bounded so it never overlaps the next line. `ENGINE_VERSION +m15phrase`.
4. **`143d523` The BEAT song's own vocal finishes its phrase + graceful hand-off fade** (`workers/render.py` — DANGEROUS, confirm-and-apply; + planner). Founder correction: the abrupt cut was the BEAT's vocal, not Song 2's. `plan._finish_beat_vocal_phrases` extends each `s1_vocal_region` to the beat singer's next breath (bounded to `fence.LEAD_XFADE_SECS` so it stays a legal R1 crossfade — `validate.py` UNTOUCHED); `render._BEAT_VOCAL_FADE_MS=1500` gives the standalone beat vocal a graceful fade vs the 400 ms tail. `ENGINE_VERSION +m16beat`.
5. **`fa538a3` No two mixing rules back-to-back + a catalog sanity sweep** (rule shuffler + routes + new script, non-dangerous). New `scripts/sanity_check.py` sweeps EVERY beat×vocal pair (plan-level, scales to 100–200+ songs) checking the referee hard rules + no rule (1/3/4) repeating back-to-back. It CAUGHT a real bug: guest-verse beats collapsed chop(3)→echo(4) after the shuffle and produced two echoes in a row (120 cases). Fixed via `beat_guest_verse.available_rules` + `rule_shuffle.sequence_over/rule_for_available/set_rules_for` (pick from the beat's usable styles up front; normal beats byte-identical/cache-stable).

### DO FIRST NEXT SESSION

1. **If the founder merged the PR to `main`,** pull `main`, delete the branch, and re-verify green on `main` (the merge also lands the vocal-rich-beat-rule feature).
2. **Founder ear-check follow-ups (only if they ask):** the vocal-fade lengths are single dials — `_EXIT_FADE_MS=400`, `_BEAT_VOCAL_FADE_MS=1500` (`render.py`), `_SENTENCE_FINISH_MAX_S=5` (`plan.py`). Adjusting them is a light change (the render ones are DANGEROUS → confirm-and-apply).
3. **Run `scripts/sanity_check.py` whenever songs are added** — it's the standing sense/bug/sanity sweep the founder asked for.

### In flight — honest state

- **Nothing half-done. All five fixes are complete, committed, pushed, and self-consistent.** Working tree clean.
- **Deliberately DEFERRED (founder-aware, NOT bugs):**
  - **Stage 2 "trail under" beyond 1.2 s:** the founder chose to let a finishing vocal trail under the next line even when they butt together; that only matters past the 1.2 s R1 crossfade allowance, which would require WIDENING the R1 referee (`validate.py`, DANGEROUS). Deferred — the current fix (finish-the-phrase + fade within 1.2 s) covers every case heard so far.
  - **Vocal loudness makeup gain** (a quiet beat vocal ~5.6 dB under the beat, from the 2026-08-08 session) — still parked, NOT addressed this session; needs the founder's level pick + a `render.py` change.
  - **Breath-finishing coverage:** the sanity sweep reports 59% of Song-2 lines and 48% of beat lines land exactly on a breath; the rest are correctly bounded (a non-stop singer with no reachable breath, or the next line is too close). Not a failure — a future quality lever if the founder wants more.

### Verification evidence (this session, on `fa538a3`)

- **Full backend suite:** `cd services/api && .venv/Scripts/python.exe -m pytest -q -p no:randomly` → **647 passed (203s)**. (An intermittent `test_cache_sweep.py` Windows FS-order flake surfaced once mid-session on a different run — non-deterministic, git-confirmed unrelated to this session's files; it passed on the final full run.)
- **Web:** `npm run typecheck` → clean (`tsc --noEmit`, no errors); `npm test` → **9 files, 66 passed**.
- **Catalog sanity sweep:** `scripts/sanity_check.py` → **280 plans built, 0 declined, 0 crashes, 0 referee failures, 0 rule back-to-back — ALL SANITY CHECKS PASSED.**
- **Live end-to-end:** app running (backend :8000, web :5173); fresh mixes render to `ready` and serve audio; `ENGINE_VERSION = m12match+m8echo+m10key+m12force+m13vrb+m14fade+m15phrase+m16beat`. Before/after ear-check clips were sent to the founder for the fade, the phrase-finish, and the beat-vocal hand-off.

### Open escalations / RE-VERIFY next session (claims, not settled facts)

- **`workers/render.py` (DANGEROUS) was edited twice this session** — the exit-fade (commit 2) and the beat-vocal graceful fade (commit 4). Both went through confirm-and-apply + an **adversarial safety review that returned SAFE** (length-preserving, golden gate holds, referee-invariant). Treat "SAFE" as a CLAIM to re-verify if that code is touched again: the golden byte-identity gate (`test_render.py::test_golden_enabled_false_is_byte_identical_to_m6_0`) is the guard — it must stay green.
- **`ExportScreen.test.tsx` (DANGEROUS test-harness surface)** was edited via confirm-and-apply for the Download fix; approvals were cleared after landing (`.zuko/approvals.json` should be empty — verify).
- **No escalation is waiting on a human** except the founder's decision to MERGE the PR. `gh` is not installed here, so the founder opens/merges from the compare link.

---

## Previous session (2026-08-08)

2026-08-08 (session close) — **NEW FEATURE built, committed, pushed: the VOCAL-RICH BEAT RULE.** Branch **`feat/vocal-rich-beat-rule`** (commit `e56036a`, 11 files) is **pushed to `origin` (akshay09438/Dhun)** and **deployed to the running localhost app** — but the **PR is NOT opened/merged yet** (the `gh` CLI isn't installed here; the founder opens it from the GitHub compare link: https://github.com/akshay09438/Dhun/pull/new/feat/vocal-rich-beat-rule). This branch was cut from `docs/handoff-2026-08-08` HEAD, so its PR also carries that one prior docs-handoff commit — both belong on `main`.

**What the rule does:** a beat that is also a full vocal song (Faded, Lean On, Wake Me Up, Closer) now **sings ONE founder-marked guest-verse window, then hands the mic to Song 2** — one voice at a time ("two singers, one mic"). Founder ear-approved on Faded × Dooriyan / Lean On × Khuda Jaane / Wake Me Up × Don't Start Now.

**How it's built (all NON-dangerous files — `render.py`/`validate.py` UNTOUCHED):**

- `app/planner/beat_guest_verse.py` (NEW) — `GUEST_VERSE {song_id: (start,end)}` hand-list + `guest_verse_for()` + `no_chop_rule()`.
- `plan.py` — guest-verse branch in `_apply_flourishes` (runs BEFORE the `_confident` gate, so it works on a shaky grid like Lean On); `_clamp_s1_regions_to_r1` (R1 safety clamp AFTER `_produce_drops` — trims beat-vocal overlap to a clean hand-off so a dense beat keeps its lyrics and never skips on R1).
- `vocal_windows.py` — Song-2 entry floor derived from the guest-verse window (one source of truth).
- `no-chop fix` — rule 3 (chop) drops a vocal-heavy beat's vocal, so `no_chop_rule` remaps rule 3→4 for guest-verse beats in `mix._resolve_rule_take` + `set._resolve_pairs`. `ENGINE_VERSION +m13vrb`.
- Marks in `hooks.py` + `main_drops.py` for the four beats.
- Catalog (LOCAL-ONLY, gitignored) grew to 24: +Wake Me Up, Faded, Lean On, Closer.

### DO FIRST NEXT SESSION

1. **Founder's Wake Me Up loudness pick.** Three clips were sent (before / +6 dB / +10 dB on Wake Me Up × Wari Jawa's guest vocal). The founder hasn't chosen. Once they do → apply a **vocal makeup gain** to the beat's guest vocal. **This touches `workers/render.py` (a DANGEROUS surface) → heavy path: confirm-and-apply via `.zuko/approve.js`, adversarial review, test.**
2. **The abrupt-cut fade** at the hand-off (also `workers/render.py`, dangerous) — for a non-stop singer (Lean On) there's no clean phrase gap, so the fix is a gentle fade-down. Same heavy path.
3. **Open/merge the PR** (link above) if the founder is happy.

### In flight — honest state

- **NOT DONE (known, founder-flagged):** (1) hand-off cut can be abrupt (fade pending); (2) a quiet-voiced beat's guest vocal is **buried ~5.6 dB under the beat** (measured on Wake Me Up × Wari Jawa — it IS rendered, just too quiet) — makeup gain pending the founder's level pick. Both fixes live in the dangerous `render.py`.
- Everything committed is green and self-consistent. The only uncommitted work is THIS handoff + the living-doc updates (docs-only) — committed next, on the same feature branch.

### Verification evidence (this session, on `feat/vocal-rich-beat-rule` @ `e56036a`)

- **Backend:** `cd services/api && .venv/Scripts/python.exe -m pytest -q -p no:randomly` → **622 passed (191s)**.
- **Web:** `npm run typecheck` → clean; `npm run lint` → clean.
- **Live end-to-end (HTTP /mix API on the running app):** Wake Me Up × Wari Jawa on the generation that previously got the chop rule now returns **rule 4, status ready, Wake Me Up guest verse `[38.78, 69.81]` present**. Faded × Dooriyan renders its guest verse (0:31–0:54) then Dooriyan at 0:55. Closer × Dooriyan: Closer sings 0:51–1:10, Dooriyan enters 1:11.
- **New tests (green):** `test_plan.py::test_vocal_rich_beat_sings_its_guest_verse_then_hands_off`, `::test_clamp_trims_song1_vocal_off_song2_so_r1_holds`; `test_mix_route.py::test_vocal_rich_beat_never_gets_the_chop_rule`.

### Open escalations / re-verify next session (claims, not facts)

- **The two pending fixes (loudness makeup gain + hand-off fade) BOTH edit `workers/render.py` — a dangerous 5% surface.** Do NOT apply on the light path. Re-verify with the confirm-and-apply flow (`.zuko/approve.js`), an adversarial safety review, and a test, before merge. The claim "the guest vocal is buried" is measured (−5.6 dB vs beat) but the FIX is unbuilt.
- **FLAKY (pre-existing, NOT from this work):** `test_cache_sweep.py::test_evictable_files_is_top_level_only` + `::test_dry_run_reports_but_deletes_nothing` fail intermittently on Windows (test-order / FS state). Git-stash-verified to fail on the untouched baseline too. Flagged as its own background task; do NOT block on it, but harden it separately.
- **DEV APP SECURITY (still true from prior handoff):** the `/#dev` dashboard exposes user content; it is open on localhost but MUST have `PROMPTDJ_DASHBOARD_TOKEN` set before ANY internet-reachable deploy.
