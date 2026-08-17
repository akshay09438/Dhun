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

import dataclasses
import hashlib
import json
import logging
import re
import sys
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import events, failure, renderq, storage
from app.audio import chroma, pitch
from app.audio.analysis import analysis_path
from app.audio.stems import stem_path
from app.config import settings
from app.models import Mix, MixPlan, TrackAnalysis, VocalChainConfig, chain_config_hash
from app.planner import validate
from app.planner import anomaly
from app.planner import beatgrid
from app.planner import hooks
from app.planner import instrumental_beats
from app.planner import uploads
from app.planner import name as name_planner
from app.planner import beat_guest_verse
from app.planner import rule_shuffle
from app.planner import window
from app.planner.keys import CAP_SEMITONES, resolve_key_shift
from app.planner.plan import (MixDeclined, build_mix_plan, effect_pool_enabled,
                              exit_fade_enabled, finish_beat_vocal_enabled,
                              finish_sentences_enabled, force_tempo_enabled, rule4_enabled)
from app.storage import mark_used, maybe_sweep, path_for

# workers/ lives at the repo root; put it on the path so we can import the engine.
_REPO = Path(__file__).resolve().parents[4]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
from workers.render import RenderError, render_mix  # noqa: E402
# RenderError is imported READ-ONLY, purely so a failure can be classified as a quality
# verdict about this pair rather than an unexplained crash. workers/render.py is a dangerous
# surface and is NOT modified.

router = APIRouter()
log = logging.getLogger("promptdj.mix")

_HEX_ID = re.compile(r"[0-9a-f]{64}")
_S1_STEMS = ("drums", "bass", "other")
KEY_SHIFT_CAP = CAP_SEMITONES  # HARD PITCH RULE (single source of truth): the empirical chroma matcher may NEVER
#                              exceed the label-rule cap keys.CAP_SEMITONES (±2, the CDJ-3000 / founder ceiling).
#                              Was ±3 (2026-08-07) — that looser fallback let a flagged song ship a +3 st shift
#                              (Silence×With You, 2026-08-10); tightened to ±2 so no path can over-shift. See RULEBOOK.md.

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
# m6.0:  PHASE 0 (Slice 1) — the AI arrangement engine is gated OFF by default (plan.USE_AI_ARRANGEMENT),
#        so every mix now uses the loved RULES arrangement; camelot_fit is attached + logged (never
#        gated); and the vocal-chain config hash joins the cache id (mix_id_for) so tuning-week dial
#        changes invalidate cleanly. Bumped so cached AI-path mixes re-plan on the rules path. Stems +
#        analysis are keyed by song_id, NOT this version, so the bump triggers ZERO Replicate calls.
# m6.1: SECTION MAP dropped from the decision path (diagnostic A.1 — ~23% precise, uncorrelated with
#        energy clarity). fence.py removes the section-map fallbacks from vocal-slice selection; drops
#        stay energy-first (already were), hooks hand-marked, cropping off. NOTE: this is a PLANNER
#        change, so ENGINE_VERSION (the mix cache) is the right lever — NOT LOCAL_ANALYSIS_VERSION (the
#        analysis output — energy/regions/sections — is UNCHANGED). The removed fallback fires only on
#        empty vocal_regions (no catalog song), so catalog mixes re-render byte-identical. Zero Replicate.
# m6.2: LOUDEST-SLICE HOOK FALLBACK removed (Task 1) — a vocal donor with NO hand-marked hook no longer
#        lands its loudest slice on the drop (a guess measured ~28s off); it uses its vocal regions as-is
#        in song order. ⚠️ ALL FIVE shipped catalog vocal donors are currently hookless (only the 3 older
#        Anchor Point songs in hooks.py are marked, none of them in the catalog), so EVERY catalog vocal
#        mix changed — VERIFIED on Father Ocean × Der Lagi (entries 2 & 3 swap which Der Lagi section they
#        sing; the drop is unchanged). The bump is warranted (real movement), not caution: without it the
#        app would serve stale pre-Task-1 audio. PLANNER change → ENGINE_VERSION, not analysis. Zero
#        Replicate (stems/analysis keyed by song_id). Marking each donor's hook (Task 2) restores the
#        stable with-hook path per song.
# m6.3: CATALOG HOOKS MARKED — all five shipped vocal donors (Don't Start Now, Der Lagi, Tujhe Bhula
#        Diya, With You, Tere Bina) now have hand-marked hooks (app/planner/hooks.py; founder-marked by
#        ear via scripts/mark_drops.html, drops_hooks_marks.csv, 2026-07-11). The with-hook path (R1)
#        lands each donor's real hook on the drop instead of the m6.2 no-guess "regions in song order",
#        so EVERY catalog vocal mix re-renders. This is the stable baseline Task 1/2 were driving toward;
#        Der Lagi's hook specifically UN-MOVES the tuning baseline Task 1 shifted (drift log 37th entry).
#        PLANNER change → ENGINE_VERSION (mix cache), NOT analysis. Zero Replicate (stems/analysis keyed
#        by song_id).
# m6.4: BEAT-LOCK truncates instead of BAILING on a glitch bar (fence.warp_map). It used to discard the
#        whole per-bar warp when any bar's local ratio fell out of band, dropping to a single global
#        stretch — which un-snapped the ENTRY of a hand-marked hook that starts mid-bar (the Tujhe
#        late-by-~2-beats bug). Now it locks every bar UP TO the glitch and rides the rest (the un-lockable
#        glitch + tail) on one trailing global segment — the last segment, which R7 doesn't grid-check, so
#        no interior boundary drifts. The entry + body snap to the beat; only the un-lockable tail
#        global-stretches. Changes every mix whose vocal slice had a glitch bar (previously bailing);
#        clean-grid slices render identically. PLANNER change → ENGINE_VERSION. render.py/validate.py
#        UNTOUCHED (segments stay in the referee's warp band; the tail uses R7's last-segment exemption).
#        Zero Replicate (stems/analysis keyed by song_id).
# m6.7: instrumental-only beats (planner) — a beat that is really a vocal song (e.g. Merrygo, a D&B
#        remix of Khuda Jaane) no longer weaves in Song 1's OWN vocal, which was overlapping Song 2's
#        lyrics. Changes only mixes whose Song 1 is marked instrumental-only; all other pairs render
#        identically. PLANNER change → ENGINE_VERSION (invalidates the stale cached Merrygo mixes).
#        render.py/validate.py UNTOUCHED. Zero Replicate (stems/analysis keyed by song_id).
# m6.8: hand-marked main drops (planner) — a beat with no detectable energy drop (e.g. the Merrygo
#        D&B beat) can have its main drop marked by ear (app/planner/main_drops.py); the vocal's hook
#        then lands on it instead of spreading blindly. Changes only mixes whose Song 1 has a marked
#        drop; all others render identically. render.py/validate.py UNTOUCHED. Zero Replicate.
# DERIVED from the effect-pool flag so turning the pool on auto-invalidates the pool-OFF mix + set caches
# (both fold ENGINE_VERSION into their id). OFF => "m6.11" (byte-identical to pre-pool; existing caches
# stay valid). ON => "m6.11+m7pool" (fresh ids => every mix re-renders WITH the pool). Bump the BASE only
# for a non-pool engine/plan change.
# BUMPED m6.11 -> m9band15 (2026-08-06): the ±11%->±15% tempo-band widen changes mix output, so every
# mix + set must re-render fresh (no stale ±11% cache is ever served). Unique-per-behaviour, as required.
_ENGINE_VERSION_BASE = "m12match"  # empirical chroma key-match fallback (2026-08-07): when key labels are
#                                   untrusted, the vocal shift is measured from audio (AutoMashUpper) instead
#                                   of skipped -> a formerly un-shifted clash now key-matches. Bumped from
#                                   "m11rule" so those stale un-shifted mixes re-render under the matcher.
#                                   (Forced tempo auto-match is gated OFF here until the validate.py approval.)

