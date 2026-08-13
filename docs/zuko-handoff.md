# Zuko handoff — Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

**2026-08-13.** A long attended session: four pieces of work, **three merged to `main`**, the fourth pushed with its PR open. **Backend 814 passed, Discord bot 378 passed / 1 skipped, web 78 passed, typecheck + lint clean** — all re-run at handoff, not carried over. Nothing is half-written and nothing is staged.

⚠️ **READ FIRST, still true: never run `/setup` on the founder's live Discord server, any flag.** It recreates its default channels beside the renamed ones.

⚠️ **NEW, and it supersedes an old belief: the disk janitor probably never ate the founder's mix.** The 2026-08-12 handoff recorded "the janitor's deletion path appears to have run for real". The real culprit is almost certainly the TEST SUITE — see the headline below. That is now fixed.

---

## THE HEADLINE: the test suite was deleting the founder's real mixes

Not in any change under review — found while reviewing something else, and the most valuable thing in the session.

**Reproduced, not theorised:** a canary file was planted in the real `services/api/data`, a sweep was run the way a test runs one, and **the test deleted it**. Measured separately: the real folder went from **39 evictable renders / 1.21 GB to zero** across one full-suite run, free disk landing just under `_TARGET_FREE_GB` — `sweep()`'s exact signature — with **no server running**.

**Cause.** `Settings` is a frozen dataclass shared by every module. Tests redirect it per test with `monkeypatch`, which is undone at teardown. But renders do not run on the test's thread — `renderq` hands them to daemon workers, and `maybe_sweep()` runs inside the job. A render still going when its test ended read the restored **real** path. No individual test was written wrongly; the isolation was scoped to the wrong **lifetime**.

**Fixed** by a session-scoped `services/api/conftest.py`. Catalog inputs are hard-linked into the session folder so the six real-audio e2e tests keep running — without that they skip and the suite reports green while testing less (a first attempt scored 808 passed / 6 skipped and was rejected for exactly that).

**What it exposed:** the suite had been staying alive BY deleting those renders. With the real folder unreachable, a full run filled the disk and pytest died with `ENOSPC` — 4.31 GB free down to 92 MB.

---

## What shipped

