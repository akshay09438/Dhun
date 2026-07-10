"""The AI driver: arrange Song 2's vocal over Song 1's beat as a full DJ set.

The rules (fence) decide what is LEGAL; here the brain arranges what is TASTEFUL among
those legal options — 2-3 non-overlapping vocal placements that build a set (quiet
intro, vocal on the big sections, a verse of beat between entries, a strong finish),
with a one-bar tension breath before a big re-entry. Claude does the arranging; on any
failure (no API key, network, bad output) a deterministic fallback produces a valid,
simpler arrangement, so a mix never blocks on the AI. Regenerate re-plans with variety.
The LLM never touches audio; it only fills this structured plan.
"""

from __future__ import annotations

import json
import os

from app.models import (DuckMove, MixPlan, Placement, TrackAnalysis, VocalChainConfig,
                        VocalProcessMove, chain_config_hash)
from app.planner import fence, hooks, llm, window

# Phase 0 (T1): the AI arrangement engine is OFF by default. The founder prefers the
# deterministic rules arrangement (`_default_arrangement`) — a note-for-note match to the loved
# reference; the disliked AI path used to activate on mere ANTHROPIC_API_KEY presence. It is kept
# in the tree (not deleted) as the seat for constrained menu-selection later (Phase 5), just not
# driving. Flip on via this flag or the USE_AI_ARRANGEMENT env var (key presence must NOT trigger it).
USE_AI_ARRANGEMENT = os.environ.get("USE_AI_ARRANGEMENT", "").strip().lower() in {"1", "true", "yes", "on"}

_MAX_PLACEMENTS = 3
# Good-parts window: crop the mix to the beat's best ~90s. DISABLED (founder decision 2026-07-09:
# remix the FULL song, not the best ~90s). Kept as a flag — not deleted — so it's a one-line revert
# and the window machinery (window.py + render/validate window-handling) stays dormant + tested.
_GOOD_PARTS_WINDOW_ENABLED = False
_ENTRY_MARGIN = 1.0  # secs of beat-only breathing room between one vocal's end and the next entry
_WINDOW_STEP = 8.0  # ~a phrase; min spare room in a region worth sliding the vocal window for regenerate variety
_OUTRO_SECS = 12.0  # good-parts: beat runway kept AFTER the last vocal ends, so the windowed mix winds
                    # DOWN into an outro (a downward hand-off point) instead of stopping on the hook

_ARRANGE_SYSTEM = (
    "You are a DJ arranging Song 2's vocal over Song 1's (house) beat. ENERGY SYNC is the goal: "
    "land the vocal's most POWERFUL part on the house track's DROP (see house_drops_seconds), and "
    "let softer parts ride the quieter build-ups. From the given legal phrase anchors (seconds) and "
    "vocal slices, choose 2-3 non-overlapping placements that shape an arc across the WHOLE song, "
    "using track_length_seconds as your canvas. Prefer anchoring entries ON a house drop. Spread the "
    "placements over the song's thirds — one early (after an instrumental intro, not the very first "
    "anchor), one around the middle, and one in the FINAL THIRD as the strongest entry. Do NOT "
    "cluster them all in the middle or leave the first half or the ending empty. Leave a stretch of "
    "just beat between entries. Set beat_breath=true before a big re-entry (a one-bar tension dip, "
    "not silence). recommended_spread_anchors shows one good energy-synced arc; you may use or "
    "improve it. If take_number>1, choose a genuinely different arrangement. STRICT JSON only, "
    'nothing else: {"placements":[{"anchor":<sec>,"vocal_slice":[<start>,<end>],"beat_breath":<bool>}]}'
)


