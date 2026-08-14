"""Put the artist after every song name in the catalog: "Title (Artist)".

    services/api/.venv/Scripts/python.exe scripts/name_with_artist.py            # DRY RUN
    services/api/.venv/Scripts/python.exe scripts/name_with_artist.py --apply

WHY. Founder, 2026-08-14: "after all songs name, please write the artists name, very important."
A picker showing "Location", "ten", "Circles" is a memory test - two of those are famous songs and
one is unguessable. With the artist attached, a person recognises what they are choosing.

WHERE THE ARTIST COMES FROM. The ORIGINAL filename, recovered via `data/marks_id_cache.json`
(filename -> content id, built by scripts/generate_marks.py). That is the only honest record of who
made a track: the manifest name has already been shortened, and guessing an artist from a title is
exactly how "Better (Khalid)" gets confused with "Better Off Alone (Alice Deejay)".

Most files are "Artist - Title". A few are the other way round ("Ghost - Justin Bieber (128k)"),
detected by the (128k) tag their source left behind. Anything with no artist in the filename at all
is REPORTED AND LEFT ALONE rather than invented - see UNKNOWN in the output and fix those by hand
in BY_HAND below.

Discord truncates a dropdown label at 100 characters, so names are kept tight: junk like
"(Official Video)" and "ft. …" is dropped, and a very long artist list is cut to the first two.
The manifest is local-only (gitignored), so this writes data on this machine, not into git.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_DATA = _REPO / "services" / "api" / "data"
_MANIFEST = _DATA / "library" / "manifest.json"
_CACHE = _DATA / "marks_id_cache.json"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
APPLY = "--apply" in sys.argv

MAX_LEN = 90        # Discord's label cap is 100; leave headroom

# Songs whose source filename carries no artist. Named BY HAND, and only where the credit is not in
# doubt - a confidently wrong artist is worse than a missing one, and this list is shown to users.
# Anything not here is reported as UNKNOWN and left alone for the founder to fill in.
# Final names set outright, where the TITLE itself is wrong or two songs would otherwise collide.
# Keyed by the exact current name.
RENAME = {
    # The file was just "F1.mp3". Founder 2026-08-14: "Lose my mind - F1" - the track is Lose My
    # Mind, from the F1 soundtrack. Keeping F1 as the qualifier rather than asserting it as an
    # artist, which it is not.
    "F1": "Lose My Mind (F1)",
    # TWO different songs were both called "Move" and both were on the menu. Same artist, different
    # lengths - 5:53 and 2:58 - so the short one is labelled as such. Founder gave "Move - Adam Port".
    "Move": "Move - Short Edit (Adam Port)",
}

BY_HAND = {
    "Merrygo beat": "adiwav Remix",
    "Wari Jawa": "Shashwat Sachdev",
    # --- founder-supplied, 2026-08-14 ---
    "Tere Bina": "A.R. Rahman",
    "Jugni Ji": "Kanika Kapoor",
    "Tere Bin": "Rabbi Shergill",
    "Mera Yaar": "Farhan Akhtar",
    "Khuda Jaane": "Vishal & Shekhar",
    "Nadan Parinde": "Mohit Chauhan",
    "Uff Teri Ada": "Shankar Mahadevan",
    "Dooriyan": "Mohit Chauhan",
    "Woh Lamhe Woh Baatein": "Atif Aslam",
    "Hum Pyaar Karne Wale": "Dhurandhar",
    "Silence": "Marshmello",
    "Starboy": "The Weeknd",
    "Reminder": "The Weeknd",
    "I Was Never There": "The Weeknd",
    "Pray For Me": "The Weeknd, Kendrick Lamar",
    "Don't You Worry Child": "Swedish House Mafia",
    "Waiting For Love": "Avicii",
    "Losing It": "FISHER",
    "redrum": "21 Savage",
    "ten": "Fred again..",
    "Ride It": "Regard",
}

JUNK = re.compile(r"\b(official|music\s+video|video|lyrics?|audio|visuali[sz]er|hd|4k|hq|128k|"
                  r"full\s+song|full\s+video|extended\s+mix|extended\s+version|"
                  r"sopot\s+festival\s+\d+|jhankar)\b", re.I)


def tidy(s: str) -> str:
    prev = None
    while prev != s:                       # unwrap nested brackets
        prev = s
        s = re.sub(r"\(([^()]*)\)|\[([^\[\]]*)\]",
                   lambda m: "" if not re.search(r"[a-z]", JUNK.sub("", m.group(1) or m.group(2) or ""), re.I)
                   else "(" + JUNK.sub("", m.group(1) or m.group(2)).strip() + ")", s)
    s = JUNK.sub(" ", s)
    s = re.sub(r"\s*\(\s*\)|\s*\(\s*$", "", s)
    return re.sub(r"\s{2,}", " ", s).strip(" -–—_,.")


def split_outer(s: str):
    """Split on the first ' - ' outside brackets."""
    depth = 0
    for i in range(len(s) - 2):
        if s[i] in "([":
            depth += 1
        elif s[i] in ")]":
            depth = max(0, depth - 1)
        elif depth == 0 and s[i] == " " and s[i + 1] in "-–" and s[i + 2] == " ":
            return s[:i], s[i + 3:]
    return None, None


def artist_from(filename: str) -> str:
    stem = os.path.splitext(filename)[0]
    left, right = split_outer(stem)
    if left is None:
        return ""
    # "Title - Artist (128k)" is the reversed form a couple of sources produced.
    artist = left if not re.search(r"\(128k\)\s*$", right) else right
    artist = re.sub(r"\s*\b(ft|feat)\b\.?\s.*$", "", artist, flags=re.I)
    artist = tidy(artist)
    parts = [p.strip() for p in re.split(r",|&|\bx\b", artist) if p.strip()]
    if len(parts) > 2:
        artist = f"{parts[0]}, {parts[1]}"
    return artist


def main() -> int:
    entries = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    cache = json.loads(_CACHE.read_text(encoding="utf-8")) if _CACHE.exists() else {}
    by_id = {sid: fn for fn, sid in cache.items()}

    renames, unchanged, unknown = [], 0, []
    for e in entries:
        name = e["name"]
        if name in RENAME:                      # an outright new name wins over artist-appending
            renames.append((e, name, RENAME[name]))
            continue
        base = re.sub(r"\s*\([^()]*\)\s*$", "", name).strip() or name   # strip a trailing "(Artist)"
        artist = BY_HAND.get(base) or BY_HAND.get(name) or artist_from(by_id.get(e["song_id"], ""))

        if not artist:
            unknown.append(e)
            continue
        # Already credited? Compare on letters only. "Say What (Keinemusik (Rampa, &ME, Adam Port))"
        # carries its artist inside nested brackets, and a raw substring test misses it - which
        # produced "Say What (Keinemusik (...)) (Keinemusik (Rampa, ME)" on the first run.
        def letters(x):
            return re.sub(r"[^a-z0-9]", "", x.lower())

        if letters(artist) and letters(artist) in letters(name):
            unchanged += 1
            continue
        new = f"{base} ({artist})"
        if len(new) > MAX_LEN:
            new = f"{base[:MAX_LEN - len(artist) - 4]} ({artist})"
        renames.append((e, name, new))

    print(f"catalog: {len(entries)}")
    print(f"  already credited : {unchanged}")
    print(f"  will rename      : {len(renames)}")
    print(f"  NO artist known  : {len(unknown)}\n")
    for _e, old, new in sorted(renames, key=lambda r: r[2].lower()):
        print(f"   {old[:44]:<44} ->  {new}")
    if unknown:
        print("\n  LEFT ALONE - no artist in the source filename. Add them to BY_HAND:")
        for e in unknown:
            print(f"   {e['name']}")

    if not APPLY:
        print("\nDRY RUN - nothing written. Add --apply to write it.")
        return 0

    for e, _old, new in renames:
        e["name"] = new
    tmp = _MANIFEST.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, _MANIFEST)
    print(f"\nWRITTEN. {len(renames)} songs renamed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
