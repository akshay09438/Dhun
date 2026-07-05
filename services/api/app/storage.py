"""Content-addressed storage for cleaned audio.

Handle with care: this reads and writes files on disk. Two safety properties
it must always keep:
  1. Files are named by a server-computed content hash — NEVER by a
     user-supplied filename. This neutralizes filename/path attacks at the source.
  2. `path_for` only ever returns a path inside the data dir, and only for a
     strict 64-char lowercase-hex id — so a crafted id cannot escape the dir.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

from app.config import settings

# A stored id is exactly a sha256 hexdigest: 64 lowercase hex chars, nothing else.
# fullmatch (not $) so a trailing newline can never sneak past the anchor.
_HEX_ID = re.compile(r"[0-9a-f]{64}")


def store_wav(wav_path: Path) -> str:
    """Copy a cleaned WAV into the data dir under its content hash; return the id.

    Idempotent: re-storing identical content is a no-op (same hash, same file),
    so retries / double-submits are safe and never duplicate.
    """
    data = wav_path.read_bytes()
    song_id = hashlib.sha256(data).hexdigest()
    dst = settings.data_dir / f"{song_id}.wav"
    if not dst.exists():
        shutil.copyfile(wav_path, dst)
    return song_id


def path_for(song_id: str) -> Path | None:
    """Return the stored path for a valid, existing id, else None.

    Rejects any id that is not a clean 64-char hex string — which blocks path
    traversal (``..``, ``/``, ``\\``, absolute paths) by construction.
    """
    if not _HEX_ID.fullmatch(song_id):
        return None
    p = settings.data_dir / f"{song_id}.wav"
    return p if p.exists() else None
