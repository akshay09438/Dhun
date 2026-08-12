"""The disk janitor: a timer that keeps free space above a cushion, and knows when not to bother.

WHY THIS EXISTS, and why it is a SEPARATE file from storage.py.

`storage.py` owns the POLICY - what may be deleted (an allowlist of five throwaway suffixes), in
what order (oldest first), and what is never touched (sources, stems, analyses, anything in a
subdirectory, anything younger than the grace period). That file is on the dangerous list because
it deletes people's finished mixes, and deleted is deleted.

This module owns only the TRIGGER - WHEN to ask storage to sweep. Keeping the two apart means:

  - the dangerous file is not modified at all to get a background cleaner, and
  - when storage moves to object storage (R2), the trigger swaps from "free bytes on this disk"
    to an age or cost rule while the safety policy is untouched.

THE FUTILITY BRAKE is the one genuinely new safety idea here, and it came from a real observation
at kickoff on 2026-08-12: free disk fell from 9.28 GB to 5.86 GB during a single session and
Prompt-DJ was NOT the cause - its data folder was unchanged; Windows Update was holding 7.81 GB.

Without the brake, a cleaner asked to reach a 6 GB cushion would have deleted every last one of
the 3.54 GB of finished mixes and STILL not reached the cushion - destroying the whole render
cache to fix a problem that belonged to something else. storage.sweep already warns about this,
but only AFTER it has emptied the cache. Warning after the damage is not a brake.
"""
from __future__ import annotations

import pytest

from app import janitor


# --- the decision, in isolation ------------------------------------------------------------
# decide() is deliberately a pure function of three numbers so the interesting cases can be
# stated as arithmetic rather than simulated with real files and a real disk.

def test_plenty_of_room_means_do_nothing():
    d = janitor.decide(current_free_gb=9.0, could_free_gb=3.5, cushion_gb=6.0)
    assert d.action == janitor.SKIP_HEALTHY
    assert not d.should_sweep


def test_exactly_at_the_cushion_is_still_healthy():
    """The cushion is a floor to stay at or above, not a number to exceed. Sweeping here would
    delete a mix to gain nothing."""
    d = janitor.decide(current_free_gb=6.0, could_free_gb=3.5, cushion_gb=6.0)
    assert d.action == janitor.SKIP_HEALTHY
    assert not d.should_sweep


def test_below_the_cushion_with_enough_to_reclaim_sweeps():
    d = janitor.decide(current_free_gb=4.0, could_free_gb=3.5, cushion_gb=6.0)
    assert d.action == janitor.SWEEP
    assert d.should_sweep


def test_the_futility_brake_refuses_when_clearing_everything_would_not_be_enough():
    """THE KICKOFF CASE, as measured on 2026-08-12: 5.86 GB free, 3.54 GB of mixes, 6 GB cushion.
    5.86 + 3.54 = 9.40 - that reaches the cushion, so this one WOULD sweep. The genuinely futile
    case is a machine much further under, e.g. Windows Update having taken far more."""
    d = janitor.decide(current_free_gb=1.0, could_free_gb=1.5, cushion_gb=6.0)
    assert d.action == janitor.SKIP_FUTILE
    assert not d.should_sweep, (
        "deleting every finished mix and still missing the cushion is pure loss - the pressure "
        "is coming from something that is not ours"
    )


def test_the_futility_brake_is_not_trigger_happy_at_the_boundary():
    """Just barely enough must still sweep. A brake that fires when the sweep WOULD have worked
    is as bad as no brake - it would let the disk fill while holding a cache it refused to spend."""
    d = janitor.decide(current_free_gb=4.0, could_free_gb=2.0, cushion_gb=6.0)
    assert d.action == janitor.SWEEP


def test_nothing_to_reclaim_at_all_is_futile_not_a_sweep():
    """An empty cache under pressure: there is no work to do and saying 'sweeping' would be a lie
    in the logs."""
    d = janitor.decide(current_free_gb=2.0, could_free_gb=0.0, cushion_gb=6.0)
    assert d.action == janitor.SKIP_FUTILE
    assert not d.should_sweep


# --- one full cycle, against a faked storage layer -------------------------------------------

