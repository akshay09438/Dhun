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

import dataclasses

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


# --- the subfolder watch: LOOK everywhere, DELETE nowhere -------------------------------------
#
# Added 2026-08-13 after data/tuning_renders held 4.61 GB of throwaway renders for a MONTH while
# the janitor reported a clean bill of health every minute. The founder was offered a recursive
# sweep and deliberately chose "warn, don't delete", so the deleter's blast radius is unchanged
# and library/manifest.json stays behind two guards rather than one.
#
# THESE TESTS WRITE BYTES, NOT GIGABYTES. The first draft created real 1-2 GB files to cross the
# default threshold and filled the disk mid-run (`OSError: No space left on device`) - the exact
# failure this project already has a headline bug about. `subfolder_report` takes `min_gb` as an
# argument precisely so the scale can be shrunk: the comparison under test is identical at 1 KB
# and at 1 GB, and the real default is pinned by its own test below.

_KB = 1_000


def _mk(p, kb):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\0" * int(kb * _KB))


_TINY = 2 / 1e6   # 2 KB expressed in GB - the threshold these tests compare against


def test_a_big_subfolder_of_renders_is_reported(tmp_path, monkeypatch):
    """The exact case that went unnoticed for a month."""
    monkeypatch.setattr(janitor, "settings", dataclasses.replace(janitor.settings, data_dir=tmp_path))
    _mk(tmp_path / "tuning_renders" / "a.mix.wav", 2)
    _mk(tmp_path / "tuning_renders" / "b.mix.wav", 2)
    report = janitor.subfolder_report(min_gb=_TINY)
    assert [r["folder"] for r in report] == ["tuning_renders"]
    assert report[0]["files"] == 2


def test_it_reports_but_never_deletes(tmp_path, monkeypatch):
    """THE test. This pass exists INSTEAD of making the sweep recursive; the moment it removes a
    file it has become the thing the founder said no to."""
    monkeypatch.setattr(janitor, "settings", dataclasses.replace(janitor.settings, data_dir=tmp_path))
    f = tmp_path / "tuning_renders" / "a.mix.wav"
    _mk(f, 4)
    janitor.subfolder_report(min_gb=_TINY)
    assert f.exists(), "the subfolder watch must never delete anything"


def test_the_manifest_folder_is_never_named(tmp_path, monkeypatch):
    """library/ holds the catalog index and keep/ holds the pinned-mix protection. Reporting on
    either trains the reader to ignore the line, and it is the line that matters."""
    monkeypatch.setattr(janitor, "settings", dataclasses.replace(janitor.settings, data_dir=tmp_path))
    _mk(tmp_path / "library" / "big.mix.wav", 8)
    _mk(tmp_path / "keep" / "big.mix.wav", 8)
    assert janitor.subfolder_report(min_gb=_TINY) == []


def test_only_sweep_eligible_files_are_counted(tmp_path, monkeypatch):
    """It must describe what WOULD have been reclaimable one directory higher - not stems and
    sources, which are paid for on Replicate and are throwaway in no sense at all."""
    monkeypatch.setattr(janitor, "settings", dataclasses.replace(janitor.settings, data_dir=tmp_path))
    _mk(tmp_path / "sandbox" / "keeper.vocals.mp3", 8)      # a paid stem
    _mk(tmp_path / "sandbox" / "keeper.analysis.json", 8)   # a paid analysis
    assert janitor.subfolder_report(min_gb=_TINY) == []


def test_a_subfolder_under_the_threshold_is_not_worth_mentioning(tmp_path, monkeypatch):
    monkeypatch.setattr(janitor, "settings", dataclasses.replace(janitor.settings, data_dir=tmp_path))
    _mk(tmp_path / "listening" / "a.mix.wav", 1)
    assert janitor.subfolder_report(min_gb=1.0) == []


def test_top_level_renders_are_not_reported_here(tmp_path, monkeypatch):
    """Those ARE swept, so naming them would be noise about a solved problem."""
    monkeypatch.setattr(janitor, "settings", dataclasses.replace(janitor.settings, data_dir=tmp_path))
    _mk(tmp_path / "a.mix.wav", 8)
    assert janitor.subfolder_report(min_gb=_TINY) == []


def test_the_default_threshold_is_one_gigabyte():
    """The tests above shrink the scale to avoid writing gigabytes; this pins the real number so
    shrinking the scale cannot quietly shrink the feature."""
    assert janitor.SUBFOLDER_WARN_GB == 1.0


def test_an_unreadable_data_dir_returns_empty_rather_than_raising(monkeypatch, tmp_path):
    monkeypatch.setattr(janitor, "settings",
                        dataclasses.replace(janitor.settings, data_dir=tmp_path / "nope"))
    assert janitor.subfolder_report() == []


def test_the_watch_reaches_run_once_and_survives_a_failure(tmp_path, monkeypatch):
    """A reporting pass that can kill the tick costs more than the problem it describes."""
    monkeypatch.setattr(janitor, "settings", dataclasses.replace(janitor.settings, data_dir=tmp_path))
    monkeypatch.setattr(janitor, "subfolder_report",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    result = janitor.run_once(cushion_gb=0.0)
    assert result["action"] in (janitor.SKIP_HEALTHY, janitor.SKIP_FUTILE, janitor.SWEEP, janitor.ERROR)
