# Zuko handoff — Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

**2026-08-18, evening.** **SEVEN PRs MERGED IN ONE DAY, ALL LIVE. NOTHING IN FLIGHT.** The upload journey was rebuilt twice — the second time because the founder _used_ the first — and three separate failures all wearing the sentence "that did not come out" were found and fixed.

**MERGED TODAY: #70** one door · **#71** the drop is saved · **#72** one field, songs in both lists · **#73** specs · **#74** wait your turn · **#75** the 60-second wall · **#76** a wobbly beat still ships.

**THE LINK: `https://discord.gg/WJ9b78hFQb`** — permanent, lands on `#read-this-first`.

⚠️ **Never run `/setup` on the live server, any flag.** Use `scripts/refresh_copy.py` for words, `scripts/clear_channels.py` for wiping.

---

## In flight

**Nothing.** Working tree clean, `main` up to date, every suite green. The next session starts from a settled baseline — which has not been true for several sessions.

---

## Do first next session

1. **Listen, and say whether the looseness is acceptable.** `Circle With Me x Dont Start Now` is on the Desktop in `Prompt-DJ mixes to listen to`. That pair was refused at 17:08 and now ships, but only because the app stopped pinning the vocal to a drifting beat. **If it floats too much, the threshold (`grid_health` at 0.8) is one number and easy to tighten.** This is the only open decision.
2. **A and B are still unheard** — the first mixes ever made from two uploaded songs, from this morning.
3. **Top up Replicate past $5.** Below it the account is rationed to one job at a time. The retry survives that; it does not remove it.
4. **`uploads._stamp()` is still keyed on `(mtime, size)` with no path.** Reverted deliberately when the evidence for it collapsed. Worth fixing on its own merits.

---

## Verification evidence — all run 2026-08-18 evening, not carried over

| Check                               | Result                                                                                                                      |
| ----------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `pytest services/api -q`            | **978 passed, 6 skipped** in 173.89s                                                                                        |
| bot suite                           | **607 passed**                                                                                                              |
| `npm test`                          | **79 passed** (9 files)                                                                                                     |
| `npm run typecheck`                 | clean, exit 0                                                                                                               |
| `npm run lint`                      | clean, exit 0                                                                                                               |
| Live engine `/health`               | 200                                                                                                                         |
| Grinder                             | RUNNING                                                                                                                     |
| Catalogue                           | **77 songs, 64 featured**                                                                                                   |
| Founder's uploads                   | **4 of 5**, all four carrying a hand-typed drop                                                                             |
| Paid attempts                       | **11 of 40**                                                                                                                |
| Free disk                           | **15.88 GB**                                                                                                                |
| ngrok (public tunnel)               | **off** — the localhost-only findings stay contained                                                                        |
| Dangerous surfaces vs `origin/main` | `routes/songs.py`, `planner/validate.py`, `storage.py`, `workers/`, `.github/workflows/`, `conftest.py` — **all unchanged** |

**THE 6 SKIPS ARE STILL HOLLOW.** `test_effect_pool_e2e.py` (5) and `test_rule3_parked.py` (1) skip because their fixture, Father Ocean, was deleted in the catalogue prune. Offered and declined; recorded as a decision, not an oversight.

---

## The three failures that shared one sentence

"That did not come out" meant, in order:

1. **A throttle.** Below $5 Replicate rations an account to one prediction at a time. The app gave up instantly; it now waits 12s / 24s / 36s. Measured rather than assumed — the token was valid and the last 100 predictions had **all succeeded**.
2. **A 60-second wall.** `replicate.run()` defaults to `wait=True` and the library then **discards the client timeout** for `httpx.Timeout(5.0, read=60.5)`. Every job under a minute worked (53s, 58s, 58s, 47s); the one that took 124s died at 65s. Never the balance — **song length**. Fixed with `wait=False`, proven live at 108s and 63s.
3. **A forced beat-lock the referee then refused.** Never-decline pinned every bar of the vocal to a grid drifting 0.10s per beat; R7 correctly rejected the render. The guard asked whether downbeats **exist**, not whether they are **trustworthy**.

---

## ⚠️ The engine now keeps a log, and that is why (2) and (3) were solvable

It had none. Every traceback went to a console window and vanished, so two hypotheses were built on a 200-character summary and **both were wrong**. Grinder learned this on 2026-08-14, when a healthy bot was shut down and debugged because nothing could be read.

**Within minutes of adding it, the log caught itself being polluted** — 92 of its lines were staged failures invented by the test suite. The handler is now switched off under pytest, guarded by its own test.

---

## ⚠️ The parked-test mystery is CLOSED

`drop_saved_for_a_song_already_here.py` was parked this morning because adding it made unrelated tests fail. Ten runs ruled out leaked threads, a shared test account, the manifest cache key, fixture audio and machine load.

The cause: **`conftest` hard-linked the real `upload_spend.json` into the test scratch folder**, so the suite started at the founder's real Replicate spending and climbed toward the same ceiling of 40. At a real counter of 3 it finished just under and was green; at 6 it crossed the line partway through. **The suite's result was tracking the founder's bank balance.**

