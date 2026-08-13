"""Acceptance tests for ROUTINE stale-render cleanup — `storage.sweep_old()` and its janitor trigger.

Written against the approved design `docs/superpowers/specs/2026-08-13-stale-render-cleanup-design.md`,
BEFORE the implementation exists and by an author independent of it. Every test here must fail today
for one honest reason: the behaviour does not exist yet.

Danger surface: this path DELETES finished mixes. Today's sweep only deletes under disk pressure;
`sweep_old` deletes on AGE ALONE, with no disk-pressure gate at all. That removes the one accident
brake the existing sweep had, so the age window, the in-flight floor, the allowlist and the
non-recursion are the entire safety story and are pinned hard below.

Isolation contract (mandatory, copied verbatim in spirit from test_cache_sweep.py — a test that
touched the real data dir or the machine's real free-disk number would be a live-fire test):
  * settings.data_dir is redirected to a throwaway tmp_path (`_use_tmp_data_dir`).
  * storage._free_gb is monkeypatched to a constant we choose (`_force_free`), so nothing here
    depends on, or is changed by, the actual disk.
  * every file is created through `_touch` with an EXPLICIT mtime.

DELIBERATE DIVERGENCE from test_cache_sweep.py: that file has an autouse `_no_grace` fixture that
sets `_EVICT_MIN_AGE_SECS = 0.0`. This file deliberately does NOT, and must not. The headline
acceptance criterion here is that the 300-second in-flight grace is a FLOOR no caller may breach —
a fixture that zeroed the grace for the whole module would make that test vacuously green, which is
the exact hollow-test failure this suite exists to prevent. Instead every test states the age it
means as an explicit mtime.

Report shape: `sweep_old` is pinned to the SAME report keys `sweep()` already returns
(`dry_run` / `evicted` / `freed_gb` / `free_gb_after` / `candidates` / `files`). Reusing the
established shape is the project's "do not invent a second way" rule, and the janitor and any future
dashboard read it.
"""

from __future__ import annotations

import dataclasses
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import janitor, storage
from app.main import app
from app.routes import mix as mix_route
from app.routes import set as set_route

client = TestClient(app)

# A 64-hex-looking stem, the shape real stored ids take.
H = "a" * 64

_DAY = 86400.0


# --------------------------------------------------------------------------- #
# Isolation helpers — identical contract to test_cache_sweep.py.
# --------------------------------------------------------------------------- #
def _use_tmp_data_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        storage, "settings", dataclasses.replace(storage.settings, data_dir=tmp_path)
    )


