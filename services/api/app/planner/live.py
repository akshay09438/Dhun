"""The live driver: turn a plain-language steering command into a structured LiveOp.

Slice 1 is a deterministic keyword parser for the lean command set; an LLM path will
sit in front of it later with this same function as the fallback (mirrors planner.plan).
The op is executed by the browser on the beat — this module never touches audio.
"""

from __future__ import annotations

from app.models import LiveOp

# Phrases that mean "remove Song 1's bassline", and "restore it".
_MUTE_BASS = ("take the bass out", "drop the bass", "bass out", "kill the bass", "no bass")
_UNMUTE = ("bring it back", "bring the bass back", "bass back", "back to normal", "undo")


def parse_command(text: str) -> LiveOp:
    """Map a typed command to a LiveOp. Unknown/out-of-scope asks are declined plainly."""
    t = " ".join(text.lower().split())
    if not t:
        return LiveOp(op="decline", say="Type a command like 'take the bass out'.")
    if any(p in t for p in _UNMUTE):
        return LiveOp(op="unmute", target="bass", say="bringing the bass back on the next bar")
    if any(p in t for p in _MUTE_BASS):
        return LiveOp(op="mute", target="bass", say="dropping the bass on the next bar")
    return LiveOp(
        op="decline",
        say="I can't do that in this version — try 'take the bass out' or 'bring it back'.",
        reason="out of scope",
    )
