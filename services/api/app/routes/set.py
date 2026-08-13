"""Routes for building a continuous DJ SET from up to two two-song mixes.

A "set" is 1 or 2 beat+vocal pairs (V1 caps at two, to keep render time and the finished
WAV small). Each pair is rendered through the SAME /mix pipeline — reusing mix._run_mix,
never a special render path — then the finished mixes are joined by the shipped seam engine
(workers.set_render.assemble_beatmatched_set), which picks each transition from the tempos
either side of it: the beat-matched phrase blend where they agree, a DJ cut where they are too
far apart to blend. A tempo gap never drops a member. Sets are added on the Setup screen only
(there is no live "add a set" during playback), so this route builds the whole set up front and
serves one continuous WAV.

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
from pathlib import Path

import soundfile as sf
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from app import events, failure, renderq
from app.config import settings
from app.models import MixPlan
from app.planner import beat_guest_verse
from app.planner import fence
from app.planner import rule_shuffle
from app.planner.plan import force_tempo_enabled
from app.routes import mix as mixroute
from app.storage import mark_used, maybe_sweep

# workers/ lives at the repo root; mixroute already puts it on the path, but be defensive.
_REPO = Path(__file__).resolve().parents[4]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
from workers.set_render import (  # noqa: E402  (shipped engine — reuse, never copy)
    CUT_RAMP_SECS,
    SR,
    SetRenderError,
    _phrase_seam,
    assemble_beatmatched_set,
    tempo_blendable,
)

router = APIRouter()
log = logging.getLogger("promptdj.set")

# V1 hard cap: how many mixes one continuous SET may hold. Raised 2 -> 5 (2026-08-07) with the auto-rule
# set flow. Kept in ONE named constant on purpose — bigger sets mean longer renders + larger WAVs, so
# this is the single dial to trade reach against cost.
MAX_MIXES_PER_SET = 5

# Bump when the set-ASSEMBLY logic changes, so stale sets aren't re-served while the per-mix renders
# (unaffected, and expensive) stay cached.
#   s2 — the set tempo is reconciled on each MIX's real playing tempo (plan master_bpm) instead of the
#        raw song BPMs; the old way voted with each vocal's ORIGINAL tempo, which the mix has already
#        stretched away, and wrongly dropped joinable sets.
#   s3 — a tempo gap no longer drops a member at all: the seam is CUT instead of blended.
SET_PLAN_VERSION = "s3"

# set_id -> (status, message). "ready" is inferred from the stored WAV + manifest; absent with no
# files is "idle". In-memory is fine for single-worker validation (same pattern as the mix route).
_jobs: dict[str, tuple[str, str | None]] = {}


class SetPairRequest(BaseModel):
    song1_id: str  # the beat / instrumental bed
    song2_id: str  # the vocal source
    rule: int = 1  # explicit RULE (1/3/4). Used by older callers + the dev CLI; IGNORED when the set is
    #                auto-ruled (user_id + set_index below).


class SetRequest(BaseModel):
    sets: list[SetPairRequest]
    # AUTO RULE ASSIGNMENT (2026-08-07): when a stable user_id + the set's 0-based ordinal (set_index)
    # are supplied, EACH mix's rule is auto-assigned by the shared shuffler — rule_for_set(user_id,
    # set_index, position) — where position is the mix's index in the set. Same (user, set_index, pairs)
    # -> same rules -> same set id, so a rebuild hits cache. Without them, each pair's explicit rule wins.
    user_id: str | None = None
    set_index: int | None = None
    # OPS ATTRIBUTION ONLY (2026-08-10) — where the set was built ('web' | 'discord') and a display
    # name if the surface has one. Recorded with the outcome and passed to each member mix; like
    # user_id they are absent from set_id_for/mix_id_for, so they cannot change any cache id or audio.
    source: str | None = None
    user_name: str | None = None


def _resolve_pairs(req: "SetRequest") -> list[tuple[str, str, int]]:
    """The (song1, song2, rule) triples for a set. With user_id + set_index the rule of the mix at each
    position is auto-assigned by the shared shuffler; otherwise each pair's explicit rule is used."""
    if req.user_id is not None and req.set_index is not None:
        # Each position picks from ONLY that beat's usable styles, and the sequence is made no-repeat
        # across positions — so two consecutive mixes in the set never share a style, even when a
        # guest-verse beat (which can't chop) sits next to an echo mix. Supersedes the post-hoc
        # no_chop_rule remap, which could leave two echoes adjacent.
        allowed = [beat_guest_verse.available_rules(p.song1_id) for p in req.sets]
        rules = rule_shuffle.set_rules_for(req.user_id, req.set_index, allowed)
        return [(p.song1_id, p.song2_id, rules[i]) for i, p in enumerate(req.sets)]
    return [(p.song1_id, p.song2_id, beat_guest_verse.no_chop_rule(p.song1_id, p.rule))
            for p in req.sets]


