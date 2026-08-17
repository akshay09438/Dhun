"""Routes for splitting a song into stems (async) and playing each part back.

Splitting a long song in the cloud takes a couple of minutes. Holding a single
web request open that whole time is fragile — browsers and proxies kill
long-running requests (this is what made long songs fail). So the split runs in
a background thread: POST starts it and returns immediately; the client polls
GET for status until the stems are ready.
"""

from __future__ import annotations

import re
import threading

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse

from app.audio.stems import STEMS, separate_stems, stem_path
from app.models import StemSet
from app.planner import uploads
from app.storage import path_for

router = APIRouter()

_HEX_ID = re.compile(r"[0-9a-f]{64}")

# song_id -> "processing" | "error". "ready" is inferred from stored files;
# a song absent from this map with no stored stems is simply "idle" (never
# split). In-memory is fine for the single-worker validation build; a persisted
# job table arrives when we host for real users.
_jobs: dict[str, str] = {}


def _stems_ready(song_id: str) -> bool:
    return all(stem_path(song_id, s).exists() for s in STEMS)


def _stem_urls(song_id: str) -> dict[str, str]:
    return {s: f"/songs/{song_id}/stems/{s}" for s in STEMS}


def _run_split(song_id: str, wav) -> None:
    """Background worker: do the slow cloud split without holding a request."""
    try:
        separate_stems(song_id, wav)
        _jobs.pop(song_id, None)  # done — readiness is now inferred from files
    except Exception:
        _jobs[song_id] = "error"


@router.post("/songs/{song_id}/stems")
def make_stems(song_id: str, response: Response) -> StemSet:
    """Start splitting a song (or report it's already done). Returns at once."""
    wav = path_for(song_id)  # validates hex id + that the song exists
    if wav is None:
        raise HTTPException(404, "Song not found.")

    if _stems_ready(song_id):
        return StemSet(song_id=song_id, status="ready", stems=_stem_urls(song_id))

    if _jobs.get(song_id) != "processing":
        _jobs[song_id] = "processing"
        threading.Thread(target=_run_split, args=(song_id, wav), daemon=True).start()

    response.status_code = 202
    return StemSet(song_id=song_id, status="processing")


@router.get("/songs/{song_id}/stems")
def stems_status(song_id: str) -> StemSet:
    """Report the split's state: processing / ready (with URLs) / error / idle."""
    if not _HEX_ID.fullmatch(song_id):
        raise HTTPException(404, "Not found.")
    if _stems_ready(song_id):
        return StemSet(song_id=song_id, status="ready", stems=_stem_urls(song_id))
    return StemSet(song_id=song_id, status=_jobs.get(song_id, "idle"))


@router.get("/songs/{song_id}/stems/{stem}")
def get_stem(song_id: str, stem: str):
    """Serve one stem by id + name (both validated before any disk access).

    NEVER FOR AN UPLOAD. A stem is the song pulled apart — the isolated vocal of somebody's
    unreleased Suno track, downloadable by anyone who has seen its id. Stem export and
    redistribution is an explicit non-goal in the product profile, and for a catalogue song it is
    at least a commercially released track; for somebody's own upload it is their unreleased work
    being handed to a stranger. Flagged in the 2026-08-17 security review; the founder's call was
    to lock it down.

    Catalogue stems still serve, because the web console's live mixer plays from them.
    """
    if stem not in STEMS or not _HEX_ID.fullmatch(song_id):
        raise HTTPException(404, "Not found.")
    if uploads.is_upload(song_id):
        raise HTTPException(403, "That song's parts are not shared.")
    p = stem_path(song_id, stem)
    if not p.exists():
        raise HTTPException(404, "Not found.")
    return FileResponse(p, media_type="audio/mpeg")
