"""Acceptance tests for the cache-eviction sweep in app.storage.

Danger surface: this sweep DELETES files on disk. A wrong allowlist or a
recursing scan would irreversibly destroy Replicate-cost stems, uploaded
sources, analyses, the library manifest, or the approved tuning config — all
unrecoverable. So these tests pin the allowlist, non-recursion, LRU order, the
stop-at-target behavior, and the auto-hook gating, hard.

Isolation contract (both are mandatory — a test that touched the real data dir
or the real disk-free number would be a live-fire test):
  * settings.data_dir is redirected to a throwaway tmp_path (matches the
    established _use_tmp_data_dir pattern in test_storage.py).
  * storage._free_gb is monkeypatched to a stub we control, so eviction
    decisions never depend on the machine's actual free disk.
"""

import dataclasses
import os
import time
from pathlib import Path

import pytest

from app import storage

# A 64-hex-looking stem, the shape real stored ids take. Distinct suffixes are
# what the sweep keys on, so the stem itself is arbitrary but realistic.
H = "a" * 64


@pytest.fixture(autouse=True)
def _no_grace(monkeypatch):
    """These tests pin the allowlist / keep-list / LRU / gating logic, which is orthogonal to the age
    grace — so disable the grace (0 s) here so a freshly-created evictable file is eligible. The grace
    itself has a dedicated test below that restores it."""
    monkeypatch.setattr(storage, "_EVICT_MIN_AGE_SECS", 0.0)


def test_age_grace_protects_a_fresh_render_from_a_concurrent_sweep(monkeypatch, tmp_path):
    """F1 (adversarial finding): a render younger than the grace period is NEVER evicted, even under
    full disk pressure — this protects an in-flight / just-rendered / being-served file from another
    job's concurrent sweep. An older regenerable render is still evicted."""
    monkeypatch.setattr(storage, "_EVICT_MIN_AGE_SECS", 300.0)  # restore the real grace for THIS test
    _use_tmp_data_dir(monkeypatch, tmp_path)
    now = time.time()
    fresh = _touch(tmp_path / f"{H}.mix.wav", mtime=now)              # just rendered / in-flight
    old = _touch(tmp_path / f"{'b' * 64}.mix.wav", mtime=now - 1000)  # older than the grace
    _force_free(monkeypatch, 0.0)  # maximum disk pressure
    storage.sweep(target_free_gb=999.0)
    assert fresh.exists(), "the age grace must protect a fresh (in-flight) render"
    assert not old.exists(), "an older regenerable render should still be evicted"


def _use_tmp_data_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        storage, "settings", dataclasses.replace(storage.settings, data_dir=tmp_path)
    )