# KEY MATCHING (Change ②, 2026-08-06): shift Song 2's vocal into a compatible key BEFORE the mix
# (verified + cached upstream in app/audio/pitch.py; referee K1 re-checks the chroma). INSTANT OFF-SWITCH:
# set False -> no shift, ENGINE_VERSION drops the +m10key tag -> byte-identical to the pre-key-match engine.
_KEY_MATCH_ENABLED = True


def key_match_enabled() -> bool:
    """Whether key-matching is live. Folded into ENGINE_VERSION, so flipping it auto-invalidates the
    mix/set caches (every mix re-renders with — or without — the key shift)."""
    return _KEY_MATCH_ENABLED


ENGINE_VERSION = (_ENGINE_VERSION_BASE
                  + ("+m8echo" if rule4_enabled() else "")           # Rule 4: gap-sized echo + reverb bed
                  + ("+m10key" if key_match_enabled() else "")       # Change ②: key-matching (pitch-shift)
                  + ("+m12force" if force_tempo_enabled() else "")   # forced tempo auto-match (never decline)
                  + ("+m7pool" if effect_pool_enabled() else "")     # effect pool (superseded, stays off)
                  + "+m13vrb"                                        # vocal-rich beats: guest verse + R1 clamp + no-chop
                  + ("+m14fade" if exit_fade_enabled() else "")      # musical exit-fade on each vocal line's tail
                  + ("+m15phrase" if finish_sentences_enabled() else "")   # phrase-safe slice ends (finish the sentence)
                  + ("+m16beat" if finish_beat_vocal_enabled() else "")   # beat vocal finishes its phrase + graceful fade
                  + "+m17marks6"   # wired 6 new songs' hand-marked hooks/drops (2026-08-10) -> re-render so they land
                  + "+m18cap2"   # pitch cap hardened ±3 -> ±2 everywhere (2026-08-10) -> re-render any >2-shifted mix
                  + "+m19k1")   # K1 referee re-ruled (f0-first) + never-refuse native-key fallback -> fresh ids so
#                                 previously-declined pairs (wrongly failed by the chroma misread) re-render
#          slices so the held-out window is FULL of vocal, not holes (founder: "more parts").
#         (NOT m6.9: that string was already burned by a reverted experiment, so its stale renders
#          would have been served as cache hits. A version string must be unique PER BEHAVIOUR.)

