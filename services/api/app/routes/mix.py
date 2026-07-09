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
from app.planner import name as name_planner
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
# m4b.1: contrast (Song 1's vocal in gaps) + subtle sweep + confidence fallbacks.
# m4c.1: energy-arc arrangement — vocal spreads across the whole song (thirds, strong
#        finish) instead of clustering; a span guard rebuilds any clustered plan.
# m4d.1: per-bar beat-lock — each vocal bar re-locked to Song 1's grid (no drift); the
#        referee gains R7 (per-bar ratios in band + bars lock to the grid).
# m5a.1: energy-sync (Phase A) — the arrangement lands Song 2's loudest vocal peak on Song 1's
#        real DROP (fence.energy_drops/vocal_peaks/synced_anchors); no engine/referee change.
# m5b.1: the produced drop — a multi-bar filter+volume BUILD into each drop and a decaying vocal
#        ECHO throw on the climax (render._build_bed/_echo; additive plan fields, referee unchanged).
# m5c.1: catalog vocal detection repaired — 3 vocals were analyzed BEFORE their stem was split
#        (empty vocal_regions -> crude, short, mid-word section chunks); recomputed from the stems
#        (Der Lagi 0->15 regions), so vocals now enter cleanly and last their real sung length.
# m5d.1: both vocals TRADE (Step 1) — Song 1 leads its own substantial sung passages in the gaps
#        (fence.lead_sections; keep the real ones, drop the scraps), never over Song 2 (R1).
# m5e.1: judgment upgrade — KEEP Song 1's vocal LICK into a drop (fence.predrop_licks): a short bit
#        against a drop is the vocal-into-the-drop a DJ never cuts, not a scrap. General to any pair.
# m5f.1: natural hand-off — Song 1's vocal runs a SHORT bound past a drop so its OWN natural
#        phrase-end decay blends into Song 2 (no imposed fade); Song 2 enters full. R1 allows it.
# m5f.2: let the outgoing vocal RING longer (0.3s -> 1.2s) so "…alone…" decays fully under Song 2.
# m5g.1: Step 2 throws — echo the vocal on EVERY safe drop (not just the climax), where the echo
#        tail is clear of the next lead vocal (plan._produce_drops; reuses the render echo engine).
# m5g.2: proper throw — echo only the LAST word or two (render._echo), so it rings out AFTER the
#        line ends instead of smearing echoes across the whole lyric. Echo tail length unchanged.
# m5g.3: per-PHRASE throw — split the vocal on its pauses and echo after EACH sung phrase into its
#        own pause (render._phrase_ends), not once for the whole slice. Tail-past-vocal unchanged.
# m5h.1: movable-master tempo — house-protective shared tempo unblocks far-apart pairs (e.g. Tere
#        Bina). MixPlan.bed_stretch time-stretches Song 1's whole bed to the target; the planner and
#        referee rescale Song 1's grid by the same factor (fence.retimed_analysis). Additive.
# m5i.1: wider per-bar beat-lock grip band (fence.WARP_LO/HI, referee R7) so a vocal whose overall
#        stretch sits near a SAFE_STRETCH edge (Tere Bina, Der Lagi) stays LOCKED to the beat instead
#        of drifting (warp_map was bailing to a single global stretch). Changes the rendered vocal.
# m5j.0: Step 3 Wave 1 — auto-performed stem dynamics. The engine can ride Song 1's bed stems by a
#        per-stem gain envelope; the planner emits a BASS pull-and-slam on every produced drop
#        (MixPlan.stem_moves). Additive: a plan with no stem_moves renders as before.
# m5k.0: Step 3 Wave 2 (first move) — "drop to just the beat" precedes each produced drop's build:
#        bass + melody ("other") are cut for a stretch (drums alone), then bass stays held SILENT
#        (not a fading ramp) through the build too, slamming to full only at the anchor — a real
#        held-breath before the hit (fence.stem_moves_for_drops rework). render.py/validate.py
#        UNCHANGED — same StemMove primitive, only which windows/gains the planner emits.
# m5l.0: Step 3 Wave 2 (2nd move) — "beat-up": the melody ducks (to fence._BEAT_UP_TARGET, matching
#        the live "beat up" command's own sound) for up to 4 bars in the strongest beat-only stretch,
#        so the drums+bass visibly drive (fence.beat_up_moves). render.py/validate.py UNCHANGED.
# m5m.0: Step 3 Wave 2 (3rd/last move) — "breakdown": drums+bass RAMP DOWN to a low simmer for 8 bars
#        in the next-best energetic stretch, leaving the melody exposed, then kick back to full at the
#        window end (fence.breakdown_moves). Completes the four beat moves. render.py/validate.py UNCHANGED.
# m5n.0: Step 4 (1st) — VOCAL CHOPS on the biggest drop. Additive Placement.chop; the engine
#        (render._chop_pattern) re-fires the hook onset over that entry's FIRST bar ("dum-da-ra-dum").
#        Replaces bar 1 only, so the placement's length — and the referee's overlap math — are
#        unchanged; validate.py UNTOUCHED. A plan with no chop flag renders as before.
# m5o.0: HOOK-ON-DROP — the drop plays each curated song's signature hook (app/planner/hooks.py),
#        not the loudest blob; other entries get the setup. plan.py only (additive, safe); no marker
#        -> old loudest pick. (An earlier m5o.0 "phrasing" attempt was reverted the same day.)
ENGINE_VERSION = "m5o.0"

# mix_id -> (status, message). "ready" is inferred from the stored WAV; a mix absent
# here with no stored file is "idle". In-memory is fine for single-worker validation.
_jobs: dict[str, tuple[str, str | None]] = {}


class MixRequest(BaseModel):
    song1_id: str  # the beat / instrumental bed
    song2_id: str  # the vocal source
    prompt: str = ""
    take: int = 1  # regenerate iteration — a new take is a distinct arrangement + cache slot


class MixNameRequest(BaseModel):
    song1_name: str = ""  # Song 1's upload filename (the beat)
    song2_name: str = ""  # Song 2's upload filename (the vocals)
    prompt: str = ""


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
        s1_voc = stem_path(song1_id, "vocals")  # Song 1's own vocal, for the contrast move
        if s1_voc.exists():
            stems["vocals"] = s1_voc
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


@router.post("/mix/name")
def name_mix(req: MixNameRequest) -> dict:
    """Coin a short playful name for a mix from the two song filenames (AI, cached)."""
    key = hashlib.sha256(
        f"{req.song1_name}|{req.song2_name}|{req.prompt}".encode()
    ).hexdigest()
    cache = settings.data_dir / f"{key}.mixname.txt"
    if cache.exists():
        return {"name": cache.read_text(encoding="utf-8")}
    name = name_planner.mix_name(req.song1_name, req.song2_name, req.prompt)
    try:
        cache.write_text(name, encoding="utf-8")
    except OSError:
        pass  # a cache-write failure must not fail the request
    return {"name": name}


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
