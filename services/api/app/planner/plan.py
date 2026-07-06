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
from app.planner import fence

# A small, fast model is plenty for arranging among pre-vetted options.
_MODEL = "claude-sonnet-5"
_MAX_PLACEMENTS = 3
_ENTRY_MARGIN = 1.0  # secs of beat-only breathing room between one vocal's end and the next entry

_ARRANGE_SYSTEM = (
    "You are a DJ arranging Song 2's vocal over Song 1's beat. From the given legal "
    "phrase anchors (seconds, best-energy first) and vocal slices, choose 2-3 non-"
    "overlapping placements that build a set: keep an instrumental intro, land the vocal "
    "on high-energy sections, leave a verse of just beat between entries, and finish "
    "strong. Don't start on the very first anchor. Set beat_breath=true before a big "
    "re-entry (a one-bar tension dip, not silence). If take_number>1, choose a genuinely "
    "different arrangement. STRICT JSON only, nothing else: "
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


def _describe_arrangement(placements: list[Placement]) -> str:
    if len(placements) == 1:
        return _describe(placements[0].anchor)
    spots = ", ".join(f"{int(p.anchor) // 60}:{int(p.anchor) % 60:02d}" for p in placements)
    return f"Vocal weaves in at {spots}, tempo-locked to Song 1 with the beat running throughout."


def _extract_json(text: str) -> dict:
    """Tolerate a model that wraps its JSON in prose or a code fence."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model output")
    return json.loads(text[start : end + 1])


def _default_arrangement(opts: dict, take: int) -> list[Placement]:
    """Deterministic arrangement: 2-3 top-energy phrase anchors (spaced so vocals never
    overlap), each given a vocal slice trimmed to fit before the next entry, rotated by
    `take` for regenerate variety. The first placement never breathes; later ones do."""
    anchors = sorted(opts["anchors_ranked"])
    slices = opts["vocal_slices"]
    stretch = opts["vocal_stretch"]
    if len(anchors) < 2:
        return [Placement(anchor=anchors[0] if anchors else 0.0, vocal_src=slices[0])]

    n = min(_MAX_PLACEMENTS, len(anchors))
    offset = (take - 1) % max(1, len(anchors) - n + 1)  # slide the window per take
    chosen = anchors[offset : offset + n]
    placements: list[Placement] = []
    for i, anc in enumerate(chosen):
        s0, s1 = slices[i % len(slices)]
        gap = (chosen[i + 1] - anc) if i + 1 < len(chosen) else _MAX_PLACEMENTS * 60.0
        # A vocal of SOURCE length d renders to d / stretch output-seconds; we want that
        # to fit the output gap, so the max source length is (gap - margin) * stretch.
        fit = max(0.0, (gap - _ENTRY_MARGIN) * stretch)
        length = min(s1 - s0, fit)
        if length < fence.MIN_VOCAL_SECS:
            continue  # not enough clean room before the next entry — skip this spot
        placements.append(Placement(anchor=anc, vocal_src=(s0, round(s0 + length, 3)), beat_breath=i > 0))
    if not placements:  # nothing fit — one safe placement at the best anchor
        s0, s1 = slices[0]
        end = s0 + min(s1 - s0, fence.MAX_VOCAL_SECS)
        placements = [Placement(anchor=anchors[0], vocal_src=(s0, round(end, 3)))]
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
        payload = {
            "shared_tempo_bpm": opts["master_bpm"],
            "phrase_anchors_seconds": [round(a, 1) for a in legal[:8]],
            "vocal_slices_seconds": [[round(s, 1), round(e, 1)] for s, e in opts["vocal_slices"]],
            "keys_compatible": opts["key_fit"],
            "user_request": prompt or "",
            "take_number": take,
            "make_it_different_from_previous_takes": take > 1,
        }
        msg = client.messages.create(
            model=_MODEL, max_tokens=600, system=_ARRANGE_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload)}],
        )
        data = _extract_json(msg.content[0].text)
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


def _dedupe_nonoverlapping(placements: list[Placement], stretch: float) -> list[Placement]:
    """Sort by anchor and drop any placement that would overlap the previous vocal —
    enforces one-voice-at-a-time before the render (the referee re-checks)."""
    kept: list[Placement] = []
    for p in sorted(placements, key=lambda pl: pl.anchor):
        if not kept:
            kept.append(p)
            continue
        if p.anchor >= fence.placement_end(kept[-1].anchor, kept[-1].vocal_src, stretch):
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
    placements = _dedupe_nonoverlapping(placements, opts["vocal_stretch"])
    first = placements[0]
    return MixPlan(
        mix_id=mix_id, song1_id=a1.song_id, song2_id=a2.song_id,
        master_bpm=opts["master_bpm"], vocal_stretch=opts["vocal_stretch"],
        vocal_src=first.vocal_src, anchor=first.anchor,  # scalar mirrors first (M3 back-compat)
        placements=placements, take=take, notes=_describe_arrangement(placements),
        confidence=0.75 if source == "ai" else 0.6, source=source,
    )