# Phase 0 (turned ON 2026-07-14): the founder-approved vocal chain, tuned dial-by-dial by ear during the
# tuning week and confirmed on the full-set A/B. The model default stays enabled=False (the disabled path
# is byte-identical to m6.0 — the golden gate + a fallback), so the shipped sound is opted in HERE, in one
# place, rather than by flipping the model default. All non-tuned stages keep their model defaults; pitch
# stays 0 (Slice 2d still parked). Character: bright, forward, punchy, clean, natural.
SHIPPED_CHAIN = VocalChainConfig(
    enabled=True,
    saturate_wet=0.3,       # dial 1 — grit / warmth
    presence_gain_db=4.0,   # dial 2 — brightness / cut
    reverb_wet=0.08,        # dial 3 — space (dry / close)
    duck_depth_db=1.0,      # dial 4 — subtle ducking
    compress_ratio=2.0,     # dial 5 — light compression
    highpass_hz=120,        # dial 6 — cleanest low-cut
    deess_intensity=0.4,    # dial 7 — balanced de-ess (= model default, explicit for provenance)
)

# The vocal-chain config hash is folded into the mix cache id, so turning the chain ON here yields a fresh
# hash -> fresh mix ids -> every mix re-renders WITH the chain (old chain-off cached mixes are never served).
_CHAIN_CONFIG_HASH = chain_config_hash(SHIPPED_CHAIN)

# mix_id -> (status, message). "ready" is inferred from the stored WAV; a mix absent
# here with no stored file is "idle". In-memory is fine for single-worker validation.
_jobs: dict[str, tuple[str, str | None]] = {}


class MixRequest(BaseModel):
    song1_id: str  # the beat / instrumental bed
    song2_id: str  # the vocal source
    prompt: str = ""
    take: int = 1  # regenerate iteration — a new take is a distinct arrangement + cache slot
    rule: int = 1  # explicit RULE (1 = simple, 3 = chop & repeat, 4 = echo). Used by the set path + tests;
    #                IGNORED when user_id + generation drive the shuffler (below).
    # AUTO RULE ASSIGNMENT (2026-08-07): the manual rule buttons are gone. When a stable per-browser
    # user_id and a 0-based generation index are supplied, the rule is auto-assigned by the DETERMINISTIC
    # shuffler (rule_shuffle.rule_for) and the generation index is the take (cache slot). Same
    # (user, pair, generation) -> same rule -> same mix id, forever — so a regenerate hits cache.
    user_id: str | None = None
    generation: int | None = None
    # OPS ATTRIBUTION ONLY (2026-08-10). Where this mix was made ('web' | 'discord') and a display
    # name if the surface has one (Discord gives a username; the web app has no login yet). Like
    # user_id these are RECORDED and nothing else — deliberately absent from mix_id_for, so adding
    # them cannot change a cache id, re-render a cached mix, or alter a single sample of audio.
    source: str | None = None
    user_name: str | None = None


def _resolve_rule_take(req: "MixRequest") -> tuple[int, int]:
    """The effective (rule, take) for a request. With a user_id + generation index the rule is
    auto-assigned by the deterministic shuffler and the 0-based generation is the take (cache slot);
    otherwise the explicit rule/take are used (the set path + tests). This changes only WHERE `rule`
    comes from — the cache-id formula (mix_id_for) is untouched, so existing cached mixes stay valid."""
    if req.user_id is not None and req.generation is not None:
        gen = max(0, req.generation)
        # Pick from ONLY the beat's usable styles up front, so the effective rule never repeats
        # back-to-back (a guest-verse beat has {simple, echo} → strict alternation). This SUPERSEDES the
        # old rule_for + no_chop_rule remap, which collapsed chop→echo AFTER the shuffle and produced two
        # echoes in a row. A normal beat's set is {1,3,4}, so its rule is byte-identical to before.
        rule = rule_shuffle.rule_for_available(
            req.user_id, req.song1_id, req.song2_id, gen, beat_guest_verse.available_rules(req.song1_id))
        return rule, gen + 1
    return beat_guest_verse.no_chop_rule(req.song1_id, req.rule), req.take


class MixNameRequest(BaseModel):
    song1_name: str = ""  # Song 1's upload filename (the beat)
    song2_name: str = ""  # Song 2's upload filename (the vocals)
    prompt: str = ""


def mix_id_for(song1_id: str, song2_id: str, prompt: str, take: int = 1, rule: int = 1) -> str:
    # `rule` is in the cache id so Rule 3 (chop & repeat) never collides with the Rule-1 render of the
    # same pair. Default rule=1 keeps every existing cached mix id byte-identical (…:{take} with no suffix).
    rule_tag = "" if rule == 1 else f":r{rule}"
    raw = f"{ENGINE_VERSION}:{_CHAIN_CONFIG_HASH}:{song1_id}:{song2_id}:{prompt}:{take}{rule_tag}".encode()
    return hashlib.sha256(raw).hexdigest()


def _mix_wav(mix_id: str) -> Path:
    return settings.data_dir / f"{mix_id}.mix.wav"


def _bestparts_wav(mix_id: str) -> Path:
    return settings.data_dir / f"{mix_id}.bestparts.wav"


