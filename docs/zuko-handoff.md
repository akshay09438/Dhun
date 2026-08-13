# Zuko handoff — Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

**2026-08-13, evening (the second session that day).** Account security, three new catalog songs, a run of ear-tests that overturned two things the project believed, and 4.6 GB of disk found hiding in plain sight. **Everything is merged — PRs #42, #43 and #44 are all in `main` and the working tree is clean.** Suites re-run at handoff, not carried over.

⚠️ **READ FIRST, still true: never run `/setup` on the founder's live Discord server, any flag.** It recreates its default channels beside the renamed ones. To change channel copy use `scripts/refresh_copy.py` (dry run by default).

⚠️ **THE BOT AND THE API ARE RUNNING AS BACKGROUND PROCESSES OF THAT SESSION.** They were started from the agent shell, not from `Start-Grinder.bat`, and **they will die when the machine sleeps or the session ends, silently.** Do not assume Grinder is live tomorrow — check `services/discord-bot/logs/run.log` for a recent line, and restart with `Start-Grinder.bat` if it is stale.

---

## THE HEADLINE: two beliefs about the engine were wrong, and the founder's ears proved it

**1. The ±15% stretch band does not predict how a pair sounds. Direction and octave-folding do.**

I told the founder Confusion (120) × Location (80) would warble — "a 50% stretch, three times past your threshold". That was arithmetic on raw BPM, and it was wrong, because I had not read `fence.best_stretch`. It **folds octaves**: it tries `master/source`, `master/(source*2)`, `master/(source/2)` and takes whichever is closest to 1.0. It chose **0.75 — a 25% slow-down**, treating Location as double-time 160. Founder's verdict: _"the mix sounds bangerrrrrrrrr"_.

Lean On (98) × Old Town Road (136) then went further — **0.72, a 28% slow-down, the furthest out of band anything has gone** — and the founder said _"works perfectly"_.

Against the one bad case on record (Silence 143 × With You 118, **+21% SPEED-UP, not octave-folded**): **speeding a voice up chipmunks; slowing it down smears, and the ear forgives that far more.** An octave-folded slow-down is the ordinary DJ half/double-time relationship and stays musical.

**Never predict a pair from raw BPM again.** Read `vocal_stretch` out of the plan, check which candidate won, then let the ears decide.

**2. `role_hint` never restricted anything — the catalog is ~2.5× bigger than the app shows.**

`services/api/app/routes/library.py:37` says it in its own comment: _"a display nudge, not a restriction"_. The engine has always accepted any song in either slot; only the two dropdowns filter on it (`SetupScreen.tsx`, `bot.py:120-121`).

**Proved:** Don't Start Now (Dua Lipa, 125, tagged `vocals`) used as the **BEAT** under Old Town Road rendered first time **with no guest-verse window marked**, and the founder said _"sound soo gooooood"_. That last part matters — Faded / Lean On / Wake Me Up / Closer all needed a hand-marked window first, so the assumption was that every vocal-rich beat needs one. At least sometimes it does not.

**The prize: 13 beats × 20 vocals = 260 pairs today; 33 × 20 ≈ 660 if vocals can also be beats. Zero cost, no new songs.** Exposing it needs a `"both"` role value plus widening those two filters. **The founder is picking the songs and will name them next session — that is job 1.**

---

## What shipped (all merged)

1. **The security check — PR #42.** `scripts/server_status.py` gained a read-only **SECURITY** section: server owner, whether require-2FA is on, every role holding Administrator, what Grinder holds but has no code to use, and what it would LOSE if Administrator were removed. **Three bugs found by running it for real, all "a check that lies quietly":** `Member.guild_permissions` returns `Permissions.all()` for anything holding Administrator, so the first run gave a falsely clean bill of health that would have talked the founder into breaking the Door; the report **stopped mid-run and exited 0** because one tick mark could not be encoded on a Windows console and discord.py discarded the traceback; and **two live roles are both named `@Grinder`**, so a name lookup could credit the wrong one.
2. **Account security — done by the founder.** 2FA on Discord and Google with backup codes saved, spend limits set. **Correction made mid-session: Anthropic is prepaid credits, so the balance IS the cap — do NOT enable auto-reload**, which is stronger than a cap and free.
3. **Three catalog songs — PR #43.** Confusion (Drake) **120 BPM / 10A / beat**, Location (Khalid) **80 / 12A / vocals**, Old Town Road **136 / 4B / vocals**. **Catalog now 33 (13 beats, 20 vocals).** Marks wired from the founder's own `song_marks.csv`, including a **guest-verse window for Confusion** (21 vocal regions — without one Drake sings over Song 2 everywhere and R1 bins the mix). Audio and manifest stay local-only; only the marks are code.
4. **The disk, and the janitor's blind spot — PR #44.** See below.
5. **`#read-this-first` now ends with the founder's line:** _"This is a beta version, do not expect perfection, and have fun!"_ Placed LAST, after the instructions, because leading with "do not expect perfection" tells somebody what to think before they have heard anything. **Applied live with `refresh_copy.py --apply` and read back off Discord to confirm.**
6. **Grinder taken live** — `Grinder#7345`, commands synced, 2 voice identities, no door warning at startup. **See the warning at the top about how it was started.**