class _FakeStorage:
    """Stands in for storage.py. Records what it was asked to do, so a test can prove the janitor
    NEVER calls a live sweep in the futile case - the whole point of the brake."""

    def __init__(self, free_gb: float, reclaimable_gb: float):
        self.free_gb = free_gb
        self.reclaimable_gb = reclaimable_gb
        self.calls: list[dict] = []

    def sweep(self, target_free_gb: float, dry_run: bool = False) -> dict:
        self.calls.append({"target": target_free_gb, "dry_run": dry_run})
        need = max(0.0, target_free_gb - self.free_gb)
        freed = min(need, self.reclaimable_gb)
        if not dry_run:
            self.free_gb += freed
            self.reclaimable_gb -= freed
        return {"dry_run": dry_run, "evicted": 1 if freed else 0, "freed_gb": round(freed, 3),
                "free_gb_after": round(self.free_gb, 2), "candidates": 1, "files": []}


def test_a_healthy_disk_never_triggers_a_live_sweep(monkeypatch):
    fake = _FakeStorage(free_gb=9.0, reclaimable_gb=3.5)
    monkeypatch.setattr(janitor, "storage", fake)
    result = janitor.run_once(cushion_gb=6.0)
    assert result["action"] == janitor.SKIP_HEALTHY
    assert all(c["dry_run"] for c in fake.calls), "a healthy disk must never delete anything"


def test_a_pressured_disk_sweeps_for_real_and_reaches_the_cushion(monkeypatch):
    fake = _FakeStorage(free_gb=4.0, reclaimable_gb=3.5)
    monkeypatch.setattr(janitor, "storage", fake)
    result = janitor.run_once(cushion_gb=6.0)
    assert result["action"] == janitor.SWEEP
    assert any(not c["dry_run"] for c in fake.calls)
    assert fake.free_gb >= 6.0


def test_the_futile_case_never_deletes_a_single_file(monkeypatch):
    """The most important test in this file. If this regresses, a machine whose disk is being
    eaten by something else loses its entire render cache for no benefit."""
    fake = _FakeStorage(free_gb=1.0, reclaimable_gb=1.5)
    monkeypatch.setattr(janitor, "storage", fake)
    result = janitor.run_once(cushion_gb=6.0)
    assert result["action"] == janitor.SKIP_FUTILE
    assert all(c["dry_run"] for c in fake.calls), (
        "the brake failed: the janitor deleted mixes it knew could not fix the problem"
    )
    assert fake.reclaimable_gb == 1.5, "nothing may be reclaimed in the futile case"


def test_a_futile_check_reports_the_shortfall_so_the_log_can_name_the_real_cause(monkeypatch):
    fake = _FakeStorage(free_gb=1.0, reclaimable_gb=1.5)
    monkeypatch.setattr(janitor, "storage", fake)
    result = janitor.run_once(cushion_gb=6.0)
    assert result["shortfall_gb"] == pytest.approx(3.5, abs=0.01), (
        "6.0 cushion - (1.0 free + 1.5 reclaimable) = 3.5 GB that is not ours to free"
    )


def test_a_storage_failure_never_kills_the_janitor(monkeypatch):
    """A background timer that dies on one bad cycle silently stops protecting the disk forever.
    It must survive and try again next tick."""
    class _Broken:
        def sweep(self, *a, **k):
            raise OSError("disk went away")

    monkeypatch.setattr(janitor, "storage", _Broken())
    result = janitor.run_once(cushion_gb=6.0)
    assert result["action"] == janitor.ERROR
    assert "disk went away" in result["detail"]


# --- the cushion itself ----------------------------------------------------------------------

def test_the_default_cushion_is_the_one_the_founder_chose():
    """6 GB, decided at kickoff on 2026-08-12. Above the ~2.5 GB line where renders start failing,
    with headroom for a full evening in a listening room, and low enough that the 0.03s instant
    repeat survives on a healthy machine."""
    assert janitor.DEFAULT_CUSHION_GB == 6.0


def test_the_cushion_can_be_overridden_by_environment(monkeypatch):
    """A rented box has a different disk from the founder's laptop. The number must be settable
    without a code change - and resolved at CALL time, not import time.

    That last part is not hypothetical: the previous night's version of this feature froze a
    default at import and silently broke every runtime override. Five tests caught it."""
    monkeypatch.setenv("PROMPTDJ_DISK_CUSHION_GB", "20")
    assert janitor.cushion_gb() == 20.0


def test_a_nonsense_cushion_falls_back_to_the_default_rather_than_crashing(monkeypatch):
    monkeypatch.setenv("PROMPTDJ_DISK_CUSHION_GB", "not-a-number")
    assert janitor.cushion_gb() == janitor.DEFAULT_CUSHION_GB
