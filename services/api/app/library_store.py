"""The ONE reader/writer for `data/library/manifest.json` — the catalogue index.

Every song the app can play has a row here, so this file is the most load-bearing small thing in the
project: lose it and 112 songs vanish at once. It used to be read-modify-written whole by
`scripts/ingest_catalog.py` with a plain `write_text`, which had two measured holes (see
tests/test_library_store.py — both were demonstrated red before this module existed):

  * CONCURRENT WRITERS LOSE ROWS. Two writers read the same list, each appends its own row, the
    second write overwrites the first. Measured: **19 of 20 rows lost** with 20 writers. The losing
    song is stored, split, analysed and PAID FOR, and is invisible. Same shape as the 2026-08-14
    incident where 103 songs were loaded and unreachable.
  * A FAILED WRITE DESTROYS EVERYTHING. `open(...,"w")` truncates first, so a raise between truncate
    and flush leaves the manifest EMPTY — measured: the file read back as `''`. Not one row lost;
    all of them.

Three protections, each pinned by a test:
  1. `_PROCESS_LOCK` serialises writers inside this process (the API).
  2. A real OS file lock serialises them ACROSS processes, so the operator ingest script and a
     running API cannot interleave. The OS releases it if a process dies, so there is no stale-lock
     failure mode to clean up.
  3. `save()` writes a temp file in the SAME directory, fsyncs it, then `os.replace`s it into place.
     A reader therefore sees either the whole old file or the whole new one, never a partial.

`song_lock(song_id)` is a separate, per-song guard: two people uploading the SAME track must not
both run the pipeline and both pay Replicate for it. It is deliberately NOT the manifest lock —
different songs must ingest side by side.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from app.config import settings

# Serialises writers within this process. RLock so a caller already holding it (upsert -> save)
# does not deadlock on itself.
_PROCESS_LOCK = threading.RLock()

# One lock object per song id, handed out under `_REGISTRY_LOCK`. Bounded in practice by the number
# of distinct songs ever ingested by this process — tens, not thousands.
_SONG_LOCKS: dict[str, threading.Lock] = {}
_REGISTRY_LOCK = threading.Lock()

# Windows only: `os.replace` fails while another process holds the destination open for reading,
# because Python's `open` does not pass FILE_SHARE_DELETE. Readers hold it for microseconds, so a
# short retry converts a spurious PermissionError into a wait. POSIX renames straight through.
_REPLACE_ATTEMPTS = 40
_REPLACE_BACKOFF_S = 0.01
# Same Windows window, seen from the reader's side — see `load()`.
_READ_ATTEMPTS = 40


def manifest_path(data_dir: Path | None = None) -> Path:
    """The catalogue index. `data_dir` lets a caller resolve against its own (possibly test)
    folder; defaults to the configured one."""
    return (data_dir if data_dir is not None else settings.data_dir) / "library" / "manifest.json"


def _lock_path() -> Path:
    return manifest_path().parent / ".manifest.lock"


@contextmanager
def _file_lock():
    """An OS-level exclusive lock shared with any other PROCESS touching the manifest.

    Held on a sidecar file, never on the manifest itself: locking the manifest would conflict with
    the atomic replace that is the whole point of `save()`.
    """
    p = _lock_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fh = open(p, "a+b")
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)  # blocks, retries, then raises
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    finally:
        fh.close()


def load(data_dir: Path | None = None) -> list[dict]:
    """Every manifest row, or `[]` if the file is missing or malformed.

    Never raises: a broken manifest must degrade to an empty catalog rather than crash the app —
    the same contract `routes/library.py` already honours.

    RETRIES ON AN OS ERROR, and that is not belt-and-braces. On Windows the atomic `os.replace` in
    `save()` makes the destination briefly un-openable, so a reader landing in that window gets a
    sharing violation. Returning `[]` there would report an EMPTY CATALOG for an instant — the
    picker showing no songs at all — which is worse than the partial read the atomic write was
    added to prevent. Found by test_a_reader_never_sees_a_half_written_manifest, which saw it on
    the very first run. A genuinely malformed file is NOT retried: that is a real answer, not a
    race, and it degrades to `[]` immediately as before.
    """
    p = manifest_path(data_dir)
    for _attempt in range(_READ_ATTEMPTS):
        if not p.exists():
            return []
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        except OSError:
            time.sleep(_REPLACE_BACKOFF_S)
            continue
        return data if isinstance(data, list) else []
    return []


def save(entries: list[dict]) -> None:
    """Write the whole manifest ATOMICALLY. Either it fully lands or the previous file is untouched.

    Callers holding `_PROCESS_LOCK` + `_file_lock` (i.e. `upsert`) get read-modify-write safety too;
    `save` alone only guarantees that no reader ever sees a half-written file.
    """
    p = manifest_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(p.parent), prefix=".manifest-", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, indent=2, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())  # the bytes are on disk BEFORE the rename makes them the manifest
        last: OSError | None = None
        for _ in range(_REPLACE_ATTEMPTS):
            try:
                os.replace(tmp, p)
                return
            except PermissionError as e:  # Windows: a reader has it open for an instant
                last = e
                time.sleep(_REPLACE_BACKOFF_S)
        raise last if last else OSError("could not replace the manifest")
    except BaseException:
        tmp.unlink(missing_ok=True)  # never leave a .tmp to be mistaken for catalogue data
        raise


def upsert(name: str, song_id: str, role_hint: str, language: str = "",
           extra: dict | None = None) -> str:
    """Add or update this song's row and persist it. Returns "added" or "updated".

    LANGUAGE IS NOT OPTIONAL FOR A VOCAL, and forgetting it is silent. The Discord picker filters
    vocals by language and DEFAULTS to English (`bot.py::_vocals_for`), so a vocal with no tag
    appears in neither list — loaded, paid for, analysed, and invisible. That is exactly what
    happened on 2026-08-14 to 103 songs. Beats are never language-filtered, so a blank is harmless
    there.

    `extra` carries fields this module has no opinion about (`uploaded_by`, `main_drop`). They are
    merged, never dropped: a later operator re-upsert (a rename, a re-run of the ingest) must not
    silently erase who uploaded a song or where its drop is.
    """
    with _PROCESS_LOCK, _file_lock():
        entries = load()  # re-read INSIDE the lock — this is what makes it not lose rows
        for e in entries:
            if str(e.get("song_id", "")) == song_id:
                e["name"], e["role_hint"] = name, role_hint
                if language:
                    e["language"] = language
                if extra:
                    e.update(extra)
                save(entries)
                return "updated"
        entry = {"name": name, "song_id": song_id, "role_hint": role_hint}
        if language:
            entry["language"] = language
        if extra:
            entry.update(extra)
        entries.append(entry)
        save(entries)
        return "added"


@contextmanager
def song_lock(song_id: str):
    """Serialise work on ONE song id, so the same track is never ingested (and paid for) twice at
    once. Per-song by design: two DIFFERENT uploads must still run side by side."""
    with _REGISTRY_LOCK:
        lock = _SONG_LOCKS.setdefault(song_id, threading.Lock())
    with lock:
        yield
