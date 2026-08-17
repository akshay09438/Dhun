"""The catalogue index must survive concurrent writers and a crash mid-write.

`data/library/manifest.json` indexes the ENTIRE catalog (112 songs today). Until now it was
read-modify-written whole by `scripts/ingest_catalog.py`: load the list, mutate it in memory, write
it back. That has two holes, both live today with no uploads involved:

  * TWO WRITERS AT ONCE -> LAST WRITER WINS. Both read the same list, both append their own row,
    the second write overwrites the first. The losing song is stored, split, analysed and PAID FOR,
    and is invisible to the picker. That is the same shape as the 2026-08-14 incident where 103
    songs were loaded and unreachable.
  * THE WRITE IS NOT ATOMIC. `write_text` truncates first, so a crash (or a full disk) between
    truncate and flush leaves a partial or empty manifest — losing all 112 rows, not one.

These tests pin both, plus the per-song-id in-flight guard that stops two people ingesting the same
track from both paying Replicate for it.
"""

from __future__ import annotations

import json
import threading

import pytest

from app import library_store


def _sid(n: int) -> str:
    """A distinct, well-formed 64-hex song id."""
    return f"{n:064x}"


@pytest.fixture(autouse=True)
def _clean_manifest():
    """Each test starts from no manifest at all (the session data dir is a temp folder)."""
    p = library_store.manifest_path()
    if p.exists():
        p.unlink()
    yield
    if p.exists():
        p.unlink()


# --- the race ------------------------------------------------------------------------------

