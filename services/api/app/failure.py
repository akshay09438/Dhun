"""WHY a mix failed - the four causes, told apart.

Until 2026-08-11 every failure ended up as the same sentence to the user ("Couldn't
build this mix. Try another pair or regenerate.") and the same sentence in `events.db`.
That made two completely unrelated situations indistinguishable:

  * these two songs genuinely do not work together - the engine built the audio, the
    quality referee listened to it and refused to ship it; and
  * the machine ran out of memory or disk part-way through, which has nothing whatever
    to do with the songs the person picked.

The measured cost of that confusion (docs/concurrency-diagnosis.md): a catalog sweep run
while the host sat at 89.5% memory with the disk falling toward 2 GB reported a 20.7%
failure rate - and the SAME pairs at the SAME concurrency then passed 10/10 and 6/6 once
the machine had headroom. Almost all of those "broken pairs" were a tired laptop wearing
a broken pair's clothes, and neither the user nor the ops dashboard could tell.

FOUR CAUSES, keyed off the exception TYPE, never off matching words in a message:

  DECLINED  - refused before rendering. The planner looked at the two songs and said no
              (no detectable beat, no on-beat room for the chops). Nothing was built.
  QUALITY   - built, then rejected. The engine produced audio and the referee measured it
              and refused (R1 two vocals at once, clipping, a collapsed crest factor).
              This is the guardrail working, and it IS a fact about this pair.
  RESOURCES - the host ran out of room. Says nothing at all about the songs.
  BUG       - something broke that we did not anticipate.

ONE DELIBERATE ASYMMETRY. A verdict the referee actually reached by measuring the rendered
audio is NEVER downgraded to "the machine was busy", even if the machine was in fact busy -
the referee's measurement is evidence and a resource excuse is not. The escalation only runs
the other way: an otherwise-unexplained BUG that happened while the machine was starved is
reported as RESOURCES, because that is overwhelmingly what it is.

The machine's actual state at the moment of failure is recorded alongside the verdict either
way, so a wrong guess here is always visible and correctable from the data - this module can
mislabel a failure, but it can never hide one.
"""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("promptdj.failure")

# The four causes. Stored verbatim in events.db (`fail_kind`), so treat these strings as
# a persisted contract - renaming one silently splits every historical count in two.
DECLINED = "declined"
QUALITY = "quality"
RESOURCES = "resources"
BUG = "bug"

ALL_KINDS = (DECLINED, QUALITY, RESOURCES, BUG)

# Below these, the host has no room to render and the next failure is meaningless as a
# judgement on anybody's songs. Disk: the eviction sweep's own floor is 2.0 GB, so 2.5 GB
# means "the sweep is about to fire and we are already scraping". Memory: the diagnosis
# measured ~0.4 GB marginal cost per concurrent render, so under 1 GB available there is
# not room for even one more.
STARVED_DISK_GB = 2.5
STARVED_RAM_GB = 1.0

# What the person actually reads. The RESOURCES line deliberately does NOT say "try another
# pair" - that sentence sent people off changing their song choice to fix a problem that was
# never theirs. (When the retry path is in play it replaces this with its own "busy" wording;
# this is the terminal message for a resource failure we have stopped retrying.)
_MESSAGES = {
    DECLINED: "These two can't be mixed.",
    QUALITY: "This pair didn't come out clean, so it wasn't shipped.",
    RESOURCES: "The grinder ran out of room - nothing to do with your songs. Give it a minute.",
    BUG: "Something broke on our side, not with your songs. Try that again.",
}


@dataclass
class Failure:
    """One failure, explained. `detail` is the engine's own words (for the log and the ops
    dashboard); `user_message` is what a person in Discord reads."""

    kind: str
    user_message: str
    detail: str
    machine: dict[str, Any] = field(default_factory=dict)

    @property
    def is_resources(self) -> bool:
        """Whether this is worth retrying. A resource failure is the ONLY kind that a retry
        can fix - re-running a rejected pair just rejects it again, more slowly."""
        return self.kind == RESOURCES


def _free_ram_gb() -> float | None:
    """Available RAM in GB, or None if this host will not tell us cheaply.

    psutil is used by the load-test scripts but is NOT a dependency of the API, so it is
    imported defensively: memory pressure is a bonus signal, and disk (stdlib) is the one
    that actually bit us. None means "unknown", which is never treated as starved - an
    unknown must not manufacture a resource excuse out of nothing."""
    try:
        import psutil  # noqa: PLC0415 - optional, deliberately not a hard dependency
        return psutil.virtual_memory().available / 1e9
    except Exception:  # noqa: BLE001 - not installed, or refused to answer
        return None


def machine_state(data_dir: Path | None = None) -> dict[str, Any]:
    """A snapshot of how much room the host had, recorded with every failure so a
    misclassification is always visible in the data rather than baked in."""
    disk_gb: float | None = None
    try:
        target = Path(data_dir) if data_dir is not None else Path.cwd()
        disk_gb = round(shutil.disk_usage(target).free / 1e9, 2)
    except OSError:  # noqa: PERF203 - a path we cannot stat tells us nothing, and must not raise
        pass
    ram_gb = _free_ram_gb()
    starved = bool(
        (disk_gb is not None and disk_gb < STARVED_DISK_GB)
        or (ram_gb is not None and ram_gb < STARVED_RAM_GB)
    )
    return {
        "free_disk_gb": disk_gb,
        "free_ram_gb": round(ram_gb, 2) if ram_gb is not None else None,
        "starved": starved,
    }


def _is_out_of_space(exc: BaseException) -> bool:
    """True for the errors a full disk or a full memory actually raises. ENOSPC is 28 on
    every platform we run on; sqlite and ffmpeg both surface a full disk as an OSError."""
    if isinstance(exc, MemoryError):
        return True
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == 28:
        return True
    return False


def classify(exc: BaseException, *, data_dir: Path | None = None,
             declined: type[BaseException] | tuple[type[BaseException], ...] = (),
             quality: type[BaseException] | tuple[type[BaseException], ...] = ()) -> Failure:
    """Work out WHY this failed, from the exception type plus the host's state.

    `declined` and `quality` are the caller's own exception classes (MixDeclined; and
    ValidationError / RenderError / PitchError respectively), passed in rather than imported
    here so this module stays free of the render path and remains trivially testable.
    """
    machine = machine_state(data_dir)
    detail = f"{type(exc).__name__}: {exc}".strip()

    if _is_out_of_space(exc):
        return Failure(RESOURCES, _MESSAGES[RESOURCES], detail, machine)

    if declined and isinstance(exc, declined):
        # The planner's own plain-language reason is better than anything generic.
        reason = str(getattr(exc, "reason", "") or exc).strip()
        return Failure(DECLINED, reason or _MESSAGES[DECLINED], detail, machine)

    if quality and isinstance(exc, quality):
        # NEVER downgraded to RESOURCES, even on a starved machine: the referee reached this
        # verdict by measuring the audio it had actually produced. That is evidence.
        return Failure(QUALITY, _MESSAGES[QUALITY], detail, machine)

    if machine.get("starved"):
        log.warning("unexplained failure on a starved host (%s) -> reporting as resources: %s",
                    machine, detail)
        return Failure(RESOURCES, _MESSAGES[RESOURCES], detail, machine)

    return Failure(BUG, _MESSAGES[BUG], detail, machine)
