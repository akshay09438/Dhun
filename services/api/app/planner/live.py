"""The live driver: turn a plain-language steering command into a structured LiveOp.

Slice 2 grows the lean command set to every part (drums/bass/other/vocals) plus the
"drop everything but the beat" combo. Still deterministic; an LLM path will sit in
front of it later with this same function as the fallback (mirrors planner.plan).
The op is executed by the browser on the beat — this module never touches audio.
"""

from __future__ import annotations

from app.models import LiveOp

_ALL = ["drums", "bass", "other", "vocals"]

# Phrase -> the bus a single-part command targets.
_MUTE_BASS = ("take the bass out", "drop the bass", "bass out", "kill the bass", "no bass")
_UNMUTE_BASS = ("bring the bass back", "bass back")
_MUTE_VOCALS = ("remove the vocals", "take the vocals out", "drop the vocals", "no vocals",
                "kill the vocals", "mute the vocals", "vocals out")
_UNMUTE_VOCALS = ("bring the vocals back", "vocals back", "add the vocals", "add vocals")
_MUTE_DRUMS = ("take the drums out", "drop the drums", "no drums", "mute the drums", "drums out")
_UNMUTE_DRUMS = ("bring the drums back", "drums back")
_MUTE_OTHER = ("take the melody out", "drop the melody", "no melody", "mute the melody", "melody out")
_UNMUTE_OTHER = ("bring the melody back", "melody back")
# Combos.
_JUST_DRUMS = ("drop everything but the beat", "just the drums", "only the beat", "beat only",
               "everything but the beat")
_ALL_BACK = ("bring it all back", "bring everything back", "full mix", "all back", "reset the mix")
# Slice-1 generic "bring it back" / undo -> restore the bass (kept for back-compat).
_UNMUTE_GENERIC = ("bring it back", "back to normal", "undo")
_FADE = ("fade away", "fade it out", "fade out", "fade the mix out", "fade the music out")


def _mute(targets: list[str], say: str) -> LiveOp:
    return LiveOp(op="mute", targets=targets, target=(targets[0] if len(targets) == 1 else None), say=say)


def _unmute(targets: list[str], say: str) -> LiveOp:
    return LiveOp(op="unmute", targets=targets, target=(targets[0] if len(targets) == 1 else None), say=say)


def parse_command(text: str) -> LiveOp:
    """Map a typed command to a LiveOp. Unknown/out-of-scope asks are declined plainly."""
    t = " ".join(text.lower().split())
    if not t:
        return LiveOp(op="decline", say="Type a command like 'take the bass out'.")

    if any(p in t for p in _FADE):
        return LiveOp(op="fade", targets=list(_ALL), say="fading the whole mix out")

    # Combos first (they contain words that would otherwise match single parts).
    if any(p in t for p in _ALL_BACK):
        return _unmute(list(_ALL), "bringing the whole mix back on the next bar")
    if any(p in t for p in _JUST_DRUMS):
        return _mute(["bass", "other", "vocals"], "dropping everything but the beat on the next bar")

    # Single parts — unmute checked before mute per part so "bring the X back" wins over "X out".
    if any(p in t for p in _UNMUTE_VOCALS):
        return _unmute(["vocals"], "bringing the vocals back on the next bar")
    if any(p in t for p in _MUTE_VOCALS):
        return _mute(["vocals"], "pulling the vocals on the next bar")
    if any(p in t for p in _UNMUTE_DRUMS):
        return _unmute(["drums"], "bringing the drums back on the next bar")
    if any(p in t for p in _MUTE_DRUMS):
        return _mute(["drums"], "dropping the drums on the next bar")
    if any(p in t for p in _UNMUTE_OTHER):
        return _unmute(["other"], "bringing the melody back on the next bar")
    if any(p in t for p in _MUTE_OTHER):
        return _mute(["other"], "pulling the melody on the next bar")
    if any(p in t for p in _UNMUTE_BASS):
        return _unmute(["bass"], "bringing the bass back on the next bar")
    if any(p in t for p in _UNMUTE_GENERIC):
        return _unmute(["bass"], "bringing the bass back on the next bar")
    if any(p in t for p in _MUTE_BASS):
        return _mute(["bass"], "dropping the bass on the next bar")

    return LiveOp(
        op="decline",
        say="I can't do that in this version — try 'take the bass out', 'remove the vocals', or 'drop everything but the beat'.",
        reason="out of scope",
    )