class SetMember(BaseModel):
    """One set's place in the finished line-up."""

    index: int  # 1-based position in the ORIGINAL request order
    song1_id: str
    song2_id: str
    rule: int = 1  # the mixing RULE this mix was made with (auto-assigned by the shuffler, or explicit)
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
    # WHERE THIS IS IN THE LINE - mirrors Mix, so one card handler serves both (2026-08-11).
    stage: str | None = None
    queue_position: int | None = None
    queue_waiting: int | None = None
    queue_eta_secs: int | None = None


def set_id_for(pairs: list[tuple[str, str, int]]) -> str:
    """Content id for a set: the engine + chain + the ordered pairs (each with its chosen RULE). Best-parts
    is the default output now, so ':bestparts' is permanent — it invalidates any pre-best-parts full-length
    set cached under the old key. Identical requests hit cache.

    `SET_PLAN_VERSION` invalidates SETS ONLY when the set-assembly logic changes, leaving the far more
    expensive per-mix renders cached (they are unaffected — a set never re-arranges a mix, it only
    joins finished ones). Bumping mixroute.ENGINE_VERSION for a set-only change would needlessly
    re-render every mix. The per-pair rule tag is omitted for rule 1 so all-Rule-1 set ids stay stable."""
    body = "|".join(f"{a}:{b}" + (f":r{r}" if r != 1 else "") for a, b, r in pairs)
    raw = (f"{mixroute.ENGINE_VERSION}:{mixroute._CHAIN_CONFIG_HASH}"
           f":set:bestparts:{SET_PLAN_VERSION}:{body}").encode()
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
    `frames` (int), `phrase_starts` (secs) and `bpm` (float|None).

    This MIRRORS the engine, so every branch there needs its twin here or the manifest lies about the
    set's length and draws the transition in the wrong place. `test_seam_positions_match_the_rendered_set`
    pins the two together against a real render."""
    y_len = seq[0]["frames"]
    y_ps = list(seq[0]["phrase_starts"])
    seams: list[float] = []
    for i in range(1, len(seq)):
        nxt_len, nxt_ps = seq[i]["frames"], seq[i]["phrase_starts"]
        blendable = tempo_blendable(seq[i - 1].get("bpm"), seq[i].get("bpm"))
        seam = _phrase_seam(y_ps, y_len / SR, nxt_ps, 1) if blendable else None
        if not blendable:  # CUT — mirrors the engine: no overlap, just the declick ramp
            a_len, b_skip, xf, b_len = y_len, 0, int(SR * CUT_RAMP_SECS), nxt_len
        elif seam is None:
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


def _record_set_event(set_id: str, user_id: str | None, status: str,
                      members: list["SetMember"], reason: str | None, duration: float | None,
                      source: str | None = None, user_name: str | None = None,
                      fail: "failure.Failure | None" = None) -> None:
    """Record this set's outcome to the ops event log. NON-FATAL: any failure is swallowed."""
    try:
        extra: dict = {"duration": duration} if duration is not None else {}
        if fail is not None:
            extra["fail_detail"] = fail.detail
            extra["machine"] = fail.machine
        events.record_set(
            settings.data_dir, set_id=set_id, status=status, user_id=user_id,
            members=[m.model_dump() for m in members], fail_reason=reason,
            extra=extra or None,
            fail_kind=(fail.kind if fail is not None else None),
            source=source, user_name=user_name)
    except Exception:  # noqa: BLE001 — telemetry must never break a set
        log.exception("failed to record set event for %s", set_id)


