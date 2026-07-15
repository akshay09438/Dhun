"""Routes for building a continuous DJ SET from up to two two-song mixes.

A "set" is 1 or 2 beat+vocal pairs (V1 caps at two, to keep render time and the finished
WAV small). Each pair is rendered through the SAME /mix pipeline — reusing mix._run_mix,
never a special render path — then the finished mixes are joined by the shipped beat-matched
seam engine (workers.set_render.assemble_beatmatched_set), after reconciling every song to
ONE master tempo and declining any outlier (set_tempo_plan). Sets are added on the Setup
screen only (there is no live "add a set" during playback), so this route builds the whole
set up front and serves one continuous WAV.

Async start-then-poll, exactly like /mix: POST kicks off a background job and returns at once;
GET reports processing / ready (url + the per-set line-up) / error. Cached by a content id
derived from the ordered pairs, so an identical request is free.

Reuses, never duplicates, the engine: this route is thin orchestration over `mix.*` and
`workers.set_render.*`. The by-ear sibling is the dev CLI `scripts/build_set.py`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
import threading
from pathlib import Path

import soundfile as sf
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from app.config import settings
from app.models import MixPlan
from app.routes import mix as mixroute

# workers/ lives at the repo root; mixroute already puts it on the path, but be defensive.
_REPO = Path(__file__).resolve().parents[4]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
from workers.set_render import (  # noqa: E402  (shipped engine — reuse, never copy)
    SR,
    SetRenderError,
    _phrase_seam,
    assemble_beatmatched_set,
    set_tempo_plan,
)

router = APIRouter()
log = logging.getLogger("promptdj.set")

# V1 hard cap: a session holds 1 or 2 sets. Kept small on purpose (render time + file size).
MAX_SETS = 2

# set_id -> (status, message). "ready" is inferred from the stored WAV + manifest; absent with no
# files is "idle". In-memory is fine for single-worker validation (same pattern as the mix route).
_jobs: dict[str, tuple[str, str | None]] = {}


class SetPairRequest(BaseModel):
    song1_id: str  # the beat / instrumental bed
    song2_id: str  # the vocal source


class SetRequest(BaseModel):
    sets: list[SetPairRequest]


class SetMember(BaseModel):
    """One set's place in the finished line-up."""

    index: int  # 1-based position in the ORIGINAL request order
    song1_id: str
    song2_id: str
    kept: bool  # False when declined (too far from the set tempo, or the pair couldn't be mixed)
    seam_at: float | None = None  # seconds into the set where this member's crossfade begins
    reason: str | None = None  # why it was dropped, in plain language (when kept is False)


class SetJob(BaseModel):
    set_id: str
    status: str  # processing | ready | error | idle
    url: str | None = None
    members: list[SetMember] = []
    duration: float | None = None  # total set length in seconds
    message: str | None = None


def set_id_for(pairs: list[tuple[str, str]]) -> str:
    """Content id for a set: the engine + chain + the ordered pairs. Best-parts is the default output
    now, so ':bestparts' is permanent — it invalidates any pre-best-parts full-length set cached under
    the old key. Identical requests hit cache."""
    body = "|".join(f"{a}:{b}" for a, b in pairs)
    raw = f"{mixroute.ENGINE_VERSION}:{mixroute._CHAIN_CONFIG_HASH}:set:bestparts:{body}".encode()
    return hashlib.sha256(raw).hexdigest()


def _set_wav(set_id: str) -> Path:
    return settings.data_dir / f"{set_id}.set.wav"


def _set_manifest(set_id: str) -> Path:
    return settings.data_dir / f"{set_id}.setmanifest.json"


def _ready(set_id: str) -> SetJob | None:
    wav, manifest = _set_wav(set_id), _set_manifest(set_id)
    if not (wav.exists() and manifest.exists()):
        return None
    return SetJob(**json.loads(manifest.read_text()))


