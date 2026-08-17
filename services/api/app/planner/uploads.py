"""Is this song somebody's upload, and where did they say its drop is?

Both answers live on the song's own catalogue row (`uploaded_by`, `main_drop`), written by `/add`.
Keeping them as DATA rather than in the hand-written mark tables is deliberate: those tables are
ear-confirmed, curated by the founder, and must always win — an upload can never retune a catalog
beat that already sounds right. The precedence is the same one `marks_generated` already follows.

WHY THERE IS A CACHE. `is_upload` and `main_drop_for` are called on the planning path, several
times per mix. Reading `manifest.json` (118 rows) on every call would be a disk hit inside the hot
loop. The cache is invalidated by the file's mtime and size, never by a timer — so a song added by
`/add` is visible to the very next grind, with no restart.

EVERY FAILURE READS AS "NOT AN UPLOAD". An unreadable or missing manifest, an unknown song, a
malformed row: all return False. That direction matters. Reading "upload" when we do not know would
SILENCE THE BEAT'S OWN VOCAL on ordinary catalog grinds for everybody — a visible, catalog-wide
regression caused by a bad file read. Reading "catalogue" when we do not know costs an uploader one
mix that plans the old way.
"""

from __future__ import annotations

import logging
import threading

from app import library_store

log = logging.getLogger("promptdj.uploads")

_LOCK = threading.Lock()
_CACHE: dict[str, dict] | None = None
_STAMP: tuple[float, int] | None = None


def forget_cached_manifest() -> None:
    """Drop the cache. For tests, and for any caller that has just rewritten the manifest."""
    global _CACHE, _STAMP
    with _LOCK:
        _CACHE, _STAMP = None, None


def _stamp() -> tuple[float, int]:
    """(mtime, size) of the manifest — cheap, and enough to notice any write."""
    try:
        st = library_store.manifest_path().stat()
        return (st.st_mtime, st.st_size)
    except OSError:
        return (0.0, 0)


def _rows() -> dict[str, dict]:
    """song_id -> row, re-read only when the manifest has actually changed on disk."""
    global _CACHE, _STAMP
    now = _stamp()
    with _LOCK:
        if _CACHE is not None and _STAMP == now:
            return _CACHE
    fresh: dict[str, dict] = {}
    for e in library_store.load():
        sid = str(e.get("song_id", ""))
        if sid:
            fresh[sid] = e
    with _LOCK:
        _CACHE, _STAMP = fresh, now
        return _CACHE


def is_upload(song_id: str) -> bool:
    """Did somebody add this song with `/add`? False for catalog songs and for anything unknown."""
    try:
        return bool(_rows().get(song_id, {}).get("uploaded_by"))
    except Exception:  # noqa: BLE001 — see the module docstring: never guess "upload"
        log.exception("could not read the catalogue while checking if %s is an upload", song_id)
        return False


def is_upload_or_unknown(song_id: str) -> bool:
    """FAILS CLOSED. True if this is an upload OR if we cannot tell. For ACCESS CONTROL only.

    `is_upload` above fails OPEN by design — a planner that cannot read the catalogue must not
    silence a catalogue beat's vocal mid-mix. Reusing it as the guard on somebody's uploaded stems
    was a category error, and the re-review broke it in two ways: corrupt the manifest and every
    upload's stems became downloadable, and because `_rows()` caches on (mtime, size), a single
    transient empty read LATCHED that open until something wrote the file again.

    A permission check has the opposite duty to a planner: when it does not know, the answer is no.
    Refusing a catalogue stem for a moment is a nuisance; serving a stranger's unreleased track is
    not undoable.

    THE "UNKNOWN" THAT MATTERS IS AN UNREADABLE CATALOGUE, not a song that simply has no row.
    Every upload gets its row BEFORE the paid work starts, so "not in the catalogue" reliably means
    "not an upload" — an orphan, or a song from the old web upload path. Refusing those too was a
    first attempt at this and it was too broad: it broke the web player on any song that predates
    the catalogue, which is a real regression bought for no safety at all.
    """
    try:
        rows = _rows()
    except Exception:  # noqa: BLE001 — cannot read the catalogue, so assume it is somebody's
        log.exception("could not read the catalogue while guarding %s; refusing", song_id)
        return True
    if not rows:
        # Empty is ambiguous, and the two cases pull opposite ways: a file that is NOT THERE is a
        # fresh install with nothing to protect, while a file that IS there and still read as empty
        # is the corrupt-or-transient case that opened this lock in the review. The file's own
        # existence is what tells them apart.
        return library_store.manifest_path().exists()
    return bool((rows.get(song_id) or {}).get("uploaded_by"))


