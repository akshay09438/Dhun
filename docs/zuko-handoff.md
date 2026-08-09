# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-08-10 (session close — **song-marker tool + cost correction + beat marks**) — **MARKER SIMPLIFIED TO DROP + BEST PART; 57/59 BEAT SONGS MARKED (committed to `scripts/song_marks.csv`); LAUNCH COST CORRECTED ~$4 → ~$26 (the All-In-One analysis call was missed). Branch `feat/song-marker-vocal-bestparts`, NOT merged. No app/engine code touched.**

**What happened this session (operator tooling + data; no app-code change):**

1. **Marker tool** (`scripts/mark_drops.html`) — extended to mark on RAW song files (any audio ext, real filenames, keyed by filename, not just ingested `{hash}.wav`), then **simplified per the founder to just Drop (D) + Best part (H)** (a vocal-in / vocal-window pass was built then removed on request). Exports `song_marks.csv` (kinds `drop`, `hook`); autosaves to localStorage; browser-verified clean.
2. **Beat marks captured** — the founder marked **57 of 59 beat songs** (93 drops + 49 best parts), committed to `scripts/song_marks.csv`. **2 beat songs left** (need re-downloaded files). **English vocals (61) + Hindi (16) not yet marked** — founder does **English next session**.
3. **COST CORRECTION** — the launch estimate wrongly treated structure analysis as free/local. Reality (code: `app/audio/analysis.py`): per song the app makes TWO Replicate calls — Demucs stems (~~$0.018) + the **All-In-One structure analyzer** (`sakemin/all-in-one-music-structure-analyzer`, A100, ~94 s, **~$0.11/song**). One-time catalog = **~~$0.13/song → ~$26 for 200 (~$26–37 for ~215)**, not ~$4. Fixed in `docs/reference/web-launch-cost-estimate.md`.

### DO FIRST NEXT SESSION

1. **Founder marks the English vocal songs (61).** Open the marker in the founder's OWN Chrome (the Claude Browser pane CANNOT reach local folders): serve it — `python -m http.server 8123 --directory scripts`, then open `localhost:8123/mark_drops.html` — or just double-click `scripts/mark_drops.html`. Point it at `200 songs/English vocal songs`, mark Drop (D) + Best part (H), **Export CSV** (saves to Downloads as `song_marks.csv`), then I commit the updated file.
2. **Get new files for the 2 unmarked beat songs**, mark them, re-export.
3. **Before ingesting the ~215 songs** (the one-time ~$26–37 Demucs + All-In-One step): resolve **disk** — only ~8 GB free on C:, and ~215 songs' stems need ~30–40 GB. Either free space, or point storage at the cloud (R2 — the launch storage) so stems never touch C:. THEN ingest and **reconcile the filename-keyed marks to song_ids** (ingestion hashes normalized audio; marks must be matched filename → song_id and folded into the planner mark maps `hooks.py`/`main_drops.py`).

### In flight — honest state

- **Nothing half-done in code.** Beat marks captured + committed. Working tree clean apart from the benign `ExportScreen.tsx`/`.test.tsx` CRLF flag (unchanged, not touched this session).
- **NOT DONE (expected, founder-scheduled):** English + Hindi marking; the 2 pending beat songs; ingesting any of the ~136 new songs (raw MP3s only — no stems/analysis yet); wiring the new marks into the engine.
- **Branch `feat/song-marker-vocal-bestparts` is NOT merged** — it carries the marker tool + the cost fix + `song_marks.csv` (+ this handoff). Merge when ready.

### Verification evidence (this session)

- **Marker tool:** loads with **no console errors** (verified twice — the 4-mark version and the simplified 2-mark version). Interactive when served over `localhost:8123`; a `file://` open in the Claude pane renders static (non-interactive) and can't reach local folders — use the founder's real Chrome.
- **Beat marks CSV:** `Import-Csv scripts/song_marks.csv` → **142 rows (93 `drop` + 49 `hook`), 57 distinct songs.**
- **Cost correction:** All-In-One price verified via the Replicate model page (`sakemin/all-in-one-music-structure-analyzer` — A100, ~94 s, ~$0.11/run) + aimodels.fyi.
- **Engine/app suites:** NOT re-run — **no engine/app code changed** (the only files touched are `scripts/*` + docs). Grinder bot tests stand at 15 green from 2026-08-09.

### Open escalations / RE-VERIFY next session (claims, not settled facts)

- **No dangerous-surface file was touched this session.** Nothing dangerous to re-verify.
- **The marks (`scripts/song_marks.csv`) are keyed by RAW FILENAME, not song_id** — they are NOT yet usable by the engine. Treat "the marks are wired in" as FALSE until reconciled at ingestion.
- **Disk pressure is real** (~8 GB free on C:). Confirm free space (or cloud storage) before any large ingest — the founder's <2 GB stop rule applies.

