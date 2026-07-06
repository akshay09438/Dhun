"""Routes for live steering: turn a typed command into a LiveOp, and serve the beatgrid
the browser schedules on. Stateless — the browser holds live playback state."""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.audio.analysis import analysis_path
from app.models import LiveOp
from app.planner.live import parse_command

router = APIRouter()
_HEX_ID = re.compile(r"[0-9a-f]{64}")


class LiveCommand(BaseModel):
    song1_id: str
    song2_id: str
    text: str = ""


class LiveContext(BaseModel):
    bpm: float | None = None
    downbeats: list[float] = []


@router.post("/live/command")
def live_command(cmd: LiveCommand) -> LiveOp:
    for sid in (cmd.song1_id, cmd.song2_id):
        if not _HEX_ID.fullmatch(sid):
            raise HTTPException(404, "Song not found.")
    return parse_command(cmd.text)


@router.get("/live/context/{song1_id}")
def live_context(song1_id: str) -> LiveContext:
    if not _HEX_ID.fullmatch(song1_id):
        raise HTTPException(404, "Not found.")
    p = analysis_path(song1_id)
    if not p.exists():
        raise HTTPException(409, "Song 1 hasn't been analyzed yet.")
    a = json.loads(p.read_text())
    return LiveContext(bpm=a.get("bpm"), downbeats=a.get("downbeats", []))
