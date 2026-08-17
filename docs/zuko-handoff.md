# Zuko handoff — Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

**2026-08-18, small hours.** **`/add` SHIPPED AND IS LIVE.** Anyone in the Discord can now add their own song and mix it. It went through three adversarial security reviews before it was switched on — and then the first real upload failed, on a five-second default nobody had chosen.

**MERGED: PR #68** (`feat/wire-upload-instrumental` → main, 13 commits). **IN FLIGHT: `fix/uploads-can-actually-reach-replicate`, one commit, pushed, NO PR yet.**

**THE LINK: `https://discord.gg/WJ9b78hFQb`** — permanent, lands on `#read-this-first`.

⚠️ **Never run `/setup` on the live server, any flag.** Use `scripts/refresh_copy.py` for words, `scripts/clear_channels.py` for wiping.

---

## The one-line version

Uploads work end to end on paper, and the first one that failed proved the safety work was right: nothing kept, no quota burned, the person told plainly. The failure itself was a 5-second timeout on a 50 MB upload — fixed, and the engine is running the fix. **No upload has yet succeeded.**

---

## Live state, measured 2026-08-18 (not claimed)

|                        |                                                                        |
| ---------------------- | ---------------------------------------------------------------------- |
| Engine (uvicorn :8000) | UP, restarted **after** the timeout fix; `/health` 200, size guard 413 |
| Grinder                | UP since 00:38:53, `Grinder#7345`, **commands synced to the guild**    |
| Second Grinder voice   | online — two listening rooms can have sound                            |
| `/add` and `/mine`     | registered and visible                                                 |
| Catalogue              | **77 rows, 64 featured, 0 uploads**                                    |
| Paid attempts spent    | **1 of 40** (the founder's failed upload)                              |
| Free disk              | **7.06 GB**                                                            |

⚠️ **Grinder runs from a console window opened by `Start-Grinder.bat`.** It survives a Claude session ending, **not the laptop sleeping**.

---

## What shipped this session

1. **The catalogue index made safe to write.** It was read-modify-written whole: measured at **19 of 20 rows lost** under concurrent writes, and a failed write left the file **empty** — all 112 rows, not one. Now one locked, atomic writer (`app/library_store.py`). A third hole surfaced from the very first test run: on Windows the atomic replace makes the file briefly un-openable, and the catalogue route read that as "no songs", so the picker could answer **zero** mid-write.
2. **`guest_is_upload` wired.** It had shipped defaulting to False **with no caller**, so it had never once run. Generalised to uploaded beats with a second explicit parameter. **A gap found while reading it:** the hand-marked guest-verse branch returned early, so the fix would have skipped five menu beats entirely.
3. **`/add` and `/mine`.** Both roles; a beat is asked for its drop, because the energy detector measured ~36% precision and Suno masters flat. Progress on the card, the reply carries the grind, your own uploads listed first.
4. **Three adversarial security reviews** (8 + 8 + 4 findings), every fix pinned by a test that was red first.
5. **Catalogue pruned** by 41 off-menu songs (3.34 GB) on the founder's call, keeping every ear-tuned one.

---

## The first real upload failed — and what that proved

At 00:41 the founder's `/add` returned _"That did not come out: The read operation timed out."_

**Not the network.** Replicate's account endpoint answered in **0.8 s** with the same token on the same machine. The cause is a default nobody chose: `replicate.run(...)` builds a client with `timeout=None` and hands it to httpx, **whose default is 5 seconds for every operation, the upload included**. A normalised song is a 45–85 MB WAV, so finishing inside 5 s needs 10–17 MB/s upstream. **The feature could not have worked for anybody** — and no test caught it, because every test stubs the paid call.

**Fixed:** `app/audio/replicate_client.py`, one client at connect 30 s / transfer 600 s, used by both paid calls. A test fails if either ever goes back to the bare module. **The engine has been restarted on this fix and is live.**

**What the failure proved, which is worth as much as the fix:** nothing was kept on disk, the attempt did **not** use one of the founder's five, one paid attempt was recorded, and the card said so in plain words. The safety machinery did exactly its job the first time it met a real failure.

---

## Verification evidence — run 2026-08-18

| Check                                | Result                                  |
| ------------------------------------ | --------------------------------------- |
| `pytest services/api -q`             | **956 passed, 6 skipped** in 228.55s    |
| `pytest services/discord-bot -q`     | **567 passed, 1 skipped** in 25.35s     |
| `npm test`                           | **79 passed** (9 files)                 |
| `npm run lint` / `npm run typecheck` | clean, exit 0                           |
| Live engine `/health`                | 200                                     |
| Live engine size guard               | oversized body → **413**                |
| Live engine cross-site guard         | POST with a foreign `Origin` → **403**  |
| Live `replicate_client` timeout      | `connect=30.0, read=600.0, write=600.0` |
| Grinder                              | connected, commands synced, 2 voices    |
| Free disk                            | 7.06 GB                                 |

**THE 6 SKIPS ARE NOT NEUTRAL.** `test_effect_pool_e2e.py` (5) and `test_rule3_parked.py` (1) are real-audio end-to-end tests whose fixture was **Father Ocean**, which the catalogue prune deleted. They now skip silently — the hollow green this project refuses. The founder decided against restoring it (~12c). **Either restore it or re-point those tests at another cached pair.**

---

## Do first next session

1. **Open the PR for `fix/uploads-can-actually-reach-replicate`.** One commit, pushed, no PR. The engine is already running this code, so main is behind what is live.
2. **Get a real upload through.** Nothing has ever been ingested successfully via `/add`. **Until that happens, "uploads work" is a claim, not a fact.**
3. **Listen to the first uploaded mix.** The upload-owns-the-mix behaviour — the catalogue song stopping singing — has never been heard by anybody.
4. **Decide on the 6 skipped tests.**

---

## Open escalations and things to RE-VERIFY (claims, not facts)

- **⚠️ NO UPLOAD HAS EVER SUCCEEDED.** One attempt, one failure, cause found and fixed — but **the fix is unproven against a real Replicate call.** The next `/add` is the test.
- **⚠️ THE 6 SKIPPED TESTS ARE A HOLLOW GREEN.** See above.
- **⚠️ LOCALHOST-ONLY SECURITY FINDINGS, DELIBERATELY NOT FIXED** (founder: not chasing an attacker already on the machine). **All four become serious the moment anything is tunnelled publicly:**
  - `POST /songs/{id}/analysis` reaches Replicate with **no budget check** — the bot never calls it.
  - `GET /songs/mine/{id}` is unauthenticated: anyone on the machine can list any member's uploads.
  - `uploaded_by` is an unverified form field, so the per-person cap only holds because Discord fills it in honestly.
  - `data/upload_spend.json` can be hand-edited downward to reset the ceiling.
- **⚠️ THE DEV DASHBOARD HAS NO PASSWORD** and `/admin/*` answers 200 with no credentials. Fine on localhost; the public ngrok link is deliberately OFF — **re-verify it is still off before trusting any of the above.**
- **⚠️ THE BOT'S TEST SUITE STILL WRITES INTO THE LIVE `logs/grinder.log`.** No `conftest.py` in `services/discord-bot/tests/`. It made the log useless for checking whether Grinder was running, twice today.
- **⚠️ 20-SONG SHELF vs 40 PAID ATTEMPTS.** Spend never decrements. When the budget runs out, `/add` refuses for everybody until `max_paid_upload_attempts` is raised. By design — but the first person to meet it should not be a stranger.
- **⚠️ UPLOAD SQUATTING.** A byte-identical file uploaded by somebody else first makes that song permanently unreachable to everyone else. Narrow, real, unfixed.
- **⚠️ DISCORD'S 10 MB IS A TIER, NOT A CEILING.** A Nitro member can attach far more, and boosting the server raises it for everyone. The app now refuses on size itself rather than trusting Discord.
- **⚠️ `services/api/app/routes/stems.py` IS NOW AN ACCESS-CONTROL FILE** and is **not** on `dangerousGlobs`. Worth adding.
- **⚠️ `CLAUDE.md` PART B'S ARCHITECTURE MAP IS STILL WRONG** — it lists `workers/analyze.py` and `workers/stems.py`; neither exists.
- **⚠️ The vocal has no makeup gain.** Parked since 08-08, still unfixed.
- **⚠️ Two DIFFERENT people who pick the same pair still share a file** (~1 in 3). Founder was offered the fix and declined.
- **⚠️ `apps/web` shows 6 files permanently modified** by CRLF churn; `git diff --ignore-all-space` is empty. Not real changes.
- **Sleep still kills everything.**

---

## Process notes

- **A green suite proved nothing about the thing that mattered.** 953 tests passed while the only two paid calls in the product could not send a file, because every test stubs them. The bug was found by a real person's first attempt.
- **Measuring beat me twice, the same way.** My first beat-detection metric scored white noise above a real song; my first density metric scored the attack 1.000. Both looked reasonable, both were useless, and only measuring BOTH populations showed it.
- **A passing test hid the hole it was written for.** My first cap test passed because the stub finished instantly — which closed the very window the attack needs. Under realistic timing, 30 uploads went through a cap of 5.
- **The reviews earned their cost.** Three rounds, twenty findings; the two that mattered most — caps that did not cap, and an engine with no door on it — were invisible from reading the code.
- **The disk scare was mine.** 12.7 GB of test litter and a 2.4 GB file a security review left behind, not the founder's music. Worth checking scratch space after any agent run.
