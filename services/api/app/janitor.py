"""The disk janitor — a timer that keeps free space above a cushion, and knows when not to bother.

WHY THIS IS A SEPARATE FILE FROM storage.py, which is the whole design.

`storage.py` owns the **policy**: what may be deleted (an allowlist of five throwaway suffixes),
in what order (oldest first), and what is never touched — sources, stems, analyses, anything in a
subdirectory, anything younger than the grace period. It is on the dangerous list because it
deletes people's finished mixes, and deleted is deleted.

This file owns only the **trigger**: when to ask storage to sweep. Two things fall out of that:

  1. Adding a background cleaner does not require editing the dangerous file at all. Every safety
     rule in `storage.py` is reused exactly as written, byte for byte.
  2. When storage moves to object storage (R2), only the trigger changes — from "free bytes on
     this disk" to an age or cost rule. The safety policy moves untouched. That is the one-way
     door worth getting right up front.

THE FUTILITY BRAKE
------------------
The genuinely new safety idea, and it came from a real measurement on 2026-08-12: free disk fell
from 9.28 GB to 5.86 GB during one session, and Prompt-DJ was NOT the cause — its data folder was
unchanged and the founder's test grinds accounted for 0.51 GB. Windows Update was sitting on
7.81 GB.

A naive cleaner told to reach a 6 GB cushion in that situation deletes every one of the 3.54 GB of
finished mixes and STILL misses the cushion: the whole render cache destroyed to fix a problem
belonging to something else. `storage.sweep` already warns about this — but only AFTER it has
emptied the cache. A warning after the damage is not a brake.

So this asks first. `storage.sweep(dry_run=True)` reports what it WOULD reclaim without deleting
anything; if free-plus-reclaimable still falls short of the cushion, the janitor deletes nothing
and says which way the shortfall lies.
"""
from __future__ import annotations

import asyncio
import logging
import os

from app import storage

log = logging.getLogger(__name__)

# The cushion the founder chose on 2026-08-12: above the ~2.5 GB line where renders start failing,
# with headroom for a full evening in a listening room, and low enough that the 0.03s instant
# repeat survives on a healthy machine. A higher floor would evict the cache continuously and
# spend exactly the property the founder chose to protect.
DEFAULT_CUSHION_GB = 6.0
_ENV_CUSHION = "PROMPTDJ_DISK_CUSHION_GB"

# One disk-usage call per tick when idle, so this is free to run often.
DEFAULT_INTERVAL_SECS = 60.0
_ENV_INTERVAL = "PROMPTDJ_DISK_CHECK_SECS"

# What a cycle decided. Strings rather than an enum so they read plainly in logs and in /queue-style
# JSON without a serialiser.
SKIP_HEALTHY = "skip-healthy"
SKIP_FUTILE = "skip-futile"
SWEEP = "sweep"
ERROR = "error"


class Decision:
    """The outcome of looking at the numbers, before anything is deleted."""

    __slots__ = ("action", "current_free_gb", "could_free_gb", "cushion_gb", "shortfall_gb")

    def __init__(self, action: str, current_free_gb: float, could_free_gb: float,
                 cushion_gb: float, shortfall_gb: float = 0.0) -> None:
        self.action = action
        self.current_free_gb = current_free_gb
        self.could_free_gb = could_free_gb
        self.cushion_gb = cushion_gb
        self.shortfall_gb = shortfall_gb

    @property
    def should_sweep(self) -> bool:
        return self.action == SWEEP

    def as_dict(self) -> dict:
        return {"action": self.action, "current_free_gb": round(self.current_free_gb, 2),
                "could_free_gb": round(self.could_free_gb, 2),
                "cushion_gb": self.cushion_gb, "shortfall_gb": round(self.shortfall_gb, 2)}


