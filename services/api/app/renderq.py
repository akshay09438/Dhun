"""The render queue - a bounded line, so the machine is never asked for more than it has.

WHAT WAS THERE BEFORE: nothing. `routes/mix.py` did `threading.Thread(...).start()` per
request, with no semaphore, no pool and no cap anywhere in the render path. Fifty requests
started fifty renders. Measured consequences (docs/concurrency-diagnosis.md):

  * it IS about 5.5x parallel in practice - ten pairs cost ~288s one at a time and 52.4s
    fired together - so this is emphatically NOT about making things serial. The cap only
    has to stop the cliff, not the concurrency.
  * a SINGLE render already peaks all ten cores, and each concurrent render costs roughly
    0.4 GB more RAM (1.26 GB at one, 5.15 GB at ten). Ten is this host's practical ceiling.
  * with no back-pressure, a sweep at 89.5% memory produced a 20.7% failure rate, and the
    same pairs at the same concurrency passed 10/10 and 6/6 with headroom. The failures
    were the ABSENCE of this file.

FOUR PROPERTIES, each one a thing a person in the Discord actually feels:

  1. AT MOST `max_concurrent` RENDER AT ONCE. Everyone else waits in line and is served.
     Waiting is a fine experience; failing because the tenth person pressed a button is not.
  2. THE LINE IS FIFO AND KNOWABLE. `position_of` answers "where am I", so the card can say
     "6th, about 3 minutes" instead of sitting frozen and looking broken.
  3. NO ONE PERSON CAN TAKE THE ROOM. A user holds at most `max_per_user` slots at a time;
     their eleventh grind waits behind other people's first. Fair queuing, not first-come.
  4. A RESOURCE FAILURE IS RETRIED, NOT REPORTED. If a render died because the host ran out
     of room, that is the queue's fault and not the user's, so it goes back in the line.
     A QUALITY failure is never retried - re-running a rejected pair just rejects it again,
     more slowly, and would burn the machine on work already known to be pointless.

Deliberately in-process and in-memory, matching the rest of validation-scale Prompt-DJ
(SQLite, local disk, in-process jobs). It upgrades to a real broker without the callers
changing: they hand over a job id and a callable and ask where it is in the line.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

log = logging.getLogger("promptdj.renderq")

# One render already saturates every core, so the cap is about MEMORY and disk, not CPU.
# Measured marginal cost is ~0.4 GB per concurrent render on a 16.8 GB host; 8 leaves room
# for the OS, the browser and the Discord bot. Overridable for a bigger box.
_DEFAULT_MAX_CONCURRENT = 8
_ENV_MAX_CONCURRENT = "PROMPTDJ_MAX_CONCURRENT_RENDERS"

# One person may hold this many render slots at once. Two, so a regenerate is still snappy
# while someone else's first grind never waits behind one enthusiast's tenth.
_DEFAULT_MAX_PER_USER = 2
_ENV_MAX_PER_USER = "PROMPTDJ_MAX_RENDERS_PER_USER"

# ...and this many WAITING in the line. Past it we say so plainly. An unbounded personal
# queue is not generosity: it is a five-minute wait for everybody else, silently.
_DEFAULT_MAX_QUEUED_PER_USER = 3
# Total line length. A hard stop so a runaway client cannot grow the queue without limit.
_DEFAULT_MAX_QUEUE = 200

# How many times a render that died for lack of room is put back in the line before we give
# up and tell the user. Three attempts spans a transient spike; more would hide a real
# problem behind a machine that is simply too small.
MAX_ATTEMPTS = 3
_RETRY_BACKOFF_SECS = 2.0

# Until we have measured a real one, assume a cold render takes this long (the diagnosis
# measured 22.6s / 28.3s alone, and 11.8-30.1s re-measured). Used only for the "about N
# minutes" estimate on the card, never for a decision.
_ASSUMED_RENDER_SECS = 30.0
_ETA_SAMPLE = 20      # how many recent renders the rolling average is taken over
_MIN_TIMED_SECS = 5.0  # below this it was a cache hit or an instant decline, not a render


def _env_int(name: str, default: int) -> int:
    """An int from the environment, ignoring anything that is not a positive number. A typo
    in a config value must not silently set the cap to zero and hang every render."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        log.warning("renderq: ignoring %s=%r (not a number); using %d", name, raw, default)
        return default
    if value < 1:
        log.warning("renderq: ignoring %s=%d (must be >= 1); using %d", name, value, default)
        return default
    return value


