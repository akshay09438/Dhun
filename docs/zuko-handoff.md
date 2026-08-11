# Zuko handoff — Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-08-11 (**sessions 3 and 4 — the Discord channel copy, then a concurrency diagnosis that overturned what we believed about scale**). **All suites green.** PR #30 is **merged**. One branch is open and pushed: `diag/concurrency-500-users` (2 commits, docs only, no code). **Nothing is uncommitted and nothing is unpushed.** The next session is expected to run **`/zuko:goodnight` on jobs 1–8 below**, overnight.

---

## Where things stand

**Session 3 — the Discord copy was wrong on the live server, and now cannot go wrong again.** MERGED via PR #30 and applied to the real server.

- `#read-this-first` had been showing a post from **two versions earlier** — it advertised `/mix`, `/set` and `/songs` (all deleted), pointed at `#make-a-mix` and `#i-made-this` (neither exists) and told people to grab `@Session Crew` (deleted). Root cause: the copy step **skipped any channel that already had a message**, which made `server_setup.py` write-only.
- Copy now **refreshes in place** — it edits Grinder's own earlier post. Discord will not let a bot edit anyone else's message, so nobody's words can be lost.
- Channel names are **live `<#id>` mentions**, so renaming a room re-labels every signpost. (The founder had renamed everything: `the-grinder` → `#get-shit-done`, `fresh-grinds` → `#best-mixes`, one Booth → `Bollywood_House` + `Hollywood_Blends`.)
- `#read-this-first` cut to **one embed** with the "Remix anything." banner; `#rules` cut to **three lines** ending "F\*\*k around and find out." (censored, founder's call); **both voice rooms got their first intro ever**; `/help` stopped promising a `/grind beat: ... vocal: ...` shortcut that does not exist.
- Verified live afterwards: **9 of 9 rooms carry exactly one intro, zero references to a deleted command, channel or role.**

**Session 4 — concurrency diagnosis. READ-ONLY; no engine code was changed.** Full report: [concurrency-diagnosis.md](concurrency-diagnosis.md).

- **"The engine makes one mix at a time" is FALSE.** There is no queue in the render path at all. Measured on ten identical pairs: **288s one-at-a-time became 52.4s together — ~5.5x parallel**, 10/10 succeeded.
- **A cold mix is ~25–30s** (not 80s). **A repeat is 0.03s.**
- **The real 10–15 minute problem is VOICE, and it was blamed on rendering.** One voice connection per **server**, median mix **189s**, so the 10th queued grind **starts at 28 minutes**.
- **There is no admission control anywhere**, and it causes real failures: a sweep run at 89.5% memory with the disk near 2 GB produced 20.7% failures; the **same pairs at the same concurrency passed 10/10 and 6/6 with headroom**.
- **Every failure reports the same sentence**, so a bad pair and a starved machine are indistinguishable — to the user and in `events.db`.

---

## Do first next session — the `/zuko:goodnight` batch (jobs 1–8)

The founder has approved running these overnight. **All are free (code only), and none change how a mix sounds.** Ordered; 1 and 2 are the blocking pair.

| #   | Job                                                                                                                             | Acceptance check                                                                                           | Risk                                      |
| --- | ------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| 1   | **Record WHY a mix failed** — distinguish a quality rejection from out-of-resources from a crash, in the log and in `events.db` | Force a known quality failure and a simulated resource failure; the two produce different recorded reasons | light                                     |
| 2   | **Cap concurrent renders (~6–8) + a real queue**                                                                                | 20 simultaneous requests: all 20 eventually succeed, at most 8 render at once, none fail                   | light                                     |
| 3   | **Show queue position** ("7th, ~3 min")                                                                                         | A request made while 8 are running reports a position, and it counts down                                  | light                                     |
| 4   | **Per-person limit** on queued renders                                                                                          | One user firing 10 requests cannot occupy more than N slots                                                | light                                     |
| 5   | **Auto-delete old renders**                                                                                                     | Renders past an age are removed; a fresh request re-creates on demand                                      | light                                     |
| 6   | **Keep the mp3, drop the wav** once a mix settles                                                                               | Disk per mix drops ~20x; **sets and Regenerate still work** (they read the full render — verify carefully) | light, but see caveat                     |
| 7   | **2–3 Grinder bots for 2–3 rooms**                                                                                              | Two bots hold two different rooms at the same time                                                         | light (needs founder's clicks for tokens) |
| 8   | **Profile the render** — where do the 25–30s go?                                                                                | A written breakdown per stage. Measurement only                                                            | light                                     |

**Ordering note for whoever runs the batch:** job 3 depends on job 2 — without the cap there is no queue to report a position in. Job 6 has the sharpest edge: the full `.wav` is what Regenerate and set-joining build from, so deleting it must not break either.

**Nothing in jobs 1–8 is expected to touch a dangerous-path file.** If any does — `workers/render.py`, `services/api/**/planner/validate.py`, `config.py`, `storage.py`, `routes/songs.py`, any test harness — it must be **STAGED, not applied**, per the goodnight hard gate.

---

## Verification evidence

Every check below was **run at session close**, on `diag/concurrency-500-users`. Real output:

| Check       | Command                                                           | Result                                           |
| ----------- | ----------------------------------------------------------------- | ------------------------------------------------ |
| Discord bot | `services/discord-bot/.venv/Scripts/python.exe -m pytest -q`      | **171 passed** in 7.07s _(148 at session start)_ |
| Backend     | `services/api/.venv/Scripts/python.exe -m pytest services/api -q` | **720 passed** in 260.47s                        |
| Web         | `npm test`                                                        | **78 passed**, 9 files                           |
| Typecheck   | `npm run typecheck`                                               | clean, no output                                 |
| Lint        | `npm run lint`                                                    | clean, no output                                 |

**Note on the backend suite:** it must be scoped to `services/api`. From the repo root pytest also collects the Discord bot's tests, which need the bot's own virtualenv and fail at collection. Harness quirk, not a broken suite.

### Measured facts (session 4), each re-runnable via `scripts/loadtest/`

| Measurement                | Value                                                      |
| -------------------------- | ---------------------------------------------------------- |
| Cold render, alone         | 22.6s / 28.3s; re-measured pairs 11.8–30.1s                |
| Cached repeat              | **0.03s**                                                  |
| 10 pairs one at a time     | ~288s                                                      |
| The same 10 fired together | **52.4s**, 10/10 succeeded, 11.5 mixes/min                 |
| CPU during ONE render      | peak 100%, all 10 of 10 cores >50% busy                    |
| Engine RAM                 | 1.26 GB at 1 concurrent → 5.15 GB at 10                    |
| Median finished mix length | **189s** (min 162, max 265) across 40 real files           |
| Machine                    | Snapdragon X, 10 logical cores, 16.8 GB RAM, Windows ARM64 |

### Verified against the real world, not a fake

- The channel copy was **applied to the live server** and then **re-read**: 9 of 9 rooms carry exactly one intro; zero dead command/channel/role references.
- The failing-pair error was captured from the engine's **own log**, not inferred: `workers.render.RenderError: vocal chain collapsed the crest factor 10.76 -> 5.33`.
- The "songs are broken" conclusion was **overturned by re-testing** — see the corrections below.

---

## Corrections made in-session (do not re-litigate)

- **"Innerbloom and Rapture are broken" was WRONG.** Re-test: Innerbloom × Dooriyan 6/6, Rapture × Panda 6/6, Rapture × Uff Teri Ada 6/6, Innerbloom × 10 vocals at once 10/10. They failed only on a starved machine. **Do not withdraw them.**
- **"Khuda Jaane cannot be mixed with anything" is UNPROVEN.** It failed 0/6 with Father Ocean and also with I Adore You, Innerbloom and Rapture — but the **founder reports it sounds good with Anchor Point and Lean On**, and those two beats were among the **8 of 12 the sweep never reached**. Treat as open.
- **The 20.7% catalog failure rate is an UPPER BOUND** measured on a starved machine, not a property of the catalog. Re-measure with headroom before believing any number.
- **The first parallel-speedup figure (8.7x) was wrong**; two anomalous readings inflated it. **5.5x** is the corrected figure.

---

## Open escalations and things to RE-VERIFY (claims, not facts)

- **The engine and the Grinder bot are BOTH STOPPED.** No process is listening on 8000. The founder's normal setup has them running; **jobs 1–6 need the engine up to verify anything.**
- **Voice still cannot work on this machine.** Windows ARM64: discord.py 2.5.x speaks a retired voice protocol (closes with code 4017), 2.6+ needs `davey`, which has no win-arm64 build. **Unchanged, still blocking, needs an x86 host.** Everything voice-shaped remains **unverified**, including the live pinned status message and arrival notes.
- **Grinder is missing the "Manage Messages" permission**, so 8 of the 9 channel intros are unpinned. Harmless; fixed in Server Settings → Roles → Grinder whenever convenient.
- **Disk: 10.13 GB free, `services/api/data` is 6.7 GB.** During this session it fell to **2.01 GB** and I stopped work to reclaim it. **I deleted ~4 GB of derived render files that my own tests created** (`*.mix.wav`, `*.set.wav`, `*.bestparts.wav` modified within the test window). No original song, stem or analysis was touched. **Claim to re-verify:** nothing the founder made was lost — mixes are content-addressed and regenerate on demand, but this has not been checked against a specific expected mix.
- **`events.db` still holds the `aaaaaaaa`/`bbbbbbbb` placeholder rows** from earlier testing, plus **~160 rows from this session's load tests**, which will skew any real usage numbers. Should be cleared before launch.
- **The catalog sweep is INCOMPLETE** — 82 of 216 pairs. 8 of 12 beats untested: Anchor Point, Merrygo, Wake Me Up, Faded, Lean On, Closer, Hey Brother, Silence. Finishing it needs ~16 GB free disk, or job 5/6 first.
- **The GitHub CLI is still not installed**, so PRs are opened by hand from the link git prints on push.
- **`diag/concurrency-500-users` is pushed but has no PR yet** — docs only, safe to merge.
