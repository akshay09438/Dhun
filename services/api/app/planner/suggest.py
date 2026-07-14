"""Per-section live suggestion chips.

For each of Song 1's sections, propose 1-3 live moves that fit that part of the song —
chosen ONLY from a closed vocabulary the live engine already executes (mute/unmute a part,
drop-to-the-beat, bring-it-all-back, fade). Claude picks; a deterministic label->chips
fallback runs on any AI failure, so suggestions work with no API key. One call per mix
(the route caches the result). Never touches audio — mirrors planner.plan's LLM-plans /
rules-fallback shape.
"""

from __future__ import annotations

import json
import os

from app.models import LiveChip, SectionSuggestions, TrackAnalysis
from app.planner import llm

_MAX_CHIPS = 3

# The closed vocabulary: chip text -> (op, targets). The brain may pick ONLY these.
_VOCAB: dict[str, tuple[str, list[str]]] = {
    "Bring the vocal in": ("unmute", ["vocals"]),
    "Take the vocal out": ("mute", ["vocals"]),
    "Take the bass out": ("mute", ["bass"]),
    "Drop to just the beat": ("mute", ["bass", "other", "vocals"]),
    "Bring it all back": ("unmute", ["drums", "bass", "other", "vocals"]),
    "Fade it out": ("fade", ["drums", "bass", "other", "vocals"]),
}
_DEFAULT_TEXTS = ["Drop to just the beat", "Bring it all back", "Fade it out"]

_SUGGEST_SYSTEM = (
    "You are a DJ suggesting live moves for a playing mix, section by section. For EACH "
    "section index, choose 1-3 moves that fit that part of the song, using ONLY this exact "
    "menu (copy the text verbatim): 'Bring the vocal in', 'Take the vocal out', 'Take the "
    "bass out', 'Drop to just the beat', 'Bring it all back', 'Fade it out'. Suit the move "
    "to the part: introduce/build in intros and choruses, strip back in breakdowns, fade in "
    "the outro. STRICT JSON only, nothing else: "
    '{"sections":{"<index>":["<move text>", ...]}}'
)


def _chip(text: str) -> LiveChip:
    op, targets = _VOCAB[text]
    return LiveChip(text=text, op=op, targets=list(targets))


def _fallback_texts(label: str) -> list[str]:
    """Deterministic label -> chip texts (the fallback, and the AI's menu framing)."""
    l = label.lower()
    if "intro" in l or "start" in l:
        return ["Bring the vocal in", "Drop to just the beat"]
    if "chorus" in l:
        return ["Bring the vocal in", "Bring it all back"]
    if "verse" in l:
        return ["Take the bass out", "Drop to just the beat"]
    if "bridge" in l or "break" in l:
        return ["Drop to just the beat", "Take the vocal out"]
    if "outro" in l or "end" in l:
        return ["Fade it out", "Bring it all back"]
    return ["Drop to just the beat", "Bring it all back"]


def _sections_of(a1: TrackAnalysis) -> list[tuple[float, float, str]]:
    secs = [(float(s.start), float(s.end), s.label) for s in a1.sections]
    if not secs:  # thin/absent structure -> one default section spanning the track
        return [(0.0, 1.0e9, "track")]
    return secs


def _ai_suggest(sections: list[tuple[float, float, str]], prompt: str) -> dict[int, list[str]] | None:
    """Ask Claude for per-section chip texts. Returns {section_index: [text, ...]} with only
    known-vocabulary texts kept, or None on any failure (caller then uses the fallback)."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import anthropic

        # Explicit short timeout: this runs in-request, so a hung API must fall back fast
        # (any error is caught below → deterministic chips), honoring the "instant" promise.
        client = anthropic.Anthropic(api_key=key, timeout=8.0)
        payload = {
            "sections": [{"index": i, "label": lbl, "start": round(s0, 1)}
                         for i, (s0, _s1, lbl) in enumerate(sections)],
            "menu": list(_VOCAB.keys()),
            "user_request": prompt or "",
        }
        msg = client.messages.create(
            model=llm.MODEL, max_tokens=600, system=_SUGGEST_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload)}],
        )
        raw = llm.extract_json(llm.first_text(msg)).get("sections", {})
        result: dict[int, list[str]] = {}
        for k, texts in raw.items():
            try:
                idx = int(k)
            except (TypeError, ValueError):
                continue
            kept = [t for t in texts if t in _VOCAB][:_MAX_CHIPS]
            if kept:
                result[idx] = kept
        return result or None
    except Exception:
        return None


def _merge_same(out: list[SectionSuggestions]) -> list[SectionSuggestions]:
    """Collapse consecutive sections whose chips are identical into one span — so the live
    chips only 'change' at a genuine transition, not across repeated same-suggestion parts."""
    merged: list[SectionSuggestions] = []
    for s in out:
        prev = merged[-1] if merged else None
        if prev and [c.text for c in prev.chips] == [c.text for c in s.chips]:
            prev.end = s.end  # extend the previous span over this identical one
        else:
            merged.append(s)
    return merged


def suggest_moves(a1: TrackAnalysis, prompt: str = "") -> list[SectionSuggestions]:
    """1-3 suggestion chips per Song-1 section, AI-picked with a deterministic fallback."""
    sections = _sections_of(a1)
    ai = _ai_suggest(sections, prompt) or {}
    out: list[SectionSuggestions] = []
    for i, (s0, s1, label) in enumerate(sections):
        texts = ai.get(i) or (_fallback_texts(label) if a1.sections else _DEFAULT_TEXTS)
        chips = [_chip(t) for t in texts if t in _VOCAB][:_MAX_CHIPS]
        if not chips:  # guard: never emit an empty section
            chips = [_chip(t) for t in _fallback_texts(label)][:_MAX_CHIPS]
        out.append(SectionSuggestions(start=s0, end=s1, label=label, chips=chips))
    return _merge_same(out)
