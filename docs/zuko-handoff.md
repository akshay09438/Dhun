# Zuko handoff — Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

**2026-08-17, evening.** An audit day. `/add` was designed, decided and **not built**. One piece of groundwork shipped, the disk crisis was solved, and eleven real people have now used Grinder.

**IN FLIGHT: `feat/add-your-own-song`, ONE commit, not pushed, no PR.** `/add` does not exist. Nothing user-visible changed today.

**THE LINK: `https://discord.gg/WJ9b78hFQb`** — permanent, lands on `#read-this-first`.

⚠️ **Never run `/setup` on the live server, any flag.** Use `scripts/refresh_copy.py` for words, `scripts/clear_channels.py` for wiping.

⚠️ **Grinder runs from a console window opened by `Start-Grinder.bat`** (12:28 today). It survives a Claude session ending, but **not the laptop sleeping**. Sleep timer is still 60 minutes idle.

---

## People are using it

Eleven named people have made a grind; **five arrived in the last two days**, and every mix in that window was delivered successfully.

| | | |
| ----------------- | -- | ------------------------- |
| akshay09          | 26 | the founder               |
| Lucas George      |  6 |                           |
| bearwolf101       |  5 |                           |
| Aashwin           |  3 |                           |
| DICTATØR          |  2 |                           |
| **Shinchann**     |  2 | new 16 Aug                |
| **IDWChat**       |  1 | new 16 Aug                |
| **DaDdyゼロ(NiLL)** |  1 | new 16 Aug                |
| **shreyansh**     |  1 | first mix after weeks in  |
| **AceyMagic**     |  1 | new 16 Aug — **then left** |
| **big**           |  1 | new 17 Aug 07:50          |

49 grinds all time. **The DM delivery fix has now carried real strangers with zero failures.**

---

## What happened today

1. **A full read-the-code audit of the analysis pipeline**, published as an artifact: every stored field, what produces it, stems, caching, hand-marks, the grind-time contract, cost per track.
2. **The founder froze the `/add` design** (below).
3. **The stated blocker was measured and turned out to be mis-stated** — so a different, larger fix shipped instead.
4. **The disk crisis was solved** — 2.25 GB to 10.07 GB.

---

## The blocker was not what this file said it was

The old open item read _"Anchor Point talks over its guest — one line on a hand-maintained list is the fix."_ Measured against the 216 real mixplans on disk, that is wrong in both directions:

- Anchor Point **averages 44% guest share across 20 plans** — not a broken beat.
- The specific reported pair **Anchor Point × Location gives the guest 20%** (33s vs 135s).
- **8 of 30 beats leave the guest under half.** I Was Never There is 27% — worse than Anchor Point.

One list entry would have fixed roughly one pairing. **What shipped instead:** `build_mix_plan(..., guest_is_upload=False)`. When Song 2 is an upload, Song 1's own vocal is not placed, so the uploader's track carries the whole mix — every beat at once, no per-beat ear-work. Default off; a test pins that the default plan is byte-identical.

**The eight squeezed beats remain an open CATALOGUE question**, untouched by this. It is a taste call, answered by ear, one beat at a time in `beat_guest_verse.GUEST_VERSE`.

---

## The `/add` design, as frozen by the founder

| | |
| ------------------- | ------------------------------------------------------------------ |
| Storage             | laptop for now — 3 users × 5 uploads = 15 songs                     |
| Replicate           | $5 available, ~7¢/song, enough                                      |
| Menu                | uploads **never** enter the 25-slot picker; the reply carries grind |
| Role                | every upload is a **vocal** (song2). Beat uploads out of scope      |
| Access              | 3 hardcoded Discord ids, 5 each, hard cap                           |
| Copyright           | uploader asserts ownership; store uploader id per song              |
| allin1              | keep the Replicate wrapper; local allin1 **dropped**                |
| Stems               | keep all four (see the cache trap below)                            |

**Still to build:** the `/add` command, the free local beat pre-check, and the manifest entry that records the uploader.

---

## Verification evidence — run 2026-08-17

| Check                                           | Result                                                                          |
| ----------------------------------------------- | --------------------------------------------------------------------------------- |
| `pytest services/api -q`                        | **850 passed** in 209.84s (was 845 — 5 new)                                     |
| `pytest services/discord-bot -q`                | **555 passed**                                                                  |
| `npm test`                                      | **79 passed**                                                                   |
| `npm run typecheck` / `npm run lint`            | clean                                                                           |
| Dangerous surfaces                              | **NONE touched** — the only code change is `planner/plan.py`                    |
| Engine `/health`                                | ok                                                                              |
| Grinder                                         | up since 12:28, connected, 49 grinds                                            |
| Free disk                                       | **10.07 GB** — was 2.25 GB                                                      |
| Chrome cache cleared                            | **85 folders, 6.94 GB reclaimed.** Bookmarks, logins, cookies, history verified intact afterwards |
| Guest-share measurement                         | computed over **216 real mixplan.json** files, not estimated                    |
| Working tree                                    | 3 AdminScreen files show as modified — **line endings only**, `git diff --ignore-all-space` is empty |