def _touch(path: Path, content: bytes = b"x", mtime: float | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def _force_free(monkeypatch, value: float) -> None:
    """Pin the disk-free reading to a constant GB value we choose."""
    monkeypatch.setattr(storage, "_free_gb", lambda path: float(value))


# The full set of things the sweep must NEVER delete when they sit at top level.
def _protected_names() -> list[str]:
    return [
        f"{H}.wav",            # uploaded source — unrecoverable
        f"{H}.drums.mp3",      # Replicate-cost stems
        f"{H}.bass.mp3",
        f"{H}.other.mp3",
        f"{H}.vocals.mp3",
        f"{H}.analysis.json",  # analyses
        f"{H}.structure.json",
        f"{H}.mixplan.json",   # small metadata
        f"{H}.mixname.txt",
        f"{H}.setmanifest.json",
        f"{H}.suggestions.json",
    ]


def _evictable_names() -> list[str]:
    return [
        f"{H}1.mix.wav",
        f"{H}2.bestparts.wav",
        f"{H}3.set.wav",
        f"{H}4.livearr.wav",
    ]


# --------------------------------------------------------------------------- #
# Criterion 1: the keep-list is sacred.
# --------------------------------------------------------------------------- #
def test_keep_list_is_sacred_even_when_disk_is_full(tmp_path, monkeypatch):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    for name in _protected_names():
        _touch(tmp_path / name)
    # Subdirectory contents — including catalog and an evictable-suffixed file
    # NESTED under listening/, which must be safe because the sweep never recurses.
    _touch(tmp_path / "library" / "x")
    _touch(tmp_path / "tuning_renders" / "APPROVED_CHAIN_CONFIG.txt")
    _touch(tmp_path / "listening" / "foo.wav")
    _touch(tmp_path / "listening" / f"{H}.mix.wav")

    # Free disk forced to 0 — below any conceivable target, maximum pressure.
    _force_free(monkeypatch, 0.0)
    report = storage.sweep()

    assert report["evicted"] == 0
    assert report["files"] == []
    for name in _protected_names():
        assert (tmp_path / name).exists(), f"protected file deleted: {name}"
    assert (tmp_path / "library" / "x").exists()
    assert (tmp_path / "tuning_renders" / "APPROVED_CHAIN_CONFIG.txt").exists()
    assert (tmp_path / "listening" / "foo.wav").exists()
    assert (tmp_path / "listening" / f"{H}.mix.wav").exists()


# --------------------------------------------------------------------------- #
# Criterion 2: evicts ONLY the allowlist, nothing adjacent.
# --------------------------------------------------------------------------- #
def test_evicts_only_the_allowlist(tmp_path, monkeypatch):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    for name in _evictable_names():
        _touch(tmp_path / name)
    # Non-evictable neighbors that must survive.
    keepers = [f"{H}.wav", f"{H}.analysis.json", f"{H}.vocals.mp3"]
    for name in keepers:
        _touch(tmp_path / name)

    _force_free(monkeypatch, 0.0)  # never reaches target -> sweep everything it may
    report = storage.sweep()

    assert set(report["files"]) == set(_evictable_names())
    assert report["evicted"] == len(_evictable_names())
    for name in _evictable_names():
        assert not (tmp_path / name).exists(), f"evictable not deleted: {name}"
    for name in keepers:
        assert (tmp_path / name).exists(), f"non-evictable deleted: {name}"


# --------------------------------------------------------------------------- #
# Criterion 3: LRU order — oldest mtime first, stop at target, no over-eviction.
# --------------------------------------------------------------------------- #
def test_lru_order_stops_at_target(tmp_path, monkeypatch):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    # Names are deliberately in the REVERSE order of their mtimes, so a sort by
    # name would evict a/b/c but a sort by mtime (correct) evicts e/d/c.
    plan = [
        ("e.mix.wav", 100),  # oldest
        ("d.mix.wav", 200),
        ("c.mix.wav", 300),
        ("b.mix.wav", 400),
        ("a.mix.wav", 500),  # newest
    ]
    initial = [_touch(tmp_path / name, mtime=t) for name, t in plan]

    # Each deletion frees 1 GB. Target 3.0 GB -> crosses after exactly 3 deletes.
    def fake_free(path):
        return float(sum(1 for p in initial if not p.exists()))

    monkeypatch.setattr(storage, "_free_gb", fake_free)
    report = storage.sweep(target_free_gb=3.0)

    assert report["evicted"] == 3
    # The 3 OLDEST are gone...
    for name in ("e.mix.wav", "d.mix.wav", "c.mix.wav"):
        assert not (tmp_path / name).exists(), f"oldest survived: {name}"
    # ...and the 2 NEWEST survive (stopped at target, did not over-evict).
    for name in ("b.mix.wav", "a.mix.wav"):
        assert (tmp_path / name).exists(), f"newest over-evicted: {name}"
    assert report["files"] == ["e.mix.wav", "d.mix.wav", "c.mix.wav"]


# --------------------------------------------------------------------------- #
# Criterion 4: already at/above target -> delete nothing.
# --------------------------------------------------------------------------- #
def test_respects_target_when_already_free(tmp_path, monkeypatch):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    for name in _evictable_names():
        _touch(tmp_path / name)

    _force_free(monkeypatch, 5.0)  # already above the 3.0 target
    report = storage.sweep(target_free_gb=3.0)

    assert report["evicted"] == 0
    assert report["files"] == []
    for name in _evictable_names():
        assert (tmp_path / name).exists()


# --------------------------------------------------------------------------- #
# Criterion 5: dry-run deletes nothing but reports the set live-mode would evict.
# --------------------------------------------------------------------------- #
def test_dry_run_reports_but_deletes_nothing(tmp_path, monkeypatch):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    for name in _evictable_names():
        _touch(tmp_path / name)

    _force_free(monkeypatch, 0.0)  # never reaches target -> full set reported
    report = storage.sweep(dry_run=True)

    assert report["dry_run"] is True
    assert report["files"]  # non-empty
    # Same set live-mode would delete under identical pressure (cf. criterion 2).
    assert set(report["files"]) == set(_evictable_names())
    for name in _evictable_names():
        assert (tmp_path / name).exists(), f"dry-run deleted a file: {name}"


# --------------------------------------------------------------------------- #
# Criterion 6: maybe_sweep only fires below the MIN_FREE floor.
# --------------------------------------------------------------------------- #
def test_maybe_sweep_noop_above_floor(tmp_path, monkeypatch):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    for name in _evictable_names():
        _touch(tmp_path / name)

    _force_free(monkeypatch, storage._MIN_FREE_GB + 1.0)  # above the floor
    result = storage.maybe_sweep()

    assert result is None
    for name in _evictable_names():
        assert (tmp_path / name).exists(), "maybe_sweep evicted above the floor"


def test_maybe_sweep_fires_below_floor(tmp_path, monkeypatch):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    for name in _evictable_names():
        _touch(tmp_path / name)
    for name in _protected_names():
        _touch(tmp_path / name)

    _force_free(monkeypatch, storage._MIN_FREE_GB - 1.0)  # below the floor
    result = storage.maybe_sweep()

    assert result is not None
    for name in _evictable_names():
        assert not (tmp_path / name).exists(), "maybe_sweep did not evict below floor"
    for name in _protected_names():
        assert (tmp_path / name).exists(), "maybe_sweep touched a protected file"


# --------------------------------------------------------------------------- #
# Criterion 7: _evictable_files never recurses into subdirectories.
# --------------------------------------------------------------------------- #
def test_evictable_files_is_top_level_only(tmp_path, monkeypatch):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    top = _touch(tmp_path / "top.mix.wav")
    _touch(tmp_path / "sub" / "nested.mix.wav")

    found = storage._evictable_files()

    assert [p.name for p in found] == ["top.mix.wav"]
    assert top in found


# --------------------------------------------------------------------------- #
# Criterion 8: empty and missing data dir — zero report, no exception.
# --------------------------------------------------------------------------- #
def test_sweep_on_empty_dir(tmp_path, monkeypatch):
    _use_tmp_data_dir(monkeypatch, tmp_path)  # tmp_path exists but is empty
    _force_free(monkeypatch, 5.0)

    report = storage.sweep()

    assert report["evicted"] == 0
    assert report["files"] == []
    assert report["candidates"] == 0


def test_sweep_on_missing_dir(tmp_path, monkeypatch):
    missing = tmp_path / "does_not_exist"
    monkeypatch.setattr(
        storage, "settings", dataclasses.replace(storage.settings, data_dir=missing)
    )
    _force_free(monkeypatch, 5.0)  # stub avoids touching the missing path on disk

    report = storage.sweep()  # must not raise

    assert report["evicted"] == 0
    assert report["files"] == []
