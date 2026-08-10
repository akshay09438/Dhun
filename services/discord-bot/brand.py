"""Grinder's brand in one place — the palette and the artwork.

Every colour and every image the bot shows comes from here, so a rebrand is one file. The hex
values are SAMPLED FROM THE FOUNDER'S ARTWORK (`Icon.png`, `Main logo.png`, the emoji set), not
picked by eye, so the cards match the logo exactly instead of approximately.

Note on the colour change (2026-08-10): the bot previously used `#6D3BF5`, the web app's original
"Electric Violet". The Grinder artwork is a RED-violet/magenta, so `#6D3BF5` — a BLUE-violet — read
as a second, clashing brand sitting next to the logo. PRIMARY is now the artwork's own purple.

Images are loaded lazily as bytes and cached: Discord wants raw bytes for an avatar, a guild icon
and a custom emoji, and the files are small enough that reading each once and keeping it costs
almost nothing.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "assets"

# --- palette (sampled from the artwork) ------------------------------------------------
PRIMARY = 0xA824CC     # the bright brand purple — the accent on every card the bot posts
DEEP = 0x600C9C        # the gradient's dark end; also the banner's dominant tone
MID = 0x8418C0         # mid-violet
PINK = 0xFC309C        # the emoji accent — highlights and "done" states
FAIL = 0xB00020        # unchanged: an error must not look like the brand

# --- artwork --------------------------------------------------------------------------
ICON = ASSETS / "icon.png"        # the "G" on vinyl grooves: bot avatar AND server icon
LOGO = ASSETS / "logo.png"        # the GRINDER wordmark disc: welcome post + /help
BANNER = ASSETS / "banner.png"    # glow banner — needs server boost level 2 before it can be set
EMOJI_DIR = ASSETS / "emojis"

# The custom emojis, and what each one is FOR. The bot uploads these to the server on /setup and
# then refers to them by name, falling back to a plain unicode glyph if a server has not got them
# (so every message still renders in a server where /setup was never run).
EMOJI_FALLBACK: dict[str, str] = {
    "grind_pair": "🎛️",      # two songs becoming one — the /mix identity
    "grind_shuffle": "🔄",    # "another take"
    "grind_mic": "🎤",        # the vocal song (Song 2)
    "grind_up": "➕",         # "add mix" in the set builder, energy moves
    "grind_fire": "🔥",       # the reaction for "I'd actually post this"
    "grind_moon": "🌙",       # late-night sessions in voice
}

_cache: dict[Path, bytes] = {}


def image_bytes(path: Path) -> bytes | None:
    """Raw bytes for Discord (avatar / guild icon / custom emoji). None if the file is missing, so
    a missing asset degrades to "skipped" instead of crashing a command."""
    if path in _cache:
        return _cache[path]
    try:
        data = path.read_bytes()
    except OSError:
        return None
    _cache[path] = data
    return data


# Which avatar art was last uploaded, so a NEW export gets applied on the next start while an
# unchanged one doesn't burn Discord's avatar rate limit. Per-installation state, not source.
_APPLIED_MARKER = ASSETS / ".applied-avatar"


def icon_fingerprint() -> str | None:
    """A short hash of the avatar art, or None if it's missing."""
    data = image_bytes(ICON)
    return hashlib.sha256(data).hexdigest()[:16] if data else None


def avatar_needs_upload() -> bool:
    """True when the shipped avatar art differs from whatever was last uploaded. Comparing against
    Discord's copy is not viable — it re-encodes uploads, so the bytes never match — hence a local
    marker of what we last sent."""
    fp = icon_fingerprint()
    if fp is None:
        return False
    try:
        return _APPLIED_MARKER.read_text(encoding="utf-8").strip() != fp
    except OSError:
        return True          # no marker yet -> never uploaded from this checkout


def mark_avatar_applied() -> None:
    try:
        _APPLIED_MARKER.write_text(icon_fingerprint() or "", encoding="utf-8")
    except OSError:
        pass                 # cosmetic bookkeeping; never worth failing a startup over


def emoji_files() -> list[tuple[str, Path]]:
    """(emoji_name, file) for every shipped emoji, in the order EMOJI_FALLBACK declares — so the
    upload order is stable and predictable rather than filesystem-dependent."""
    out: list[tuple[str, Path]] = []
    for name in EMOJI_FALLBACK:
        p = EMOJI_DIR / f"{name}.png"
        if p.exists():
            out.append((name, p))
    return out
