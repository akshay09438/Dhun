"""Turn the founder's raw brand exports into the small, Discord-sized files the bot ships with.

Run this again whenever the artwork changes:

    python services/discord-bot/scripts/prepare_assets.py "C:/path/to/Grinder assets"

Why this exists rather than committing the raw exports: the source art is 2048-4096px and 7-14 MB
per file, which is far larger than anything Discord displays (an avatar renders at 128px, an emoji
at 128px, a server banner at 960x540). Shipping the raw files would bloat the repo for no visible
gain, and Discord rejects an emoji over 256 KB outright. So the raw art stays on the founder's
drive as the master, and this script produces the committed, runtime copies.

Deliberately NOT copied: the four "Avatar *.png" exports. Every one of them is broken the same way
(the disc is sliced horizontally, the halves offset, and the G mashed into a blob), which points at
a shifted layer or a broken clipping mask in the source. `Icon.png` is the correct avatar art.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

OUT = Path(__file__).resolve().parent.parent / "assets"

# (source name, output name, size) — each size is what Discord actually renders, not more.
IMAGES: tuple[tuple[str, str, tuple[int, int]], ...] = (
    # The bot's avatar AND the server icon. Discord shows an avatar at 128px at most, so 512 is
    # already generous and keeps the file tiny.
    # FOUNDER'S CHOICE (2026-08-11): the split-disc "Avatar biggest size.png", not the "G" mark.
    # Flagged twice that the disc reads as sliced into two offset halves with no G — if that is
    # deliberate (a cut record) it is a design decision, not a defect, and it is the founder's call.
    # `Icon.png` (the G) stays in the source folder if it is ever wanted back.
    ("Avatar biggest size.png", "icon.png", (512, 512)),
    # The GRINDER wordmark disc: the picture on the welcome post and /help. Discord renders an
    # embed image about 400px wide, so 640 is already more than it can show — and the grain in the
    # source art compresses badly, so every extra pixel costs real bytes for no visible gain.
    ("Main logo.png", "logo.png", (640, 640)),
    # The glow banner. 960x540 is Discord's server-banner size, and the source is already 16:9,
    # so this is a clean downscale with no cropping. Cannot be APPLIED until the server reaches
    # boost level 2 — committed now so it is ready the moment it can be used.
    ("grinder-banner-glow-3840.png", "banner.png", (960, 540)),
)

# Custom emojis. Discord's hard cap is 256 KB; 128x128 is the display size.
EMOJI_SIZE = (128, 128)
EMOJI_MAX_BYTES = 256 * 1024


def _save(im: Image.Image, path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, "PNG", optimize=True)
    return path.stat().st_size


def main(src_dir: str) -> int:
    src = Path(src_dir)
    if not src.is_dir():
        print(f"ERROR: not a folder: {src}")
        return 1

    print(f"source: {src}\noutput: {OUT}\n")
    missing: list[str] = []

    for name, out_name, size in IMAGES:
        p = src / name
        if not p.exists():
            missing.append(name)
            continue
        with Image.open(p) as im:
            im = im.convert("RGBA")
            im.thumbnail(size, Image.LANCZOS)
            kb = _save(im, OUT / out_name) / 1024
        print(f"  {out_name:12s} {im.size[0]:4d}x{im.size[1]:<4d} {kb:7.0f} KB")

    emoji_src = src / "Emojis"
    if emoji_src.is_dir():
        print()
        for p in sorted(emoji_src.glob("*.png")):
            with Image.open(p) as im:
                im = im.convert("RGBA")
                im.thumbnail(EMOJI_SIZE, Image.LANCZOS)
                out = OUT / "emojis" / p.name.lower()
                n = _save(im, out)
            flag = "" if n <= EMOJI_MAX_BYTES else "  !! OVER DISCORD'S 256 KB EMOJI LIMIT"
            print(f"  emojis/{p.name.lower():20s} {n / 1024:6.0f} KB{flag}")
    else:
        missing.append("Emojis/")

    if missing:
        print("\nMISSING from the source folder: " + ", ".join(missing))
    total = sum(f.stat().st_size for f in OUT.rglob("*.png")) / 1024
    print(f"\ntotal shipped: {total:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else ""))