---

## The disk, in full

`services/api/data` was **9.09 GB**, of which **4.61 GB was `tuning_renders/`** — 60 throwaway renders from the July vocal-chain tuning week, oldest 14 July, **untouched for a month**, larger than everything else in the project. The janitor never mentioned it because `storage._evictable_files` scans only the top level.

Cleared by hand with the founder's explicit yes (the `APPROVED_CHAIN_CONFIG.txt` record was kept), plus 1.44 GB of pytest scratch. **8.39 GB free → 12.47 GB.**

**The founder was offered a recursive sweep and chose "warn, don't delete" — correctly.** Not recursing is the second of two independent guards (the first is the five-suffix allowlist) between the deleter and `data/library/manifest.json`, which indexes the whole catalog. So `janitor.subfolder_report()` walks subfolders, totals files matching the same allowlist the sweep uses, and warns at ≥1 GB; `run_once` logs it on **every** exit path including the healthy one. No `unlink` in the path, mutation-verified. **`storage.py` byte-for-byte unchanged.**

---

## Do first next session

1. **The founder names which vocal songs should also be beats**, then wire the `"both"` role value + widen the two picker filters (`SetupScreen.tsx`, `bot.py:120-121`). Biggest return available: ~2.5× the pairings for nothing.
2. **Two stranded marks: Dooriyan and How Deep Is Your Love.** The founder marked them and the marks never reached the app (see below). Dooriyan is the one the functional spec has been carrying as _"the only catalog vocal with no hand-marked hook."_ Thirty seconds each.
3. **Answer the dashboard question.** The founder asked for "the Discord dev dashboard". **There is no dashboard inside Discord** — the bot has nine commands and none is one; a Discord-specific ops view is recorded in the spec as "Parked, not built". Discord activity surfaces in the **web** `#dev` page. Ask which they meant before building anything.
4. **The render waiting list.** Still unbuilt, still the highest-value item in `docs/launch-costing-200-500-users.md`. The founder said they would handle the 8-at-once problem themselves — confirm before building it.
5. **Correct `docs/launch-costing-200-500-users.md`.** It says ~1.5¢/mix and $16/month at 300 members, assuming two Claude calls per mix. **Neither fires.** Offered and not yet done.

---

## Findings worth keeping

- **⚠️ `scripts/song_marks.csv` IS DEAD CODE — nothing reads it.** The founder's marking tool writes it, but a mark does not reach the app until it is hand-copied into `hooks.py` / `main_drops.py` / `beat_guest_verse.py` **against the song's content id**. Audited: **Dooriyan and How Deep Is Your Love have marks that never landed**; four beats are also unwired (Father Ocean, Anchor Point, Rapture, I Adore You) but those are house tracks where energy detection works. **149 of the 176 marked songs are not in the catalog at all** — a pipeline of future additions.
- **Merging a PR does not update Discord copy.** The copy lives in a posted message; only `refresh_copy.py --apply` edits it. The founder hit this directly ("I don't see the change"). Same trap the spec already records about `/setup`.
- **The served web build was 8 days stale** (built 5 Aug, predating the entire `#dev` ops dashboard) — which is why the dashboard appeared not to exist. Rebuilt. Check `apps/web/dist` is current whenever the UI "is missing" something.
- **Costs at 50 users are effectively zero.** Verified in code: the AI arrangement is OFF (`USE_AI_ARRANGEMENT` unset) and the Discord bot **never calls Claude at all** (`api_client.mix_name` exists but nothing calls it — confirmed by the console logs stopping on 10 Aug while Discord work continued to the 13th). Stems and analysis are cached **per song by content**, so a grind on catalog songs calls nothing.
- **The real ceiling is disk, not money.** ~98 MB per mix against ~10 GB free is roughly 100 mixes of headroom.

---

## Verification evidence — all run at handoff, on `docs/handoff-2026-08-13-evening`