def uploaded_by(song_id: str) -> str:
    """The Discord id that added this song, or "" — the per-person cap counts these."""
    try:
        return str(_rows().get(song_id, {}).get("uploaded_by") or "")
    except Exception:  # noqa: BLE001
        return ""


def main_drop_for(song_id: str) -> list[float]:
    """The drop the uploader typed in, as the planner's drop list, or [] if there isn't one.

    Only ever consulted AFTER the hand-written tables (see `main_drops.main_drops_for`).
    """
    try:
        raw = _rows().get(song_id, {}).get("main_drop")
    except Exception:  # noqa: BLE001
        return []
    if raw is None:
        return []
    try:
        t = float(raw)
    except (TypeError, ValueError):
        log.warning("song %s has an unusable main_drop %r; falling back to detection", song_id, raw)
        return []
    return [t] if t > 0 else []


def count_all() -> int:
    """How many uploaded songs exist across everybody — the global cap counts these.
    PENDING ROWS DO NOT COUNT. A row is written before the paid work so the stem guard covers
    that window, but the in-flight upload is ALREADY counted by its reservation - counting
    both halved everybody's effective limit (measured: 3 accepted against a cap of 5).
    """
    try:
        return sum(1 for r in _rows().values() if r.get("uploaded_by") and not r.get("pending"))
    except Exception:  # noqa: BLE001
        return 0


def count_for(discord_id: str) -> int:
    """How many songs this person has uploaded — the per-person cap counts these.

    Counted from the manifest rather than a separate ledger so the quota and the copyright record
    can never disagree. A song removed from the catalogue therefore returns its slot, which is the
    behaviour we want.
    
    PENDING ROWS DO NOT COUNT. A row is written before the paid work so the stem guard covers
    that window, but the in-flight upload is ALREADY counted by its reservation - counting
    both halved everybody's effective limit (measured: 3 accepted against a cap of 5).
    """
    if not discord_id:
        return 0
    try:
        return sum(1 for r in _rows().values()
                   if str(r.get("uploaded_by") or "") == discord_id and not r.get("pending"))
    except Exception:  # noqa: BLE001
        return 0


def mine(discord_id: str) -> list[dict]:
    """This person's own uploads, newest last — what `/mine` lists.

    FILTERED ON `uploaded_by` AND NOTHING ELSE. Deliberately not on language: the 2026-08-14
    incident hid 103 songs because a list filtered by a language tag that was not set. An upload's
    language is a default nobody was asked for, so it must never be able to hide somebody's own
    song from them.
    """
    if not discord_id:
        return []
    try:
        return [r for r in _rows().values()
                if str(r.get("uploaded_by") or "") == discord_id and not r.get("pending")]
    except Exception:  # noqa: BLE001
        return []


def upload_flags(song1_id: str, song2_id: str) -> tuple[bool, bool]:
    """(beat_is_upload, guest_is_upload) for a pair — what `routes/mix.py` hands the planner.

    Both can be true at once: mixing two of your OWN uploads is a supported case, so nothing here
    may assume one side is always a catalog song.
    """
    return is_upload(song1_id), is_upload(song2_id)
