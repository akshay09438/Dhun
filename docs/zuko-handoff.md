# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. `/handoff` rewrites this at the end of a session; `/start` and the SessionStart hook replay it at the beginning. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-07-21 (**A light session: NO source code changed at all. One catalog song added (Dooriyan, local-only), one long-standing false alarm closed, and one real user-facing DEFECT found and root-caused but deliberately NOT fixed — it is waiting on the founder's decision. `main` @ `03abc99`, unchanged. Web checks green: typecheck 0, lint 0, 49/49 tests. Backend suite NOT run this session — no backend code was touched.**)

## Where things stand (one breath)

`main` @ `03abc99` is the shipped app and **this session did not change a single line of it**. Everything below is either data (gitignored), documentation, or a finding.

- **The app runs locally at `http://localhost:8000`** (started via `.claude/launch.json` → `backend`; it dies with the session, relaunch command at the bottom). It serves the **pre-built** web app from `apps/web/dist/`, last built **15 July** — so any future web source fix needs `npm -w apps/web run build` before localhost shows it.
- **Catalog is now 6 beats + 13 vocals = 19 entries.** Dooriyan was added. ⚠️ **LOCAL-ONLY, as always** — the manifest, stems and analyses live under gitignored `data/`, so the whole 19-song catalog exists only on the founder's machine and transfers to no other clone or deploy.
- **A real defect is open and unfixed:** the Export screen's **"Download full mix" button silently saves nothing.** Diagnosed to root cause; the fix is blocked on a founder decision because it touches a dangerous-surface test file.
- **One item from the last handoff is closed as a false alarm** — the "8 uncommitted web edits of unknown intent" are line-ending noise with zero changed lines. Do not re-raise it.

## ⚠️ Lesson from this session (carry it forward)

**The founder's words describe the symptom, not the mechanism — reproduce before believing either.** The report was "the export button is disabled". It is not disabled: rebuilt in the running app, every Export-screen button is enabled, full opacity, `pointer-events: auto`. Had the agent trusted the word "disabled" it would have gone hunting for a `disabled={...}` condition that does not exist anywhere in `ExportScreen.tsx`. The actual bug is a self-cancelling download two layers away, and it was only found by **instrumenting the live page** (wrapping `URL.createObjectURL` / `anchor.click` / `URL.revokeObjectURL`) and reading the real numbers.

This is the same lesson as 2026-07-16's, one rung up: **read/measure the engine before explaining what the engine does.** It also caught the inverse — a "known problem" carried in this very handoff for days (the 8 mystery web edits) evaporated the moment anyone ran `git diff` on it. **Re-verify carried-forward claims; some of them are already false.**

## In flight - done vs left

**Nothing is half-done in code, because no code was written.** One decision is genuinely pending.

**DONE this session:**

- **Dooriyan ingested** (`scripts/ingest_catalog.py`, existing tool, no code change) — 122 BPM, key 7A, 15 vocal regions, id `c4b28366…`, `role_hint: vocals`. Confirmed live: `/library` returns 19 songs and Dooriyan appears in the Song-2 dropdown in the running app.
- **Two end-to-end renders on the live API** proving the new song and the Merrygo beat both work (numbers under Verification).
- **Docs brought current:** functional spec gained a 2026-07-21 update (the 13th vocal + the broken Download, written as user-facing truth); implementation plan gained three drift-log entries (catalog, false-alarm, export defect).
- **A finished set copied out to the founder's Desktop by hand** as `Adore the Distance - Prompt-DJ set.wav` (6:04.84, stereo 44.1 kHz) — because the in-app Download is broken. This is the current workaround for getting audio off the machine.

**LEFT / BLOCKED:**

- 🔴 **DECISION OWED — the "Download full mix" fix.** Three options were put to the founder and none chosen yet: (a) fix the download **and** strengthen `ExportScreen.test.tsx` (recommended — otherwise the bug can silently return, which is exactly how it shipped); (b) fix the download only; (c) defer. **(a) and the test edit require dangerous-surface sign-off** (`**/*.test.tsx`). After any fix, `npm -w apps/web run build` is required or localhost keeps serving the 15-July bundle.
- **Dooriyan has no hand-marked hook.** It is the only catalog vocal without one, so it does not land its signature line on the drop — it falls back to song order. Needs a founder ear-mark, then an entry in `app/planner/hooks.py`.
- **Carried forward, unchanged and still owed** (none touched this session): the **`storage.py` cache-eviction sweep** (still the most pressing item — the disk filled twice on 2026-07-16 and is still watched by hand; dangerous surface); **short-clip (15–30s) export + final loudness master** (M6 polish); **founder ear-check** on the new vocals over Merrygo and on the **live in-app cut**; and the **Play screen still reports a dropped mix badly** (a small grey "skipped" card after rendering) — previously deferred by the founder, worth offering again.

## Do first next session

**Ask the founder to pick (a)/(b)/(c) on the Download fix** — it is the only thing blocking a user from getting their own mix out of the app, and it is one small edit plus a rebuild. If they pick (a), get the dangerous-surface approval recorded via `.zuko/approve.js` before editing the test.

