"""Upload + serve routes — the app's edge with the outside world.

Handle with care: this accepts files from anyone. Safety properties it must keep:
  - Extension allowlist gate (UX filter; NOT the security control).
  - Streaming size cap: the body is read in chunks and aborted the moment it
    exceeds the cap, so a huge upload can never be fully buffered in memory.
  - Filenames from the client are only ever used as display text / error text,
    never as a filesystem path (storage names files by content hash).
  - Audio ids are validated as strict hex in storage.path_for before any disk
    access, so a crafted id cannot escape the data dir.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.audio.normalize import AudioError, normalize_audio
from app.config import settings
from app.models import Song
from app.storage import path_for, store_wav

router = APIRouter()

_CHUNK = 1024 * 1024  # 1 MB


def _validate_ext(f: UploadFile) -> None:
    ext = Path(f.filename or "").suffix.lower()
    if ext not in settings.allowed_exts:
        raise HTTPException(400, f"'{f.filename}' is not a supported audio file.")


def _save_capped(f: UploadFile, dst: Path) -> None:
    """Stream the upload to ``dst``, aborting if it exceeds the size cap.

    Never materializes the whole body in memory — reads in chunks and stops the
    moment the cumulative size crosses the limit.
    """
    total = 0
    with dst.open("wb") as out:
        while chunk := f.file.read(_CHUNK):
            total += len(chunk)
            if total > settings.max_file_bytes:
                raise HTTPException(400, f"'{f.filename}' is larger than 30 MB.")
            out.write(chunk)


def _process(f: UploadFile) -> Song:
    _validate_ext(f)
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "in"
        _save_capped(f, src)
        out = Path(td) / "out.wav"
        try:
            normalize_audio(src, out)
        except AudioError:
            raise HTTPException(400, f"Could not read '{f.filename}' as audio.")
        song_id = store_wav(out)
    return Song(id=song_id, original_name=f.filename or "song", url=f"/songs/{song_id}/audio")


@router.post("/songs")
def upload_songs(song1: UploadFile, song2: UploadFile):
    """Accept two songs, clean each, and return records the client can play."""
    return {"songs": [_process(song1), _process(song2)]}


@router.get("/songs/{song_id}/audio")
def get_audio(song_id: str):
    """Serve a stored, cleaned WAV by its content id (hex-validated)."""
    p = path_for(song_id)
    if p is None:
        raise HTTPException(404, "Song not found.")
    return FileResponse(p, media_type="audio/wav")