def _build_bestparts(plan: MixPlan, mix_id: str) -> Path | None:
    """Crop the FULL mix to its ~180s best-parts highlight + arcs using the in-memory `plan`
    (workers.best_parts, post-render — never re-arranges, never touches render.py). Returns the
    derivative path, or None if the crop can't be produced. Built during _run_mix BEFORE the plan is
    persisted, so a mix that reads as 'ready' always already has its highlight (no read-before-crop race)."""
    try:
        from workers import best_parts as bp
        s1_voc = stem_path(plan.song1_id, "vocals")
        r = bp.crop_and_arc(plan, _mix_wav(mix_id), stem_path(plan.song2_id, "vocals"),
                            s1_voc if s1_voc.exists() else None, _bestparts_wav(mix_id))
        return Path(r["wav"])
    except Exception:  # noqa: BLE001 — a crop failure must never break the mix; fall back to the full render
        log.exception("best-parts crop failed for %s; serving the full mix", mix_id)
        return None


def _ensure_bestparts(mix_id: str) -> Path:
    """The best-parts highlight served to the user by default. Normally built eagerly in _run_mix; this
    rebuilds it lazily from the persisted plan if it's ever missing (e.g. an older cached mix). The full
    mix.wav stays canonical (Regenerate re-renders it; the set route crops it). Falls back to the full
    mix so playback never breaks."""
    bp_wav = _bestparts_wav(mix_id)
    if bp_wav.exists():
        return bp_wav
    full, plan_file = _mix_wav(mix_id), _plan_path(mix_id)
    if not (full.exists() and plan_file.exists()):
        return full
    plan = MixPlan(**json.loads(plan_file.read_text()))
    return _build_bestparts(plan, mix_id) or full


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


def _attach_set_grid(plan: MixPlan, a1: TrackAnalysis, wav: Path) -> None:
    """Stamp the mix's own beat grid (output-time downbeats + phrase boundaries) and length onto the
    plan, so a later set-join reads them as arithmetic instead of re-analyzing the rendered WAV. The
    grid is Song 1's cached grid retimed to the master tempo and cropped to the window (window.output_grid
    — the referee's own derivation); the length comes from the WAV header (metadata, not audio analysis).
    Best-effort: a header read that fails leaves mix_duration None but keeps the (load-bearing) grid."""
    g = window.output_grid(a1, plan.master_bpm, plan.bed_stretch, plan.window)
    plan.out_downbeats = list(g.downbeats)
    plan.out_phrase_starts = list(g.phrase_starts)
    try:
        import soundfile as sf
        info = sf.info(str(wav))
        plan.mix_duration = round(info.frames / info.samplerate, 4) if info.samplerate else None
    except Exception:  # noqa: BLE001 — a missing/odd WAV header must never fail the mix
        plan.mix_duration = None


def _render_rule3(plan: MixPlan, mix_id: str, song1_id: str, song2_id: str,
                  a1: TrackAnalysis, a2: TrackAnalysis, s1_voc: Path, s2_voc: Path,
                  stems: dict[str, Path]) -> None:
    """Rule 3 (chop & repeat): plan the chops on the SHARED, already tempo/key-matched grid, then render
    via the Rule-3 engine instead of render_mix. The base `plan` (built + validated upstream) carries the
    BPM+key foundation and the grid/metadata for serving; here we mark it rule=3 and swap the render.

    The chop hook is the curated `hooks.py` marker (or Rule-1's first vocal slice as a fallback). The
    beat song's own vocal is KEPT and the chops trade in its gaps; a vocal-heavy/short beat (too little
    gap room) drops the beat vocal so the chops have space."""
    from app.planner import rule3 as r3
    from app.planner.hooks import hook_for
    from workers.rule3 import envelope, render_rule3

    dur = a1.beats[-1] if a1.beats else 0.0
    venv, sr_env = envelope(s2_voc)                        # the (already key-shifted) vocal envelope
    hook = hook_for(song2_id) or (
        plan.placements[0].vocal_src if plan.placements else (a2.beats[0], a2.beats[0] + 18.0))
    try:
        a_unit, c_unit = r3.pick_blocks(hook, list(a2.downbeats), a2.bpm, venv, sr_env)
    except ValueError as e:
        raise MixDeclined(f"Rule 3 couldn't find a clear hook line to chop ({e}).")

    keep = s1_voc.exists()
    benv = envelope(s1_voc)[0] if keep else None
    gaps = r3.instrumental_gaps(benv, sr_env, dur, keep_beat_vocal=keep)
    if keep and (not gaps or sum(g1 - g0 for g0, g1 in gaps) < 0.35 * dur):
        keep, gaps = False, r3.instrumental_gaps(None, sr_env, dur, keep_beat_vocal=False)
    hits = r3.schedule(list(a1.downbeats), gaps, a_unit, c_unit, dur)
    if not hits:
        raise MixDeclined("Rule 3 found no on-beat room to place the chops for this pair.")

    r3plan = r3.Rule3Plan(a_unit=a_unit, c_unit=c_unit, hits=hits, keep_beat_vocal=keep)
    render_rule3(r3plan, list(a1.downbeats), a1.bpm, stems,
                 settings.data_dir / f"{song1_id}.wav", s2_voc, _mix_wav(mix_id))
    plan.rule = 3
    plan.notes = f"Rule 3 — chop & repeat: the hook fires as {len(hits)} on-beat chops, trading in the beat's gaps."