def _seam_positions(seq: list[dict]) -> tuple[list[float], float]:
    """Seam times (seconds into the finished set) + total length, mirroring
    assemble_beatmatched_set's sample accounting via the shipped `_phrase_seam` — so we can label
    where each transition lands without re-analyzing the rendered set. `seq` items carry
    `frames` (int) and `phrase_starts` (secs)."""
    y_len = seq[0]["frames"]
    y_ps = list(seq[0]["phrase_starts"])
    seams: list[float] = []
    for i in range(1, len(seq)):
        nxt_len, nxt_ps = seq[i]["frames"], seq[i]["phrase_starts"]
        seam = _phrase_seam(y_ps, y_len / SR, nxt_ps, 1)
        if seam is None:
            a_len, b_skip, xf, b_len = y_len, 0, int(SR * 4.0), nxt_len
        else:
            a_end, b_start, xf_t = seam
            a_len, b_skip, xf = (
                int(round(a_end * SR)),
                int(round(b_start * SR)),
                int(round(xf_t * SR)),
            )
            b_len = nxt_len - b_skip
        xf = max(0, min(xf, a_len // 2, b_len // 2))
        b_out_start = a_len - xf
        seams.append(b_out_start / SR)
        y_len = a_len + b_len - xf
        y_ps = [
            (b_out_start + (p * SR - b_skip)) / SR
            for p in nxt_ps
            if p * SR >= b_skip - 1e-6
        ]
    return seams, y_len / SR


def _run_set(set_id: str, pairs: list[tuple[str, str]]) -> None:
    """Background worker: reconcile tempo -> render each kept pair (reuse mix._run_mix) -> crop each to
    its ~180s best-parts highlight (workers.best_parts, post-render) -> join. Best-parts is the DEFAULT
    output. A crop that fails falls back to that mix's full render, so a set never fails on the crop."""
    try:
        # 1. ONE tempo across the whole set; decline outliers (shipped set_tempo_plan).
        songs: list[dict] = []
        seen: set[str] = set()
        for s1, s2 in pairs:
            for sid in (s1, s2):
                if sid not in seen:
                    seen.add(sid)
                    a = mixroute._load_analysis(sid)
                    songs.append({"id": sid, "bpm": (a.bpm if a else 0.0) or 0.0})
        declined_ids = {d["id"] for d in set_tempo_plan(songs)["declined"]}

        # 2. Render each pair through the real /mix pipeline (a pair is kept only if BOTH its
        #    songs survived the tempo reconciliation). Cache-reuse an already-rendered mix.
        members: list[SetMember] = []
        rendered: list[dict] = []  # {"index", "wav", "phrase_starts", "frames"}
        for i, (s1, s2) in enumerate(pairs, start=1):
            declined = [sid for sid in (s1, s2) if sid in declined_ids]
            if declined:
                members.append(SetMember(
                    index=i, song1_id=s1, song2_id=s2, kept=False,
                    reason="This pair is too far from the set's tempo to blend, so it sits out.",
                ))
                continue
            mid = mixroute.mix_id_for(s1, s2, "", 1)
            wav = mixroute._mix_wav(mid)
            if not (wav.exists() and mixroute._plan_path(mid).exists()):
                mixroute._run_mix(mid, s1, s2, "", 1)  # synchronous — reuses the shipped pipeline
            plan_file = mixroute._plan_path(mid)
            if not plan_file.exists():  # the pipeline declined this pair
                _status, reason = mixroute._jobs.get(mid, ("error", "This pair couldn't be mixed."))
                members.append(SetMember(
                    index=i, song1_id=s1, song2_id=s2, kept=False,
                    reason=reason or "This pair couldn't be mixed.",
                ))
                continue
            p = MixPlan(**json.loads(plan_file.read_text()))
            # Best-parts is the default: crop each finished mix to its ~180s highlight + arc before the
            # join. Post-render only (workers.best_parts) — reads the FULL cached mix.wav, never re-arranges.
            from workers import best_parts as bp
            s1_voc = mixroute.stem_path(s1, "vocals")
            try:
                cr = bp.crop_and_arc(
                    p, wav, mixroute.stem_path(s2, "vocals"),
                    s1_voc if s1_voc.exists() else None,
                    settings.data_dir / f"{set_id}_{i}.bestparts.wav",
                )
                rendered.append({"index": i, "wav": cr["wav"],
                                 "phrase_starts": cr["phrase_starts"], "frames": cr["frames"]})
            except Exception:  # noqa: BLE001 — a crop failure falls back to the full mix, never fails the set
                log.exception("best-parts crop failed for set %s member %d; using the full mix", set_id, i)
                info = sf.info(str(wav))
                rendered.append({"index": i, "wav": wav,
                                 "phrase_starts": list(p.out_phrase_starts or []), "frames": info.frames})
            members.append(SetMember(index=i, song1_id=s1, song2_id=s2, kept=True))

        if not rendered:
            _jobs[set_id] = ("error", "None of these sets could be built — try different songs.")
            return

        # 3. Join the kept mixes with the shipped beat-matched seam engine.
        assemble_beatmatched_set(
            [{"wav": r["wav"], "phrase_starts": r["phrase_starts"]} for r in rendered],
            _set_wav(set_id),
        )

        # 4. Label where each transition lands, and the total length (arithmetic, no re-analysis).
        seams, total = _seam_positions(rendered)
        kept_indices = [r["index"] for r in rendered]
        by_index = {m.index: m for m in members}
        for k, idx in enumerate(kept_indices):
            by_index[idx].seam_at = None if k == 0 else round(seams[k - 1], 3)

        # 5. Persist the manifest; readiness is now inferred from the stored files.
        done = SetJob(
            set_id=set_id, status="ready", url=f"/set/{set_id}/audio",
            members=members, duration=round(total, 3),
        )
        _set_manifest(set_id).write_text(done.model_dump_json())
        _jobs.pop(set_id, None)
    except SetRenderError as e:
        _jobs[set_id] = ("error", f"Couldn't join these mixes into a set: {e}")
    except Exception:  # noqa: BLE001 — never leak a raw trace; log so a systematic bug isn't invisible
        log.exception("set build failed for %s", set_id)
        _set_wav(set_id).unlink(missing_ok=True)
        _jobs[set_id] = ("error", "Couldn't build this set. Try different songs.")


@router.post("/set")
def start_set(req: SetRequest, response: Response) -> SetJob:
    """Start building a set (or return the cached one). Returns at once."""
    if not (1 <= len(req.sets) <= MAX_SETS):
        raise HTTPException(400, f"A set holds 1 to {MAX_SETS} mixes.")
    pairs = [(p.song1_id, p.song2_id) for p in req.sets]
    for s1, s2 in pairs:
        for sid in (s1, s2):
            if not mixroute._HEX_ID.fullmatch(sid):
                raise HTTPException(404, "Song not found.")

    set_id = set_id_for(pairs)
    ready = _ready(set_id)
    if ready is not None:
        return ready

    # Every pair must be uploaded + analyzed + split, same as /mix (plain-language reason if not).
    for s1, s2 in pairs:
        missing = mixroute._missing_prerequisite(s1, s2)
        if missing is not None:
            raise HTTPException(409, missing)

    if _jobs.get(set_id, (None,))[0] != "processing":
        _jobs[set_id] = ("processing", None)
        threading.Thread(target=_run_set, args=(set_id, pairs), daemon=True).start()

    response.status_code = 202
    return SetJob(set_id=set_id, status="processing")


@router.get("/set/{set_id}")
def set_status(set_id: str) -> SetJob:
    """Report the set state: processing / ready (url + line-up) / error / idle."""
    if not mixroute._HEX_ID.fullmatch(set_id):
        raise HTTPException(404, "Not found.")
    ready = _ready(set_id)
    if ready is not None:
        return ready
    status, message = _jobs.get(set_id, ("idle", None))
    return SetJob(set_id=set_id, status=status, message=message)


@router.get("/set/{set_id}/audio")
def get_set_audio(set_id: str):
    """Serve the finished continuous set WAV (id validated before any disk access)."""
    from fastapi.responses import FileResponse

    if not mixroute._HEX_ID.fullmatch(set_id):
        raise HTTPException(404, "Not found.")
    wav = _set_wav(set_id)
    if not wav.exists():
        raise HTTPException(404, "Not found.")
    return FileResponse(wav, media_type="audio/wav")