@dataclass
class Admission:
    """The answer to "can this go in the line, and where". `accepted` False carries a
    plain-language `reason` the user can read - never a silent drop."""

    accepted: bool
    position: int = 0          # 1-based place in the line; 0 means it started immediately
    reason: str | None = None


@dataclass(order=False)
class _Job:
    job_id: str
    fn: Callable[[], bool]     # returns True if it failed in a way a RETRY could fix
    user_id: str | None
    on_gave_up: Callable[[], None] | None = None
    attempts: int = 0
    queued_at: float = field(default_factory=time.monotonic)
    not_before: float = 0.0    # a retried job is not claimable until the host has had a breather


class RenderQueue:
    """A bounded FIFO with fair per-person slots. Thread-safe; workers are daemon threads
    started lazily on first use, so importing this module costs nothing."""

    def __init__(self, max_concurrent: int | None = None, max_per_user: int | None = None,
                 max_queued_per_user: int = _DEFAULT_MAX_QUEUED_PER_USER,
                 max_queue: int = _DEFAULT_MAX_QUEUE) -> None:
        self.max_concurrent = max_concurrent or _env_int(_ENV_MAX_CONCURRENT, _DEFAULT_MAX_CONCURRENT)
        self.max_per_user = max_per_user or _env_int(_ENV_MAX_PER_USER, _DEFAULT_MAX_PER_USER)
        self.max_queued_per_user = max_queued_per_user
        self.max_queue = max_queue

        self._cv = threading.Condition()
        self._waiting: deque[_Job] = deque()
        self._running: dict[str, _Job] = {}
        self._workers: list[threading.Thread] = []
        self._durations: deque[float] = deque(maxlen=_ETA_SAMPLE)

    # -- what the routes call ---------------------------------------------------------

    def submit(self, job_id: str, fn: Callable[[], bool], *, user_id: str | None = None,
               on_gave_up: Callable[[], None] | None = None) -> Admission:
        """Put a render in the line. `fn` runs on a worker thread and returns True if it
        failed for lack of room (and so is worth retrying). Idempotent: submitting a job id
        that is already queued or running returns its current position rather than a second copy.

        `on_gave_up` fires when a retryable job has used up its attempts. Without it, a caller
        that reports "queued, hang on" while retries are pending would leave the user waiting
        on a promise nobody was ever going to keep."""
        with self._cv:
            existing = self._position_locked(job_id)
            if existing is not None:
                return Admission(True, existing)
            if job_id in self._running:
                return Admission(True, 0)

            if len(self._waiting) >= self.max_queue:
                return Admission(False, reason=(
                    "The grinder has a long line right now. Give it a minute and try again."))
            if user_id is not None:
                mine = sum(1 for j in self._waiting if j.user_id == user_id)
                if mine >= self.max_queued_per_user:
                    return Admission(False, reason=(
                        f"You already have {mine} grinds in the line. "
                        "Let those land and then go again."))

            self._waiting.append(_Job(job_id, fn, user_id, on_gave_up))
            self._ensure_workers_locked()
            self._cv.notify()
            return Admission(True, len(self._waiting))

    def position_of(self, job_id: str) -> int | None:
        """1-based place in the line, or None if it is already running (or unknown)."""
        with self._cv:
            return self._position_locked(job_id)

    def is_running(self, job_id: str) -> bool:
        with self._cv:
            return job_id in self._running

    def eta_secs(self, position: int) -> float:
        """Roughly how long a job at `position` waits. Whole batches clear at a time, so it is
        (batches ahead) x (typical render), from REAL measured durations once we have some.
        An estimate on a card, never an input to a decision."""
        if position <= 0:
            return 0.0
        with self._cv:
            typical = (sum(self._durations) / len(self._durations)) if self._durations \
                else _ASSUMED_RENDER_SECS
        batches_ahead = (position - 1) // self.max_concurrent + 1
        return batches_ahead * typical

    def stats(self) -> dict:
        with self._cv:
            return {
                "running": len(self._running),
                "waiting": len(self._waiting),
                "capacity": self.max_concurrent,
                "per_user": self.max_per_user,
                "typical_render_secs": round(
                    (sum(self._durations) / len(self._durations)) if self._durations
                    else _ASSUMED_RENDER_SECS, 1),
            }

    # -- the machinery ----------------------------------------------------------------

    def _position_locked(self, job_id: str) -> int | None:
        for i, job in enumerate(self._waiting, start=1):
            if job.job_id == job_id:
                return i
        return None

    def _ensure_workers_locked(self) -> None:
        """Start workers on demand, never at import. Only ever grows to max_concurrent, and
        only when there is actually work, so a quiet process holds no threads at all."""
        need = min(self.max_concurrent, len(self._running) + len(self._waiting))
        while len(self._workers) < need:
            t = threading.Thread(target=self._work, name=f"renderq-{len(self._workers) + 1}",
                                 daemon=True)
            self._workers.append(t)
            t.start()

    def _claim_locked(self) -> _Job | None:
        """The next job this worker may take: the first in line that is DUE and whose owner is
        not already holding all their slots. Skipping past a hogger is what makes the queue
        fair - strict FIFO would let one person with ten grinds keep everybody else waiting."""
        if len(self._running) >= self.max_concurrent:
            return None
        now = time.monotonic()
        held: dict[str, int] = {}
        for j in self._running.values():
            if j.user_id is not None:
                held[j.user_id] = held.get(j.user_id, 0) + 1
        for i, job in enumerate(self._waiting):
            if job.not_before > now:
                continue          # retried a moment ago; let the host breathe first
            if job.user_id is not None and held.get(job.user_id, 0) >= self.max_per_user:
                continue          # this person is already using all their slots
            del self._waiting[i]
            self._running[job.job_id] = job
            return job
        return None

    def _work(self) -> None:
        while True:
            with self._cv:
                job = self._claim_locked()
                while job is None:
                    # Timed wait: a job may become claimable because ANOTHER user's render
                    # finished, and that finish notifies - but a bare wait() would also be the
                    # place a missed notification became a permanent hang. One second costs
                    # nothing and makes a stall self-healing.
                    self._cv.wait(timeout=1.0)
                    job = self._claim_locked()

            started = time.monotonic()
            retryable = False
            try:
                retryable = bool(job.fn())
            except Exception:  # noqa: BLE001 - a worker must outlive any one job, always
                log.exception("renderq: job %s raised out of its own handler", job.job_id)
            elapsed = time.monotonic() - started
            gave_up = False

            with self._cv:
                self._running.pop(job.job_id, None)
                job.attempts += 1
                if retryable and job.attempts < MAX_ATTEMPTS:
                    # Back of the line, not the front: someone whose render has not failed once
                    # should not be overtaken by one that already has. `not_before` holds it
                    # there for a beat, so no worker (including a different one) can grab it
                    # and hammer a host that just told us it has no room.
                    job.not_before = time.monotonic() + _RETRY_BACKOFF_SECS
                    self._waiting.append(job)
                    log.warning("renderq: job %s ran out of room, back in the line (attempt %d of %d)",
                                job.job_id, job.attempts + 1, MAX_ATTEMPTS)
                else:
                    gave_up = retryable
                    if elapsed >= _MIN_TIMED_SECS:
                        # Only real renders feed the estimate. A cache hit (0.03s) or an instant
                        # decline would drag the "about N minutes" down into a lie.
                        self._durations.append(elapsed)
                self._cv.notify_all()

            if gave_up and job.on_gave_up is not None:
                # Outside the lock: this tells the CALLER its job is finally dead, and a caller
                # must never be able to deadlock the queue by doing something slow in there.
                log.warning("renderq: job %s gave up after %d attempts", job.job_id, job.attempts)
                try:
                    job.on_gave_up()
                except Exception:  # noqa: BLE001 - a bad callback must not kill the worker
                    log.exception("renderq: on_gave_up for %s raised", job.job_id)


# The process-wide queue every render goes through. One per process, matching the in-process
# job model the rest of the app uses.
queue = RenderQueue()