def _record_mix_event(mix_id: str, song1_id: str, song2_id: str, take: int, rule: int,
                      user_id: str | None, via: str, status: str,
                      anomalies: list, fail_reason: str | None, plan: MixPlan | None,
                      source: str | None = None, user_name: str | None = None,
                      fail: failure.Failure | None = None,
                      timings: dict[str, float] | None = None) -> None:
    """Record this mix's outcome to the ops event log (the dashboard's memory). NON-FATAL by
    construction: any failure here is logged and swallowed — recording must never break a mix."""
    try:
        from app.routes.library import song_names
        names = song_names([song1_id, song2_id], data_dir=settings.data_dir)
        anoms = [dataclasses.asdict(a) for a in (anomalies or [])]
        extra: dict = {}
        if plan is not None:
            extra = {"tempo_forced": plan.tempo_forced, "master_bpm": plan.master_bpm,
                     "vocal_stretch": plan.vocal_stretch,
                     "camelot": plan.camelot_fit.model_dump() if plan.camelot_fit else None}
        if fail is not None:
            # The engine's own words + how much room the host actually had. Recorded so a
            # misclassified failure stays visible in the data instead of being baked in.
            extra["fail_detail"] = fail.detail
            extra["machine"] = fail.machine
        if timings:
            # Where this render's seconds went, per stage. Recorded on every mix, so "which
            # stage got slower" is answerable about real traffic instead of a synthetic run.
            extra["timings"] = timings
        events.record_mix(
            settings.data_dir, mix_id=mix_id, status=status, user_id=user_id, via=via,
            song1_id=song1_id, song2_id=song2_id,
            song1_name=names.get(song1_id), song2_name=names.get(song2_id),
            rule=rule, take=take, anomalies=anoms, fail_reason=fail_reason, extra=extra,
            fail_kind=(fail.kind if fail is not None else None),
            source=source, user_name=user_name)
    except Exception:  # noqa: BLE001 — telemetry is best-effort; a mix must never fail on it
        log.exception("failed to record mix event for %s", mix_id)