Excluded via `_NEVER_LINK`. The file is **un-parked and green**, so the drop fix has its safety net, and `tests/parked/` is gone.

---

## Open escalations and things to RE-VERIFY (claims, not facts)

- **⚠️ THE LOOSENESS HAS NOT BEEN JUDGED BY EAR.** A wobbly beat now ships instead of being refused, and the vocal floats rather than sitting tight. That trade was the founder's explicit choice but **nobody has listened to the result**. One number reverses it.
- **⚠️ NOBODY HAS COMPLETED THE NEW JOURNEY IN A REAL DISCORD CLIENT END TO END.** The founder's uploads went through, but the pop-up, the attachment field and the finished card have never been walked start-to-finish by a person. Everything else was driven through the bot's own code.
- **⚠️ NEITHER A NOR B HAS BEEN HEARD.** Two mixes from this morning, still unplayed.
- **⚠️ REPLICATE IS UNDER $5**, so the account is still rationed to one job at a time. The retry survives it; a crowd uploading at once may not.
- **⚠️ `uploads._stamp()` HAS NO PATH IN ITS CACHE KEY.** Two data dirs with same-sized manifests written in one clock tick can collide. Reverted when the evidence collapsed; production has one `data_dir` that never moves, which is why it has never bitten a user.
- **⚠️ THE 6 SKIPPED TESTS ARE A HOLLOW GREEN.** Offered and declined.
- **⚠️ `gh` IS NOT INSTALLED ON THIS MACHINE.** Any step that "checked GitHub" via `gh` checked nothing — that is how a merged PR was reported as unopened. PRs now go through the REST API with git's stored credential.
- **⚠️ LOCALHOST-ONLY SECURITY FINDINGS, DELIBERATELY NOT FIXED** (founder: not chasing an attacker already on the machine). **All four become serious the moment anything is tunnelled publicly:**
  - `POST /songs/{id}/analysis` reaches Replicate with **no budget check** — the bot never calls it.
  - `GET /songs/mine/{id}` is unauthenticated: anyone on the machine can list any member's uploads.
  - `uploaded_by` is an unverified form field, so the per-person cap only holds because Discord fills it in honestly.
  - `data/upload_spend.json` can be hand-edited downward to reset the ceiling.
- **⚠️ THE DEV DASHBOARD HAS NO PASSWORD.** Re-verified this evening: **ngrok is not running**, so the above stay contained. Re-check before trusting it.
- **⚠️ THE BOT'S TEST SUITE STILL WRITES INTO THE LIVE `logs/grinder.log`.** No `conftest.py` in `services/discord-bot/tests/`. The engine now has this guard; the bot does not.
- **⚠️ 20-SONG SHELF vs 40 PAID ATTEMPTS.** Spend never decrements. By design, but the first person to meet it should not be a stranger.
- **⚠️ UPLOAD SQUATTING.** A byte-identical file uploaded by somebody else first makes that song permanently unreachable to everyone else. Narrow, real, unfixed.
- **⚠️ `services/api/app/routes/stems.py` IS AN ACCESS-CONTROL FILE** and is **not** on `dangerousGlobs`. Worth adding.
- **⚠️ `CLAUDE.md` PART B'S ARCHITECTURE MAP IS STILL WRONG** — it lists `workers/analyze.py` and `workers/stems.py`; neither exists.
- **⚠️ The vocal has no makeup gain.** Parked since 08-08, still unfixed.
- **⚠️ Two DIFFERENT people who pick the same pair still share a file** (~1 in 3). Founder was offered the fix and declined.
- **⚠️ `apps/web` shows 6 files permanently modified** by CRLF churn; `git diff --ignore-all-space` is empty. Not real changes.
- **Sleep still kills everything.**

---

## Process notes

- **A summary is not a diagnosis.** Two wrong hypotheses were built on the 200-character failure string the bot displays. The engine's first-ever log file answered the question in one read. Neither of the two hardest bugs today was findable without it.
- **Walking the journey beat the tests, twice.** Printing what a person actually sees caught "the limit is 31 MB" and the vanishing second field. Thirty-nine passing tests said nothing about either.
- **The founder's own use corrected the design.** The two-field `/grind` survived half a day; the founder found its flaw by trying it. No amount of planning substitutes for that.
- **When somebody contradicts your measurement about their own actions, suspect the measurement.** The founder said their songs were already uploaded; the catalogue disagreed; the catalogue _cannot_ show uploads, by a design decision recorded in this repo. They were right.
- **A command that is not installed returns nothing, and nothing reads exactly like "no".** `gh pr list` produced empty output because `gh` does not exist here, and a merged PR was reported as unopened — agreeing with a handoff that was also wrong. Agreement between a document and a broken check is not corroboration.
- **The referee was right every time it was doubted.** Both quality refusals today were correct: one mix genuinely would have drifted. The bug was never the referee — it was upstream, building something the referee then had to reject.