class MixDeclined(Exception):
    """The pair cannot be mixed cleanly; carries a plain-language reason for the user."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _describe(anchor: float) -> str:
    m, s = divmod(int(anchor), 60)
    return f"Song 2's vocal enters on the drop at {m}:{s:02d}, tempo-locked to Song 1."


def _describe_arrangement(placements: list[Placement], s1_regions: list | None = None) -> str:
    if len(placements) == 1 and not s1_regions:
        return _describe(placements[0].anchor)
    spots = ", ".join(f"{int(p.anchor) // 60}:{int(p.anchor) % 60:02d}" for p in placements)
    note = f"Vocal weaves in at {spots}, tempo-locked to Song 1 with the beat running throughout."
    if s1_regions:
        note += " Song 1's own vocal answers in a gap for contrast."
    if any(p.fx for p in placements):
        note += " A filter sweep builds into a big entry."
    return note


def _confident(a1: TrackAnalysis) -> bool:
    """Is Song 1's grid trustworthy enough to risk the fancy moves? (Handbook Part 9.)"""
    return a1.bpm_confidence is None or a1.bpm_confidence >= 0.5


def _apply_flourishes(a1: TrackAnalysis, placements: list[Placement],
                      stretch: float) -> tuple[list[Placement], list[tuple[float, float]]]:
    """On a confident Song 1: let Song 1 LEAD with its own vocal in the gaps (both songs trade —
    Step 1) and put a filter-sweep into the final (big) entry. On a shaky Song 1, play safe — no
    flourishes and at most two placements — rather than bet fancy moves on bad data."""
    if not _confident(a1):
        # Play safe (<=2 placements, no flourishes) — but keep the arc's ENDS (first + last),
        # not the first two, so a long shaky song still gets an early AND a late entry instead
        # of leaving its whole final stretch silent.
        safe = [placements[0], placements[-1]] if len(placements) > 2 else placements
        for p in safe:
            p.beat_breath = False
            p.fx = None
        return safe, []
    # Both vocals trade: Song 1 leads its substantial sung passages in the gaps (keep the real
    # ones, drop the scraps), AND keeps its short vocal LICK right before each drop (the
    # vocal-into-the-drop a real DJ never cuts) — never over Song 2 (R1). Merge any overlap.
    leads = fence.lead_sections(a1, placements, stretch)
    licks = fence.predrop_licks(a1, placements, stretch)
    s1_regions = fence._merge_regions(leads + licks, max_gap=0.0)
    if len(placements) >= 2:  # one filter sweep, into the final (biggest) entry
        placements[-1].fx = "sweep_in"
    return placements, s1_regions


_BUILD_BARS = 3  # bars of rising filter+volume build the engine lays before a produced drop
# A bar this quiet or quieter is a genuine BREAKDOWN in Song 1's own source — the app's own
# invariant is that the beat never fully stops, so the produced-drop build must never be asked to
# climb THROUGH an already-near-silent bar (its filter+volume treatment would tip it into true
# silence, not just a dip). Chosen from real data: a healthy build bar in the catalog sits >=0.13;
# a genuine source breakdown measured at ~0.047-0.049 (founder ear-test, Father Ocean x Der Lagi,
# drop 2's build window) — 0.10 sits cleanly between the two with margin on both sides.
_BUILD_ENERGY_FLOOR = 0.10
# The engine's echo rings for render._ECHO_BEATS * render._ECHO_TAPS = 0.75 * 4 = 3 beats. Keep
# this in sync with those constants. We derive the tail from the ACTUAL tempo (airtight at any
# bpm, incl. an octave/quarter-tempo misread), plus a small margin, so the echo is suppressed
# whenever Song 1's own contrast vocal would fall inside it (R1 — a breach the referee can't see,
# since placement_end has no echo term), and fires freely at house tempos where it's provably safe.
_ECHO_TAIL_BEATS = 3.0
_ECHO_TAIL_MARGIN_SECS = 0.3


def _echo_tail_secs(bpm: float) -> float:
    """How long the engine's echo tail rings, at this tempo (with a small safety margin)."""
    return (60.0 / bpm) * _ECHO_TAIL_BEATS + _ECHO_TAIL_MARGIN_SECS if bpm > 0 else 1e9


