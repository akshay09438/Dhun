"""Routes for live steering: turn a typed command into a LiveOp, and serve the beatgrid
the browser schedules on. Stateless — the browser holds live playback state."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.audio import pitch
from app.audio.analysis import analysis_path
from app.audio.stems import stem_path
from app.config import settings
from app.models import LiveOp, MixPlan, TrackAnalysis
from app.planner import validate
from app.planner.keys import resolve_key_shift
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
# mix_id -> (status, message). Absence + a stored .livevocal.wav means "ready". In-memory
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
    # ".livearr": the live Vocals part is the ARRANGED, per-bar beat-locked vocal — the SAME
    # vocal as the Download (via render_vocal_bus), so the Play screen matches the finished mix.
    # (Superseded the ".livevocal" continuous bus, which drifted/wandered; the new name drops it.)
    return settings.data_dir / f"{mix_id}.livearr.wav"


def _mixplan_path(mix_id: str):
    return settings.data_dir / f"{mix_id}.mixplan.json"


def _run_vocal_bus(mix_id: str) -> None:
    """Background worker: render the arrangement's vocal layer (Song 2 placed + beat-locked +
    Song 1 contrast) as the live bus — the same vocal as the Download, so Play matches the mix."""
    final = _vocal_bus_path(mix_id)
    # Render here, then atomically publish. Keep the .wav extension on the temp so soundfile
    # can still infer the format from it (it writes by extension) -> {mix}.livearr.tmp.wav.
    tmp = final.with_name(final.stem + ".tmp" + final.suffix)
    try:
        _raw_plan = json.loads(_mixplan_path(mix_id).read_text())
        plan = MixPlan(**_raw_plan)
        # Match the Download's key: if this pair was key-matched, use the SAME shifted vocal (cached by
        # the mix render) so the live bus is NEVER a silently un-shifted "key-matched" vocal. Deterministic
        # per pair; a PitchError is caught below and surfaces as a visible "couldn't prepare" decline.
        from app.routes.mix import key_match_enabled  # local import avoids a route<->route import cycle
        orig_s2_voc = stem_path(plan.song2_id, "vocals")
        s2_voc = orig_s2_voc
        if key_match_enabled():
            # Use the shift the DOWNLOAD actually shipped (persisted on the plan). Re-deciding it here
            # would desync Play from the Download whenever a transient shift failure sent one of them
            # down the native-key fallback. Older plans lack the field (0) -> re-derive as before.
            # A PERSISTED 0 means "the Download shipped the native key" and must be honoured — so key
            # off the field's PRESENCE, not its value. Only a pre-m19k1 plan (no field) re-derives.
            if "shipped_key_shift" in _raw_plan:
                shift = int(_raw_plan["shipped_key_shift"] or 0)
            else:
                a1 = TrackAnalysis(status="ready", **json.loads(analysis_path(plan.song1_id).read_text()))
                a2 = TrackAnalysis(status="ready", **json.loads(analysis_path(plan.song2_id).read_text()))
                shift, _why = resolve_key_shift(a1, a2)
            if shift != 0:
                # Mirror mix.py's NEVER-REFUSE fallback exactly (both are deterministic on the same
                # files, so Play always matches the Download's key): a shift that can't be produced
                # or verified falls back to the NATIVE-key vocal instead of failing the live bus.
                try:
                    s2_voc = pitch.shifted_vocal(plan.song2_id, orig_s2_voc, shift)
                    validate.assert_key_shift(orig_s2_voc, s2_voc, shift)   # K1 — same referee as the Download
                except (pitch.PitchError, validate.ValidationError) as e:
                    log.warning("live %s key-shift %+d st could not be verified (%s) -> NATIVE key",
                                mix_id, shift, e)
                    s2_voc = orig_s2_voc
        song1_stems = {"vocals": stem_path(plan.song1_id, "vocals")}  # for the contrast answer
        render_vocal_bus(plan, song1_stems, s2_voc, tmp)
        # Publish atomically: the SERVED path only ever appears fully written, so a poll can
        # never catch it mid-render (which served a growing file -> Content-Length overflow ->
        # the browser couldn't decode it -> the Play button never became ready).
        os.replace(tmp, final)
        _vocal_jobs.pop(mix_id, None)  # readiness now inferred from the stored file
    except Exception:  # noqa: BLE001 — never leak a trace; log so a systematic bug isn't invisible
        log.exception("live-vocal render failed for %s", mix_id)
        tmp.unlink(missing_ok=True)  # never leave a half-written temp behind
        final.unlink(missing_ok=True)
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