def _run_mix(mix_id: str, song1_id: str, song2_id: str, prompt: str, take: int, rule: int = 1,
             user_id: str | None = None, via: str = "single",
             source: str | None = None, user_name: str | None = None) -> failure.Failure | None:
    """Background worker: plan -> validate -> render (Rule 1/4 or Rule 3) -> validate the audio.

    Returns None on success, or the classified Failure - which the queue reads to decide whether
    this is worth another go. (It only ever is when the HOST ran out of room.)

    `user_id` (the per-browser device tag, or a real Discord account id), `via` ('single' | 'set'),
    `source` ('web' | 'discord') and `user_name` (a display name where the surface has one) are
    recorded with the outcome for the ops dashboard; none of them affect the mix or its cache id."""
    anomalies: list = []  # bound up-front so a failure before the scan still records cleanly
    try:
        maybe_sweep()  # free disk (evict old regenerable renders) before this render-heavy job
        stages = _Stages(mix_id)
        stages.mark("studying the two songs")
        a1, a2 = _load_analysis(song1_id), _load_analysis(song2_id)
        # Beat-sensor health: every on-beat move trusts Song 1's downbeats, so surface a mis-detected
        # grid instead of silently locking to the wrong beats (founder rule 2026-08-07). Informational
        # for now — logged per mix; a LOW grid is where an off-beat feel would come from.
        grid_health: dict[str, dict] = {}
        for _tag, _an in (("song1/beat", a1), ("song2/vocal", a2)):
            _gh = beatgrid.grid_health(_an.bpm, _an.downbeats)
            grid_health[_tag] = _gh
            (log.warning if not _gh["ok"] else log.info)("mix %s beat-grid %s: %s", mix_id, _tag, _gh)
        # `rule` selects the arrangement style ON TOP of the shared BPM+key foundation build_mix_plan does:
        # 1 = dry simple mix, 3 = chop & repeat (rendered below), 4 = echo + reverb (build_mix_plan gates it).
        stages.mark("planning the arrangement")
        # WHOSE SONG IS THIS? Read off the catalogue rows, not assumed. When either side is an
        # upload the catalog song's own singer stands down — a guest who uploaded their vocal wants
        # to hear THEIR track, and a Suno beat brings its own singer that would collide with a
        # catalog vocal. Both can be true at once: mixing two of your own uploads is supported.
        # (This call site is the whole point of the flags — they shipped defaulting to False with
        # no caller on 2026-08-17, so until now they had never once run. Pinned by
        # tests/test_uploads_wired.py.)
        beat_is_upload, guest_is_upload = uploads.upload_flags(song1_id, song2_id)
        if beat_is_upload or guest_is_upload:
            log.info("mix %s uploads: beat=%s guest=%s -> the beat plays instrumental",
                     mix_id, beat_is_upload, guest_is_upload)
        plan = build_mix_plan(mix_id, a1, a2, prompt, take=take, chain=SHIPPED_CHAIN, rule=rule,
                              guest_is_upload=guest_is_upload, beat_is_upload=beat_is_upload)
        # Phase 0 (T1.2): log the key-fit on every render — informational only, never gated. Lets us
        # look at the log and find how many "good" pairs were quietly key-clashing.
        cf = plan.camelot_fit
        log.info("mix %s source=%s camelot_fit=%s", mix_id, plan.source,
                 cf.model_dump() if cf else None)
        validate.assert_plan(plan, a1, a2)

        # KEY MATCHING (Change ②): shift Song 2's vocal into a compatible key BEFORE the mix, via the
        # verified + cached Signalsmith helper. resolve_key_shift applies the confidence gate (a flagged
        # or low-confidence key -> shift 0, logged). The K1 referee then re-derives the shifted vocal's
        # chroma independently. Any failure -> a VISIBLE decline, never a silently un-shifted "key-matched"
        # mix (PitchError below; K1 raises ValidationError, handled with the other quality failures).
        stages.mark("matching the key")
        orig_s2_voc = stem_path(song2_id, "vocals")
        s2_voc = orig_s2_voc
        shift, why = resolve_key_shift(a1, a2) if key_match_enabled() else (0, "key-match disabled")
        # EMPIRICAL fallback (AutoMashUpper, Davies et al. 2013): when the key LABELS can't be trusted
        # (flagged / low-confidence / no compatible label -> resolve_key_shift returns a "key-skip"),
        # MEASURE the best shift from the audio chroma instead of shipping an un-shifted clash. Beat
        # harmony = Song 1's bass+other; vocal region = its hook/first sung stretch. NEVER declines;
        # capped at ±KEY_SHIFT_CAP (formant-preserved). Best-effort: any failure leaves the vocal
        # un-shifted (exactly today's behaviour), never crashes the mix.
        if key_match_enabled() and shift == 0 and why.startswith("key-skip"):
            try:
                region = hooks.hook_for(song2_id) or (a2.vocal_regions[0] if a2.vocal_regions else None)
                beat_harmony = [stem_path(song1_id, "bass"), stem_path(song1_id, "other")]
                e_shift, e_score, e_base = chroma.empirical_shift(
                    beat_harmony, orig_s2_voc, cap=KEY_SHIFT_CAP, vocal_region=region)
                if e_shift != 0:
                    shift = e_shift
                    why = (f"chroma-empirical {e_shift:+d} st (cos {e_score:.3f} vs {e_base:.3f} unshifted; "
                           f"labels untrusted -> measured from audio)")
            except Exception:  # noqa: BLE001 — a matcher failure must never fail the mix; fall back to unshifted
                log.exception("empirical chroma key-match failed for %s; leaving vocal unshifted", mix_id)
        log.info("mix %s key-shift %+d st (%s)", mix_id, shift, why)

        # BACKEND ANOMALY REPORT (founder rule 2026-08-07, point 2): the mix is STILL generated from
        # whatever we've got — forced tempo, a shaky grid, an audio-measured key — but surface each
        # degraded/unexpected condition (what happened + what to do) so a real upload's data problems
        # are visible on the backend instead of silent. Reporting only; never changes the mix.
        anomalies = anomaly.scan(grid_health=grid_health, tempo_forced=plan.tempo_forced,
                                 vocal_stretch=plan.vocal_stretch, key_why=why,
                                 beat_vocal_coverage=instrumental_beats.vocal_coverage(a1),
                                 beat_bpm=float(getattr(a1, "bpm", 0.0) or 0.0),
                                 vocal_bpm=float(getattr(a2, "bpm", 0.0) or 0.0))
        for _a in anomalies:
            (log.warning if _a.severity == "warn" else log.info)(anomaly.format_line(mix_id, _a))

        if shift != 0:
            # NEVER-REFUSE (founder rule 2026-08-10): if the shift can't be produced or verified,
            # ship the vocal in its NATIVE key instead of declining — a mix ALWAYS comes out. The
            # native key is the safest deliverable when the shift is unprovable (a blind/failed shift
            # could land the wrong direction and sound worse). Logged + surfaced as an ops anomaly.
            try:
                s2_voc = pitch.shifted_vocal(song2_id, orig_s2_voc, shift)
                validate.assert_key_shift(orig_s2_voc, s2_voc, shift)        # K1 — independent correctness
            except (pitch.PitchError, validate.ValidationError) as e:
                log.warning("mix %s key-shift %+d st could not be verified (%s) -> shipping NATIVE key",
                            mix_id, shift, e)
                anomalies.append(anomaly.Anomaly(
                    code="key_shift_fallback",
                    detail=f"the {shift:+d} st key shift could not be produced/verified: {e}",
                    action="shipped the vocal in its NATIVE key (never-refuse); ear-check this pair's key",
                    severity="warn"))
                s2_voc = orig_s2_voc
                shift = 0
        plan.shipped_key_shift = int(shift)  # record what ACTUALLY shipped, so Play reproduces it exactly

        stems = {s: stem_path(song1_id, s) for s in _S1_STEMS}
        s1_voc = stem_path(song1_id, "vocals")  # Song 1's own vocal (contrast lead / the Rule-3 trade gaps)
        if s1_voc.exists():
            stems["vocals"] = s1_voc

        stages.mark("mixing it down")
        if rule == 3:
            _render_rule3(plan, mix_id, song1_id, song2_id, a1, a2, s1_voc, s2_voc, stems)
        else:
            render_mix(plan, stems, s2_voc, _mix_wav(mix_id))
        stages.mark("checking it sounds right")
        validate.assert_render(_mix_wav(mix_id))  # the quality guard runs on EVERY rule's output

        # 3.1 (set transitions): stamp the mix's OWN beat grid + length onto the plan before caching it,
        # so joining mixes into a set is arithmetic over the plans — never a re-analysis of the WAV.
        # Grid is derived from Song 1's cached grid + tempo/window (the SAME grid the referee used), not
        # from the audio we just wrote; the length is read from the WAV header (metadata, not analysis).
        _attach_set_grid(plan, a1, _mix_wav(mix_id))

        # Best-parts highlight is COMMON to every rule (founder 2026-08-06: the same crop + set-transition
        # treatment Rule 1 uses must apply to Rule 3 and Rule 4 too — only the best parts come down, not the
        # full song). Built off the shared plan grid, so it works on any rule's rendered WAV.
        stages.mark("trimming to the best part")
        _build_bestparts(plan, mix_id)
        _plan_path(mix_id).write_text(plan.model_dump_json())  # persisting the plan, so 'ready' implies it exists
        # A previously-rendered live bus for this mix_id may hold a DIFFERENT key (it is evictable and
        # re-rendered independently). Drop it so Play can never serve a stale bus whose key disagrees
        # with the Download we just wrote. (Adversarial review finding 2.)
        try:
            (settings.data_dir / f"{mix_id}.livearr.wav").unlink(missing_ok=True)
        except OSError:  # a stale bus we cannot remove must never fail the mix
            log.warning("could not clear the stale live bus for %s", mix_id)
        _jobs.pop(mix_id, None)  # readiness now inferred from the stored files
        timings = stages.finish()
        log.info("mix %s stage timings %s", mix_id, timings)
        _record_mix_event(mix_id, song1_id, song2_id, take, rule, user_id, via, "ok",
                          anomalies, None, plan, source=source, user_name=user_name,
                          timings=timings)
        return None
    except Exception as exc:  # noqa: BLE001 — nothing leaks raw; every failure is CLASSIFIED below
        # ONE handler, four verdicts (app/failure.py). The four this replaced all ended in a
        # sentence, and three of those sentences were indistinguishable in `events.db` — so a
        # starved machine and a genuinely bad pair counted as the same thing. They no longer do.
        fail = failure.classify(
            exc, data_dir=settings.data_dir,
            declined=MixDeclined,
            quality=(validate.ValidationError, pitch.PitchError, RenderError))
        # A half-written render must never be served, cached, or joined into a set. Safe on a
        # decline too, where nothing was written in the first place.
        _mix_wav(mix_id).unlink(missing_ok=True)
        _bestparts_wav(mix_id).unlink(missing_ok=True)
        # Only a genuine BUG earns a stack trace. A referee verdict or a full disk is expected
        # behaviour, and a traceback for each one just buries the real bugs.
        if fail.kind == failure.BUG:
            log.exception("mix %s failed (bug)", mix_id)
        else:
            log.warning("mix %s failed (%s): %s [host %s]",
                        mix_id, fail.kind, fail.detail, fail.machine)
        # A resource failure stays "processing" and says BUSY, because the queue is about to
        # put it back in the line. Marking it failed here and then quietly retrying would show
        # the user an error for a mix that is, in fact, still coming. (If the retries run out,
        # the queue's on_gave_up hook writes the real error - see _submit_render.)
        _jobs[mix_id] = (("processing", BUSY_MESSAGE) if fail.is_resources
                         else ("error", fail.user_message))
        _record_mix_event(mix_id, song1_id, song2_id, take, rule, user_id, via, "failed",
                          anomalies, fail.user_message, None,
                          source=source, user_name=user_name, fail=fail)
        return fail