1. **Routine stale-render cleanup — MERGED (PR #38).** Renders nobody has played in 7 days are tidied on the janitor's timer. **Anything pinned to `#best-mixes` is never removed** — founder rule, and it holds against the emergency sweep too. Emergency floors 2.0/3.0 and `maybe_sweep()` unchanged; `render.py` and `validate.py` untouched.
2. **The Discord rooms went quiet — MERGED (PR #39).** Arrival notes and the "Nobody is listening" card deleted. `_record_arrival` deliberately kept — listening time and drop-off are one of the two data gaps blocking the community phase.
3. **Test-suite isolation — MERGED (PR #40).** The headline above.
4. **THE DOOR — pushed, PR open, branch `feat/the-door`.** Grinder is invite-only. Five questions with a **required email**, applications **pool** for comparison (`/applications`, `/applications suno`), 50 seats, `/invitefriend` gives a one-use link that skips the form. **Applied to the live server and walked end to end by the founder.**

---

## Do first next session

1. **Merge `feat/the-door`.** It is the only unmerged work and it is already running on the founder's live server, so the branch and reality are currently out of step.
2. **The render waiting list.** Still unbuilt, still the highest-value item in `docs/launch-costing-200-500-users.md`, and **the door makes it more urgent rather than less** — the founder is about to deliberately invite 50 people to a machine that builds 8 mixes at once and fails the rest instead of queueing them.
3. **Two-factor authentication on the founder's Discord account**, and the small pieces they flagged at the end of the session. Not started.
4. **Answer the question that got lost:** the dev app keeps a play button for every mix ever made, and unpinned mixes older than 7 days will now 404. The founder was asked and answered with the best-mixes rule instead, which covers a different case. Options: rebuild on play, a longer window, or accept it.

---

## Verification evidence

| Check                                      | Result                                                                                                         |
| ------------------------------------------ | -------------------------------------------------------------------------------------------------------------- |
| Backend, full (`pytest -q`)                | **814 passed** in 217s, 0 skipped                                                                              |
| Discord bot                                | **378 passed, 1 skipped** (pre-existing ARM `davey` skip)                                                      |
| Web (`npm test`)                           | **78 passed** (9 files)                                                                                        |
| `npm run typecheck` / `npm run lint`       | clean / clean                                                                                                  |
| `workers/render.py`, `planner/validate.py` | **untouched all day** — no mix changes byte-for-byte                                                           |
| Canary in the real data dir                | deleted by a test **before** the fix, survives after                                                           |
| Mutation checks                            | ~15 run and reverted; each turned the suite red, except two that exposed hollow tests and were then backfilled |
| Real data dir after the day                | 610 files, 4.03 GB; `tuning_renders` intact at 4.95 GB                                                         |

---

## Open escalations and things to RE-VERIFY (claims, not facts)

- **The bot currently holds Administrator on the live server.** It was turned on to recover a half-locked server and appears not to have been turned off. It works, and it is why granting `@Member` succeeds — but it is more permission than the design intends. Re-check and decide.
- **An approval was recorded but never granted the role, and the cause is UNKNOWN.** The bot was being restarted with `>`, which overwrote its log and destroyed the evidence. Logs now append to a gitignored `services/discord-bot/logs/`. The structural fragility that would produce exactly that symptom — a `@Member` role level with the bot's own role is ungrantable without Administrator — is now detected at startup and reported loudly, but **the actual cause was never proven**. Treat a repeat as new information, not as this same issue.
- **129 leaked `pitch_*` directories** sit inside the real `services/api/data`. `app/audio/pitch.py` makes `tempfile.mkdtemp(dir=settings.data_dir)` and its cleanup is evidently not always reaching them. Near-empty, but litter in the one folder that must stay clean.
- **The test suite needs ~2.5 GB of scratch per run** and regrows `%TEMP%\pytest-of-Akshay` every time. It used to make room by deleting the founder's renders; it cannot now, so this will bite again when the disk is low.
- **The disk is tight.** 8.2 GB free after a clean-up that recovered 6.7 GB, including a 3.19 GB folder that resisted deletion because of the Windows long-path limit. Free space hit 92 MB mid-session.
- **`bearwolf101` now holds a `@Backup Admin` role with Administrator**, at the founder's request, so a lockout cannot cost them the community. **An admin cannot transfer or delete the server** — only the owner can — so this is a strong safety net, not total insurance.
- **The catalog sweep stopped at 105 of 216 pairs.** Half the catalog has never been checked for failure rate.
- **95 mixes shipped with a 21–39% tempo stretch; 94 of them unheard.**
- **The GitHub CLI is still not installed**, so PRs are opened by hand.

---

## Process notes

- **Three adversarial reviews all returned `unsafe`, and checking each finding was worth more than the reviews themselves.** Two of five blocking findings were wrong and one was overstated. Verifying before acting cost minutes and avoided chasing problems that did not exist.
- **Two diagnoses were given to the founder with more confidence than the evidence supported, and both had to be corrected.** One claimed a live security hole that was only latent; one blamed a three-second timeout when the bot had in fact never received the click at all. The second was caught only by checking whether the approval had actually saved — check the state before explaining the cause.
- **A test existed for the exact class of bug that then bit the live server.** `lock_the_door.py` was proven to hand out the role before restricting anything — and then denied `@everyone` before allowing `@Member` per channel, locking the bot out of the channels it was editing and leaving the server half-locked. The rule was right; the test was pointed one level too high.
- **Mutation testing earned its place twice**: once finding three "fixes" with no test behind them at all, once finding a guard that an earlier check was shadowing so it was never exercised.
- Every commit went to a branch, never to `main`.
