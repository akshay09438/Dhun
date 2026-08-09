"""Pure helpers for the Discord bot — no Discord objects, no network, easy to unit-test.

Kept separate from bot.py so the mixing-style label and the autocomplete matcher can be
tested without a bot token or a live gateway connection.
"""
from __future__ import annotations

# The three shipped mixing styles (the engine's rules 1/3/4). The user never picks these —
# the engine auto-assigns one per take — but showing the label makes the variety visible,
# exactly like the web app does.
_STYLE = {1: "Simple", 3: "Chop & repeat", 4: "Echo"}


def style_label(rule: int | None, notes: str | None = None) -> str:
    """A short, friendly name for the mixing style used, from the plan's rule number
    (preferred) or, as a fallback, a keyword in the plan's notes."""
    if rule in _STYLE:
        return _STYLE[rule]
    n = (notes or "").lower()
    if "chop" in n:
        return "Chop & repeat"
    if "echo" in n:
        return "Echo"
    return "Simple"


def match_songs(pool, current: str | None, limit: int = 25):
    """Case-insensitive substring filter over a list of songs (each with a `.name`),
    capped to Discord's 25-choice autocomplete limit. Returns the matching songs."""
    cur = (current or "").lower().strip()
    if not cur:
        return list(pool)[:limit]
    return [s for s in pool if cur in s.name.lower()][:limit]


def safe_filename(name: str | None, fallback: str = "mix") -> str:
    """A filesystem/Discord-safe attachment name derived from a mix's display name."""
    keep = "".join(c if (c.isalnum() or c in " -_") else "_" for c in (name or "")).strip()
    return (keep or fallback)[:60]