# What a person reads while their grind is waiting for room to free up. Deliberately NOT
# "try another pair" - a full host says nothing whatever about the songs they picked, and
# that sentence sent people off changing their choice to fix someone else's problem.
BUSY_MESSAGE = "The grinder is slammed right now - you're in the line."


def _queue_key(mix_id: str) -> str:
    """How the queue identifies this render. Scoped to the OUTPUT DIRECTORY as well as the mix
    id, because two renders writing to different places are genuinely different jobs even when
    the recipe is identical. In production `data_dir` never changes, so this is exactly the mix
    id and the "two people asked for the same mix" dedupe is unaffected."""
    return f"{settings.data_dir}|{mix_id}"


def _submit_render(mix_id: str, req: "MixRequest", take: int, rule: int) -> renderq.Admission:
    """Hand this render to the bounded queue instead of starting a thread and hoping.

    The queue retries a render that died for lack of room; `gave_up` is how the user finally
    hears about it if the host simply never has room. Without that hook a mix would sit on
    "you're in the line" forever, which is a worse lie than the error it replaced."""
    outcome: dict[str, failure.Failure] = {}

    def run() -> bool:
        fail = _run_mix(mix_id, req.song1_id, req.song2_id, req.prompt, take, rule, req.user_id,
                        source=req.source, user_name=req.user_name)
        if fail is None:
            return False
        outcome["fail"] = fail
        return fail.is_resources

    def gave_up() -> None:
        fail = outcome.get("fail")
        _jobs[mix_id] = ("error", fail.user_message if fail is not None
                         else "The grinder ran out of room. Give it a minute and try again.")

    return renderq.queue.submit(_queue_key(mix_id), run, user_id=req.user_id, on_gave_up=gave_up)


def _stage(mix_id: str, text: str) -> None:
    """Say what is happening RIGHT NOW, so the card has something true to show. Only ever
    updates a job that is still processing - it must never overwrite a finished verdict."""
    if _jobs.get(mix_id, (None,))[0] == "processing":
        _jobs[mix_id] = ("processing", text)


