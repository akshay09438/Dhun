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


def upload_flags(song1_id: str, song2_id: str) -> tuple[bool, bool]:
    """(beat_is_upload, guest_is_upload) for a pair — what `routes/mix.py` hands the planner.

    Both can be true at once: mixing two of your OWN uploads is a supported case, so nothing here
    may assume one side is always a catalog song.
    """
    return is_upload(song1_id), is_upload(song2_id)
