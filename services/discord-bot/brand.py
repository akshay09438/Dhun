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

# The "Remix anything." strip. ONE file, TWO jobs, which is why it is named after the artwork
# rather than after either use:
#   * the strip behind the bot's picture on its PROFILE card. A DIFFERENT setting from BANNER
#     above, which is the SERVER header — that one Discord locks behind boost level 2, this one it
#     does not, so this applies today. Left flat purple, Discord invents a colour from the avatar
#     and the profile looks unfinished.
#   * the picture on the welcome post. The founder picked it over the wordmark disc (`LOGO`) on
#     2026-08-11: a 2.8:1 strip reads as a header and leaves the words room to breathe, where a
#     square disc fills the embed and pushes the copy off the first screen.
#
# 1360x480 is 2x the 680x240 Discord renders, so it stays sharp on a high-DPI screen. JPEG, not
# PNG, is deliberate: the artwork's film grain is nearly incompressible as PNG (1426 KB vs 102 KB
# for a visually identical JPEG at quality 94), and a 14x file for no visible gain is not worth it.
# The layout is avatar-aware — the avatar covers the bottom-left, so the wordmark sits top-left and
# the tagline bottom-RIGHT. Re-exporting the art without honouring that will bury the tagline.
REMIX_BANNER = ASSETS / "remix-banner.jpg"

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


# Which art was last uploaded for each slot, so a NEW export gets applied on the next start while
# an unchanged one doesn't burn Discord's rate limit (strict on both the avatar and the banner —
# they share one /users/@me budget). Per-installation state, not source.
def _marker_for(path: Path) -> Path:
    return ASSETS / f".applied-{path.stem}"


def art_fingerprint(path: Path) -> str | None:
    """A short hash of an artwork file, or None if it's missing."""
    data = image_bytes(path)
    return hashlib.sha256(data).hexdigest()[:16] if data else None


def art_needs_upload(path: Path) -> bool:
    """True when the shipped art differs from whatever was last uploaded for that slot. Comparing
    against Discord's copy is not viable — it re-encodes uploads, so the bytes never match — hence
    a local marker of what we last sent."""
    fp = art_fingerprint(path)
    if fp is None:
        return False
    try:
        return _marker_for(path).read_text(encoding="utf-8").strip() != fp
    except OSError:
        return True          # no marker yet -> never uploaded from this checkout


def mark_art_applied(path: Path) -> None:
    try:
        _marker_for(path).write_text(art_fingerprint(path) or "", encoding="utf-8")
    except OSError:
        pass                 # cosmetic bookkeeping; never worth failing a startup over


# The avatar's own marker predates the generic ones above and is named `.applied-avatar` rather
# than `.applied-icon`. Kept as-is: renaming it would read as "the art changed" on every existing
# install and re-upload an identical avatar against a strict rate limit, for no gain.
def icon_fingerprint() -> str | None:
    return art_fingerprint(ICON)


def avatar_needs_upload() -> bool:
    fp = icon_fingerprint()
    if fp is None:
        return False
    try:
        return (ASSETS / ".applied-avatar").read_text(encoding="utf-8").strip() != fp
    except OSError:
        return True


def mark_avatar_applied() -> None:
    try:
        (ASSETS / ".applied-avatar").write_text(icon_fingerprint() or "", encoding="utf-8")
    except OSError:
        pass


def emoji_files() -> list[tuple[str, Path]]:
    """(emoji_name, file) for every shipped emoji, in the order EMOJI_FALLBACK declares — so the
    upload order is stable and predictable rather than filesystem-dependent."""
    out: list[tuple[str, Path]] = []
    for name in EMOJI_FALLBACK:
        p = EMOJI_DIR / f"{name}.png"
        if p.exists():
            out.append((name, p))
    return out
