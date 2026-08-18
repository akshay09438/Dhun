# Zuko handoff — Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

**2026-08-18, midday.** **THE NEW JOURNEY IS LIVE IN DISCORD.** `/grind` now carries your own beat, your own vocal, or both; `/add` is gone. Verified by asking Discord directly, not by reading a log. The drop fix is shipped too — and its tests are **parked, not passing**, which is the one thing to know.

**MERGED: PR #70** (one door). **OPEN: [PR #71](https://github.com/akshay09438/Dhun/pull/71)** (the drop fix, already applied and running on the live engine).

**THE LINK: `https://discord.gg/WJ9b78hFQb`** — permanent, lands on `#read-this-first`.

⚠️ **Never run `/setup` on the live server, any flag.** Use `scripts/refresh_copy.py` for words, `scripts/clear_channels.py` for wiping.

---

## Live state, measured 2026-08-18 midday (not claimed)

|                             |                                                             |
| --------------------------- | ----------------------------------------------------------- |
| Engine (uvicorn :8000)      | UP, **restarted onto the drop fix**; `/health` 200          |
| Grinder                     | UP, restarted onto the new `/grind`; commands synced; 2 voices |
| `/grind` options in Discord | `my_beat` and `my_vocal`, both **FILE**, both **optional**   |
| `/add`                      | **unregistered** — Discord confirms it is gone               |
| Commands registered         | 10, visibilities all correct                                 |
| Founder's uploads           | **2 of 5**, both `role_hint=vocals`, both `main_drop=None`   |
| Paid attempts               | **3 of 40**, unchanged all session                            |
| Engine suite                | **956 passed, 6 skipped**                                     |

---

## 🎧 STILL UNHEARD

Two mixes of the founder's own two songs sit in `C:\Users\Akshay\OneDrive\Desktop\Prompt-DJ mixes to listen to`. **Nobody has listened to either.** They are the first mixes ever made from two uploaded songs.

- **A** — *The drones keep droning* is the beat (grid confidence 0.83), *Heal the planet* sings. 3:26.
- **B** — the reverse (grid confidence 0.10, so the planner plays safe). 2:00.

Both measure like real music: no silence, no clipping, ~31 dB of movement. Which is *better* is an ear question and only the founder's counts.

---

## ⚠️ THE DROP FIX SHIPPED WITH ITS TESTS PARKED

The fix works: a drop typed for a song already in the hopper is now saved instead of silently binned. Applied after the founder's explicit yes, recorded against the staged content hash, engine restarted onto it, and the guard verified live (re-posting a song as a **vocal** with a drop left it unchanged and cost nothing).

**But `services/api/tests/parked/drop_saved_for_a_song_already_here.py` is not in the suite.** Both tests are correct — red without the fix, green with it — yet adding that FILE to the suite makes one or two **unrelated** tests fail, reproducibly. Ten full-suite runs ruled out leaked ingest threads, a shared test account, the manifest cache key, byte-identical fixture audio, the paid-attempt budget, and machine load. **The cause is unidentified.**

The founder chose to ship the fix and hold the tests rather than keep drilling. `services/api/tests/parked/README.md` records every dead end and the one thing not yet tried: **move the two tests into an existing upload test file instead of adding a new one.**

**The cost, stated rather than hidden: the fix is live and nothing in the suite guards it.**

---

## A latent weakness found and deliberately NOT shipped

`uploads._stamp()` keys the manifest cache on `(mtime, size)` with **no path in it**. Two different data dirs whose manifests hold the same number of rows are the same size, and if written inside one clock tick they share an mtime — so the cache can hand back the wrong directory's rows. Adding the path took the failures 2 → 1 but did not clear them, so it was **reverted**: shipping an unrelated change on a hypothesis that turned out wrong is worse than recording the weakness. Production has one `data_dir` that never moves, which is why it has never bitten a user. **Worth fixing on its own merits, separately.**

---

## Do first next session

1. **Listen to A and B.** Still the only thing nobody can do for the founder.
2. **Use `/grind my_beat:` yourself in Discord.** I proved the code path and the live engine; the pop-up and the attachment fields have never been seen in a real Discord client by anybody.
3. **Set a real drop on your own two songs** — that is what the fix unlocked, and both still read `main_drop=None`.
4. **Merge [PR #71](https://github.com/akshay09438/Dhun/pull/71).**
5. **Un-park the drop tests** — start by moving them into an existing upload test file.

---

## Open escalations and things to RE-VERIFY (claims, not facts)

- **⚠️ NOBODY HAS USED THE NEW JOURNEY IN DISCORD.** I drove the real ingest and the real renders, but the modal, the attachment fields and the card have only ever been exercised through fakes. **The Discord half is a claim.**
- **⚠️ NEITHER MIX HAS BEEN HEARD.** Two files exist and measure like real music. That is not the same as sounding good.
- **⚠️ A DROP TYPED FOR AN ALREADY-ADDED SONG IS DISCARDED.** Admitted on the card; fix staged, not applied.
- **⚠️ THE 6 SKIPPED TESTS ARE A HOLLOW GREEN.** Offered and declined tonight.
- **⚠️ DECLINED TONIGHT, so they are not rediscovered as omissions:** surfacing `/mine` inside the picker, and repairing the 6 skips.
- **⚠️ `gh` IS NOT INSTALLED ON THIS MACHINE.** Any past or future step that "checked GitHub" via `gh` checked nothing. PRs now go through the REST API with git's stored credential.
- **⚠️ LOCALHOST-ONLY SECURITY FINDINGS, DELIBERATELY NOT FIXED** (founder: not chasing an attacker already on the machine). **All four become serious the moment anything is tunnelled publicly:**
  - `POST /songs/{id}/analysis` reaches Replicate with **no budget check** — the bot never calls it.
  - `GET /songs/mine/{id}` is unauthenticated: anyone on the machine can list any member's uploads.
  - `uploaded_by` is an unverified form field, so the per-person cap only holds because Discord fills it in honestly.
  - `data/upload_spend.json` can be hand-edited downward to reset the ceiling.
- **⚠️ THE DEV DASHBOARD HAS NO PASSWORD.** **Re-verified 2026-08-18: ngrok is NOT running, so the public tunnel is off** and the above stay contained.
- **⚠️ THE BOT'S TEST SUITE STILL WRITES INTO THE LIVE `logs/grinder.log`.** No `conftest.py` in `services/discord-bot/tests/`. Still true; it polluted the log again tonight.
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

- **A command that is not installed returns nothing, and nothing reads exactly like "no".** `gh pr list` produced empty output because `gh` does not exist here, and I reported "confirmed: no PR" from it. The handoff had the same belief, so the two agreed and reinforced each other. **Agreement between a document and a broken check is not corroboration.**
- **I told the founder a fact about their own work that was wrong, and asked them to spend money on it.** They said their songs were already uploaded; I said the catalogue disagreed. The catalogue _cannot_ show uploads — by a design decision recorded in this very repo. **When somebody contradicts your measurement about their own actions, suspect the measurement.**
- **The dry run found what the tests could not.** 33 passing tests said nothing about the app announcing "the limit is 31 MB" for a 30 MB cap. Walking the journey and reading what a person would actually see caught it in one pass.
- **The codebase argued with me and was worth listening to.** `grind_cmd`'s docstring explained why options had been removed, and one test left an instruction for exactly the case that arose. Both were followed rather than overridden: the reversal is documented, and both tests came back stricter.