---

## Do first next session

1. **Push the branch and open the PR.** `feat/add-your-own-song` is one commit, local only. Nothing is on GitHub.
2. **Build `/add`**, in this order: the free local beat pre-check (so a podcast cannot cost money), then the manifest `uploaded_by` field, then the command itself.
3. **Fix the test-suite log pollution.** Unchanged and still costing time — `services/discord-bot/tests/` has **no `conftest.py` at all**, so the suite writes fake errors into the live `logs/grinder.log`. It cost time five times on 15/16 Aug.
4. **Make an engine-down failure readable** — a stranger currently sees `Something broke on the way back: [Errno 10061]`.

---

## Open escalations and things to RE-VERIFY (claims, not facts)

- **⚠️ `/add` IS NOT BUILT.** One commit of groundwork exists. Anyone reading "uploads" in the specs should read the NOT BUILT markers with it.
- **⚠️ THE TEST SUITE WRITES INTO THE LIVE `logs/grinder.log`.** Root cause: no `conftest.py` in the bot's test folder. The database IS safe (all test files redirect via `store.reset_for_tests`); only the log and Windows Temp are polluted.
- **⚠️ DELETING THREE STEMS WOULD BREAK THE CACHE.** `separate_stems()` returns cached only if **all four** exist — delete drums/bass/other and a later call re-runs and **re-pays** Replicate, and `/stems/{id}` reports that song as never-ready. The founder chose to keep all four. Do not "optimise" this without fixing the cache check first.
- **⚠️ `role_hint` MUST BE `"vocals"`, NOT `"vocal"`.** The manifest contract is `"beat" | "vocals" | ""`; the singular silently fails the picker filter.
- **⚠️ GRIND #34 IS STILL UNREACHABLE BY THE PRODUCT.** No `ref_id`, and the rescue post was deleted with the room on the founder's explicit call. Audio survives at `231732de….bestparts.wav` until roughly **2026-08-22**; a one-field DB write would restore access before then. **The classifier blocked that write — it needs a human to allow it.**
- **⚠️ EIGHT BEATS SQUEEZE THE GUEST VOCAL** (27–59% share). Catalogue-only; needs the founder's ear per beat. Not blocking `/add` any more.
- **⚠️ `CLAUDE.md` PART B'S ARCHITECTURE MAP IS WRONG.** It lists `workers/analyze.py` and `workers/stems.py`; neither exists. Analysis is `app/audio/analysis.py`, separation is `app/audio/stems.py`. **The profile itself should be corrected.**
- **⚠️ `vocal_coverage()` IS NOT A QUALITY GATE.** I used it to size the guest-squeeze problem and reported 22 broken beats; the function's own docstring forbids exactly that inference. Corrected with mixplan data. Do not repeat it.
- **⚠️ The vocal has no makeup gain.** Parked since 08-08, still unfixed.
- **⚠️ Two DIFFERENT people who pick the same pair still share a file** (~1 in 3). Founder was offered the fix and declined.
- **⚠️ The dev dashboard has NO password** and `/admin/*` answers 200 with no credentials. Fine on localhost; the public ngrok link is deliberately OFF.
- **⚠️ `storage.py` / `pitch.py` disagree** about pitch-cache rebuild cost. Dangerous surface, needs founder sign-off. Untouched.
- **⚠️ `set_permissions` REPLACES an overwrite**, and **a verifying probe must not be the process that made the change.** Both earned their keep again today.
- **Replicate credit: $5**, roughly 40 songs. Was zero; the founder topped it up as part of the `/add` decision.
- **The GitHub CLI is still not installed**, so PRs are opened by hand.
- **Sleep still kills everything.** 60-minute idle timer, unchanged.

---

## Process notes

- **Measuring beat the written record again.** The handoff's own "one line is the fix" was wrong; 216 mixplans said so. This is the third session running where a measurement overturned a plausible written claim.
- **And measuring beat ME.** My first sizing of the same problem used a coverage number the code explicitly warns against, and produced a confident, wrong answer — caught only by reading the function I was calling.
- **The audit changed a design before it was built.** The founder was about to run allin1 locally; the code shows we already run allin1 in the cloud, and the ARM wall makes local impossible. That was a whole build avoided by reading first.
- **Every live change was dry-run first, applied, then verified by a SEPARATE process** — including confirming Chrome's bookmarks and logins survived the cache clear.
