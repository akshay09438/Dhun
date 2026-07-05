"""Routes for splitting a song into stems and playing each part back."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.audio.stems import STEMS, SeparationError, separate_stems, stem_path
from app.models import StemSet
from app.storage import path_for

router = APIRouter()

_HEX_ID = re.compile(r"[0-9a-f]{64}")


@router.post("/songs/{song_id}/stems")
def make_stems(song_id: str) -> StemSet:
    """Split a stored song into vocals/drums/bass/other (cached)."""
    wav = path_for(song_id)  # also validates the id is clean hex
    if wav is None:
        raise HTTPException(404, "Song not found.")
    try:
        separate_stems(song_id, wav)
    except SeparationError:
        raise HTTPException(502, "Could not split this song right now. Please try again.")
    return StemSet(
        song_id=song_id,
        stems={s: f"/songs/{song_id}/stems/{s}" for s in STEMS},
    )


@router.get("/songs/{song_id}/stems/{stem}")
def get_stem(song_id: str, stem: str):
    """Serve one stem by id + name (both validated before any disk access)."""
    if stem not in STEMS or not _HEX_ID.fullmatch(song_id):
        raise HTTPException(404, "Not found.")
    p = stem_path(song_id, stem)
    if not p.exists():
        raise HTTPException(404, "Not found.")
    return FileResponse(p, media_type="audio/mpeg")