def _env_float(name: str, default: float) -> float:
    """Resolved at CALL time, never captured as a default argument.

    Not a stylistic preference: the previous night's attempt at this feature wrote
    `min_age_secs: float = _EVICT_MIN_AGE_SECS`, which freezes the value at import and silently
    breaks every runtime override. Five tests caught it. Same trap, deliberately avoided."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        val = float(raw)
    except (TypeError, ValueError):
        log.warning("%s=%r is not a number — using the default %.1f", name, raw, default)
        return default
    if val <= 0:
        log.warning("%s=%r must be positive — using the default %.1f", name, raw, default)
        return default
    return val


def _cushion_from_env() -> float:
    return _env_float(_ENV_CUSHION, DEFAULT_CUSHION_GB)


def cushion_gb() -> float:
    """The cushion to defend, resolved from the environment at call time."""
    return _cushion_from_env()


def interval_secs() -> float:
    return _env_float(_ENV_INTERVAL, DEFAULT_INTERVAL_SECS)


def decide(current_free_gb: float, could_free_gb: float, cushion_gb: float) -> Decision:
    """Pure arithmetic, so the interesting cases are stated as numbers rather than simulated.

    Three outcomes and no others:
      - at or above the cushion -> nothing to do. The cushion is a floor to stay at, not a number
        to exceed; sweeping here would delete a mix to gain nothing.
      - below it, and a sweep would reach it -> sweep.
      - below it, and a sweep STILL would not reach it -> the pressure is not ours. Delete nothing.
    """
    if current_free_gb >= cushion_gb:
        return Decision(SKIP_HEALTHY, current_free_gb, could_free_gb, cushion_gb)

    reachable = current_free_gb + could_free_gb
    if reachable < cushion_gb:
        return Decision(SKIP_FUTILE, current_free_gb, could_free_gb, cushion_gb,
                        shortfall_gb=cushion_gb - reachable)

    return Decision(SWEEP, current_free_gb, could_free_gb, cushion_gb)


def run_once(*, cushion_gb: float | None = None) -> dict:
    """One cycle: look, decide, and sweep only if it would actually help.

    Never raises. A background timer that dies on one bad cycle stops protecting the disk forever
    and does it silently, which is worse than the problem it was added to solve.
    """
    target = cushion_gb if cushion_gb is not None else _cushion_from_env()

    try:
        # A dry run answers both questions in one pass: `free_gb_after` is measured and nothing was
        # deleted, so it IS the current free space; `freed_gb` is what a real sweep would reclaim.
        preview = storage.sweep(target_free_gb=target, dry_run=True)
        current = float(preview["free_gb_after"])
        could = float(preview["freed_gb"])
    except Exception as e:  # noqa: BLE001 — see docstring; surviving to the next tick is the point
        log.warning("disk janitor: could not read the disk this cycle (%s)", e)
        return {"action": ERROR, "detail": str(e)}

    d = decide(current, could, target)
    out = d.as_dict()

    if d.action == SKIP_FUTILE:
        # Loud, and it names the direction of the problem. "Something else is eating the disk" is
        # actionable; "sweep freed 0 GB" is not.
        log.warning(
            "disk janitor: NOT sweeping. %.2f GB free and only %.2f GB is ours to reclaim, "
            "%.1f GB short of the %.1f GB cushion — the pressure is coming from something that "
            "is not Prompt-DJ (check Windows Update, temp files, other applications). "
            "Deleting the render cache would not fix it.",
            current, could, d.shortfall_gb, target)
        return out

    if d.action == SKIP_HEALTHY:
        log.debug("disk janitor: %.2f GB free, cushion %.1f GB — nothing to do", current, target)
        return out

    try:
        report = storage.sweep(target_free_gb=target)
    except Exception as e:  # noqa: BLE001
        log.warning("disk janitor: sweep failed (%s)", e)
        return {"action": ERROR, "detail": str(e)}

    log.info("disk janitor: swept to keep the %.1f GB cushion — %s", target,
             {k: report[k] for k in ("evicted", "freed_gb", "free_gb_after") if k in report})
    out["swept"] = {k: report[k] for k in ("evicted", "freed_gb", "free_gb_after") if k in report}
    return out


# --- the background timer -------------------------------------------------------------------

_task: asyncio.Task | None = None


async def _loop() -> None:
    """Wake, look, sleep. The sweep itself is synchronous and brief, but it touches the filesystem,
    so it runs in a worker thread rather than stalling the event loop that is also serving requests
    and streaming audio."""
    while True:
        try:
            await asyncio.sleep(interval_secs())
            await asyncio.to_thread(run_once)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — one bad cycle must not end the timer
            log.exception("disk janitor: unexpected error in the check loop")


def start() -> None:
    """Begin watching. Idempotent: calling it twice does not create two timers, which would double
    the sweep rate and could have two sweeps racing over the same files."""
    global _task
    if _task is not None and not _task.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        log.warning("disk janitor: no running event loop — not started")
        return
    _task = loop.create_task(_loop())
    log.info("disk janitor: watching, cushion %.1f GB, every %.0fs",
             cushion_gb(), interval_secs())


async def stop() -> None:
    """Stop watching, and wait for the current cycle to finish so shutdown is not racing a sweep."""
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except (asyncio.CancelledError, Exception):  # noqa: BLE001 — shutdown must not raise
        pass
    _task = None
    log.info("disk janitor: stopped")
