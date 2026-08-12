# Routine stale-render cleanup — design

_Approved by the founder 2026-08-13. Supersedes the staged goodnight card `disk-sweep-floors-and-age`, which is withdrawn._

## Why this exists, and why the staged card did not ship

The card (staged **2026-08-11 18:36 UTC**) argued that automatic disk cleanup only woke below 2.0 GB free — inside the zone where renders already fail. That was true when it was written.

**`janitor.py` landed 2026-08-12 13:28 IST — about thirteen hours later — and solved exactly that problem**, better: a 60-second timer defending a 6.0 GB cushion, with a _futility brake_ that refuses to delete when deleting would not reach the cushion anyway (born of a real measurement: free disk fell 9.28 → 5.86 GB while Prompt-DJ sat idle and Windows Update held 7.81 GB).

The card was never revised against that. Two independent adversarial reviews on 2026-08-13 both returned **unsafe**, converging on the same blocking finding: the card raised `storage.py`'s own floors to 4.0/6.0 GB and called `sweep()` **from the render hot path with no futility brake**, so at any reading under 4.0 GB free every single grind would empty the whole render cache chasing a 6 GB target it could not reach — destroying the "0.03s instant repeat" the card claimed to protect, in precisely the scenario already measured on this machine.

**What the card was still right about:** the janitor only ever _reacts to pressure_. Nothing does routine tidying, so stale renders accumulate until they become an emergency. That is the half worth building, and it is what this design is.

## Non-goals

- **No change to the emergency floors.** `_MIN_FREE_GB = 2.0` / `_TARGET_FREE_GB = 3.0` stay exactly as they are, sitting _under_ the janitor's 6 GB band, so `maybe_sweep` remains a last-ditch backstop and the janitor remains the single owner of cushion policy.
- **No change to `maybe_sweep()`** — not its behaviour, not its return shape, not its place on the render path.
- **No change to how any mix sounds.** `workers/render.py` and `planner/validate.py` are untouched.
- No new dashboard, no new user-facing surface, no new settings beyond one optional environment override.

## Architecture

The existing split is the design, and keeping it is the point:

| File                                              | Owns                                        | Dangerous?              |
| ------------------------------------------------- | ------------------------------------------- | ----------------------- |
| `services/api/app/storage.py`                     | **Policy** — what may be deleted, and never | Yes (deletes user work) |
| `services/api/app/janitor.py`                     | **Trigger** — when to look                  | No                      |
| `services/api/app/routes/mix.py`, `routes/set.py` | Stamping a render as used when it is served | No                      |

### 1. `storage.py` — the policy (dangerous surface)

- `_MAX_RENDER_AGE_DAYS = 7.0`, overridable at call time via `PROMPTDJ_RENDER_MAX_AGE_DAYS`, resolved **inside the call** — never as a default argument, which Python binds once at import.
- `_evictable_files(min_age_secs: float | None = None)` — same allowlist, same non-recursion, with the age threshold passed in rather than read from a frozen default.
- **New: `sweep_old(max_age_days=None, dry_run=False)`** — deletes regenerable renders whose last-used stamp is older than the window, **regardless of free disk**. Same five-suffix allowlist, same top-level-only scan.

**The one hardening the card lacked:** the effective threshold is
`max(max_age_days * 86400, _EVICT_MIN_AGE_SECS)`.
The 300-second in-flight grace becomes a floor **no caller can breach** — `sweep_old(max_age_days=0)` cannot delete a render being written this second. In the staged card that grace was merely a default, and passing `0` stepped straight over it.

### 2. `janitor.py` — the trigger

`run_once()` performs the age sweep **first**, before the dry-run preview that feeds the futility decision. Order matters: stale renders are gone before free space is measured, so the futility brake decides on accurate numbers and is less likely to have to spend useful cache.

The age sweep deliberately does **not** go through the futility brake. The brake exists to stop _useful_ cache being destroyed while chasing a target that cannot be reached; the age sweep chases no target and removes only what policy already classifies as dead weight.

### 3. Last-played stamping — routes (not dangerous)

The 7 days counts from **last played**, not from creation. This is the founder's explicit choice on 2026-08-13, and it is what the card's own plain-language promise ("untouched for 7 days") always claimed while the code did otherwise.

When a render is served — `GET /mix/{id}/audio` (`routes/mix.py`) and the set audio route (`routes/set.py`) — its modification time is stamped to now.

**Bounded to at most once per day per file.** `services/api/data` sits inside the OneDrive-synced tree, so re-stamping on every play would trigger a cloud re-upload of a large WAV each time. Re-stamp only when the existing stamp is over a day old.

This also strengthens two behaviours that already key on the same timestamp: `sweep()`'s least-recently-used ordering now genuinely means least-recently-_used_, and a file being served looks fresh to the 300s grace.

## Acceptance criteria

1. A render last played 8 days ago is deleted within one janitor tick.
2. A render played yesterday survives, however long ago it was made.
3. A render written seconds ago is never deleted — including via `sweep_old(max_age_days=0)`.
4. The allowlist and non-recursion hold on the new path: sources, stems, analyses, `library/`, `listening/`, `tuning_renders/` are never candidates.
5. `maybe_sweep()` behaviour and return shape are unchanged; `_MIN_FREE_GB` and `_TARGET_FREE_GB` are unchanged.
6. Serving a render stamps it, at most once per day per file.
7. Requesting a deleted mix rebuilds and serves it.

## Testing

Tests are authored by an agent independent of the implementation, against these criteria, and must fail before the implementation exists. Then a fresh adversarial quorum (data-loss lens, caller-contract lens, reality lens) must return `safe` on every lens before the change is applied; any non-`safe` verdict escalates to the founder in plain language.

## Honest limits

- **7 days is a judgement call, not a measurement.** Nothing records how long a mix stays wanted.
- **The first live run should be watched.** No dry run against the real `services/api/data` exists yet.
- **The Discord bot's `grinds.audio_path`** persists absolute paths to `.mix.wav` / `.bestparts.wav`. Nothing reads it back today, so nothing breaks; a future replay feature reading it would find dangling paths for renders swept after 7 days.
- **`failure.py:58` and `technical-spec.md` describe the 2.0 GB floor.** This change does not move that floor, so both remain accurate — deliberately.