class _Stages:
    """Where a render's 25-30 seconds actually goes.

    Doubles as the card's progress feed and as the profile, because a profile that only exists
    when someone remembers to run a script is a profile that is always out of date. Every mix
    records its own per-stage timings into the event log, so "which stage got slower" is a
    question the ops dashboard can answer about REAL traffic rather than a synthetic run.

    Costs one monotonic clock read per stage. Nothing here can fail a mix."""

    def __init__(self, mix_id: str) -> None:
        self.mix_id = mix_id
        self.timings: dict[str, float] = {}
        self._current: str | None = None
        self._since = time.monotonic()
        self._started = self._since

    def mark(self, text: str) -> None:
        now = time.monotonic()
        if self._current is not None:
            self.timings[self._current] = round(
                self.timings.get(self._current, 0.0) + (now - self._since), 3)
        self._current, self._since = text, now
        _stage(self.mix_id, text)

    def finish(self) -> dict[str, float]:
        self.mark("done")
        self.timings.pop("done", None)
        self.timings["total"] = round(time.monotonic() - self._started, 3)
        return self.timings


def _with_queue_state(mix: Mix) -> Mix:
    """Attach where this mix is in the line, so the card can say "6th, about 3 minutes"."""
    stats = renderq.queue.stats()
    mix.queue_waiting = stats["waiting"]
    position = renderq.queue.position_of(_queue_key(mix.mix_id))
    if position is not None:
        mix.queue_position = position
        mix.queue_eta_secs = int(round(renderq.queue.eta_secs(position)))
        mix.stage = f"waiting for room - {position} ahead of you"
    elif mix.status == "processing":
        mix.stage = mix.message or "grinding"
    return mix


@router.get("/queue")
def queue_state() -> dict:
    """How busy the grinder is right now: how many are rendering, how many are waiting, and the
    cap. Counts only - no song ids, no user ids, nothing about anybody's content - so it needs
    no token and can be read by the bot, the dev dashboard, or a load test while it runs.

    Without this, the cap holding is unobservable: after the fact everything just looks finished."""
    return renderq.queue.stats()


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

    rule, take = _resolve_rule_take(req)
    mix_id = mix_id_for(req.song1_id, req.song2_id, req.prompt, take, rule)
    ready = _ready(mix_id)
    if ready is not None:
        return ready

    missing = _missing_prerequisite(req.song1_id, req.song2_id)
    if missing is not None:
        raise HTTPException(409, missing)

    if _jobs.get(mix_id, (None,))[0] != "processing":
        _jobs[mix_id] = ("processing", None)
        admission = _submit_render(mix_id, req, take, rule)
        if not admission.accepted:
            # The line is genuinely too long. Say so in plain words rather than accepting the
            # job and letting it rot, and clear the processing flag so a later try can start.
            _jobs.pop(mix_id, None)
            raise HTTPException(429, admission.reason or "The grinder is busy. Try again shortly.")

    response.status_code = 202
    return _with_queue_state(Mix(mix_id=mix_id, status="processing"))


@router.get("/mix/{mix_id}")
def mix_status(mix_id: str) -> Mix:
    """Report the mix state: processing / ready (plan + url) / error / idle."""
    if not _HEX_ID.fullmatch(mix_id):
        raise HTTPException(404, "Not found.")
    ready = _ready(mix_id)
    if ready is not None:
        return ready
    status, message = _jobs.get(mix_id, ("idle", None))
    return _with_queue_state(Mix(mix_id=mix_id, status=status, message=message))


@router.post("/keep/{render_id}")
def keep_render(render_id: str):
    """Protect a render from routine tidying, permanently. Called when a grind is pinned to
    #best-mixes — the founder's rule of 2026-08-13 is that those are never removed.

    Takes a mix id OR a set id: both are 64-hex render ids and the marker is id-shaped, not
    kind-shaped. Deliberately succeeds even when the render is not on disk right now — the marker
    is about intent, and a mix rebuilt later under the same id is protected the moment it exists.
    Idempotent, so a double-tap of 📌 is free."""
    if not storage.keep(render_id):
        raise HTTPException(400, "Not a valid render id.")
    return {"render_id": render_id, "kept": True}


@router.get("/mix/{mix_id}/audio")
def get_mix_audio(mix_id: str):
    """Serve the finished mix to the user: its best-parts ~180s highlight (the full render stays on disk
    as the canonical source for Regenerate + set-joining). id validated before any disk access."""
    if not _HEX_ID.fullmatch(mix_id):
        raise HTTPException(404, "Not found.")
    if not _mix_wav(mix_id).exists():
        raise HTTPException(404, "Not found.")
    # Playing a mix is what keeps it alive: the routine age sweep counts from LAST PLAYED, not from
    # when it was rendered. Both files, because the highlight is what we serve but the full render
    # is what Regenerate and set-joining read — a played mix keeps its whole family. Bookkeeping
    # only; `mark_used` never raises, so a stamp that cannot be written costs at worst a re-render.
    mark_used(_mix_wav(mix_id), _bestparts_wav(mix_id))
    return FileResponse(_ensure_bestparts(mix_id), media_type="audio/wav")
