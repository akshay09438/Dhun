# Zuko handoff — Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

**2026-08-18, overnight run.** **THE JOURNEY IS REBUILT: `/grind` now carries your own songs and `/add` is gone.** The founder's report was about the experience, not the sound — _"I like the mixes they are making but this is the issue and the experience is the issue."_ And for the first time in this product's life, **two uploaded songs have been mixed together.**

**IN FLIGHT: [PR #70](https://github.com/akshay09438/Dhun/pull/70)** (`feat/one-door-bring-your-own-songs` → main, 2 commits, pushed, **not merged**).
**MERGED EARLIER: PR #69** — the timeout fix has been on `main` since 2026-08-17T19:34Z.

**THE LINK: `https://discord.gg/WJ9b78hFQb`** — permanent, lands on `#read-this-first`.

⚠️ **Never run `/setup` on the live server, any flag.** Use `scripts/refresh_copy.py` for words, `scripts/clear_channels.py` for wiping.

---

## ⚠️ DO THIS FIRST — nothing is live yet

**Grinder is still running last night's code.** The new `/grind` does not exist in Discord until Grinder is restarted, which also re-syncs the command list and makes `/add` disappear. **I deliberately did not restart it**: that ships a changed command to real members while you were asleep and before you had seen the PR. It is your call, and it is one action.

Order for the morning: **listen → read PR #70 → decide the one staged card → restart Grinder.**

---

## Two things the last handoff said that were NOT TRUE

Written plainly because I repeated one of them to the founder's face.

1. **"IN FLIGHT: one commit, pushed, NO PR yet."** Wrong on all three counts. **PR #69 was MERGED** at 2026-08-17T19:34Z with **two** commits. The timeout fix has been on `main` all along. **My own first check agreed with the handoff and was also wrong** — it shelled out to `gh`, which is **not installed on this machine**, and `ErrorActionPreference='SilentlyContinue'` swallowed the error, so "no output" was read as "no PR". A command that cannot run is not evidence of anything.

2. **"NO UPLOAD HAS EVER SUCCEEDED. Catalogue: 0 uploads."** Wrong. **Two uploads have succeeded** — `GET /songs/mine` reads **2 of 5** for the founder. The catalogue reads 0 because **`GET /library` deliberately excludes uploads** (the security review), so no amount of looking at the catalogue can ever see one.

   **I repeated this error at kickoff**, told the founder their two songs were not in the app, and asked them to authorise ~24 cents on that basis. They were already there. Both ingests returned `duplicate`, and **no money was spent** — paid attempts read **3 before and 3 after**. The authorisation was never used.

---

## 🎧 LISTEN TO THIS FIRST

Two real mixes of the founder's own two songs, in `C:\Users\Akshay\OneDrive\Desktop\Prompt-DJ mixes to listen to\`:

|       | what it is                                                     | length |
| ----- | -------------------------------------------------------------- | ------ |
| **A** | _The drones keep droning_ is the beat, _Heal the planet_ sings | 3:26   |
| **B** | _Heal the planet_ is the beat, _The drones keep droning_ sings | 2:00   |

**Both directions, on purpose — the measurements do not settle it.** _The drones_ has a trustworthy beat-grid (confidence **0.83**) but using it as the beat means the other vocal is **sped up**, and this project has measured that speeding a vocal up warbles while slowing one down sounds fine. _Heal the planet_ gives the kinder stretch but its grid confidence is **0.10**, well under the 0.5 the planner needs before it risks its better moves — so on B the app deliberately plays safe. Their keys (7B and 7A) are relative major/minor, the most compatible pair there is, so key is not the variable either way.

**Which one is better is an ear question, and only yours counts.** Neither is silent, neither clips, both move ~31 dB.

---

## What shipped tonight

**The journey, measured in questions asked:**

| you type                    | what happens                                    | questions |
| --------------------------- | ----------------------------------------------- | --------- |
| `/grind`                    | today's picker, unchanged                       | 0         |
| `/grind my_vocal:`          | goes in, you pick a beat from the menu          | **0**     |
| `/grind my_beat:`           | one pop-up asks the drop, then you pick a vocal | 1         |
| `/grind my_beat: my_vocal:` | one pop-up, then **straight to your own mix**   | 1         |

Before tonight, mixing your own beat with your own vocal took **two commands, two role choices, a drop box shown twice and needed once — and was still not reachable in one go.**

**The drop question is off the command entirely.** It is now a pop-up that appears **only when a beat is attached**, so a vocal is never asked. Getting the time wrong re-asks with the reason on the box instead of throwing your upload away.

**`/add` is deleted.** Its machinery is reused, not lost. **`/mine` stays** — it answers a different question.

---

## What could NOT be built, and why

The founder's first choice was an **"Add your own song" button inside the `/grind` screen**. **Discord does not allow it.** A button or menu cannot open a file picker, and a pop-up box takes typing only. A file can only ever arrive attached to a command. The alternative was not a nicer button — it was a second command, which is the thing being removed. Told to the founder at kickoff, before they chose.

---

## ⚠️ ONE CARD WAITING FOR YOUR YES

**`save-the-drop-for-a-song-already-added`** — `services/api/app/routes/songs.py`, verdict `not-proven-safe` (the cautious default; it has not been run against the engine suite yet).

**Why you will want it:** if you attach a beat you have **already** added and type its drop, the drop is **thrown away** — the app recognises the song, skips ahead (which is why it costs nothing), and never records the new time. **Both of your own songs are stored as `vocals` with no drop**, because until tonight the fastest way past the drop question was to call every song a vocal. So the first time you use `/grind my_beat:` on either of them, you are standing on this bug. **Without this change you cannot set a drop on your own songs at all.**

The bot already **says so on the card** rather than staying silent. The staged change makes it actually save. It touches the upload file, which is on your stop-and-ask list, so it waits.

⚠️ **The queue also still holds `disk-sweep-floors-and-age`, which was WITHDRAWN on 2026-08-13** after two adversarial reviews returned `unsafe`. It is a stale record, **not** a pending decision — do not approve it.

---

## Verification evidence — run 2026-08-18

| Check                                | Result                                                                                              |
| ------------------------------------ | --------------------------------------------------------------------------------------------------- |
| `pytest services/api -q`             | **956 passed, 6 skipped** in 185.68s                                                                |
| bot suite                            | **606 passed** (was 567)                                                                            |
| `npm test`                           | **79 passed** (9 files)                                                                             |
| `npm run lint` / `npm run typecheck` | clean, exit 0                                                                                       |
| Live engine `/health`                | 200                                                                                                 |
| Real ingest through the NEW code     | both songs accepted, returned `duplicate`, £0                                                       |
| Real render, `drones x heal`         | ready **26.8s**, 307.3s full / 206.4s highlight, peak −1.66 dBFS                                    |
| Real render, `heal x drones`         | ready **16.1s**, 204.2s / 120.1s, peak −1.27 dBFS                                                   |
| Near-silent seconds, both highlights | **0.0%**                                                                                            |
| Dangerous surfaces                   | `routes/songs.py`, `render.py`, `validate.py`, `storage.py`, `.github/workflows/**` — all unchanged |
| `.zuko/risk.js`                      | score 2, route `auto-apply`                                                                         |
| Paid attempts                        | **3 of 40**, unchanged across the night                                                             |
| Free disk                            | **7.6 GB**                                                                                          |

**THE 6 SKIPS ARE STILL HOLLOW.** `test_effect_pool_e2e.py` (5) and `test_rule3_parked.py` (1) still skip silently because their fixture, Father Ocean, was deleted in the catalogue prune. **You were offered this tonight and declined it.** Recorded as a decision, not an oversight.

---

## Do first next session

1. **Listen to A and B** and say which direction is right. Everything else is guesswork until you do.
2. **Read [PR #70](https://github.com/akshay09438/Dhun/pull/70)** and merge if you are happy.
3. **Decide the staged card** — it is the difference between being able to set a drop on your own songs and not.
4. **Restart Grinder** to make any of this real in Discord.
5. **Then use `/grind my_beat: my_vocal:` yourself** — I proved the code path, not the Discord experience. Nobody has yet seen the pop-up in a real client.

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
