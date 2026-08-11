# Zuko handoff — Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-08-12 (**session 5 — the `/zuko:goodnight` concurrency batch, and the ARM voice wall coming down**). Branch `zuko/goodnight-2026-08-12`, **3 commits, not merged, no PR yet.** One dangerous change is **STAGED and waiting for the founder**. Nothing else is uncommitted.

---

## Where things stand

**The overnight batch (jobs 1-8 from the previous handoff) ran, re-scoped at kickoff against three founder lenses: developer / a consumer who wants an instant mix in Discord / a founder with no budget.** Full plain-language report: [.zuko/goodnight/report.md](../.zuko/goodnight/report.md).

**THE HEADLINE — voice works on this machine now.** Grinder had never once been able to play audio in a listening room here; both rooms were silent rooms. The recorded reason ("ARM cannot do voice") was **too broad**, and the breadth is what kept it unsolved. The true constraint: `davey` (required unconditionally at `discord/voice_client.py:222`, not just for E2EE) is a **Rust** crate publishing `win_amd64` wheels and **no `win_arm64` wheel**. Windows 11 on ARM runs Intel binaries by emulation, so an Intel CPython 3.11 installs it and it works. **Proven, not theorised: connected to `#Bollywood_House`, negotiated `aead_xchacha20_poly1305_rtpsize`, played audio, clean disconnect — and the whole bot suite (192) passes under the new venv.** Cost: nothing.

**Everything else in the batch is built and applied on the branch:** the failure taxonomy (`app/failure.py` — declined / quality / resources / bug, in `events.db` as `fail_kind`); the bounded render queue (`app/renderq.py`, cap 8, 2 slots per person); **sets routed through the same queue as ONE job** (they used to bypass the cap entirely with their own thread); resource failures re-queued instead of blamed on the user; a grinding card that moves; per-stage timings on every render; `GET /queue`; and `speakers.py`, the extra-voice-identity pool.

**Job 6 ("keep the mp3, drop the wav") was CUT at kickoff by the founder** — a repeat mix returns in 0.03s because the full render is kept, and in a busy room that instant repeat is the product.

---

## Do first next session

1. **Decide the staged disk change** (see the approval queue below). It is the only thing blocking.
2. **Wire `speakers.py` into `booth.py` — and now it can actually be PROVEN.** This was deliberately left unwired: the implementation plan records five separate occasions where a forgiving test fake hid a real Discord bug in exactly this path, and until voice ran there was no way to exercise it. That excuse is gone.
3. **The founder must create the extra bot identities** (Discord developer portal → new application → bot token) and paste them into `services/discord-bot/.env` as `GRINDER_ROOM_TOKENS=tok1,tok2`. Free; only a human can do it. Until then, one room at a time.
4. **Consider the best-parts crop.** It costs **7.98s of a 25.68s render — 31%** — and runs _after_ the full mix is already rendered. That is where the next second of speed is, not in the mixing.
5. **Open the PR for this branch** (3 commits) and merge once the staged card is decided.

---

## Approval queue — STAGED, NOT APPLIED

| Card                        | File                          | Verdict | Route                                                           |
| --------------------------- | ----------------------------- | ------- | --------------------------------------------------------------- |
| `disk-sweep-floors-and-age` | `services/api/app/storage.py` | safe    | **human-required (48)** — a full attended review, NOT a one-tap |

Raises the auto-clean floor **2.0 → 4.0 GB** (the old floor sat _inside_ the zone where renders already fail — `app/failure.py` calls anything under 2.5 GB starved) and adds a **7-day age sweep** of untouched renders. Deliberately not raised further: a high floor would evict the render cache continuously and spend the 0.03s instant repeat the founder chose to protect.

**Verified without applying:** the existing disk-safety suite run against the staged content loaded in memory — **15 passed, identical to the control**; plus a sandbox run proving a 10-day-old render goes, a 1-minute-old render stays, and every source / stem / analysis / subdirectory survives. **The gate caught a real bug:** the first version wrote `min_age_secs: float = _EVICT_MIN_AGE_SECS`, which freezes the value at import and silently breaks every runtime override (5 tests failed). Fixed to resolve at call time.

---

## Verification evidence

