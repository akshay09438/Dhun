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

from app.models import MixPlan, Placement, TrackAnalysis
from app.planner import fence, llm

_MAX_PLACEMENTS = 3
_ENTRY_MARGIN = 1.0  # secs of beat-only breathing room between one vocal's end and the next entry
_WINDOW_STEP = 8.0  # ~a phrase; min spare room in a region worth sliding the vocal window for regenerate variety

_ARRANGE_SYSTEM = (
    "You are a DJ arranging Song 2's vocal over Song 1's beat. From the given legal phrase "
    "anchors (seconds) and vocal slices, choose 2-3 non-overlapping placements that shape an "
    "arc across the WHOLE song, using track_length_seconds as your canvas. Spread the "
    "placements over the song's thirds — one early (after an instrumental intro, not the very "
    "first anchor), one around the middle, and one in the FINAL THIRD as the strongest entry. "
    "Do NOT cluster them all in the middle or leave the first half or the ending empty. Leave "
    "a stretch of just beat between entries. Set beat_breath=true before a big re-entry (a one-"
    "bar tension dip, not silence). recommended_spread_anchors shows one good arc; you may use "
    "or improve it. If take_number>1, choose a genuinely different arrangement. STRICT JSON "
    'only, nothing else: '
    '{"placements":[{"anchor":<sec>,"vocal_slice":[<start>,<end>],"beat_breath":<bool>}]}'
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
    """Slice B: on a confident Song 1, answer with Song 1's own vocal in one gap and put a
    single filter-sweep into the final (big) entry. On a shaky Song 1, play safe — no
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
    s1_regions = fence.contrast_windows(a1, placements, stretch)[:1]
    if len(placements) >= 2:  # one filter sweep, into the final (biggest) entry
        placements[-1].fx = "sweep_in"
    return placements, s1_regions


def _default_arrangement(opts: dict, take: int) -> list[Placement]:
    """Deterministic arrangement: 2-3 anchors spread across the song's thirds (an energy
    ARC, not a cluster — Handbook H1/H2), each given a vocal slice trimmed to fit before
    the next entry, rotated by `take` for regenerate variety. The first placement never
    breathes; later ones do."""
    anchors_ranked = opts["anchors_ranked"]
    slices = opts["vocal_slices"]
    stretch = opts["vocal_stretch"]
    if len(anchors_ranked) < 2:
        return [Placement(anchor=anchors_ranked[0] if anchors_ranked else 0.0, vocal_src=slices[0])]

    n = min(_MAX_PLACEMENTS, len(anchors_ranked))
    chosen = fence.arc_anchors(anchors_ranked, opts["track_end"], count=n, take=take)  # spread, in time order
    placements: list[Placement] = []
    for i, anc in enumerate(chosen):
        # Rotate WHICH slice fills this placement by `take` too (not just by position), so
        # regenerate pulls different vocal content at the same spot — not just a new
        # anchor for the same replayed excerpt (the "every mix must be unique" complaint).
        s0, s1 = slices[(i + take - 1) % len(slices)]
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
        s0, s1 = slices[0]
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
            "recommended_spread_anchors": [
                round(a, 1) for a in fence.arc_anchors(legal, track_end, count=_MAX_PLACEMENTS, take=take)
            ],
            "song1_sections": [[round(s0, 1), lbl] for s0, lbl in opts.get("sections", [])][:12],
            "vocal_slices_seconds": [[round(s, 1), round(e, 1)] for s, e in opts["vocal_slices"]],
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


def build_mix_plan(mix_id: str, a1: TrackAnalysis, a2: TrackAnalysis,
                   prompt: str = "", take: int = 1) -> MixPlan:
    """Produce the arrangement recipe. Raises MixDeclined if the pair can't blend."""
    opts = fence.arrangement_options(a1, a2)
    if not opts["mixable"]:
        raise MixDeclined(opts["reason"])

    placements = _ai_arrange(opts, prompt, take)
    source = "ai" if placements else "rules"
    if not placements:
        placements = _default_arrangement(opts, take)
    placements = _attach_warp(placements, a1, a2, opts["vocal_stretch"])  # per-bar beat-lock
    placements = _dedupe_nonoverlapping(placements, opts["vocal_stretch"])
    # The arc guard: if the plan (AI's or a thin fallback) clusters instead of spanning the
    # song, rebuild it as a deterministic energy arc so the vocal always reaches the whole
    # track with a strong finish — the founder's acceptance test, guaranteed by construction.
    if not _spans_song(placements, opts.get("track_end", 0.0)):
        rebuilt = _attach_warp(_default_arrangement(opts, take), a1, a2, opts["vocal_stretch"])
        placements = _dedupe_nonoverlapping(rebuilt, opts["vocal_stretch"])
        source = "rules"
    placements, s1_regions = _apply_flourishes(a1, placements, opts["vocal_stretch"])
    first = placements[0]
    return MixPlan(
        mix_id=mix_id, song1_id=a1.song_id, song2_id=a2.song_id,
        master_bpm=opts["master_bpm"], vocal_stretch=opts["vocal_stretch"],
        vocal_src=first.vocal_src, anchor=first.anchor,  # scalar mirrors first (M3 back-compat)
        placements=placements, s1_vocal_regions=s1_regions, take=take,
        notes=_describe_arrangement(placements, s1_regions),
        confidence=0.75 if source == "ai" else 0.6, source=source,
    )