---

## Previous session (2026-08-09 — Grinder Discord bot)

2026-08-09 (session close, later — **Grinder Discord bot**) — **"GRINDER" DISCORD BOT (`/mix` + `/set`) + A WEB-LAUNCH COST ESTIMATE — MERGED to `main` via PR #16 (`c99fe44`), LIVE in the founder's server. Bot tests 15 green; no engine file touched.**

**What shipped this session (a `/zuko:goodnight` batch + live follow-ups):**

1. **Grinder — a throwaway Discord bot** (`services/discord-bot/`, discord.py 2.x, own venv), a convenience-first front-end to the existing mix engine for a store-sector validation demo. Commands: **`/mix`** (autocomplete beat+vocals → in-channel MP3 clip + 🔄 Another take / 🔊 Play in voice / ⏹️ Leave voice), **`/set`** (a step-by-step builder — two dropdowns + ➕ Add mix / ↩️ Remove last / ✅ Build set — for a continuous **2–5-mix** set), `/songs`. Reuses the engine over its LOCAL HTTP API (`/library`, `/mix`, `/set`, audio) with the same auto-rule shuffler — **`render.py`/`validate.py`/the whole engine UNTOUCHED**. Runs locally, $0 for catalog songs. Voice works (PyNaCl installed). Launchers `Start-Grinder.bat` / `Set-Grinder-Token.bat` / `Set-Grinder-Server.bat`. UX rationale: `docs/grinder-discord-demo.md`.
2. **Dropdown-reset fix** (a `/zuko:fix`): the `/set` builder dropdowns snapped back to the placeholder after a pick because the chosen option wasn't flagged `default` on re-render. Fixed with `helpers.select_option_specs` + `SetBuilderView._refresh_selects`; reproducing tests added.
3. **Web-launch cost estimate** — `docs/reference/web-launch-cost-estimate.md`: one-time ~$4 to load 200 songs' stems; monthly ~$40 (100 users) / ~~$260 (1k) / ~$1,800 (10k), dominated by the per-mix Claude call (~~$0.008); storage/bandwidth near-zero on R2. Unit prices web-verified Aug 2026.

Also handled live during setup: the founder created the Discord app + token (token lives ONLY in the local gitignored `.env`); a first invite used the wrong Application id — corrected to the running bot's real app id `1535995274705768540`; command-sync was made non-crashing (falls back to a global sync on a `50001 Missing Access`).

### DO FIRST NEXT SESSION