Run at session close, on `zuko/goodnight-2026-08-12`. Real output:

| Check                        | Command                                                                | Result                                                   |
| ---------------------------- | ---------------------------------------------------------------------- | -------------------------------------------------------- |
| Discord bot (ARM venv)       | `services/discord-bot/.venv/Scripts/python.exe -m pytest -q`           | **192 passed** _(171 at session start)_                  |
| Discord bot (new Intel venv) | `services/discord-bot/.venv-x64/Scripts/python.exe -m pytest -q`       | **192 passed**                                           |
| Backend, mix + set routes    | `pytest services/api/tests/test_mix_route.py test_set_route.py -q`     | 34 passed                                                |
| Backend, new modules         | `pytest .../test_renderq.py test_failure.py test_events_rollups.py -q` | 14 + 13 + 24 passed                                      |
| Backend, full                | `services/api/.venv/Scripts/python.exe -m pytest services/api -q`      | **see the session's final line — re-run before merging** |

**Note (unchanged):** the backend suite must be scoped to `services/api`; from the repo root pytest also collects the Discord bot's tests, which need the bot's own virtualenv and fail at collection. Harness quirk, not a broken suite.

### Measured against the real world, not a fake

| Measurement                                                                      | Value                                                                                                                  |
| -------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| **20 grinds fired simultaneously** (`scripts/loadtest/queue_check.py`)           | **20/20 succeeded, 0 failed**, 125.3s wall, peak rendering **8**, peak waiting **12**                                  |
| Cold render stage profile (`scripts/loadtest/profile_stages.py`, n=4 real pairs) | mixing **15.23s (59.3%)**, best-parts crop **7.98s (31.1%)**, key 1.84s, referee 0.40s, planning ~0s, **total 25.68s** |
| Live voice (`services/discord-bot/scripts/voice_probe.py`, Intel venv)           | **connected to `#Bollywood_House`, played audio, clean disconnect**                                                    |
| Live voice (ARM venv, control)                                                   | `RuntimeError: davey library needed in order to use voice`                                                             |

---

## Corrections made in-session (do not re-litigate)

- **"ARM cannot do voice" was too broad and cost real time.** The narrowest true statement is "`davey` publishes no `win_arm64` wheel". The broad version closes an avenue; the narrow version invites the fix. **Record blockers at their narrowest.**
- **Reading `voice_state.py`'s `has_dave` guard suggests a graceful degradation that does not exist** — the hard requirement is in `voice_client.py`. A live probe answered in 90 seconds what code-reading had got wrong twice.
- **A set did NOT obey the render path.** `routes/set.py` started its own thread and called `_run_mix` in a loop, so the most render-heavy request in the app had the least back-pressure. Closed and pinned.

---

## Open escalations and things to RE-VERIFY (claims, not facts)

- **`speakers.py` is BUILT AND TESTED BUT NOT WIRED** to playback. Its decisions are covered by 10 tests; no audio has ever flowed through it. Treat every claim about multi-room playback as unverified.
- **Voice works only under the Intel venv.** `Start-Grinder.bat` prefers `services/discord-bot/.venv-x64` and falls back to the ARM `.venv`. **Claim to re-verify:** that the launcher picks the right one on a normal double-click — it was edited but the launcher itself was not run end to end.
- **The Intel Python lives at `%LOCALAPPDATA%\Programs\Python\Python311-x64`** and the venv at `services/discord-bot/.venv-x64` (both gitignored). A machine rebuild loses them; the recipe is in the technical spec.
- **Disk: 8.9 GB free.** The load test wrote and then removed ~60 render files. `services/api/data` is still the bulk.
- **`events.db` still holds the `aaaaaaaa`/`bbbbbbbb` placeholder rows**, plus the load-test rows from this session (~24 more) and the earlier ones. Should be cleared before launch.
- **The catalog sweep is still INCOMPLETE** — 82 of 216 pairs; 8 of 12 beats untested. Now cheaper to finish: failures finally say _why_, so a starved-machine failure will no longer be miscounted as a bad pair.
- **The engine was left RUNNING on port 8000** by this session's measurements. Stop it, or reuse it.
- **The GitHub CLI is still not installed**, so PRs are opened by hand from the link git prints on push.
