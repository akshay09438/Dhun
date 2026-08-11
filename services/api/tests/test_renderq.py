"""The render queue: a bounded line that is fair, knowable, and retries the right failures.

Before this existed, `routes/mix.py` started one unbounded thread per request. The measured
consequence (docs/concurrency-diagnosis.md) was a 20.7% failure rate on a starved host, where
the SAME pairs at the SAME concurrency passed 10/10 and 6/6 with headroom. These tests pin the
four properties that prevent that, stated as what a person in the Discord would notice.
"""
from __future__ import annotations

import threading
import time

from app.renderq import MAX_ATTEMPTS, RenderQueue


class _Peak:
    """Tracks how many jobs were genuinely in flight at the same moment."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.now = 0
        self.peak = 0
        self.done = 0

    def enter(self) -> None:
        with self.lock:
            self.now += 1
            self.peak = max(self.peak, self.now)

    def leave(self) -> None:
        with self.lock:
            self.now -= 1
            self.done += 1


def _busy(peak: _Peak, hold: float = 0.05):
    def run() -> bool:
        peak.enter()
        time.sleep(hold)
        peak.leave()
        return False          # succeeded; nothing to retry
    return run


def _wait_until(predicate, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


# --- 1. the cap -------------------------------------------------------------------------

def test_twenty_at_once_all_succeed_and_at_most_eight_ever_render_together():
    """THE acceptance check from the handoff, verbatim: 20 simultaneous requests, all 20
    eventually succeed, at most 8 render at once, none fail."""
    q = RenderQueue(max_concurrent=8, max_per_user=8, max_queued_per_user=50)
    peak = _Peak()

    for i in range(20):
        assert q.submit(f"job-{i}", _busy(peak)).accepted

    assert _wait_until(lambda: peak.done == 20), f"only {peak.done} of 20 finished"
    assert peak.peak <= 8, f"{peak.peak} rendered at once, over the cap of 8"
    assert peak.peak > 1, "serialised everything - the cap is meant to bound concurrency, not remove it"


def test_the_queue_does_not_make_the_machine_serial():
    """Guards the mistake this change could easily have been. The engine is ~5.5x parallel and
    a single render already fills every core; capping is about survival, not about one-at-a-time."""
    q = RenderQueue(max_concurrent=4, max_per_user=4, max_queued_per_user=50)
    peak = _Peak()
    for i in range(8):
        q.submit(f"j{i}", _busy(peak, hold=0.1))
    assert _wait_until(lambda: peak.done == 8)
    assert peak.peak >= 3, f"peak was {peak.peak}; the cap should let renders overlap"


# --- 2. the line is knowable ------------------------------------------------------------

def test_a_grind_made_while_the_machine_is_full_is_told_its_place_in_line():
    """What the card needs in order to say "6th, about 3 minutes" instead of sitting frozen."""
    q = RenderQueue(max_concurrent=1, max_per_user=5, max_queued_per_user=50)
    release = threading.Event()
    started = threading.Event()

    def blocker() -> bool:
        started.set()
        release.wait(timeout=10)
        return False

    q.submit("running", blocker)
    assert started.wait(timeout=5), "the first job never started"

    assert q.submit("second", lambda: False).position == 1
    assert q.submit("third", lambda: False).position == 2
    assert q.position_of("third") == 2
    assert q.position_of("running") is None, "already running, so it is not IN the line"
    release.set()


def test_the_position_counts_down_as_the_line_clears():
    q = RenderQueue(max_concurrent=1, max_per_user=5, max_queued_per_user=50)
    release = threading.Event()
    q.submit("running", lambda: (release.wait(timeout=10), False)[1])
    q.submit("a", _busy(_Peak()))
    q.submit("mine", lambda: False)
    assert _wait_until(lambda: q.position_of("mine") == 2)

    release.set()
    assert _wait_until(lambda: q.position_of("mine") in (1, None)), "never moved up the line"


def test_the_estimate_grows_with_the_line_and_is_zero_at_the_front():
    q = RenderQueue(max_concurrent=4)
    assert q.eta_secs(0) == 0.0
    assert q.eta_secs(1) < q.eta_secs(9), "further back must read as a longer wait"


# --- 3. no one person takes the room ----------------------------------------------------

def test_one_person_firing_ten_grinds_cannot_occupy_more_than_their_slots():
    """The handoff's job 4, from the consumer's seat: someone else's FIRST grind must not wait
    behind one enthusiast's tenth."""
    q = RenderQueue(max_concurrent=8, max_per_user=2, max_queued_per_user=50)
    release = threading.Event()
    hog_running = _Peak()

    def hog() -> bool:
        hog_running.enter()
        release.wait(timeout=10)
        hog_running.leave()
        return False

    for i in range(10):
        q.submit(f"hog-{i}", hog, user_id="loud-one")
    # Give the workers a moment to claim everything they are allowed to claim.
    assert _wait_until(lambda: hog_running.now >= 2)
    time.sleep(0.2)
    assert hog_running.now <= 2, f"one person held {hog_running.now} slots, cap is 2"

    # ...and a different person gets served straight away, not after all ten.
    newcomer = threading.Event()
    q.submit("newcomer", lambda: (newcomer.set(), False)[1], user_id="someone-else")
    assert newcomer.wait(timeout=5), "a newcomer waited behind one person's backlog"
    release.set()


