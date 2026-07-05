"""The AI driver: pick a MixPlan from the fence's legal options.

The rules (fence) decide what is LEGAL; here the brain picks what is TASTEFUL among
those legal options. Claude chooses which drop to land the vocal on and small
touches (a one-bar beat breath before it enters). It only ever selects from options
the fence already cleared, and on any failure — no API key, network error, or
malformed output — we fall back to the deterministic 'obvious best' pick, so a mix
never blocks on the AI. The LLM never touches audio; it only fills this structured
plan (technical-spec's one architectural principle).
"""

from __future__ import annotations

import json
import os

from app.models import MixPlan, TrackAnalysis
from app.planner import fence

# A small, fast model is plenty for choosing among a handful of pre-vetted options.
_MODEL = "claude-sonnet-5"

_SYSTEM = (
    "You are a skilled DJ deciding where to drop Song 2's vocal over Song 1's beat. "
    "You are given a list of legal, phrase-aligned drop points (in seconds) already "
    "ranked best-first, the shared tempo, and whether the keys are compatible. Pick "
    "the ONE drop that lands the vocal on the biggest, most intentional moment. Set "
    "beat_breath=true only when cutting Song 1's beat for one bar right before the "
    "vocal would make a punchier re-entry. Reply with STRICT JSON and nothing else: "
    '{"chosen_drop_index": <int>, "beat_breath": <bool>, "why": "<one short DJ-language sentence>"}'
)


class MixDeclined(Exception):
    """The pair cannot be mixed cleanly; carries a plain-language reason for the user."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _describe(anchor: float) -> str:
    m, s = divmod(int(anchor), 60)
    return f"Song 2's vocal enters on the drop at {m}:{s:02d}, tempo-locked to Song 1."


def _extract_json(text: str) -> dict:
    """Tolerate a model that wraps its JSON in prose or a code fence."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model output")
    return json.loads(text[start : end + 1])


def _ai_choose(opts: dict, prompt: str) -> tuple[int, bool, str] | None:
    """Ask Claude to pick a drop. Returns (drop_index, beat_breath, why) or None on
    any failure (missing key, network, bad output) — the caller then falls back."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    drops = opts["drops"][:6]  # a small menu is enough in M3
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        payload = {
            "shared_tempo_bpm": opts["master_bpm"],
            "drop_options_seconds": [round(d, 1) for d in drops],
            "keys_compatible": opts["key_fit"],
            "user_request": prompt or "",
        }
        msg = client.messages.create(
            model=_MODEL,
            max_tokens=300,
            system=_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload)}],
        )
        data = _extract_json(msg.content[0].text)
        idx = int(data["chosen_drop_index"])
        if not 0 <= idx < len(drops):
            return None
        return idx, bool(data.get("beat_breath", False)), str(data.get("why", ""))[:200]
    except Exception:
        return None


def _plan_from(mix_id: str, a1: TrackAnalysis, a2: TrackAnalysis, opts: dict,
               anchor: float, beat_breath: bool, notes: str, source: str,
               confidence: float) -> MixPlan:
    return MixPlan(
        mix_id=mix_id, song1_id=a1.song_id, song2_id=a2.song_id,
        master_bpm=opts["master_bpm"], vocal_stretch=opts["vocal_stretch"],
        vocal_src=opts["vocal_src"], anchor=anchor, beat_breath=beat_breath,
        notes=notes or _describe(anchor), confidence=confidence, source=source,
    )


def build_mix_plan(mix_id: str, a1: TrackAnalysis, a2: TrackAnalysis,
                   prompt: str = "") -> MixPlan:
    """Produce the recipe for one mix. Raises MixDeclined if the pair can't blend."""
    opts = fence.legal_options(a1, a2)
    if not opts["mixable"]:
        raise MixDeclined(opts["reason"])

    choice = _ai_choose(opts, prompt)
    if choice is None:  # deterministic fallback — the obvious best drop
        return _plan_from(mix_id, a1, a2, opts, opts["drops"][0], False, "",
                          source="rules", confidence=0.6)

    # M3 keeps Song 1's beat playing continuously under the vocal. The AI may still
    # pick the drop, but we force beat_breath off: a full-bar beat drop rendered as
    # dead air (~2s of silence before the vocal), which sounds like the song paused.
    # A real DJ breath (tension, not silence) is an M4 move once the engine supports it.
    idx, _breath, why = choice
    return _plan_from(mix_id, a1, a2, opts, opts["drops"][idx], False, why,
                      source="ai", confidence=0.75)