1. **Confirm a mix/set actually PLAYS (audibly) in Discord.** The founder ran `/mix` and the `/set` builder and the commands work end-to-end (login, guild sync, catalog load, clip path), but an explicit "I heard the finished clip and it sounds good" was NOT captured this session. First thing: run `Start-Grinder.bat` (or `.venv/Scripts/python.exe bot.py` in `services/discord-bot`, with the engine on :8000), make one `/mix` and one `/set`, and confirm the clip plays and sounds right.
2. **(If the founder wants it) build the PARKED Discord tracking view** — a `via="discord"` source tag + Discord username + a Discord-specific unique-users/retention panel on the `/#dev` dashboard. NOTE: recording ALREADY works — Grinder mixes/sets are logged to `events.db` with the Discord user id as `user_id`, so the existing dashboard already counts them (pooled with web, shown as numeric ids). This is a display/tagging add, not a new pipeline. Touches `routes/mix.py`/`routes/set.py` (add a `via`/source field — NON-dangerous) + web `AdminScreen.tsx` (non-dangerous; no need to touch its `.test.tsx`).
3. **The bot runs LOCALLY** (founder's PC; the PowerShell window open = Grinder online). For the validation meeting it must be running; there is no cloud host (deliberate for a demo).

### In flight — honest state

- **Nothing half-done.** Grinder is complete, merged, and live; the dropdown fix landed. Working tree clean apart from a benign Windows CRLF flag on `apps/web/src/components/screens/ExportScreen.tsx`/`.test.tsx` (content-identical, NOT touched this session).
- **Deliberately PARKED (not bugs):** the Discord-specific tracking view (above). Nothing else.

### Verification evidence (this session)

- **Grinder bot suite:** `services/discord-bot/.venv/Scripts/python.exe -m pytest tests -q` → **15 passed (2.8s)** (mocked httpx + real ffmpeg; the dropdown-fix reproducing test included — RED before the fix, GREEN after).
- **Bot modules compile:** `py_compile bot.py api_client.py media.py voice_player.py helpers.py botconfig.py` → OK.
- **Live end-to-end (real Discord):** Grinder logged in as `Grinder#7345`; `commands synced to guild 1533819407866793985` (merrygo); catalog `24 songs (10 beats, 14 vocals)` loaded from the engine (`GET /library 200`); founder saw and used `/mix` and the `/set` builder.
- **Engine (backend/web) suites:** NOT re-run this session — **no engine/web file was changed** (Grinder is an additive, separate package). They stand as of the prior session's green run below.

### Open escalations / RE-VERIFY next session (claims, not settled facts)

- **No dangerous-surface file was touched this session** (the bot reuses the engine over HTTP; nothing in the dangerous-5% list was edited). Nothing dangerous from this session to re-verify.
- **The bot token is a secret held ONLY in the founder's local `services/discord-bot/.env`** (gitignored; never committed, never seen by the agent). If Grinder is ever hosted beyond the founder's PC, that `.env` + token handling become a real secret-management surface to treat carefully.
- **Nothing is waiting on a human.**

---

## Previous session (2026-08-09 — five fixes)

2026-08-09 (session close) — **FIVE FIXES — MERGED to `main` (2026-08-09, via PRs #12/#13; latest merge `f8ad403`), suites GREEN, app live on localhost.** The merge ALSO landed the prior vocal-rich-beat-rule feature (the fix branch was cut from it), so `main` now has both. Local `main` was re-synced to `origin/main` after a transient Windows/OneDrive file lock stalled the first pull (harmless; `git reset --hard origin/main` recovered it, no work lost). This handoff commit itself missed PR #12 (pushed just after the founder opened it) and is being re-added on branch `docs/handoff-2026-08-09` — a docs-only follow-up. The five fixes below are ALL on `main`.

**What shipped this session (each a `/zuko:fix`, in order):**

1. **`eff6bbf` Download button now saves the file** (`ExportScreen.tsx`, non-dangerous). It fetched the mix but never saved it — the `<a>` was never added to the DOM and the object URL was revoked in the same tick as the click. Fix: append the link; defer `revokeObjectURL`+`remove`. The protected `ExportScreen.test.tsx` was strengthened via confirm-and-apply (asserts the link is DOM-connected at click + the URL isn't revoked synchronously).
2. **`94d0cc7` Musical vocal exit-fade** (`workers/render.py` — DANGEROUS, confirm-and-apply). `Placement.exit_fade_ms` + `_exit_fade` — a length-preserving raised-cosine tail fade on Song-2 placements AND standalone Song-1 answers. Gated (0.0 default) so the golden byte-identity gate holds; `validate.py` UNTOUCHED. `ENGINE_VERSION +m14fade`.
3. **`f0326e7` Vocal-song lines finish their sentence** (analysis + planner, non-dangerous). `analysis._vocal_pauses` (breath detection, `TrackAnalysis.vocal_pauses`, `LOCAL_ANALYSIS_VERSION la1→la2`, catalog recomputed free); `plan._finish_sentences` extends each Song-2 slice to the next breath, bounded so it never overlaps the next line. `ENGINE_VERSION +m15phrase`.
4. **`143d523` The BEAT song's own vocal finishes its phrase + graceful hand-off fade** (`workers/render.py` — DANGEROUS, confirm-and-apply; + planner). Founder correction: the abrupt cut was the BEAT's vocal, not Song 2's. `plan._finish_beat_vocal_phrases` extends each `s1_vocal_region` to the beat singer's next breath (bounded to `fence.LEAD_XFADE_SECS` so it stays a legal R1 crossfade — `validate.py` UNTOUCHED); `render._BEAT_VOCAL_FADE_MS=1500` gives the standalone beat vocal a graceful fade vs the 400 ms tail. `ENGINE_VERSION +m16beat`.
5. **`fa538a3` No two mixing rules back-to-back + a catalog sanity sweep** (rule shuffler + routes + new script, non-dangerous). New `scripts/sanity_check.py` sweeps EVERY beat×vocal pair (plan-level, scales to 100–200+ songs) checking the referee hard rules + no rule (1/3/4) repeating back-to-back. It CAUGHT a real bug: guest-verse beats collapsed chop(3)→echo(4) after the shuffle and produced two echoes in a row (120 cases). Fixed via `beat_guest_verse.available_rules` + `rule_shuffle.sequence_over/rule_for_available/set_rules_for` (pick from the beat's usable styles up front; normal beats byte-identical/cache-stable).

### DO FIRST NEXT SESSION

1. **DONE 2026-08-09:** PR #12 merged to `main` (`e26983f`); local `main` re-synced and RE-VERIFIED green on `main` — sanity sweep 280 plans / 0 referee failures / 0 rule back-to-back, and the full backend suite (see Verification). Merge this `docs/handoff-2026-08-09` follow-up too, then the `fix/download-and-abrupt-vocal-fade` branch can be deleted.
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