def _safe_build_bars(a1_downbeats: list[float], a1_energy: list[float], anchor: float,
                     max_bars: int) -> int:
    """How many bars of BUILD are safe to place before `anchor`: walk backward bar-by-bar from the
    anchor's downbeat and stop at the first bar whose energy is at/under `_BUILD_ENERGY_FLOOR` — a
    real breakdown in Song 1's own recording (founder ear-test: the pre-existing filter+volume build,
    applied blindly across a fixed window, tipped an already-near-silent source bar into a full
    second of true silence — 'a continuous song can't go blank'). The build shrinks to only the
    CONTIGUOUS run of bars that actually have something to build from; if even the bar right before
    the anchor is too quiet, returns 0 (no build at all — a plain entry). Without energy/grid data,
    returns `max_bars` unchanged (can't judge, so don't second-guess the caller)."""
    if not a1_downbeats or not a1_energy:
        return max_bars
    anchor_i = min(range(len(a1_downbeats)), key=lambda k: abs(a1_downbeats[k] - anchor))
    n = 0
    for k in range(anchor_i - 1, anchor_i - 1 - max_bars, -1):
        if k < 0 or k >= len(a1_energy) or a1_energy[k] <= _BUILD_ENERGY_FLOOR:
            break
        n += 1
    return n


def _produce_drops(placements: list[Placement], drops: list[float],
                   s1_regions: list[tuple[float, float]], stretch: float, bpm: float,
                   a1: TrackAnalysis | None = None) -> list[Placement]:
    """Mark the placements that land on a real house DROP as PRODUCED: a multi-bar filter+volume
    BUILD into the entry (so the drop is felt coming), and an ECHO throw so the vocal rings out on
    EVERY big drop (Step 2). The engine executes both; here we only decide where. FX-only and
    additive — a placement not on a drop is untouched (stays a plain, valid entry). The build window
    SHRINKS to skip any real breakdown in Song 1's own source (`_safe_build_bars`) — never 0 bars of
    real music, only ever the amount of build the source can actually support."""
    if not placements or not drops:
        return placements
    ordered = sorted(placements, key=lambda p: p.anchor)
    is_drop = lambda p: any(abs(p.anchor - d) <= 0.06 for d in drops)
    a1_downbeats = a1.downbeats if a1 else []
    a1_energy = a1.energy_curve if a1 else []
    for p in ordered:
        if is_drop(p):
            bars = _safe_build_bars(a1_downbeats, a1_energy, p.anchor, _BUILD_BARS)
            p.build_bars = bars
            if bars > 0:
                p.fx = None  # the multi-bar build supersedes the one-bar sweep on this entry
    # Throw an echo on each drop, BUT only where the echo tail is clear of the next lead vocal —
    # neither a Song 1 lead/lick nor the next Song 2 placement may start inside it (R1: the echo
    # tail must never ring over a later lead, a breach the referee can't see — placement_end has
    # no echo term). This generalises the old climax-only guard to every drop.
    tail = _echo_tail_secs(bpm)
    for i, p in enumerate(ordered):
        if not is_drop(p):
            continue
        p_end = fence.placement_end(p.anchor, p.vocal_src, stretch, getattr(p, "warp", None))
        next_anchor = ordered[i + 1].anchor if i + 1 < len(ordered) else float("inf")
        s1_in_tail = any(p_end - 1e-6 <= s < p_end + tail for s, _e in s1_regions)
        s2_in_tail = next_anchor < p_end + tail - 1e-6
        if not s1_in_tail and not s2_in_tail:
            p.echo = True
    return placements


