"""Routes for live steering: turn a typed command into a LiveOp, and serve the beatgrid
the browser schedules on. Stateless — the browser holds live playback state."""

from __future__ import annotations

import json
import logging
import re
import sys
import threading

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.audio.analysis import analysis_path
from app.audio.stems import stem_path
from app.config import settings
from app.models import LiveOp, MixPlan, TrackAnalysis
from app.planner.live import parse_command
from app.planner.suggest import suggest_moves

# workers/ lives at the repo root; put it on the path so we can import the vocal-bus renderer.
_REPO = __import__("pathlib").Path(__file__).resolve().parents[4]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
from workers.live_stems import render_vocal_bus  # noqa: E402

router = APIRouter()
_HEX_ID = re.compile(r"[0-9a-f]{64}")

log = logging.getLogger("promptdj.live")
_S1_STEMS = ("drums", "bass", "other")
# mix_id -> (status, message). Absence + a stored .vocalbus.wav means "ready". In-memory
# is fine for single-worker validation (same pattern as mix.py; shared-eviction backlog note).
_vocal_jobs: dict[str, tuple[str, str | None]] = {}


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


def _vocal_bus_path(mix_id: str):
    return settings.data_dir / f"{mix_id}.vocalbus.wav"


def _mixplan_path(mix_id: str):
    return settings.data_dir / f"{mix_id}.mixplan.json"


def _run_vocal_bus(mix_id: str) -> None:
    """Background worker: load the cached plan, render its vocal layer to a bus WAV."""
    try:
        plan = MixPlan(**json.loads(_mixplan_path(mix_id).read_text()))
        stems = {s: stem_path(plan.song1_id, s) for s in _S1_STEMS}
        s1_voc = stem_path(plan.song1_id, "vocals")
        if s1_voc.exists():
            stems["vocals"] = s1_voc
        render_vocal_bus(plan, stems, stem_path(plan.song2_id, "vocals"), _vocal_bus_path(mix_id))
        _vocal_jobs.pop(mix_id, None)  # readiness now inferred from the stored file
    except Exception:  # noqa: BLE001 — never leak a trace; log so a systematic bug isn't invisible
        log.exception("vocal-bus render failed for %s", mix_id)
        _vocal_bus_path(mix_id).unlink(missing_ok=True)
        _vocal_jobs[mix_id] = ("error", "Couldn't prepare the live vocals.")


@router.get("/live/vocal-bus/{mix_id}")
def live_vocal_bus(mix_id: str):
    """Serve the arranged-vocal bus for a finished mix; render it on first request."""
    if not _HEX_ID.fullmatch(mix_id):
        raise HTTPException(404, "Not found.")
    out = _vocal_bus_path(mix_id)
    if out.exists():
        return FileResponse(out, media_type="audio/wav")
    if not _mixplan_path(mix_id).exists():
        raise HTTPException(409, "Make the mix first so I can prepare the live vocals.")
    status = _vocal_jobs.get(mix_id, (None,))[0]
    if status == "error":
        raise HTTPException(500, "Couldn't prepare the live vocals. Try regenerating the mix.")
    if status != "processing":
        _vocal_jobs[mix_id] = ("processing", None)
        threading.Thread(target=_run_vocal_bus, args=(mix_id,), daemon=True).start()
    return Response(status_code=202)  # browser polls until 200


def _suggestions_path(mix_id: str):
    return settings.data_dir / f"{mix_id}.suggestions.json"


@router.get("/live/suggestions/{mix_id}")
def live_suggestions(mix_id: str):
    """Per-section suggestion chips for a finished mix. One AI call (cached), fallback-safe."""
    if not _HEX_ID.fullmatch(mix_id):
        raise HTTPException(404, "Not found.")
    cache = _suggestions_path(mix_id)
    if cache.exists():
        return {"sections": json.loads(cache.read_text())}
    plan_file = _mixplan_path(mix_id)
    if not plan_file.exists():
        raise HTTPException(409, "Make the mix first so I can suggest moves.")
    plan = MixPlan(**json.loads(plan_file.read_text()))
    a1p = analysis_path(plan.song1_id)
    if not a1p.exists():
        raise HTTPException(409, "Song 1 hasn't been analyzed yet.")
    a1 = TrackAnalysis(status="ready", **json.loads(a1p.read_text()))
    data = [s.model_dump() for s in suggest_moves(a1)]
    cache.write_text(json.dumps(data))
    return {"sections": data}
