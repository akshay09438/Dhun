"""Routes for making a mix (async) and playing it back.

Making a mix is slow (decode + time-stretch + render), so it follows the same
start-then-poll pattern as stems and analysis: POST kicks off a background job and
returns at once; GET reports processing/ready/error and, when ready, the plan and
the audio URL. The result is cached by a content id derived from the two songs and
the prompt, so an identical request is free.

Preconditions: both songs must already be uploaded, analyzed, and split into stems
(M3 lays Song 2's vocal over Song 1's drums+bass+other). If something is missing the
route says so in plain language instead of failing opaquely.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.audio.analysis import analysis_path
from app.audio.stems import stem_path
from app.config import settings
from app.models import Mix, MixPlan, TrackAnalysis
from app.planner import validate
from app.planner.plan import MixDeclined, build_mix_plan
from app.storage import path_for

# workers/ lives at the repo root; put it on the path so we can import the engine.
_REPO = Path(__file__).resolve().parents[4]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
from workers.render import render_mix  # noqa: E402

router = APIRouter()
log = logging.getLogger("promptdj.mix")

_HEX_ID = re.compile(r"[0-9a-f]{64}")
_S1_STEMS = ("drums", "bass", "other")

# Bump when the fence rules, the render engine, or the planner prompt change, so a
# cached mix from an older engine is never silently served after we improve it.
# m3.2: beat_breath forced off (the ~2s dead-air gap). m4a.1: full arrangement +
# regenerate. m4a.2: fixed the inverted atempo length math (vocals could overlap).
ENGINE_VERSION = "m4a.2"

# mix_id -> (status, message). "ready" is inferred from the stored WAV; a mix absent
# here with no stored file is "idle". In-memory is fine for single-worker validation.
_jobs: dict[str, tuple[str, str | None]] = {}


class MixRequest(BaseModel):
    song1_id: str  # the beat / instrumental bed
    song2_id: str  # the vocal source
    prompt: str = ""
    take: int = 1  # regenerate iteration — a new take is a distinct arrangement + cache slot


def mix_id_for(song1_id: str, song2_id: str, prompt: str, take: int = 1) -> str:
    raw = f"{ENGINE_VERSION}:{song1_id}:{song2_id}:{prompt}:{take}".encode()
    return hashlib.sha256(raw).hexdigest()


def _mix_wav(mix_id: str) -> Path:
    return settings.data_dir / f"{mix_id}.mix.wav"


def _plan_path(mix_id: str) -> Path:
    return settings.data_dir / f"{mix_id}.mixplan.json"


def _load_analysis(song_id: str) -> TrackAnalysis | None:
    p = analysis_path(song_id)
    if not p.exists():
        return None
    return TrackAnalysis(status="ready", **json.loads(p.read_text()))


def _missing_prerequisite(song1_id: str, song2_id: str) -> str | None:
    """A plain-language reason a mix can't start yet, or None if all is ready."""
    for label, sid in (("Song 1", song1_id), ("Song 2", song2_id)):
        if path_for(sid) is None:
            return f"{label} hasn't been uploaded."
        if _load_analysis(sid) is None:
            return f"{label} hasn't been analyzed yet."
    if not all(stem_path(song1_id, s).exists() for s in _S1_STEMS):
        return "Song 1 hasn't been split into parts yet."
    if not stem_path(song2_id, "vocals").exists():
        return "Song 2 hasn't been split into parts yet."
    return None


def _ready(mix_id: str) -> Mix | None:
    wav, plan_file = _mix_wav(mix_id), _plan_path(mix_id)
    if not (wav.exists() and plan_file.exists()):
        return None
    plan = MixPlan(**json.loads(plan_file.read_text()))
    return Mix(mix_id=mix_id, status="ready", url=f"/mix/{mix_id}/audio",
               plan=plan, message=plan.notes)


def _run_mix(mix_id: str, song1_id: str, song2_id: str, prompt: str, take: int) -> None:
    """Background worker: plan -> validate -> render -> validate the audio."""
    try:
        a1, a2 = _load_analysis(song1_id), _load_analysis(song2_id)
        plan = build_mix_plan(mix_id, a1, a2, prompt, take=take)
        validate.assert_plan(plan, a1, a2)

        stems = {s: stem_path(song1_id, s) for s in _S1_STEMS}
        render_mix(plan, stems, stem_path(song2_id, "vocals"), _mix_wav(mix_id))
        validate.assert_render(_mix_wav(mix_id))

        _plan_path(mix_id).write_text(plan.model_dump_json())
        _jobs.pop(mix_id, None)  # readiness now inferred from the stored files
    except MixDeclined as e:
        _jobs[mix_id] = ("error", e.reason)
    except validate.ValidationError as e:
        _mix_wav(mix_id).unlink(missing_ok=True)
        _jobs[mix_id] = ("error", f"The mix didn't pass the quality check: {e}")
    except Exception:  # noqa: BLE001 — never leak a raw trace to the user...
        log.exception("mix render failed for %s", mix_id)  # ...but do log it, so a systematic bug isn't invisible
        _mix_wav(mix_id).unlink(missing_ok=True)
        _jobs[mix_id] = ("error", "Couldn't build this mix. Try another pair or regenerate.")


@router.post("/mix")
def start_mix(req: MixRequest, response: Response) -> Mix:
    """Start making a mix (or return the cached one). Returns at once."""
    for sid in (req.song1_id, req.song2_id):
        if not _HEX_ID.fullmatch(sid):
            raise HTTPException(404, "Song not found.")

    mix_id = mix_id_for(req.song1_id, req.song2_id, req.prompt, req.take)
    ready = _ready(mix_id)
    if ready is not None:
        return ready

    missing = _missing_prerequisite(req.song1_id, req.song2_id)
    if missing is not None:
        raise HTTPException(409, missing)

    if _jobs.get(mix_id, (None,))[0] != "processing":
        _jobs[mix_id] = ("processing", None)
        threading.Thread(
            target=_run_mix,
            args=(mix_id, req.song1_id, req.song2_id, req.prompt, req.take),
            daemon=True,
        ).start()

    response.status_code = 202
    return Mix(mix_id=mix_id, status="processing")


@router.get("/mix/{mix_id}")
def mix_status(mix_id: str) -> Mix:
    """Report the mix state: processing / ready (plan + url) / error / idle."""
    if not _HEX_ID.fullmatch(mix_id):
        raise HTTPException(404, "Not found.")
    ready = _ready(mix_id)
    if ready is not None:
        return ready
    status, message = _jobs.get(mix_id, ("idle", None))
    return Mix(mix_id=mix_id, status=status, message=message)


@router.get("/mix/{mix_id}/audio")
def get_mix_audio(mix_id: str):
    """Serve the finished mix WAV (id validated before any disk access)."""
    if not _HEX_ID.fullmatch(mix_id):
        raise HTTPException(404, "Not found.")
    wav = _mix_wav(mix_id)
    if not wav.exists():
        raise HTTPException(404, "Not found.")
    return FileResponse(wav, media_type="audio/wav")