def _flag_chop_on_biggest_drop(placements: list[Placement], a1: TrackAnalysis) -> None:
    """Set `chop=True` on the ONE produced drop (build_bars>0) whose anchor sits on Song 1's loudest
    bar — the biggest drop, where a vocal chop signature lands best (recipe R2). One showcase moment
    per mix; no-op if there are no produced drops or no energy/grid to rank by."""
    produced = [p for p in placements if getattr(p, "build_bars", 0) > 0]
    if not produced or not a1.downbeats or not a1.energy_curve:
        return

    def _anchor_energy(p: Placement) -> float:
        i = min(range(len(a1.downbeats)), key=lambda k: abs(a1.downbeats[k] - p.anchor))
        return a1.energy_curve[i] if i < len(a1.energy_curve) else 0.0

    max(produced, key=_anchor_energy).chop = True


def _default_arrangement(opts: dict, take: int) -> list[Placement]:
    """Deterministic ENERGY-SYNCED arrangement: 2-3 anchors spread across the song's thirds
    (an energy ARC, not a cluster — Handbook H1/H2), PREFERRING the house track's real drops
    (recipe R1), with Song 2's most powerful vocal peak paired onto the biggest drop. Each
    slice is trimmed to fit before the next entry and rotated by `take` for regenerate variety.
    The first placement never breathes; later ones do."""
    anchors_ranked = opts["anchors_ranked"]
    peaks = opts.get("vocal_peaks") or opts["vocal_slices"]  # loudest-first; slices is the fallback
    drops = opts.get("drops", [])
    stretch = opts["vocal_stretch"]
    if len(anchors_ranked) < 2:
        return [Placement(anchor=anchors_ranked[0] if anchors_ranked else 0.0,
                          vocal_src=opts.get("hook") or peaks[0])]

    n = min(_MAX_PLACEMENTS, len(anchors_ranked))
    chosen = fence.synced_anchors(anchors_ranked, drops, opts["track_end"], count=n, take=take)  # drop-aware arc
    # Pair Song 2's loudest peak onto the strongest anchor (a real drop beats a mere loud phrase),
    # rotating the pairing by `take` so regenerate pulls different vocal content (R1 + variety).
    drops_set = set(drops)
    a1g = opts.get("a1_grid")
    def _drop_energy(t: float) -> float:
        """Energy at drop `t` on the (windowed) grid — so the LOUDEST drop is picked, not just any."""
        if not (a1g and a1g.downbeats and a1g.energy_curve):
            return 0.0
        i = min(range(len(a1g.downbeats)), key=lambda k: abs(a1g.downbeats[k] - t))
        return a1g.energy_curve[i] if i < len(a1g.energy_curve) else 0.0
    def _strength(t: float) -> tuple[float, float]:
        if t in drops_set:
            # A real drop wins; among several drops the LOUDEST (the MAIN drop the window is built
            # around) wins the hook — founder ear-test 2026-07-09: the signature line must land on the
            # big beat drop, not merely the first drop in time.
            return (1.0, _drop_energy(t))
        try:
            return (0.0, float(-anchors_ranked.index(t)))  # else louder = earlier in the energy-ranked list
        except ValueError:
            return (0.0, -10_000.0)
    by_strength = sorted(range(len(chosen)), key=lambda i: _strength(chosen[i]), reverse=True)
    hook = opts.get("hook")
    if hook:
        # Land the signature HOOK on the strongest anchor (the drop); the other entries get the SETUP
        # — the song's other vocal parts, never the hook again, rotated by `take` for regenerate variety.
        drop_idx = by_strength[0]
        setup = [p for p in peaks if p != hook] or peaks
        slice_for = {drop_idx: hook}
        for rank, idx in enumerate(by_strength[1:]):
            slice_for[idx] = setup[(rank + take - 1) % len(setup)]
    else:
        slice_for = {idx: peaks[(rank + take - 1) % len(peaks)] for rank, idx in enumerate(by_strength)}

    placements: list[Placement] = []
    for i, anc in enumerate(chosen):
        s0, s1 = slice_for[i]
        gap = (chosen[i + 1] - anc) if i + 1 < len(chosen) else _MAX_PLACEMENTS * 60.0
        # A vocal of SOURCE length d renders to d / stretch output-seconds; we want that
        # to fit the output gap, so the max source length is (gap - margin) * stretch.
        fit = max(0.0, (gap - _ENTRY_MARGIN) * stretch)
        length = min(s1 - s0, fit)
        if length < fence.MIN_VOCAL_SECS:
            continue  # not enough clean room before the next entry — skip this spot
        # Slide the window WITHIN the region by `take` when the region is longer than we'll
        # use, so regenerate plays a different part of the same section — genuine vocal
        # variety even when there's only one region to draw from (thin analysis). The warp
        # map re-snaps the start to a Song-2 downbeat, so this stays beat-locked.
        spare = (s1 - s0) - length
        if spare >= _WINDOW_STEP:
            n_pos = min(3, int(spare // _WINDOW_STEP) + 1)  # up to 3 distinct windows
            s0 = s0 + spare * ((take - 1) % n_pos) / (n_pos - 1)
        placements.append(Placement(anchor=anc, vocal_src=(round(s0, 3), round(s0 + length, 3)), beat_breath=i > 0))
    if not placements:  # nothing fit — one safe placement at the best anchor
        s0, s1 = peaks[0]
        end = s0 + min(s1 - s0, fence.MAX_VOCAL_SECS)
        placements = [Placement(anchor=chosen[0] if chosen else anchors_ranked[0], vocal_src=(s0, round(end, 3)))]
    return placements


def _ai_arrange(opts: dict, prompt: str, take: int) -> list[Placement] | None:
    """Ask Claude to arrange the set. Returns placements (anchors snapped to legal phrase
    starts) or None on any failure — the caller then falls back."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    legal = opts["anchors_ranked"]
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        track_end = opts.get("track_end", 0.0)
        payload = {
            "shared_tempo_bpm": opts["master_bpm"],
            "track_length_seconds": round(track_end, 1),  # the whole canvas, so it can span it
            "phrase_anchors_seconds": [round(a, 1) for a in legal[:12]],
            "house_drops_seconds": [round(d, 1) for d in opts.get("drops", [])],  # land the peak here (R1)
            "recommended_spread_anchors": [
                round(a, 1) for a in fence.synced_anchors(
                    legal, opts.get("drops", []), track_end, count=_MAX_PLACEMENTS, take=take)
            ],
            "song1_sections": [[round(s0, 1), lbl] for s0, lbl in opts.get("sections", [])][:12],
            "vocal_slices_seconds": [[round(s, 1), round(e, 1)] for s, e in opts["vocal_slices"]],
            "vocal_peaks_seconds": [[round(s, 1), round(e, 1)] for s, e in opts.get("vocal_peaks", [])],
            "keys_compatible": opts["key_fit"],
            "user_request": prompt or "",
            "take_number": take,
            "make_it_different_from_previous_takes": take > 1,
        }
        msg = client.messages.create(
            model=llm.MODEL, max_tokens=600, system=_ARRANGE_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload)}],
        )
        data = llm.extract_json(llm.first_text(msg))
        out: list[Placement] = []
        for p in data["placements"][:_MAX_PLACEMENTS]:
            anc = min(legal, key=lambda x: abs(x - float(p["anchor"])))  # snap to a legal anchor
            sl = p["vocal_slice"]
            s0 = float(sl[0])
            s1 = min(float(sl[1]), s0 + fence.MAX_VOCAL_SECS)  # never longer than the fence allows
            out.append(Placement(anchor=anc, vocal_src=(s0, s1),
                                 beat_breath=bool(p.get("beat_breath", False))))
        return out or None
    except Exception:
        return None


def _spans_song(placements: list[Placement], track_end: float) -> bool:
    """Does the arrangement reach across the whole song — a vocal in the first half AND a
    strong entry in the final third — rather than clustering in the middle? This encodes
    the founder's acceptance test and guards against a clustering AI (or thin analysis)."""
    if not placements or track_end <= 0:
        return True  # nothing to judge against — don't force a needless rebuild
    anchors = [p.anchor for p in placements]
    return min(anchors) <= track_end / 2 and max(anchors) >= track_end * 2 / 3


def _attach_warp(placements: list[Placement], a1: TrackAnalysis, a2: TrackAnalysis,
                 stretch: float) -> list[Placement]:
    """Give each Song-2 placement a per-bar phase-lock warp map (M4d) so its vocal re-locks
    to Song 1's beat instead of drifting under one global stretch. With no usable grid on
    either side, leave warp empty — the engine then uses the legacy global stretch."""
    if not (a1.downbeats and a2.downbeats):
        return placements
    for p in placements:
        p.warp = fence.warp_map(p.anchor, p.vocal_src, a1.downbeats, a2.downbeats, stretch)
    return placements


def _dedupe_nonoverlapping(placements: list[Placement], stretch: float) -> list[Placement]:
    """Sort by anchor and drop any placement that would overlap the previous vocal —
    enforces one-voice-at-a-time before the render (the referee re-checks). Uses the
    warp-aware real length so a beat-locked vocal's true end is what's compared."""
    kept: list[Placement] = []
    for p in sorted(placements, key=lambda pl: pl.anchor):
        if not kept:
            kept.append(p)
            continue
        if p.anchor >= fence.placement_end(kept[-1].anchor, kept[-1].vocal_src, stretch, kept[-1].warp):
            kept.append(p)
    return kept


def _emit_vocal_chain(placements: list[Placement], cfg: VocalChainConfig,
                      a1g: TrackAnalysis, stretch: float) -> tuple[list[VocalProcessMove], list[DuckMove]]:
    """Phase 0 (G5): translate the vocal-chain CONFIG into per-placement timeline INSTRUCTIONS — one
    `VocalProcessMove` (stages 1-8) and one bed `DuckMove` (stage 9) per placement. This is the whole
    architecture: the config is the planner's input; the moves are the renderer's input; the renderer
    never reads the config. Emitted ONLY when the chain is enabled — disabled ⇒ ([], []) so the render
    is byte-identical (mirrors `stem_moves == []`). A stage disabled in the config emits its NEUTRAL
    dial (the renderer treats a neutral dial as off — the per-stage kill switch). `pitch_semitones`
    stays 0 here: key-correction repair is Slice 2d, still off. `placement_id` is positional (`p{i}`),
    matching the renderer's lookup."""
    if not cfg.enabled or not placements:
        return [], []
    downbeats = a1g.downbeats or []

    def bar_of(t: float) -> int:
        return min(range(len(downbeats)), key=lambda k: abs(downbeats[k] - t)) if downbeats else 0

    vmoves: list[VocalProcessMove] = []
    dmoves: list[DuckMove] = []
    for i, p in enumerate(placements):
        pid = f"p{i}"
        end_t = fence.placement_end(p.anchor, p.vocal_src, stretch, getattr(p, "warp", None))
        sb = bar_of(p.anchor)
        eb = max(sb + 1, bar_of(end_t))
        vmoves.append(VocalProcessMove(
            placement_id=pid, start_bar=sb, end_bar=eb,
            pitch_semitones=0.0,  # key-correction repair is Slice 2d (off)
            deess=cfg.deess_intensity if cfg.deess_enabled else 0.0,
            highpass_hz=cfg.highpass_hz if cfg.highpass_enabled else 0,
            compress_ratio=cfg.compress_ratio if cfg.compress_enabled else 1.0,
            saturate_wet=cfg.saturate_wet if cfg.saturate_enabled else 0.0,
            presence_gain_db=cfg.presence_gain_db if cfg.presence_enabled else 0.0,
            reverb_wet=cfg.reverb_wet if cfg.reverb_enabled else 0.0,
            reason="chain: bollywood_vocal_over_house v0 (static config dials)",
        ))
        if cfg.duck_enabled:
            dmoves.append(DuckMove(
                target_stems=["drums", "bass", "other"], key_placement_id=pid,
                depth_db=cfg.duck_depth_db, attack_ms=cfg.duck_attack_ms, release_ms=cfg.duck_release_ms))
    return vmoves, dmoves


def build_mix_plan(mix_id: str, a1: TrackAnalysis, a2: TrackAnalysis,
                   prompt: str = "", take: int = 1,
                   chain: VocalChainConfig | None = None) -> MixPlan:
    """Produce the arrangement recipe. Raises MixDeclined if the pair can't blend.

    `chain` is the vocal-chain config (Phase 0). Defaults to OFF (`VocalChainConfig()`), so a mix
    emits no vocal_moves/duck_moves and renders byte-identically to m6.0 until the founder flips it on
    after the tuning week."""
    chain = chain or VocalChainConfig()
    opts = fence.arrangement_options(a1, a2)
    if not opts["mixable"]:
        raise MixDeclined(opts["reason"])
    # The signature HOOK to land on the drop (curated per song; None -> fall back to loudest peak).
    opts["hook"] = hooks.hook_for(a2.song_id)
    # Plan against the (possibly retimed) grid the movable master chose — warp, flourishes and
    # drops all key off Song 1's downbeats, which move when the house bed is stretched. a1g is
    # a1 on the native path (bed_stretch == 1.0), so nothing changes for today's pairs.
    a1g = opts.get("a1_grid", a1)
    full_end = a1g.beats[-1] if a1g.beats else 0.0  # pre-window track end (abs), to clamp the outro extension

    # Good-parts window: build the mix on the beat's best ~90s (the run-up into its main drop) instead
    # of the whole track. DISABLED by default via _GOOD_PARTS_WINDOW_ENABLED (founder decision: full-
    # song mixes); when off, window_span stays None and the engine's own "no window -> full track" path
    # runs, so render.py and validate.py need NO change (they already treat window=None as full track).
    window_span = (window.choose_window(a1g, opts.get("drops", []), take)
                   if (_GOOD_PARTS_WINDOW_ENABLED and _confident(a1g)) else None)
    if window_span:
        opts = window.windowed_options(opts, *window_span)
        a1g = opts["a1_grid"]

    placements = _ai_arrange(opts, prompt, take) if USE_AI_ARRANGEMENT else None
    source = "ai" if placements else "rules"
    if not placements:
        placements = _default_arrangement(opts, take)
    placements = _attach_warp(placements, a1g, a2, opts["vocal_stretch"])  # per-bar beat-lock
    placements = _dedupe_nonoverlapping(placements, opts["vocal_stretch"])
    # The arc guard: if the plan (AI's or a thin fallback) clusters instead of spanning the
    # song, rebuild it as a deterministic energy arc so the vocal always reaches the whole
    # track with a strong finish — the founder's acceptance test, guaranteed by construction.
    if not _spans_song(placements, opts.get("track_end", 0.0)):
        rebuilt = _attach_warp(_default_arrangement(opts, take), a1g, a2, opts["vocal_stretch"])
        placements = _dedupe_nonoverlapping(rebuilt, opts["vocal_stretch"])
        source = "rules"
    placements, s1_regions = _apply_flourishes(a1g, placements, opts["vocal_stretch"])
    stem_moves: list = []
    if _confident(a1g):  # only produce (build/echo/stem-moves) on a trustworthy grid — shaky songs stay safe
        placements = _produce_drops(placements, opts.get("drops", []), s1_regions,
                                    opts["vocal_stretch"], opts["master_bpm"], a1g)
        # Step 3: auto-perform each produced drop's tension arc (cut to just the beat, then bass held
        # silent through the build, then the slam), on the retimed grid the audio plays at. Keys off
        # build_bars, so it only fires where a real drop got a build. Skips any drop where Father
        # Ocean's OWN vocal (s1_regions) is already leading into it — never hollow out the backing
        # under his voice.
        stem_moves = fence.stem_moves_for_drops(placements, a1g.downbeats, opts["vocal_stretch"], s1_regions)
        # Wave 2's 2nd move: one "beat-up" moment (melody ducks, drums+bass drive) in the strongest
        # beat-only stretch. Checked directly against stem_moves so it can never collide with a
        # produced drop's own cut/build/bass.
        stem_moves = stem_moves + fence.beat_up_moves(a1g, placements, s1_regions, stem_moves,
                                                       opts["vocal_stretch"])
        # Wave 2's 3rd move: one "breakdown" (drums+bass fade to a simmer, then kick back) in the
        # next-best energetic stretch — passed the running stem_moves, so it avoids the beat-up and
        # every produced drop and lands on its own clear spot.
        stem_moves = stem_moves + fence.breakdown_moves(a1g, placements, s1_regions, stem_moves,
                                                        opts["vocal_stretch"])
        # Step 4: vocal chops on the BIGGEST drop — PARKED 2026-07-09 (founder decision). The chop
        # re-fired the vocal's first 0.22s onset; on real material that onset can be a breath, which
        # made the drop go DEAD (founder ear-test at 3:56 on Father Ocean × Der Lagi). The machinery
        # (render._chop_pattern, Placement.chop, _flag_chop_on_biggest_drop) stays in the tree, dormant
        # and tested, so reviving is a one-line change — but only after the chop grabs a punchy syllable
        # instead of the raw first slice (see the drift log, 17th/18th entries).
        # _flag_chop_on_biggest_drop(placements, a1g)  # <- re-enable here to revive

    # Good-parts ending: extend the beat past the last vocal so the windowed mix winds DOWN into a
    # short outro (a downward hand-off / transition point) instead of stopping on the hook. The extra
    # beat is plain Song-1 audio after the arrangement, clamped to the real track end. window-relative
    # placements are unchanged; only plan.window (the render's bed crop) grows. (Founder ear-test 2026-07-09.)
    if window_span and placements:
        ws, we = window_span
        last_end = max(fence.placement_end(p.anchor, p.vocal_src, opts["vocal_stretch"], getattr(p, "warp", None))
                       for p in placements)
        we = max(we, min(ws + last_end + _OUTRO_SECS, full_end))  # never shrink; never past the real track
        window_span = (round(ws, 3), round(we, 3))

    # Phase 0 (G5): emit the vocal-processing timeline instructions from the chain config (none when
    # disabled → byte-identical render). key-correction pitch stays 0 (Slice 2d).
    vocal_moves, duck_moves = _emit_vocal_chain(placements, chain, a1g, opts["vocal_stretch"])

    first = placements[0]
    return MixPlan(
        mix_id=mix_id, song1_id=a1.song_id, song2_id=a2.song_id,
        master_bpm=opts["master_bpm"], vocal_stretch=opts["vocal_stretch"],
        bed_stretch=opts.get("bed_stretch", 1.0),  # movable master: how much Song 1's bed is stretched
        vocal_src=first.vocal_src, anchor=first.anchor,  # scalar mirrors first (M3 back-compat)
        placements=placements, s1_vocal_regions=s1_regions, stem_moves=stem_moves, take=take,
        window=window_span,
        camelot_fit=fence.camelot_detail(a1, a2),  # Phase 0: informational key-fit (logged, never gates)
        chain_config_hash=chain_config_hash(chain),  # the chain config this mix was rendered under
        vocal_moves=vocal_moves, duck_moves=duck_moves,  # Phase 0 vocal chain (empty when disabled)
        notes=_describe_arrangement(placements, s1_regions),
        confidence=0.75 if source == "ai" else 0.6, source=source,
    )