def _touch(path: Path, content: bytes = b"x", mtime: float | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    # Same Windows caveat as test_cache_sweep.py: a just-written file's recorded mtime can read
    # slightly AHEAD of time.time(), so never rely on the implicit mtime for an age assertion —
    # every caller in this file passes an explicit one.
    os.utime(path, ((mtime, mtime) if mtime is not None else (time.time() - 1.0,) * 2))
    return path


def _force_free(monkeypatch, value: float) -> None:
    """Pin the disk-free reading to a constant GB value we choose."""
    monkeypatch.setattr(storage, "_free_gb", lambda path: float(value))


def _days_ago(days: float) -> float:
    return time.time() - days * _DAY


# A disk so healthy that ANY pressure-driven sweep would delete nothing. Used in every age test, so
# a deletion here can only have come from the age rule.
_PLENTY_OF_FREE_DISK_GB = 500.0


# --------------------------------------------------------------------------- #
# Criterion 1: a render nobody has played for 8 days is tidied away.
# --------------------------------------------------------------------------- #
def test_a_render_unused_for_eight_days_is_deleted(tmp_path, monkeypatch):
    """The whole point of the feature: routine tidying, with no disk emergency in sight.

    Free disk is pinned at 500 GB, so if this render disappears it is because it went stale — not
    because anything was under pressure."""
    _use_tmp_data_dir(monkeypatch, tmp_path)
    stale = _touch(tmp_path / f"{H}.mix.wav", mtime=_days_ago(8))

    _force_free(monkeypatch, _PLENTY_OF_FREE_DISK_GB)
    report = storage.sweep_old()

    assert not stale.exists(), "a render untouched for 8 days should have been tidied away"
    assert report["files"] == [f"{H}.mix.wav"]
    assert report["evicted"] == 1


# --------------------------------------------------------------------------- #
# Criterion 2: a render played yesterday survives, however old it actually is.
# --------------------------------------------------------------------------- #
def test_a_render_played_yesterday_survives_however_old_the_mix_is(tmp_path, monkeypatch):
    """The window counts from LAST PLAYED, not from when the mix was made. A favourite mix from
    months ago that the founder played yesterday must still be there today."""
    _use_tmp_data_dir(monkeypatch, tmp_path)
    # Every evictable kind, all played yesterday — the age stamp is the only thing that matters.
    recently_played = [
        _touch(tmp_path / f"{H}1.mix.wav", mtime=_days_ago(1)),
        _touch(tmp_path / f"{H}2.bestparts.wav", mtime=_days_ago(1)),
        _touch(tmp_path / f"{H}3.set.wav", mtime=_days_ago(1)),
        _touch(tmp_path / f"{H}4.livearr.wav", mtime=_days_ago(1)),
        _touch(tmp_path / f"{H}5.pitchshift.wav", mtime=_days_ago(1)),
    ]
    # A control that IS stale, so a `sweep_old` that simply did nothing cannot pass this test.
    stale = _touch(tmp_path / f"{H}6.mix.wav", mtime=_days_ago(30))

    _force_free(monkeypatch, _PLENTY_OF_FREE_DISK_GB)
    report = storage.sweep_old()

    for p in recently_played:
        assert p.exists(), f"a render played yesterday was deleted: {p.name}"
    assert not stale.exists(), "the 30-day-old control should have been tidied away"
    assert report["files"] == [f"{H}6.mix.wav"]


# --------------------------------------------------------------------------- #
# Criterion 3 (THE CRITICAL ONE): the 300s in-flight grace is a FLOOR, not a default.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("caller_asked_for_days", [0, 0.0, -1, -5.0])
def test_no_caller_can_delete_a_render_that_is_still_being_written(
    tmp_path, monkeypatch, caller_asked_for_days
):
    """The single most dangerous way this feature can go wrong.

    `sweep_old(max_age_days=0)` means "everything is stale" — and a render being written THIS
    SECOND would be destroyed mid-write, taking the user's mix with it. The design requires the
    effective threshold to be `max(max_age_days * 86400, _EVICT_MIN_AGE_SECS)`, so the 300-second
    in-flight grace is a floor NO caller can step over, however small or negative the number they
    pass. In the withdrawn card that grace was only a default, and passing 0 walked straight over it.

    Note this test runs against the REAL `_EVICT_MIN_AGE_SECS` (300.0). It is never zeroed by a
    fixture in this module — a zeroed grace would make this test prove nothing.
    """
    assert storage._EVICT_MIN_AGE_SECS == 300.0, (
        "this test is only meaningful against the real in-flight grace"
    )
    _use_tmp_data_dir(monkeypatch, tmp_path)
    now = time.time()
    being_written = _touch(tmp_path / f"{H}1.mix.wav", mtime=now)          # in flight, this second
    just_finished = _touch(tmp_path / f"{H}2.mix.wav", mtime=now - 120)    # 2 min old, inside grace
    # Control: comfortably outside the 300s floor, so it SHOULD go at max_age_days=0. Without this,
    # a `sweep_old` that deleted nothing at all would pass and prove nothing.
    safely_old = _touch(tmp_path / f"{H}3.mix.wav", mtime=now - 1200)      # 20 min old

    _force_free(monkeypatch, _PLENTY_OF_FREE_DISK_GB)
    report = storage.sweep_old(max_age_days=caller_asked_for_days)

    assert being_written.exists(), (
        f"sweep_old(max_age_days={caller_asked_for_days}) deleted a render being written this "
        "second — the 300s in-flight grace must be a floor no caller can breach"
    )
    assert just_finished.exists(), (
        f"sweep_old(max_age_days={caller_asked_for_days}) deleted a 2-minute-old render — inside "
        "the 300s in-flight grace"
    )
    assert not safely_old.exists(), "the 20-minute-old control should have been deleted"
    assert report["files"] == [f"{H}3.mix.wav"]


# --------------------------------------------------------------------------- #
# Criterion 4: the allowlist and non-recursion hold on the NEW path too.
# --------------------------------------------------------------------------- #
def test_sources_stems_analyses_and_subfolders_are_never_touched_by_the_age_sweep(
    tmp_path, monkeypatch
):
    """The unrecoverable half of the data dir. `sweep()` is already fenced by an allowlist; the age
    sweep is a SECOND door into the same folder, and it opens with no disk-pressure gate at all, so
    the same fence has to hold on it. Everything here is 90 days old — far outside any window — and
    must still be present afterwards."""
    _use_tmp_data_dir(monkeypatch, tmp_path)
    ancient = _days_ago(90)
    protected = {
        f"{H}.wav": "the uploaded source — unrecoverable",
        f"{H}.vocals.mp3": "a Replicate-cost stem",
        f"{H}.drums.mp3": "a Replicate-cost stem",
        f"{H}.analysis.json": "the analysis",
        f"{H}.structure.json": "the structure analysis",
        f"{H}.mixplan.json": "the mix plan",
        f"{H}.mixname.txt": "the mix name",
        f"{H}.setmanifest.json": "the set manifest",
        f"{H}.suggestions.json": "the suggestions",
    }
    for name in protected:
        _touch(tmp_path / name, mtime=ancient)
    # Subdirectories are safe by construction because the scan never recurses — including a file
    # with an EVICTABLE suffix nested inside one, which is the case that would break if it did.
    nested = {
        "library/manifest.json": "the library manifest",
        "tuning_renders/APPROVED_CHAIN_CONFIG.txt": "the approved tuning config",
        "listening/foo.wav": "an ear-test file",
        "listening/" + f"{H}.mix.wav": "a render nested under listening/",
    }
    for rel in nested:
        _touch(tmp_path / rel, mtime=ancient)
    # A top-level stale render, so a `sweep_old` that did nothing cannot pass this test.
    stale = _touch(tmp_path / f"{H}9.mix.wav", mtime=ancient)

    _force_free(monkeypatch, _PLENTY_OF_FREE_DISK_GB)
    report = storage.sweep_old()

    for name, what in protected.items():
        assert (tmp_path / name).exists(), f"the age sweep deleted {what}: {name}"
    for rel, what in nested.items():
        assert (tmp_path / rel).exists(), f"the age sweep recursed and deleted {what}: {rel}"
    assert not stale.exists(), "the stale top-level render should have been tidied away"
    assert report["files"] == [f"{H}9.mix.wav"], (
        "only the one top-level stale render may ever be a candidate"
    )
    assert report["candidates"] == 1


# --------------------------------------------------------------------------- #
# Criterion 5: a dry run tells the truth and deletes nothing.
# --------------------------------------------------------------------------- #
def test_a_dry_run_says_what_it_would_delete_and_deletes_nothing(tmp_path, monkeypatch):
    """The safe way to look before the first live run on the founder's real data folder. The report
    must be HONEST: the same set that a live run then actually deletes."""
    _use_tmp_data_dir(monkeypatch, tmp_path)
    stale = [
        _touch(tmp_path / f"{H}1.mix.wav", mtime=_days_ago(9)),
        _touch(tmp_path / f"{H}2.set.wav", mtime=_days_ago(40)),
    ]
    fresh = _touch(tmp_path / f"{H}3.mix.wav", mtime=_days_ago(2))

    _force_free(monkeypatch, _PLENTY_OF_FREE_DISK_GB)
    preview = storage.sweep_old(dry_run=True)

    assert preview["dry_run"] is True
    assert set(preview["files"]) == {p.name for p in stale}
    assert preview["evicted"] == 2
    for p in stale:
        assert p.exists(), f"a dry run deleted a file: {p.name}"
    assert fresh.exists()

    # And the preview was not a fiction: a live run deletes exactly what it named, no more.
    live = storage.sweep_old()
    assert set(live["files"]) == set(preview["files"]), (
        "the dry run must report exactly what a live run then deletes"
    )
    for p in stale:
        assert not p.exists()
    assert fresh.exists(), "the live run deleted a render that is not stale"


# --------------------------------------------------------------------------- #
# Criterion 6: the emergency floors are NOT moved. Regression guard.
# --------------------------------------------------------------------------- #
def test_the_emergency_disk_floors_are_still_two_and_three_gb():
    """The blocking safety finding that sank the withdrawn card: it raised these to 4.0/6.0, which
    meant that at any reading under 4 GB free EVERY render emptied the whole cache chasing a 6 GB
    target it could not reach. These floors sit deliberately UNDER the janitor's 6 GB band so that
    `maybe_sweep` stays a last-ditch backstop and the janitor stays the only owner of cushion policy.

    This guard is expected to be GREEN before and after the change. If it ever goes red, the
    withdrawn card has crept back in."""
    assert storage._MIN_FREE_GB == 2.0, "the emergency floor moved — the withdrawn card's mistake"
    assert storage._TARGET_FREE_GB == 3.0, "the emergency target moved — the withdrawn card's mistake"


# --------------------------------------------------------------------------- #
# Criterion 7: the render hot path is untouched.
# --------------------------------------------------------------------------- #
def test_a_healthy_disk_still_deletes_nothing_on_the_render_path_even_with_stale_renders(
    tmp_path, monkeypatch
):
    """`maybe_sweep()` runs at the start of EVERY render. If the age sweep were wired in here, a
    machine with a healthy disk would start silently deleting week-old mixes on every grind, and the
    "0.03s instant repeat" would quietly stop working. Above the floor: nothing happens, full stop.

    Behavioural half of the criterion — expected GREEN before and after."""
    _use_tmp_data_dir(monkeypatch, tmp_path)
    ancient = [
        _touch(tmp_path / f"{H}1.mix.wav", mtime=_days_ago(60)),
        _touch(tmp_path / f"{H}2.set.wav", mtime=_days_ago(365)),
        _touch(tmp_path / f"{H}3.bestparts.wav", mtime=_days_ago(9)),
    ]

    _force_free(monkeypatch, storage._MIN_FREE_GB + 1.0)  # healthy: above the 2.0 GB floor
    result = storage.maybe_sweep()

    assert result is None, "maybe_sweep must stay silent above the floor"
    for p in ancient:
        assert p.exists(), (
            f"the render hot path deleted a stale render ({p.name}) on a healthy disk — the age "
            "sweep has been wired into maybe_sweep, which the design forbids"
        )


def test_the_render_path_never_calls_the_age_sweep(tmp_path, monkeypatch):
    """The structural half of the same criterion, and the one that catches the wiring directly
    rather than by its symptom: `maybe_sweep()` must never invoke `sweep_old` — neither above the
    floor nor below it. Below the floor it must behave exactly as it does today: sweep by pressure,
    return today's report shape, keep the catalog."""
    _use_tmp_data_dir(monkeypatch, tmp_path)
    calls: list[dict] = []

    def _spy_sweep_old(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return {"dry_run": False, "evicted": 0, "freed_gb": 0.0, "free_gb_after": 0.0,
                "candidates": 0, "files": []}

    # No raising=False: if `sweep_old` does not exist yet this fails loudly, which is the honest
    # state of the world before the feature lands.
    monkeypatch.setattr(storage, "sweep_old", _spy_sweep_old)

    stale = _touch(tmp_path / f"{H}1.mix.wav", mtime=_days_ago(9))
    source = _touch(tmp_path / f"{H}.wav", mtime=_days_ago(9))

    _force_free(monkeypatch, storage._MIN_FREE_GB + 1.0)  # healthy
    assert storage.maybe_sweep() is None
    assert calls == [], "maybe_sweep called the age sweep on a healthy disk"

    _force_free(monkeypatch, storage._MIN_FREE_GB - 1.0)  # under the floor
    report = storage.maybe_sweep()

    assert calls == [], "maybe_sweep called the age sweep under disk pressure"
    assert report is not None
    assert set(report) == {"dry_run", "evicted", "freed_gb", "free_gb_after", "candidates", "files"}, (
        "maybe_sweep's return shape changed — callers read these keys"
    )
    assert not stale.exists(), "under the floor, the pressure sweep must still evict as it does today"
    assert source.exists(), "the pressure sweep touched an unrecoverable source"


# --------------------------------------------------------------------------- #
# Criterion 8: the janitor tidies first, then measures.
# --------------------------------------------------------------------------- #
class _FakeStorage:
    """Stands in for storage.py, recording the ORDER of what it was asked to do.

    Same shape as the `_FakeStorage` in test_janitor.py, plus `sweep_old`, because the order of the
    two calls is the thing under test.

    It records the ARGUMENTS of every call, not just the name. A spy that keeps only the name is a
    hollow spy: an adversarial review changed the call site to `sweep_old(0)` and to
    `sweep_old(dry_run=True)` and the whole suite stayed green. Those are not cosmetic slips —
    `sweep_old(0)` means `max(0, 300)`, i.e. every render older than five minutes deleted on every
    60-second tick of a perfectly healthy disk, and `dry_run=True` means the feature quietly does
    nothing at all while logging as if it worked."""

    def __init__(self, free_gb: float, reclaimable_gb: float, stale_gb: float = 0.5):
        self.free_gb = free_gb
        self.reclaimable_gb = reclaimable_gb
        self.stale_gb = stale_gb
        self.calls: list[tuple] = []  # (name, args, kwargs) — the args are the point

    def max_render_age_days(self) -> float:
        return 7.0

    def sweep(self, *args, **kwargs) -> dict:
        target_free_gb = kwargs.get("target_free_gb", args[0] if args else 0.0)
        dry_run = kwargs.get("dry_run", args[1] if len(args) > 1 else False)
        self.calls.append(("preview" if dry_run else "sweep", args, kwargs))
        need = max(0.0, target_free_gb - self.free_gb)
        freed = min(need, self.reclaimable_gb)
        if not dry_run:
            self.free_gb += freed
            self.reclaimable_gb -= freed
        return {"dry_run": dry_run, "evicted": 1 if freed else 0, "freed_gb": round(freed, 3),
                "free_gb_after": round(self.free_gb, 2), "candidates": 1, "files": []}

    def sweep_old(self, *args, **kwargs) -> dict:
        self.calls.append(("sweep_old", args, kwargs))
        dry_run = bool(kwargs.get("dry_run", args[1] if len(args) > 1 else False))
        freed = 0.0 if dry_run else self.stale_gb
        if not dry_run:
            self.free_gb += self.stale_gb
            self.stale_gb = 0.0
        return {"dry_run": dry_run, "evicted": 1 if freed else 0, "freed_gb": round(freed, 3),
                "free_gb_after": round(self.free_gb, 2), "candidates": 1, "files": []}


@pytest.mark.parametrize(
    "free_gb, reclaimable_gb, expected_action",
    [
        (9.0, 3.5, janitor.SKIP_HEALTHY),   # plenty of room — still tidies
        (1.0, 1.5, janitor.SKIP_FUTILE),    # someone else is eating the disk — still tidies
        (4.0, 3.5, janitor.SWEEP),          # a real pressure sweep — tidies first
    ],
)
def test_the_janitor_tidies_stale_renders_before_it_measures_free_space(
    monkeypatch, free_gb, reclaimable_gb, expected_action
):
    """Two things at once, both from the design:

    ORDER — the age sweep runs BEFORE the dry-run preview that feeds the futility decision, so the
    futility brake decides on numbers that already reflect the tidying, and is less likely to have
    to spend useful cache.

    ALWAYS — routine tidying is not a pressure response, so it happens on every tick, including the
    ticks where the janitor decides to do nothing (healthy) or refuses to sweep (futile). If it were
    skipped on those two, stale renders would only ever be cleared during an emergency, which is the
    exact problem this feature was built to end.

    HOW — with no age override and not in dry-run. The window belongs to the policy file; a trigger
    that passes its own number is quietly rewriting the deletion rule from the outside, and one that
    passes `dry_run=True` ships a feature that only pretends to run."""
    fake = _FakeStorage(free_gb=free_gb, reclaimable_gb=reclaimable_gb)
    monkeypatch.setattr(janitor, "storage", fake)

    result = janitor.run_once(cushion_gb=6.0)

    names = [c[0] for c in fake.calls]
    assert "sweep_old" in names, (
        f"the janitor skipped routine tidying on a {expected_action} tick — stale renders would "
        "then only ever be cleared during an emergency"
    )
    assert names[0] == "sweep_old", (
        f"the janitor measured free space before tidying (call order: {names}) — the futility "
        "brake would then decide on stale numbers"
    )
    assert names.count("sweep_old") == 1, f"routine tidying ran {names.count('sweep_old')} times in one tick"
    assert fake.calls[0] == ("sweep_old", (), {}), (
        f"the janitor called sweep_old{fake.calls[0][1]} with {fake.calls[0][2]} — it must pass NO "
        "arguments at all. An age override here (e.g. sweep_old(0), which floors to the 300s grace) "
        "would delete every render older than five minutes on every 60-second tick of a healthy "
        "disk; dry_run=True would make the whole feature a no-op that still logs like it worked"
    )
    assert result["action"] == expected_action, "the futility decision itself must be unchanged"


# --------------------------------------------------------------------------- #
# Criterion 9: the window is settable without a code change, and read at CALL time.
# --------------------------------------------------------------------------- #
def test_the_age_window_can_be_changed_by_environment_after_import(tmp_path, monkeypatch):
    """A rented box, or a founder who wants a fortnight, must be able to change the window without a
    code change — and the value must be read INSIDE the call, never captured as a default argument,
    which Python binds once at import.

    That trap is not hypothetical here: the previous night's attempt at this very feature wrote
    `min_age_secs: float = _EVICT_MIN_AGE_SECS` and silently broke every runtime override. This test
    sets the variable AFTER `app.storage` was imported (it was imported at the top of this file, long
    before this line runs), so it can only pass if the value is resolved at call time."""
    _use_tmp_data_dir(monkeypatch, tmp_path)
    three_days_old = _touch(tmp_path / f"{H}1.mix.wav", mtime=_days_ago(3))
    twelve_hours_old = _touch(tmp_path / f"{H}2.mix.wav", mtime=_days_ago(0.5))

    _force_free(monkeypatch, _PLENTY_OF_FREE_DISK_GB)

    # Default window (7 days): a 3-day-old render is still young. Nothing goes.
    assert storage.sweep_old()["files"] == [], "the default window is 7 days, not 3"
    assert three_days_old.exists()

    # Now shrink the window to one day, after import.
    monkeypatch.setenv("PROMPTDJ_RENDER_MAX_AGE_DAYS", "1")
    report = storage.sweep_old()

    assert not three_days_old.exists(), (
        "PROMPTDJ_RENDER_MAX_AGE_DAYS=1 did not take effect — the window is frozen at import"
    )
    assert twelve_hours_old.exists(), "a 12-hour-old render is inside a 1-day window"
    assert report["files"] == [f"{H}1.mix.wav"]


# =========================================================================== #
# SECOND PASS — the "last PLAYED, not last written" half of the design.
#
# Everything above measures staleness from a file's mtime. That is only the founder's promise if
# something MOVES that mtime when a mix is played. Without it, "untouched for 7 days" silently means
# "rendered more than 7 days ago", and a mix played every single morning is deleted on day eight —
# the exact failure the whole feature was meant to prevent.
#
# Implementation decisions being pinned here (settled 2026-08-13):
#   1. `storage.mark_used(*paths, min_interval_secs=86400.0)` stamps each EXISTING path's mtime to
#      now, but only if that file's mtime is already older than `min_interval_secs`. It never
#      creates a file, never raises on a missing path or an OSError, and returns the paths it
#      actually stamped.
#   2. `GET /mix/{mix_id}/audio` marks BOTH `<mix_id>.mix.wav` and `<mix_id>.bestparts.wav` — the
#      highlight is what gets served, but the full render is what Regenerate and set-joining need,
#      so a played mix keeps its whole family alive together.
#   3. `GET /set/{set_id}/audio` does the same for the set's own served WAV.
#
# The once-a-day bound is not a nicety: `services/api/data` sits inside the OneDrive-synced tree, so
# re-stamping on every play would trigger a cloud re-upload of a large WAV every time.
#
# Route setup follows test_mix_route.py / test_set_route.py: a module-level TestClient and a
# tmp_path data dir pushed onto every module that resolves paths from `settings`.
# =========================================================================== #

MIX_ID = "c" * 64
SET_ID = "d" * 64


def _use_tmp_data_dir_for_routes(monkeypatch, tmp_path: Path) -> None:
    """Same redirect as `_use_tmp_data_dir`, applied to every module that resolves a served path.

    `mix_route` and `set_route` hold their own `settings` reference, so patching only `storage`
    would leave the routes reading the REAL data dir — a live-fire test."""
    for mod in (storage, mix_route, set_route):
        monkeypatch.setattr(
            mod, "settings", dataclasses.replace(mod.settings, data_dir=tmp_path)
        )


def _mtime(p: Path) -> float:
    return p.stat().st_mtime


def _is_now(p: Path, tolerance_secs: float = 60.0) -> bool:
    return abs(time.time() - _mtime(p)) < tolerance_secs


# --------------------------------------------------------------------------- #
# Decision 2: playing a mix keeps its whole family alive.
# --------------------------------------------------------------------------- #
def test_playing_a_mix_marks_both_the_highlight_and_the_full_render_as_used(tmp_path, monkeypatch):
    """The endpoint serves the best-parts highlight, but Regenerate and set-joining both read the
    FULL render. If only the served file were marked, a mix played every day would still lose its
    full render on day eight and quietly stop being re-mixable. Both move, or the promise is half
    kept."""
    _use_tmp_data_dir_for_routes(monkeypatch, tmp_path)
    full = _touch(tmp_path / f"{MIX_ID}.mix.wav", mtime=_days_ago(2))
    highlight = _touch(tmp_path / f"{MIX_ID}.bestparts.wav", mtime=_days_ago(2))

    r = client.get(f"/mix/{MIX_ID}/audio")

    assert r.status_code == 200
    assert _is_now(highlight), (
        "playing a mix did not mark the highlight it just served as used — its last-used stamp is "
        f"still {(time.time() - _mtime(highlight)) / _DAY:.1f} days old"
    )
    assert _is_now(full), (
        "playing a mix did not mark the FULL render as used — Regenerate and set-joining read that "
        "file, so it must stay alive with the highlight, not age out separately"
    )


# --------------------------------------------------------------------------- #
# The once-a-day bound (the OneDrive re-upload guard).
# --------------------------------------------------------------------------- #
def test_playing_the_same_mix_again_immediately_does_not_stamp_it_a_second_time(
    tmp_path, monkeypatch
):
    """`services/api/data` is inside the OneDrive-synced tree. Touching a large WAV re-uploads it to
    the cloud, so a stamp on EVERY play would turn each replay of a 30 MB mix into a fresh upload.
    Once per day per file is the bound; a second play seconds later must leave the file completely
    alone."""
    _use_tmp_data_dir_for_routes(monkeypatch, tmp_path)
    full = _touch(tmp_path / f"{MIX_ID}.mix.wav", mtime=_days_ago(2))
    highlight = _touch(tmp_path / f"{MIX_ID}.bestparts.wav", mtime=_days_ago(2))

    assert client.get(f"/mix/{MIX_ID}/audio").status_code == 200
    # Precondition, not the point of this test: the FIRST play must have stamped them. Without this
    # the test would pass vacuously against a route that never stamps anything at all.
    assert _is_now(full) and _is_now(highlight), (
        "precondition failed: the first play did not mark the mix as used at all"
    )
    after_first = (full.stat().st_mtime_ns, highlight.stat().st_mtime_ns)

    assert client.get(f"/mix/{MIX_ID}/audio").status_code == 200

    assert (full.stat().st_mtime_ns, highlight.stat().st_mtime_ns) == after_first, (
        "a second play within the same day re-stamped the files — every replay would re-upload the "
        "whole WAV to OneDrive"
    )


# --------------------------------------------------------------------------- #
# Decision 3: the set route does the same for its own served file.
# --------------------------------------------------------------------------- #
def test_playing_a_set_marks_the_set_wav_as_used(tmp_path, monkeypatch):
    """A joined set is a `.set.wav` — an evictable suffix like any other, and the most expensive
    thing in the folder to rebuild (up to five renders). Playing one must keep it alive on exactly
    the same terms as a mix."""
    _use_tmp_data_dir_for_routes(monkeypatch, tmp_path)
    set_wav = _touch(tmp_path / f"{SET_ID}.set.wav", mtime=_days_ago(2))

    r = client.get(f"/set/{SET_ID}/audio")

    assert r.status_code == 200
    assert _is_now(set_wav), (
        "playing a set did not mark it as used — a set the founder plays every evening would still "
        "be deleted on day eight, and it costs up to five renders to rebuild"
    )


# --------------------------------------------------------------------------- #
# Decision 1: `mark_used` itself — the interval, the return value, never creating a file.
# --------------------------------------------------------------------------- #
def test_marking_a_file_that_is_not_there_is_a_quiet_no_op(tmp_path, monkeypatch):
    """This runs on the serving path of every play, so it must never be able to break playback: a
    missing file (already swept, or a set with no highlight) is a no-op, not a 500. And it must
    never CREATE the file it was asked to stamp — a phantom empty `.mix.wav` would make the mix
    route's `exists()` check say "ready" and serve the user zero bytes."""
    _use_tmp_data_dir_for_routes(monkeypatch, tmp_path)
    missing = tmp_path / f"{MIX_ID}.mix.wav"

    stamped = storage.mark_used(missing)  # must not raise

    assert stamped == [], "mark_used claimed to stamp a file that does not exist"
    assert not missing.exists(), (
        "mark_used CREATED the file it was asked to stamp — an empty phantom render would then be "
        "served to the user as a finished mix"
    )

    # An OSError from the filesystem (locked file, read-only, OneDrive mid-sync) is also swallowed:
    # failing to record a play must never fail the play.
    real = _touch(tmp_path / f"{H}.mix.wav", mtime=_days_ago(2))
    monkeypatch.setattr(os, "utime", lambda *a, **k: (_ for _ in ()).throw(OSError("locked")))
    assert storage.mark_used(real) == [], "an unstampable file must be reported as not stamped"


def test_mark_used_only_stamps_what_is_older_than_the_interval_and_says_which(tmp_path, monkeypatch):
    """The contract the routes lean on, stated directly: old files move, files stamped within the
    interval are left completely untouched, and the return value names exactly what moved so a
    caller can log it."""
    _use_tmp_data_dir_for_routes(monkeypatch, tmp_path)
    stale = _touch(tmp_path / f"{H}1.mix.wav", mtime=_days_ago(2))
    stamped_today = _touch(tmp_path / f"{H}2.mix.wav", mtime=_days_ago(0.25))  # 6 hours ago
    untouched_ns = stamped_today.stat().st_mtime_ns

    moved = storage.mark_used(stale, stamped_today)

    assert moved == [stale], f"expected only the 2-day-old file to be stamped, got {moved}"
    assert _is_now(stale)
    assert stamped_today.stat().st_mtime_ns == untouched_ns, (
        "a file stamped 6 hours ago was re-stamped — the once-a-day bound is not holding"
    )

    # The bound is a parameter, not a constant, so a caller can be explicit about it.
    assert storage.mark_used(stamped_today, min_interval_secs=60.0) == [stamped_today]
    assert _is_now(stamped_today)


# --------------------------------------------------------------------------- #
# THE PROMISE, end to end: "last played", not "last written".
# --------------------------------------------------------------------------- #
def test_a_mix_made_nine_days_ago_but_played_today_survives_the_cleanup(tmp_path, monkeypatch):
    """The test the whole second pass exists for, and the one a non-technical reader should read
    first: the founder's favourite mix, made nine days ago and played this morning, is still there
    tonight. A mix nobody has played in nine days is not.

    Without stamping on the serve path, BOTH of these files are nine days old to `sweep_old` and
    both are deleted — the feature would then be "we delete mixes older than a week", which is not
    what was approved."""
    _use_tmp_data_dir_for_routes(monkeypatch, tmp_path)
    played_today = _touch(tmp_path / f"{MIX_ID}.mix.wav", mtime=_days_ago(9))
    played_today_highlight = _touch(tmp_path / f"{MIX_ID}.bestparts.wav", mtime=_days_ago(9))
    # The control: same age, same suffix, never played. This one SHOULD go — otherwise the test
    # would pass against a cleanup that simply never deletes anything.
    forgotten = _touch(tmp_path / f"{H}9.mix.wav", mtime=_days_ago(9))

    assert client.get(f"/mix/{MIX_ID}/audio").status_code == 200  # the founder plays it this morning

    _force_free(monkeypatch, _PLENTY_OF_FREE_DISK_GB)
    report = storage.sweep_old()

    assert played_today.exists(), (
        "the cleanup deleted a mix that was played TODAY — the window is counting from when the "
        "mix was written, not from when it was last played"
    )
    assert played_today_highlight.exists(), (
        "the cleanup deleted the highlight of a mix played today"
    )
    assert not forgotten.exists(), "a mix nobody has played for nine days should have been tidied"
    assert report["files"] == [f"{H}9.mix.wav"]


# --------------------------------------------------------------------------- #
# THE HOLLOW-TEST BACKFILL (2026-08-13).
#
# A mutation run proved three safety properties this module already CLAIMED were the reason the
# change was safe had, in fact, no test at all: deleting the TOCTOU re-stat, the `math.isfinite`
# fallback in `sweep_old`, and `math.isfinite` in `envnum.env_float` each left the whole suite
# green. Every one of those three lines is credited in a code comment to "adversarial review
# 2026-08-13" — so the fixes were real and their protection was imaginary.
#
# The scripts that DID catch them lived in a staging folder and vanish when the change is applied.
# These tests are those attacks, moved into the suite where they will run forever.
# --------------------------------------------------------------------------- #
def test_a_mix_played_DURING_the_sweep_is_not_deleted(tmp_path, monkeypatch):
    """The TOCTOU re-stat. Candidates are listed, then deleted one at a time — and somebody can
    press play in between. Without a second look at the stamp immediately before `unlink`, the
    sweep deletes the very mix they just started listening to.

    Mutation M2 (delete the re-stat) left the suite fully green before this test existed."""
    _use_tmp_data_dir(monkeypatch, tmp_path)
    played_mid_sweep = _touch(tmp_path / f"{H}.mix.wav", mtime=_days_ago(9))
    control = _touch(tmp_path / f"{'b' * 64}.mix.wav", mtime=_days_ago(9))
    _force_free(monkeypatch, _PLENTY_OF_FREE_DISK_GB)

    # Somebody presses play after the candidate list is built but before the deletions run.
    real_evictable = storage._evictable_files

    def list_then_play(*a, **kw):
        files = real_evictable(*a, **kw)
        os.utime(played_mid_sweep, (time.time(),) * 2)  # <- the play, mid-sweep
        return files

    monkeypatch.setattr(storage, "_evictable_files", list_then_play)
    report = storage.sweep_old()

    assert played_mid_sweep.exists(), (
        "the sweep deleted a mix that was played while the sweep was running — the stamp is not "
        "being re-read immediately before the delete"
    )
    assert not control.exists(), "the control render should still have been tidied"
    assert report["files"] == [control.name]


@pytest.mark.parametrize("hostile", ["nan", "NaN", "inf", "-inf", "Infinity"])
def test_a_nonsense_age_window_in_the_environment_cannot_delete_a_fresh_render(
        tmp_path, monkeypatch, hostile):
    """`float('nan')` parses, and EVERY comparison against NaN is False — so a bare `val <= 0`
    guard waves it through as positive and `now - mtime < nan` then reads False for every file,
    including one being written this second. Infinity is the mirror image.

    Mutations M3 and M9 (drop `math.isfinite` from `sweep_old` and from `envnum`) BOTH left the
    suite green before this test existed. Two independent guards, neither of them tested."""
    _use_tmp_data_dir(monkeypatch, tmp_path)
    monkeypatch.setenv("PROMPTDJ_RENDER_MAX_AGE_DAYS", hostile)
    in_flight = _touch(tmp_path / f"{H}.mix.wav", mtime=time.time())  # being written RIGHT NOW
    _force_free(monkeypatch, _PLENTY_OF_FREE_DISK_GB)

    storage.sweep_old()

    assert in_flight.exists(), (
        f"PROMPTDJ_RENDER_MAX_AGE_DAYS={hostile!r} deleted a render written this second — a "
        "non-finite window became the deletion threshold"
    )


def test_a_nonsense_window_passed_straight_to_sweep_old_is_also_refused(tmp_path, monkeypatch):
    """Defence in depth: `sweep_old` re-checks the window itself rather than trusting its caller,
    because an ops script can call it directly (`scripts/evict_cache.py` parses a float from argv)."""
    _use_tmp_data_dir(monkeypatch, tmp_path)
    in_flight = _touch(tmp_path / f"{H}.mix.wav", mtime=time.time())
    _force_free(monkeypatch, _PLENTY_OF_FREE_DISK_GB)

    storage.sweep_old(max_age_days=float("nan"))

    assert in_flight.exists(), "sweep_old(nan) deleted a render written this second"


# --------------------------------------------------------------------------- #
# The anomaly brake and the coupled stamp interval (both added 2026-08-13 after review).
# --------------------------------------------------------------------------- #
def test_one_tick_cannot_wipe_the_whole_render_cache(tmp_path, monkeypatch):
    """The restored-backup / copied-folder / clock-jump case. `shutil.copy2`, robocopy, Explorer
    and a OneDrive re-materialisation all preserve mtimes, so a restore hands back files that read
    as instantly ancient — and a restore is exactly what somebody does AFTER losing renders.

    The cap does not make the timestamps right; it makes the loss slow, logged and interruptible
    rather than instant and total."""
    _use_tmp_data_dir(monkeypatch, tmp_path)
    everything = [_touch(tmp_path / f"{'c' * 63}{i:01x}.mix.wav", mtime=_days_ago(30))
                  for i in range(16)]
    _force_free(monkeypatch, _PLENTY_OF_FREE_DISK_GB)

    report = storage.sweep_old()

    survivors = [p for p in everything if p.exists()]
    assert report["evicted"] == storage._SWEEP_OLD_MAX_PER_TICK, (
        f"one tick deleted {report['evicted']} renders — the per-tick cap is not holding"
    )
    assert len(survivors) == len(everything) - storage._SWEEP_OLD_MAX_PER_TICK


def test_the_cap_takes_the_oldest_first(tmp_path, monkeypatch):
    """With a cap, WHICH ones go is a real decision — the deadest weight is the only defensible
    answer, and it matches `sweep()`'s existing least-recently-used ordering."""
    _use_tmp_data_dir(monkeypatch, tmp_path)
    newer = _touch(tmp_path / f"{'e' * 64}.mix.wav", mtime=_days_ago(8))
    ancient = [_touch(tmp_path / f"{'d' * 63}{i:01x}.mix.wav", mtime=_days_ago(100 + i))
               for i in range(storage._SWEEP_OLD_MAX_PER_TICK)]
    _force_free(monkeypatch, _PLENTY_OF_FREE_DISK_GB)

    # HAND THE SWEEP ITS WORST CASE, rather than hoping for it. Directory order is not a promise:
    # an earlier version of this test relied on `iterdir` returning creation order and passed
    # happily with the sort removed, which made it decoration. Feeding the candidates in newest-
    # first order means the only thing that can save the newest render is the sort itself.
    real_evictable = storage._evictable_files
    monkeypatch.setattr(
        storage, "_evictable_files",
        lambda *a, **kw: sorted(real_evictable(*a, **kw),
                                key=lambda p: p.stat().st_mtime, reverse=True))

    storage.sweep_old()

    assert newer.exists(), "the cap spent its budget on a newer render and left older ones behind"
    assert not any(p.exists() for p in ancient)


def test_playing_a_mix_still_protects_it_when_the_window_is_shorter_than_a_day(
        tmp_path, monkeypatch):
    """`PROMPTDJ_RENDER_MAX_AGE_DAYS` is a documented knob. A flat 24h stamp interval meant that at
    any window under a day, playing a mix REFUSED to re-stamp it — so the next tick deleted the
    file somebody was listening to. The interval is now a quarter of the window."""
    _use_tmp_data_dir(monkeypatch, tmp_path)
    monkeypatch.setenv("PROMPTDJ_RENDER_MAX_AGE_DAYS", "0.5")
    played = _touch(tmp_path / f"{H}.mix.wav", mtime=_days_ago(0.4))
    _force_free(monkeypatch, _PLENTY_OF_FREE_DISK_GB)

    assert storage.mark_used(played) == [played], (
        "playing the mix did not re-stamp it — the stamp interval is longer than the age window"
    )
    storage.sweep_old()
    assert played.exists(), "a mix played moments ago was deleted under a short age window"


@pytest.mark.parametrize("hostile", ["nan", "NaN", "inf", "-inf", "Infinity"])
def test_env_float_itself_refuses_non_finite_numbers(monkeypatch, hostile):
    """The guard in `envnum.env_float`, pinned DIRECTLY rather than through `sweep_old`.

    Mutation M9 removed `math.isfinite` from `envnum` and the whole suite stayed green, because
    `sweep_old` has its own second guard that caught it. Defence in depth is good; a test that
    cannot tell the two layers apart is not. This one fails if either layer is removed alone.

    `interval_secs` is the reason the infinity half matters as much as the NaN half: a window of
    `inf` would put the janitor's timer into `asyncio.sleep(inf)`, a loop that never wakes — the
    disk defence would be silently dead with nothing in the log to say so."""
    from app.envnum import env_float

    monkeypatch.setenv("PROMPTDJ_TEST_KNOB", hostile)
    assert env_float("PROMPTDJ_TEST_KNOB", 7.0) == 7.0, (
        f"env_float let {hostile!r} through — a non-finite number reached a caller that will "
        "compare it against a file age or sleep on it"
    )

    monkeypatch.setenv("PROMPTDJ_DISK_CHECK_SECS", hostile)
    assert janitor.interval_secs() == janitor.DEFAULT_INTERVAL_SECS, (
        f"PROMPTDJ_DISK_CHECK_SECS={hostile!r} reached the janitor's timer"
    )


# --------------------------------------------------------------------------- #
# FOUNDER RULE 2026-08-13: a mix pinned to #best-mixes is never routine-tidied.
# "the mixes which will be in the best mixes tab should not be removed, and other than that,
#  everything should be removed."
# --------------------------------------------------------------------------- #
def test_a_pinned_mix_is_never_tidied_however_old_it_gets(tmp_path, monkeypatch):
    """The founder's own pick of what was worth keeping. A year of not playing it must not lose it."""
    _use_tmp_data_dir(monkeypatch, tmp_path)
    kept_id, forgotten_id = "f" * 64, "1" * 64
    kept = _touch(tmp_path / f"{kept_id}.mix.wav", mtime=_days_ago(365))
    kept_highlight = _touch(tmp_path / f"{kept_id}.bestparts.wav", mtime=_days_ago(365))
    forgotten = _touch(tmp_path / f"{forgotten_id}.mix.wav", mtime=_days_ago(365))

    assert storage.keep(kept_id) is True
    assert storage.is_kept(kept_id) and not storage.is_kept(forgotten_id)

    _force_free(monkeypatch, _PLENTY_OF_FREE_DISK_GB)
    storage.sweep_old()

    assert kept.exists(), "a mix pinned to #best-mixes was deleted by the routine tidy-up"
    assert kept_highlight.exists(), "the highlight of a pinned mix was deleted"
    assert not forgotten.exists(), "'everything else should be removed' — the control survived"


def test_a_pinned_mix_survives_the_EMERGENCY_sweep_too(tmp_path, monkeypatch):
    """"Should not be removed" is absolute, so the protection sits in `_evictable_files` — the one
    place BOTH sweeps get their candidates from. The trade-off is deliberate and worth stating: a
    pinned mix is no longer available for the disk to reclaim under pressure. At validation scale
    the showcase is small; if it ever grows enough to matter, `sweep`'s existing "evicted everything
    and still missed the target" warning is what will say so."""
    _use_tmp_data_dir(monkeypatch, tmp_path)
    kept_id = "f" * 64
    kept = _touch(tmp_path / f"{kept_id}.mix.wav", mtime=_days_ago(365))
    other = _touch(tmp_path / f"{'2' * 64}.mix.wav", mtime=_days_ago(365))
    storage.keep(kept_id)

    _force_free(monkeypatch, 0.1)          # desperate: far below _MIN_FREE_GB
    storage.sweep(target_free_gb=999.0)    # a target it can never reach — it will take everything

    assert kept.exists(), "the emergency sweep deleted a mix pinned to #best-mixes"
    assert not other.exists(), "the emergency sweep should still have taken the unpinned render"


def test_the_keep_markers_can_never_be_swept_by_the_sweep_they_guard(tmp_path, monkeypatch):
    """The markers live in `keep/`, and neither sweep recurses. A protection that the thing it
    protects against could delete would be no protection at all."""
    _use_tmp_data_dir(monkeypatch, tmp_path)
    kept_id = "f" * 64
    storage.keep(kept_id)
    marker = tmp_path / "keep" / kept_id
    # Bait: a file INSIDE keep/ that is named exactly like an evictable render.
    decoy = _touch(tmp_path / "keep" / f"{'3' * 64}.mix.wav", mtime=_days_ago(365))

    _force_free(monkeypatch, 0.1)
    storage.sweep(target_free_gb=999.0)
    storage.sweep_old()

    assert marker.exists(), "the keep marker was deleted — the protection is self-erasing"
    assert decoy.exists(), "a sweep recursed into keep/"


def test_keep_refuses_an_id_that_is_not_a_clean_hash(tmp_path, monkeypatch):
    """`keep()` puts its argument on the filesystem as a name, so it gets `path_for`'s treatment:
    a strict 64-hex id, or nothing. Otherwise `keep('../../x')` writes outside the data dir."""
    _use_tmp_data_dir(monkeypatch, tmp_path)
    for hostile in ["../../escape", "a" * 63, "A" * 64, "", "x" * 64, f"{'a' * 64}/../b"]:
        assert storage.keep(hostile) is False, f"keep() accepted {hostile!r}"
        assert storage.is_kept(hostile) is False


def test_the_keep_endpoint_protects_a_render_and_refuses_a_bad_id(tmp_path, monkeypatch):
    """The route the Discord bot calls when somebody hits 📌. Idempotent, because the button stays
    live for half an hour and people double-tap."""
    _use_tmp_data_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(mix_route, "settings",
                        dataclasses.replace(mix_route.settings, data_dir=tmp_path))
    good = "c" * 64

    assert client.post(f"/keep/{good}").status_code == 200
    assert client.post(f"/keep/{good}").status_code == 200   # double-tap is free
    assert storage.is_kept(good)

    assert client.post(f"/keep/{'z' * 64}").status_code == 400
    assert client.post(f"/keep/{'c' * 63}").status_code == 400


def test_a_pinned_render_that_is_not_on_disk_yet_is_still_protected(tmp_path, monkeypatch):
    """The marker records INTENT, not a file. A mix rebuilt later under the same id — ids are a
    hash of the inputs, so it is the same id — is protected the moment it exists again."""
    _use_tmp_data_dir(monkeypatch, tmp_path)
    render_id = "d" * 64
    storage.keep(render_id)                                   # pinned while nothing is on disk

    later = _touch(tmp_path / f"{render_id}.mix.wav", mtime=_days_ago(400))  # rebuilt, then ignored
    _force_free(monkeypatch, _PLENTY_OF_FREE_DISK_GB)
    storage.sweep_old()

    assert later.exists(), "a render rebuilt under a pinned id was tidied away"
