"""Routes for analyzing a song (async) and reading the result.

Analysis includes a cloud call (~1–2 min on long songs), so it follows the
same start-then-poll pattern as stem splitting: POST kicks off a background
job and returns at once; GET reports processing/ready/error and, when ready,
the full TrackAnalysis.
"""

from __future__ import annotations

import json
import re
import threading

from fastapi import APIRouter, HTTPException, Response

from app.audio.analysis import analysis_is_current, analysis_path, analyze_track
from app.models import TrackAnalysis
from app.storage import path_for

router = APIRouter()

_HEX_ID = re.compile(r"[0-9a-f]{64}")

# song_id -> "processing" | "error" (readiness = cached analysis file exists)
_jobs: dict[str, str] = {}


def _load_ready(song_id: str) -> TrackAnalysis | None:
    # Ready only when BOTH halves are fresh — a stale LOCAL version (an improved analyzer) re-derives
    # on next access (free, no cloud) rather than serving the old blobby analysis forever.
    if not analysis_is_current(song_id):
        return None
    data = json.loads(analysis_path(song_id).read_text())
    return TrackAnalysis(status="ready", **data)


def _run_analysis(song_id: str, wav) -> None:
    try:
        analyze_track(song_id, wav)
        _jobs.pop(song_id, None)
    except Exception:
        _jobs[song_id] = "error"


@router.post("/songs/{song_id}/analysis")
def start_analysis(song_id: str, response: Response) -> TrackAnalysis:
    """Start analyzing a song (or return the cached result). Returns at once."""
    wav = path_for(song_id)
    if wav is None:
        raise HTTPException(404, "Song not found.")

    ready = _load_ready(song_id)
    if ready is not None:
        return ready

    if _jobs.get(song_id) != "processing":
        _jobs[song_id] = "processing"
        threading.Thread(target=_run_analysis, args=(song_id, wav), daemon=True).start()

    response.status_code = 202
    return TrackAnalysis(song_id=song_id, status="processing")


@router.get("/songs/{song_id}/analysis")
def analysis_status(song_id: str) -> TrackAnalysis:
    """Report the analysis state: processing / ready (with data) / error / idle."""
    if not _HEX_ID.fullmatch(song_id):
        raise HTTPException(404, "Not found.")
    ready = _load_ready(song_id)
    if ready is not None:
        return ready
    return TrackAnalysis(song_id=song_id, status=_jobs.get(song_id, "idle"))
