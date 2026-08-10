# Zuko handoff — Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-08-11 (**ops dashboard + Grinder brand + a live Discord community**) — **Nothing is in flight. `main` == GitHub `main` @ `04115e4` (PRs #23, #24, #25, #26 merged). Working tree clean. All suites green.** Two things need a decision, and one needs urgent action (**disk: 4.3 GB free**).

---

## Where things stand

**The Discord community is real and working.** Grinder is online in the founder's own server (`Grinder`, id `1536469142436057088`), wearing the founder's artwork, and plays mixes out loud in a voice channel. The internal dev dashboard now answers "who is using this, what are they making, when" instead of just showing a feed.

- **Catalog: 30 songs** (12 beats, 18 vocals), loaded and mixable.
- **Running locally:** engine `:8000`, web `:5173`, Grinder bot (2 python processes seen).
- **The founder's server:** icon set, all 6 custom emojis uploaded, 2 roles, The Booth voice channel. Boost level **0**, so banner and invite splash are locked by Discord.

## What shipped (2026-08-11)

1. **The timezone one-way door, closed before launch.** Event timestamps were naive local time with no offset. On a UTC cloud box the same string means a different instant, with nothing in the row to tell them apart — a post-launch "activity by hour" chart would have silently blended two clocks across the deploy date, unrecoverably. Stamps are now timezone-aware; day/hour rollups happen in one explicit **report zone** (`PROMPTDJ_REPORT_TZ`), and the dashboard states which clock it is showing. `tzdata` added because Windows ships no IANA database, so the setting would otherwise look applied and be ignored.
2. **Every mix records its source** ('web' | 'discord') **and a display name.** Recorded only — deliberately absent from the cache-id formulas, so it cannot change a mix or re-render a cached one.
3. **The dev app is four tabs** — Overview (health + feed + a ranked "what is actually breaking"), People (busiest first → click for a per-person page: sittings, favourite songs, own hour pattern), Music (per-song beat/vocal use, degraded/failed, top partner), When (by hour, weekday, last 30 days). Deliberately plain: no charting library, exact numbers always rendered as text.
4. **Grinder wears the founder's brand.** `Icon.png`→ later the founder's chosen `Avatar biggest size.png` as the bot avatar and server icon; the wordmark on `/help` and the welcome post; accent moved from the web app's blue-violet `#6D3BF5` to `#A824CC` **sampled from the artwork** (the old one clashed beside the logo).
5. **`/setup` builds the community** — categories, channels, roles, server icon, all 6 emojis, welcome post. Manage-Server gated, **idempotent**, with a `refresh_branding` flag to replace already-set artwork.
6. **Seven follow-up fixes from real use** — the launcher dying from a PowerShell prompt, `/setup` invisible in a new server, six `/setup` step failures, all em/en dashes removed from user-facing text, the layout cut from ten channels to four, and `#welcome` matching the leftover `WELCOME` category. See the implementation plan's 2026-08-11 status for what each one taught.
7. **New read-only tool:** `python services/discord-bot/scripts/server_status.py` prints the live Discord server and diffs it against the plan. It caught two things a visual check had missed.

## Verification evidence

Re-run on merged `main` @ `04115e4`, this session, real output:

- **Backend:** `services/api/.venv/Scripts/python.exe -m pytest -q` → **720 passed** in 190s.
- **Discord bot:** `services/discord-bot/.venv/Scripts/python.exe -m pytest -q` → **75 passed** (was 23 at session start).
- **Web:** `npm test` → **78 passed** (9 files). `npm run typecheck` → clean. `npm run lint` → clean.
- **Migration + every dashboard read path exercised against the founder's REAL 68-row `events.db`** (backed up to the scratchpad first): 68/68 rows preserved, retention intact, `by_source={'unknown':68}`.
- **All four dashboard tabs + the per-person page driven in a live browser** against real data, **zero console errors**.
- **Grinder confirmed live:** logged in as `Grinder#7345`, in 2 servers, commands synced to the new guild, `brand: avatar uploaded from icon.png`, catalog 30 songs. Bot avatar **fetched from Discord's CDN and visually confirmed** as the founder's disc artwork.
- **Each new test for the seven fixes was verified to FAIL against the old code** before its fix landed — not assumed.
- **NOT run this session:** the catalog sanity sweep (`scripts/sanity_check.py`) and any render/ear check. No engine, `render.py`, `validate.py` or planner file was touched, so those are unaffected — but that is reasoning, not a fresh result.