def test_concurrent_upserts_never_lose_a_row():
    """20 writers at once -> 20 rows. Against a naive read-modify-write this loses rows."""
    n = 20
    ready = threading.Barrier(n)
    errors: list[BaseException] = []

    def add(i: int) -> None:
        try:
            ready.wait(timeout=10)  # maximise the overlap
            library_store.upsert(f"song {i}", _sid(i), "beat")
        except BaseException as e:  # noqa: BLE001 — surfaced below so a failure is readable
            errors.append(e)

    threads = [threading.Thread(target=add, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"writers raised: {errors!r}"
    rows = library_store.load()
    got = {r["song_id"] for r in rows}
    missing = {_sid(i) for i in range(n)} - got
    assert not missing, f"{len(missing)} song(s) lost their row to a concurrent write"
    assert len(rows) == n


def test_a_reader_never_sees_a_half_written_manifest():
    """While writers churn, every `load()` returns the old list or the new one — never broken JSON,
    never truncated, and never EMPTY.

    "Never empty" is the case that matters most and the one that nearly shipped. The atomic replace
    guarantees no reader sees half a file, but on Windows it also makes the destination briefly
    un-openable — and a reader that treats that error as "no catalogue" reports zero songs to the
    picker. Reading raw bytes here would test the filesystem; reading through `load()` tests the
    contract every caller actually depends on.
    """
    library_store.upsert("seed", _sid(999), "beat")
    stop = threading.Event()
    bad: list[str] = []

    def reader() -> None:
        while not stop.is_set():
            rows = library_store.load()
            if not isinstance(rows, list):
                bad.append(f"load() returned {type(rows).__name__}")
            elif not rows:
                bad.append("load() reported an EMPTY catalog mid-write")
            # and when the raw file is readable at all, it must never be partial
            try:
                raw = library_store.manifest_path().read_text(encoding="utf-8")
            except OSError:
                continue  # the transient Windows replace window — `load()` above is the contract
            try:
                json.loads(raw)
            except json.JSONDecodeError:
                bad.append(f"partial JSON on disk ({len(raw)} bytes)")

    r = threading.Thread(target=reader, daemon=True)
    r.start()
    for i in range(40):
        library_store.upsert(f"song {i}", _sid(i), "vocals", language="english")
    stop.set()
    r.join(timeout=10)
    assert not bad, f"reader saw a broken manifest: {bad[:5]}"


# --- the crash -----------------------------------------------------------------------------

def test_a_failed_write_leaves_the_previous_manifest_intact(monkeypatch):
    """If serialising or writing blows up, the catalogue that was already there must survive."""
    library_store.upsert("good song", _sid(1), "beat")
    before = library_store.manifest_path().read_text(encoding="utf-8")

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(library_store.json, "dump", boom)
    with pytest.raises(OSError):
        library_store.upsert("doomed", _sid(2), "beat")

    assert library_store.manifest_path().read_text(encoding="utf-8") == before
    assert [r["song_id"] for r in library_store.load()] == [_sid(1)]


def test_a_failed_write_leaves_no_temp_files_behind(monkeypatch):
    """A litter of .tmp files in the library folder would be mistaken for catalogue data."""
    library_store.upsert("good song", _sid(1), "beat")

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(library_store.json, "dump", boom)
    with pytest.raises(OSError):
        library_store.upsert("doomed", _sid(2), "beat")

    # `.manifest.lock` is infrastructure and is meant to persist; a `.tmp` is litter that a later
    # reader could mistake for catalogue data.
    leftovers = [p.name for p in library_store.manifest_path().parent.iterdir()
                 if p.name.endswith(".tmp")]
    assert leftovers == [], f"temp files left behind: {leftovers}"


# --- row semantics -------------------------------------------------------------------------

def test_upsert_preserves_fields_it_does_not_know_about():
    """`uploaded_by` and `main_drop` are written by /add and must survive an operator script
    re-upserting the same song (e.g. renaming it, or re-running the ingest)."""
    library_store.upsert("mine", _sid(7), "beat",
                         extra={"uploaded_by": "12345", "main_drop": 84.0})
    library_store.upsert("mine, renamed", _sid(7), "beat")
    row = next(r for r in library_store.load() if r["song_id"] == _sid(7))
    assert row["name"] == "mine, renamed"
    assert row["uploaded_by"] == "12345"
    assert row["main_drop"] == 84.0


def test_upsert_updates_in_place_rather_than_adding_a_second_row():
    library_store.upsert("a", _sid(3), "beat")
    library_store.upsert("b", _sid(3), "vocals", language="english")
    rows = library_store.load()
    assert len(rows) == 1
    assert rows[0]["name"] == "b"
    assert rows[0]["role_hint"] == "vocals"
    assert rows[0]["language"] == "english"


def test_a_broken_manifest_reads_as_empty_rather_than_raising():
    """Matches the existing readers' behaviour — a malformed file must never crash the catalog."""
    p = library_store.manifest_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ not json", encoding="utf-8")
    assert library_store.load() == []


# --- the per-song in-flight guard ----------------------------------------------------------

def test_the_same_song_id_cannot_be_ingested_twice_at_once():
    """Two people uploading the SAME track must not both run (and both pay for) the pipeline."""
    order: list[str] = []
    entered = threading.Event()

    def first() -> None:
        with library_store.song_lock(_sid(5)):
            order.append("first-in")
            entered.set()
            threading.Event().wait(0.2)
            order.append("first-out")

    def second() -> None:
        entered.wait(timeout=5)
        with library_store.song_lock(_sid(5)):
            order.append("second-in")

    t1, t2 = threading.Thread(target=first), threading.Thread(target=second)
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)
    assert order == ["first-in", "first-out", "second-in"]


def test_different_songs_are_not_blocked_by_each_other():
    """The guard is per song id — two DIFFERENT uploads must run side by side."""
    both_in = threading.Barrier(2, timeout=5)
    ok: list[bool] = []

    def hold(sid: str) -> None:
        with library_store.song_lock(sid):
            try:
                both_in.wait()
                ok.append(True)
            except threading.BrokenBarrierError:
                ok.append(False)

    ts = [threading.Thread(target=hold, args=(_sid(i),)) for i in (10, 11)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=10)
    assert ok == [True, True], "a per-song guard must not serialise different songs"