| Check                                      | Result                                                                  |
| ------------------------------------------ | ----------------------------------------------------------------------- |
| Backend, full (`pytest -q`)                | **823 passed**, 0 skipped (was 814; +9 janitor tests)                   |
| Discord bot (`pytest -q`)                  | **397 passed, 1 skipped** (pre-existing ARM `davey` skip)               |
| Web (`npm test`)                           | **78 passed** (9 files)                                                 |
| `npm run typecheck`                        | clean                                                                   |
| `npm run lint`                             | clean                                                                   |
| `workers/render.py`, `planner/validate.py` | **untouched all session** — no mix changed byte-for-byte                |
| `services/api/app/storage.py`              | **untouched** — verified with `git diff --quiet`                        |
| Mutation check (janitor)                   | adding an `unlink` turns `test_it_reports_but_never_deletes` red        |
| Mutation check (security)                  | inverting the Administrator-masking guard turns the suite red           |
| Security check, run live                   | completes, exit 0, reports the real permission picture                  |
| Subfolder warning, run live                | fires correctly against a real 1.2 GB probe; probe removed              |
| Beta line on the live server               | read back off Discord — `BETA LINE PRESENT: True`                       |
| Mixes rendered + founder-ear-approved      | Confusion×Location, Confusion×OTR, LeanOn×OTR, DontStartNow-as-beat×OTR |
| Disk                                       | **~10 GB free**, 96% used; `services/api/data` 4.5 GB                   |

---

## Open escalations and things to RE-VERIFY (claims, not facts)

- **The bot holds Administrator, and this is now MEASURED rather than claimed.** Read honestly (ignoring the Administrator shortcut) it **already holds every permission it needs in its own right and already outranks `@Member`** — so removing Administrator is safe and approvals keep working. Its only other unused grant is `mention_everyone`. **Not removed** — judged cheap but not urgent at this size.
- **`require 2FA for moderator actions` is OFF on the server, deliberately.** It is a TRAP if switched on carelessly: Discord gates Manage Roles behind it, so with no 2FA on the OWNER's account the Door stops granting `@Member` **silently**. The founder now has 2FA, so it would be safe — but the decision to leave it off stands. The reason and the trap are written into `server_status.py` itself.
- **An approval was once recorded but never granted the role, cause UNKNOWN.** Evidence was destroyed by a log overwrite. Treat a repeat as new information.
- **132 leaked `pitch_*` directories** in the real `services/api/data` from `app/audio/pitch.py`'s `mkdtemp` — still growing (was 129 on 12 Aug), so the cleanup is still missing them.
- **The Recycle Bin holds ~3.76 GB.** Not emptied — that is permanent deletion and the founder's call. Worth ~3.7 GB if they want it.
- **The test suite needs ~2.5 GB of scratch per run** and regrows `%TEMP%\pytest-of-Akshay`.
- **`bearwolf101` holds `@Backup Admin` with Administrator.** Their account security is now the founder's too — no 2FA conversation has been had with them.
- **The catalog sweep stopped at 105 of 216 pairs**, and the catalog has since grown to 33 songs.
- **95 mixes shipped with a 21–39% tempo stretch; 94 of them unheard.** Re-read this in light of the headline — direction matters, so some may be fine and some not.
- **Old Town Road's analysis found only ONE vocal region** for the whole track (a degenerate blob read, same pattern as Rapture). Its hand-marked hook is carrying more weight than usual. It sounded good anyway.
- **Three stale branches were never merged and are superseded:** `docs/handoff-2026-08-06`, `docs/handoff-post-merge`, `fix/application-icon` — each a single old handoff-doc commit. Safe to delete.
- **The GitHub CLI is still not installed**, so PRs are opened by hand.

---

## Process notes

- **Three ear-verdicts contradicted what the numbers predicted, and the numbers were mine.** The lesson is not "the thresholds are wrong" but "a threshold is not a prediction". Where a claim is about how something SOUNDS, render it and ask — pennies and half a minute.
- **I gave the founder an eight-item security list when two items mattered.** They pushed back with _"I don't want to spend my time on things that aren't relevant for 50-100 users"_ and were right. Sizing the work to the actual risk is part of the work.
- **A flagged problem turned out to be already solved.** I raised the applicant-email privacy gap; reading the actual form showed the founder had already written _"so we can tell you the outcome"_ into the email box. Check the artefact before reporting a gap in it.
- **I reintroduced the project's own headline bug.** My first draft of the janitor tests wrote real 1–2 GB files and filled the disk mid-run — the exact failure the morning's handoff was about. Caught, rewritten to kilobytes, and the 3.5 GB of scratch cleaned up.
- **The same Windows encoding bug bit three times in one day** — in `server_status.py`, in the Discord welcome copy (caught by `test_no_fancy_dashes_on_any_card`), and in the janitor's warning text. Anything printed or logged on this machine must be plain ASCII.
- Every commit went to a branch, never to `main`.