def _run_set(set_id: str, pairs: list[tuple[str, str, int]], user_id: str | None = None,
             source: str | None = None, user_name: str | None = None) -> failure.Failure | None:
    """Background worker: reconcile tempo -> render each kept pair (reuse mix._run_mix) -> crop each to
    its ~180s best-parts highlight (workers.best_parts, post-render) -> join. Best-parts is the DEFAULT
    output. A crop that fails falls back to that mix's full render, so a set never fails on the crop.

    `user_id` (the device tag or Discord account id) is recorded with the set outcome, and passed to
    each member's mix so a mix made inside a set is attributed to the same person (via='set'), along
    with `source` ('web' | 'discord') and `user_name`. None of them ever affects audio."""
    members: list[SetMember] = []  # bound before the try so an early failure still records cleanly
    try:
        maybe_sweep()  # free disk (evict old regenerable renders) before this render-heavy job
        # 1. Work out the tempo each MIX will actually PLAY at. A set joins finished mixes, not raw
        #    songs: inside a mix the vocal is already stretched onto the beat's grid, so the mix plays
        #    at a single tempo — its plan's `master_bpm`. `arrangement_options` is the fence: pure
        #    arithmetic, no AI, no audio, no render, so this stays cheap and pre-render.
        #
        #    A tempo gap NO LONGER drops a member. Nothing is time-stretched at a seam, so a far-off
        #    mix was never a warble risk — only a messy overlap — and the seam engine now CUTS such a
        #    seam instead (workers.set_render.tempo_blendable). Every mixable pair is kept; the tempos
        #    only decide how each seam is joined. A pair the fence can't mix AT ALL is still dropped —
        #    that is a mix-level decline (a real stretch), not a set-level one.
        unmixable: dict[int, str] = {}   # index -> reason; there is no mix to join
        bpm_of: dict[int, float] = {}    # index -> the tempo that mix really plays at
        for i, (s1, s2, _rule) in enumerate(pairs, start=1):  # mixability is the shared foundation — rule-independent
            a1, a2 = mixroute._load_analysis(s1), mixroute._load_analysis(s2)
            # NEVER-DECLINE (founder rule): a far-apart pair is FORCED onto the beat, not dropped for
            # tempo. This gate must honour the same force_tempo flag the single-mix path uses
            # (plan.build_mix_plan) — otherwise a set silently drops a pair that mixes fine on its own
            # (the Innerbloom × Jugni Ji bug). The ONLY mixability decline left is a track with no beat grid.
            opts = (fence.arrangement_options(a1, a2, force_tempo=force_tempo_enabled())
                    if (a1 and a2) else None)
            if not (opts and opts.get("mixable") and opts.get("master_bpm")):
                unmixable[i] = (opts or {}).get("reason") or "This pair couldn't be mixed."
                continue
            bpm_of[i] = opts["master_bpm"]

        # 2. Render each kept pair through the real /mix pipeline. Cache-reuse an already-rendered mix.
        rendered: list[dict] = []  # {"index", "wav", "phrase_starts", "frames", "bpm"}
        for i, (s1, s2, rule) in enumerate(pairs, start=1):
            if i in unmixable:
                members.append(SetMember(
                    index=i, song1_id=s1, song2_id=s2, rule=rule, kept=False, reason=unmixable[i],
                ))
                continue
            _stage(set_id, f"mixing {i} of {len(pairs)}")
            mid = mixroute.mix_id_for(s1, s2, "", 1, rule)   # each song plays under ITS chosen rule
            wav = mixroute._mix_wav(mid)
            if not (wav.exists() and mixroute._plan_path(mid).exists()):
                # synchronous — reuses the shipped pipeline; attributed to this set's device, marked via='set'
                mixroute._run_mix(mid, s1, s2, "", 1, rule, user_id=user_id, via="set",
                                  source=source, user_name=user_name)
            else:
                # REUSED FROM CACHE — so it is still wanted, and the routine age sweep must be told.
                # A set's members are never served directly (only the joined `.set.wav` is), so
                # nothing else stamps them: a set somebody plays every day would keep its own file
                # fresh while the mixes it is built from silently aged out underneath it. They would
                # be re-rendered above rather than lost, but that is a needless 25-30s per member.
                mark_used(wav)
            plan_file = mixroute._plan_path(mid)
            if not plan_file.exists():  # the pipeline declined this pair
                _status, reason = mixroute._jobs.get(mid, ("error", "This pair couldn't be mixed."))
                members.append(SetMember(
                    index=i, song1_id=s1, song2_id=s2, rule=rule, kept=False,
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
                rendered.append({"index": i, "wav": cr["wav"], "bpm": p.master_bpm,
                                 "phrase_starts": cr["phrase_starts"], "frames": cr["frames"]})
            except Exception:  # noqa: BLE001 — a crop failure falls back to the full mix, never fails the set
                log.exception("best-parts crop failed for set %s member %d; using the full mix", set_id, i)
                info = sf.info(str(wav))
                rendered.append({"index": i, "wav": wav, "bpm": p.master_bpm,
                                 "phrase_starts": list(p.out_phrase_starts or []), "frames": info.frames})
            members.append(SetMember(index=i, song1_id=s1, song2_id=s2, rule=rule, kept=True))

        if not rendered:
            reason = "None of these sets could be built — try different songs."
            _jobs[set_id] = ("error", reason)
            _record_set_event(set_id, user_id, "failed", members, reason, None,
                              source=source, user_name=user_name)
            return

        # 3. Join the kept mixes with the shipped seam engine. Each member carries the tempo it plays
        #    at, so the engine picks the transition PER SEAM: the normal beat-matched phrase blend
        #    where the tempos agree, a DJ cut where they are too far apart to blend.
        assemble_beatmatched_set(
            [{"wav": r["wav"], "phrase_starts": r["phrase_starts"], "bpm": r["bpm"]}
             for r in rendered],
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
        _record_set_event(set_id, user_id, "ok", members, None, round(total, 3),
                          source=source, user_name=user_name)
        return None
    except Exception as exc:  # noqa: BLE001 — nothing leaks raw; every failure is CLASSIFIED
        # Same four verdicts as a single mix (app/failure.py). A set is five renders back to
        # back, so it is the MOST likely thing to run the host out of room — and "try different
        # songs" was exactly the wrong advice when that happened.
        fail = failure.classify(exc, data_dir=settings.data_dir, quality=SetRenderError)
        _set_wav(set_id).unlink(missing_ok=True)
        if fail.kind == failure.BUG:
            log.exception("set %s failed (bug)", set_id)
        else:
            log.warning("set %s failed (%s): %s [host %s]",
                        set_id, fail.kind, fail.detail, fail.machine)
        # Same promise as a single mix: while the queue still intends to retry, the user is
        # told it is busy, not that it failed. The gave_up hook writes the real error if the
        # host never frees up.
        _jobs[set_id] = (("processing", mixroute.BUSY_MESSAGE) if fail.is_resources
                         else ("error", fail.user_message))
        _record_set_event(set_id, user_id, "failed", members, fail.user_message, None,
                          source=source, user_name=user_name, fail=fail)
        return fail


def _submit_set(set_id: str, pairs: list[tuple[str, str, int]], req: "SetRequest") -> renderq.Admission:
    """Put the WHOLE set in the same line the single mixes use.

    Granularity matters here. A set is up to five renders, and it already runs them one after
    another on its own thread - so it takes ONE slot, not five. Before this, a set bypassed the
    cap completely: twenty people each building a five-mix set started twenty concurrent renders
    no matter what the mix route's cap said, which made the cap a half-cap and left the most
    render-heavy request in the app as the one thing with no back-pressure at all."""
    outcome: dict[str, failure.Failure] = {}

    def run() -> bool:
        fail = _run_set(set_id, pairs, req.user_id, source=req.source, user_name=req.user_name)
        if fail is None:
            return False
        outcome["fail"] = fail
        return fail.is_resources

    def gave_up() -> None:
        fail = outcome.get("fail")
        _jobs[set_id] = ("error", fail.user_message if fail is not None
                         else "The grinder ran out of room. Give it a minute and try again.")

    return renderq.queue.submit(_queue_key(set_id), run, user_id=req.user_id, on_gave_up=gave_up)


def _stage(set_id: str, text: str) -> None:
    """Say which mix of the set is being built, so a five-pair grind is visibly progressing
    rather than looking hung for two and a half minutes. Never overwrites a finished verdict."""
    if _jobs.get(set_id, (None,))[0] == "processing":
        _jobs[set_id] = ("processing", text)


def _queue_key(set_id: str) -> str:
    """Scoped to the output directory for the same reason as the mix route's: two builds writing
    to different places are different jobs. In production `data_dir` never changes."""
    return f"{settings.data_dir}|{set_id}"


def _with_queue_state(job: SetJob) -> SetJob:
    stats = renderq.queue.stats()
    job.queue_waiting = stats["waiting"]
    position = renderq.queue.position_of(_queue_key(job.set_id))
    if position is not None:
        job.queue_position = position
        job.queue_eta_secs = int(round(renderq.queue.eta_secs(position)))
        job.stage = f"waiting for room - {position} ahead of you"
    elif job.status == "processing":
        job.stage = job.message or "grinding"
    return job


@router.post("/set")
def start_set(req: SetRequest, response: Response) -> SetJob:
    """Start building a set (or return the cached one). Returns at once."""
    if not (1 <= len(req.sets) <= MAX_MIXES_PER_SET):
        raise HTTPException(400, f"A set holds 1 to {MAX_MIXES_PER_SET} mixes.")
    pairs = _resolve_pairs(req)
    for s1, s2, _rule in pairs:
        for sid in (s1, s2):
            if not mixroute._HEX_ID.fullmatch(sid):
                raise HTTPException(404, "Song not found.")

    set_id = set_id_for(pairs)
    ready = _ready(set_id)
    if ready is not None:
        return ready

    # Every pair must be uploaded + analyzed + split, same as /mix (plain-language reason if not).
    for s1, s2, _rule in pairs:
        missing = mixroute._missing_prerequisite(s1, s2)
        if missing is not None:
            raise HTTPException(409, missing)

    if _jobs.get(set_id, (None,))[0] != "processing":
        _jobs[set_id] = ("processing", None)
        admission = _submit_set(set_id, pairs, req)
        if not admission.accepted:
            _jobs.pop(set_id, None)
            raise HTTPException(429, admission.reason or "The grinder is busy. Try again shortly.")

    response.status_code = 202
    return _with_queue_state(SetJob(set_id=set_id, status="processing"))


@router.get("/set/{set_id}")
def set_status(set_id: str) -> SetJob:
    """Report the set state: processing / ready (url + line-up) / error / idle."""
    if not mixroute._HEX_ID.fullmatch(set_id):
        raise HTTPException(404, "Not found.")
    ready = _ready(set_id)
    if ready is not None:
        return ready
    status, message = _jobs.get(set_id, ("idle", None))
    return _with_queue_state(SetJob(set_id=set_id, status=status, message=message))


@router.get("/set/{set_id}/audio")
def get_set_audio(set_id: str):
    """Serve the finished continuous set WAV (id validated before any disk access)."""
    from fastapi.responses import FileResponse

    if not mixroute._HEX_ID.fullmatch(set_id):
        raise HTTPException(404, "Not found.")
    wav = _set_wav(set_id)
    if not wav.exists():
        raise HTTPException(404, "Not found.")
    mark_used(wav)  # last PLAYED, not last rendered — see the same call in routes/mix.py
    return FileResponse(wav, media_type="audio/wav")