def test_a_person_with_too_many_already_waiting_is_told_plainly_not_silently_dropped():
    q = RenderQueue(max_concurrent=1, max_per_user=1, max_queued_per_user=2)
    release = threading.Event()
    q.submit("running", lambda: (release.wait(timeout=10), False)[1], user_id="u")
    q.submit("q1", lambda: False, user_id="u")
    q.submit("q2", lambda: False, user_id="u")

    rejected = q.submit("q3", lambda: False, user_id="u")
    assert not rejected.accepted
    assert "line" in (rejected.reason or "").lower()
    assert rejected.reason and not rejected.reason.endswith("Error")
    release.set()


# --- 4. the right failures are retried --------------------------------------------------

def test_a_render_that_ran_out_of_room_goes_back_in_the_line_instead_of_failing_the_user():
    """The founder's decision, 2026-08-11. A host with no room left is not the user's problem
    and must never be reported as one."""
    q = RenderQueue(max_concurrent=2, max_per_user=2, max_queued_per_user=50)
    attempts = []
    lock = threading.Lock()

    def out_of_room_once() -> bool:
        with lock:
            attempts.append(1)
            return len(attempts) == 1        # first go: no room. second: fine.

    q.submit("flaky", out_of_room_once)
    assert _wait_until(lambda: len(attempts) == 2), "it was never retried"
    time.sleep(0.3)
    assert len(attempts) == 2, "retried more times than it needed to"


def test_a_render_that_keeps_running_out_of_room_eventually_gives_up():
    """Retrying forever would hide a host that is simply too small behind an endless wait."""
    q = RenderQueue(max_concurrent=2, max_per_user=2, max_queued_per_user=50)
    attempts = []
    lock = threading.Lock()

    def always_out_of_room() -> bool:
        with lock:
            attempts.append(1)
        return True

    q.submit("doomed", always_out_of_room)
    assert _wait_until(lambda: len(attempts) == MAX_ATTEMPTS, timeout=20)
    time.sleep(0.5)
    assert len(attempts) == MAX_ATTEMPTS, f"kept going past {MAX_ATTEMPTS} attempts"


def test_a_pair_the_referee_rejected_is_NEVER_retried():
    """Re-running a rejected pair just rejects it again, more slowly, and burns the machine on
    work already known to be pointless. Only a RESOURCE failure is worth another go."""
    q = RenderQueue(max_concurrent=2)
    attempts = []

    def rejected() -> bool:
        attempts.append(1)
        return False          # a real verdict about this pair - not retryable

    q.submit("bad-pair", rejected)
    assert _wait_until(lambda: len(attempts) == 1)
    time.sleep(0.3)
    assert len(attempts) == 1


# --- housekeeping -----------------------------------------------------------------------

def test_submitting_the_same_job_twice_does_not_run_it_twice():
    """Two people asking for the identical mix is a cache hit waiting to happen, not two renders."""
    q = RenderQueue(max_concurrent=1, max_per_user=4, max_queued_per_user=50)
    release, started = threading.Event(), threading.Event()
    runs = []

    def blocker() -> bool:
        started.set()
        release.wait(timeout=10)
        return False

    q.submit("blocker", blocker)
    assert started.wait(timeout=5), "the blocker never got claimed, so the line is not full yet"

    first = q.submit("same", lambda: (runs.append(1), False)[1])
    again = q.submit("same", lambda: (runs.append(1), False)[1])

    assert first.position == 1
    assert again.accepted and again.position == first.position, "queued a second copy"
    release.set()
    assert _wait_until(lambda: len(runs) == 1)
    time.sleep(0.2)
    assert len(runs) == 1


def test_a_job_that_explodes_does_not_kill_its_worker():
    """One bad job must never take the queue down with it - everyone behind it still gets served."""
    q = RenderQueue(max_concurrent=1, max_per_user=4, max_queued_per_user=50)
    survived = threading.Event()

    def boom() -> bool:
        raise RuntimeError("this should not end the world")

    q.submit("boom", boom)
    q.submit("after", lambda: (survived.set(), False)[1])
    assert survived.wait(timeout=10), "the worker died and took the queue with it"


def test_a_nonsense_cap_in_the_environment_is_ignored_rather_than_hanging_everything(monkeypatch):
    """A cap of 0 from a typo would mean nothing ever renders, with no error anywhere."""
    monkeypatch.setenv("PROMPTDJ_MAX_CONCURRENT_RENDERS", "0")
    assert RenderQueue().max_concurrent >= 1
    monkeypatch.setenv("PROMPTDJ_MAX_CONCURRENT_RENDERS", "banana")
    assert RenderQueue().max_concurrent >= 1
    monkeypatch.setenv("PROMPTDJ_MAX_CONCURRENT_RENDERS", "3")
    assert RenderQueue().max_concurrent == 3


def test_stats_report_what_the_queue_is_actually_doing():
    q = RenderQueue(max_concurrent=6)
    s = q.stats()
    assert s["capacity"] == 6
    assert s["running"] == 0 and s["waiting"] == 0
    assert s["typical_render_secs"] > 0