## DO FIRST NEXT SESSION

1. **Free disk space — this is the blocker for everything else.** C: fell from ~12 GB to **4.3 GB free (99% full)** during this session; `services/api/data` alone is **9.7 GB for 30 songs** (~320 MB/song including rendered mixes). A 100-song catalog needs ~32 GB and **will not fit**. Either run the cache-eviction sweep, clear old renders, or move storage to R2. Nothing about catalog growth is possible until this is dealt with.
2. **Decide the channel-plan divergence** (see Open below) — 10 minutes either way, and it stops `/setup` disagreeing with the live server.
3. **Then the real product gap: radio mode.** The founder's stated goal is a Discord community with **continuous music in voice channels**. That does not exist — The Booth is silent unless someone runs `/mix` and taps play. Building it also yields the listening data (voice join/leave events are already permitted, no new Discord permission needed), which is the honest measure of whether a mix is any good. Worth a `/zuko:discover` first: what plays when nobody has asked for anything, does it loop the catalog or generate fresh mixes, can people queue requests, does it stop when the room empties.

## Open / parked (honest)

- **DIVERGENCE, accepted, needs a decision:** `server_setup.STRUCTURE` describes `#welcome` and `#best-mixes`; the live server has **neither** — the founder kept their own layout and said "right now it's fine". So `/setup` reports those as missing and the founder's channels as "not in the plan" every run. Also: **the welcome post has never been posted anywhere**, because its target `#welcome` was never created. Do not trust an older status block that says otherwise — check with `server_status.py`.
- **Source tagging is deployed but UNPROVEN in the wild.** All 68 events still read `source='unknown'`; no real mix has been made since the tagging shipped, so the end-to-end path (Discord `/mix` → a row tagged `discord` with a username) is verified only by tests, not by a real mix. **Re-verify next session:** make one mix in Discord, refresh `/#dev`, confirm the row shows a Discord badge and a name.
- **WAITING ON THE FOUNDER (only they can do it):** the **Application icon** in the Discord Developer Portal still shows the old "G" next to `/mix` in the command picker. The bot's _avatar_ is correct (fetched and confirmed); the command-picker icon is a separate Developer Portal field the API cannot change.
- **`@Session Crew` is a role nobody can join.** Created as an opt-in "ping me for sessions" role, but only an admin can grant it, which defeats the point. Either make it self-assignable or delete it. Founder decision pending.
- **Banner + invite splash locked** at boost level 0 (need levels 2 and 1). Artwork is shipped and ready at `services/discord-bot/assets/banner.png`; `/setup` applies it automatically the moment the server qualifies.
- **Founder artwork defect:** all four `Avatar *.png` exports are broken identically (disc sliced horizontally, halves offset, the G mashed into a blob) at every size including the 2048 master — a shifted layer or broken clipping mask in the source. Flagged twice; the founder chose `Avatar biggest size.png` anyway, which is their call and may be a deliberate "cut record" look. `Icon.png` (the clean G) is still in the source folder if it is ever wanted back.
- **Still wanted from the founder:** a **horizontal lockup** (G + GRINDER on one line) — the wordmark lives inside a circle so it cannot sit across a banner or a web header.
- **The two data gaps that matter, both still unbuilt:** nothing records **listening** (played to the end vs skipped) or **drop-off** (people who open the app or bot and leave without finishing a mix). The first is the whole game for a listening room; the second is the actual answer to "where do people get stuck".
- **The engine is the founder's laptop.** It renders one mix at a time in-process and must stay awake, so it cannot serve the 100–500 people the founder is considering. Costed this session: ~$13 one-time to load 100 songs (~$0.13/song via Replicate), then ~$40/month hosting + R2 for a few hundred users. **Advice given: invite 5–10 friends on the current setup first and find out whether people stay, before paying for scale.**
- **Housekeeping:** the founder's `events.db` still contains leftover test rows with placeholder songs (`aaaaaaaa`/`bbbbbbbb`, shown as "Song 1 → Song 2") that will skew launch numbers. Also, `PROMPTDJ_REPORT_TZ` must be set to `Asia/Kolkata` when the API moves to a cloud box, or day/hour rollups will group by UTC days.
- **Pre-existing, not introduced:** the repo has no `.gitattributes`, so several web files show as modified purely from CRLF/LF churn on every checkout. Cosmetic, but it makes `git status` noisy.
