# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

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