Then, in priority order: **the `storage.py` eviction sweep** (disk safety), **Dooriyan's hook mark** (a short ear-check that finishes the song properly), or **M6 polish**.

## Verification evidence (which checks ran, what they returned)

Run 2026-07-21 on `main` @ `03abc99`, working tree effectively clean:

- **Web typecheck:** `npm run typecheck` (→ `tsc --noEmit`) → **exit 0**.
- **Lint:** `npm run lint` (→ `eslint src`) → **exit 0**.
- **Web tests:** `cd apps/web && npx vitest run --pool=forks --poolOptions.forks.singleFork=true` → **8 files, 49 passed**, 3.67s. (Single-fork is still required; the default `npm test` OOMs on this machine.)
- **Backend suite: NOT RUN this session.** Justification, not an excuse: **zero backend files were changed** (`git diff` reports 0 content lines repo-wide), and the live uvicorn server was deliberately left running for the founder, which is known to make `test_mix_is_cached` fail with a JSONDecodeError. The last real result stands as a CLAIM to re-verify: 427 passed on 2026-07-16.
- **Working-tree truth:** `git diff` → **0 changed content lines**; `git diff --ignore-cr-at-eol --stat` → **empty**. The 8 "modified" web files differ only in line endings.
- **`main` vs `origin/main`:** `git fetch` then `git status -sb` → **`## main...origin/main`**, no ahead/behind. Nothing was unpushed.
- **Live end-to-end on the running API (real audio, not unit tests):**
  - Catalog: `GET /library` → **19 songs**, Dooriyan `status: ready`, its `/audio` → HTTP 200.
  - **Merrygo × Jugni Ji** → rendered **ready**, 15,937,784-byte WAV = **90.3s**, master_bpm 85.0 — matches the known-good 90.34s Merrygo length.
  - **I Adore You × Dooriyan** → rendered **ready**, 33,867,080-byte WAV = **192s**, master_bpm 120.0, vocal_stretch 0.9836, 3 placements.
  - **2-set run** (I Adore You × Tujhe Bhula Diya → Innerbloom × Dooriyan) → both kept, **BLEND** at seam 176.0s, manifest duration 364.84s == real WAV 364.84s (re-measured with `wave`, not trusted from the API).
- **Export defect, measured not guessed** (instrumented in the live page): blob created **64,357,820 bytes / `audio/wav`** ✓, anchor clicked with `download: "Adore the Distance.wav"` ✓, but `inDom: false` and `revokeObjectURL` fired **2.1 ms** after creation.

## Open escalations / re-verify next session (claims, not settled facts)

- 🔴 **`ExportScreen.tsx` download is broken in the shipped build.** Not a claim — reproduced and measured (above). Fix pending founder choice. **`ExportScreen.test.tsx` passes on the broken code**; treat that test as not covering download at all until it is strengthened.
- **⚠️ The whole 19-song catalog is LOCAL-ONLY** and gitignored — it will not transfer to another clone or a deploy. Hand-marked hooks and per-song overrides key off content ids (`4fc82b59…` Merrygo, `c4b28366…` Dooriyan); on any re-ingest elsewhere the ids must match or the marks silently do not apply.
- **`render.py` / `validate.py` / `storage.py` were NOT edited this session.** CLAIM: re-verify with `git log --oneline -1 -- workers/render.py services/api/app/planner/validate.py services/api/app/storage.py` (should predate 2026-07-21) before trusting it. No dangerous-surface file was touched at all — the session wrote only docs and gitignored data.
- **The 8 "uncommitted web edits" item is CLOSED (false alarm).** Zero content lines. Do not re-raise; do not "finish or discard" them.
- **`test_mix_is_cached` still fails if a live uvicorn server runs during the backend suite.** Stop the server before trusting a red suite.
- **The default `npm test` still OOMs on this machine.** Single-fork passes 49/49. Making single-fork the default needs sign-off (`vitest.config.*` is a dangerous glob).
- **`_GOOD_PARTS_WINDOW_ENABLED` is still `False`**; best-parts (post-render crop) remains the default. Not touched. Re-confirm.
- **`_seam_positions` (`routes/set.py`) remains a SECOND copy** of `assemble_beatmatched_set`'s sample accounting — it drifted once before. Any new branch in the seam engine needs its twin there. Still worth collapsing into one function.
- **CORS lockdown** must be re-verified before any public exposure. `Start-PromptDJ.bat` puts the app on a public ngrok link — do not run it for testers until that is checked.
- **The disk filled to 0 bytes free twice on 2026-07-16** and the eviction sweep still does not exist. Until it does, disk must be watched by hand; this session added ~130 MB of renders.
- **Local dev server:** relaunch with `services/api/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir services/api --port 8000`, or `Start-PromptDJ.bat` for a public link. It does not survive the session. **Rebuild the web app (`npm -w apps/web run build`) after any web source change**, or localhost keeps serving the 15-July bundle.
