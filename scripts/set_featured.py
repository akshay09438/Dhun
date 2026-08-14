"""Choose the 25 songs shown in each Discord dropdown, and mark them in the manifest.

    services/api/.venv/Scripts/python.exe scripts/set_featured.py            # DRY RUN
    services/api/.venv/Scripts/python.exe scripts/set_featured.py --apply

WHY THIS EXISTS. A Discord select menu holds 25 options, full stop, and `select_option_specs` takes
the first 25 in list order - so with 63 beats and 59 English vocals, 72 songs were simply
unreachable, and WHICH 25 appeared was an accident of manifest order. Founder, 2026-08-14: keep a
curated catalogue rather than adding search. This is that catalogue.

THE SELECTION RULE, AND WHY IT IS NOT ALPHABETICAL. Measured on the real catalog: **26 of 59
English vocals pair with NO house beat at all.** They sit in a ~75-100 BPM dead zone - too slow to
ride a 120-130 beat at 1:1, too fast to work at half-time - so the planner can only reach them by
stretching past the point where a voice warbles. Filling the dropdown alphabetically would hand the
founder a menu where a third of the choices cannot make a mix. So:

  * BEATS: the house band (118-132 BPM), which is where 39 of 63 already sit, spread evenly across
    the band rather than clustered on one tempo.
  * ENGLISH VOCALS: ranked by how many of those chosen beats they actually pair with - counting
    1:1, double-time and half-time, each within +/-15% - then the top 25.
  * BOLLYWOOD VOCALS: all of them. There are only 14, which is already under the limit.

A song is "pairable" here on tempo alone. Key is deliberately NOT part of the ranking: the engine
pitch-shifts to fit, and the key referee has its own say at render time.

Swapping a song later is a one-line edit to PINNED / BANNED below, then re-run. The manifest is
local-only (gitignored), so this writes data on this machine, not into git.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_DATA = _REPO / "services" / "api" / "data"
_MANIFEST = _DATA / "library" / "manifest.json"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
APPLY = "--apply" in sys.argv

PER_LIST = 25
HOUSE_LO, HOUSE_HI = 118, 132
TOLERANCE = 0.15

# Founder overrides, matched on a substring of the song name. PINNED is always in, BANNED always
# out, whatever the ranking says - the founder knows which songs people actually want to hear, and
# recognisability is a real quality the tempo maths cannot see.
#
# 2026-08-14: the founder swapped six mid-tier pop vocals for six far bigger songs. All six incoming
# are 74-95 BPM hip-hop/pop and paired with ZERO of the house beats then on show, so four slower
# beats are pinned alongside them - otherwise those six would sit in the menu unable to make a
# single mix. Pin vocals and beats together or the menu looks fuller than it is.
PINNED: set[str] = {
    # --- VOCALS the founder asked for (2026-08-14) ---
    "God's Plan", "Location", "SICKO MODE", "Shape of You", "Intentions", "Watermelon Sugar",
    # --- BEATS the founder asked for (2026-08-14) ---
    "Let Me Love You", "One Dance", "Lose My Mind", "All The Stars", "Losing It",
    "Reminder", "Sirens", "Starboy", "Summertime Sadness", "São Paulo",
    # second round of beat swaps, same evening
    "Feel So Close", "Calm Down", "Habits", "This Is What You Came For",
    # --- beats kept to carry the slow vocals above (85-90 BPM; the 167 works at half-time) ---
    # Merrygo beat WAS here and the founder has since dropped it, so it is gone from the pin list
    # rather than only added to BANNED - a pin beats a ban, so leaving it here would have kept it.
    "redrum", "Faded",
}
BANNED: set[str] = {
    # vocals dropped by the founder
    "Beautiful Things", "abcdefu", "Someone You Loved", "greedy", "Flowers", "Gimme! Gimme! Gimme!",
    # beats dropped by the founder. "Water (Tyla)" is spelled out in full on purpose: a bare "Water"
    # also matches "Watermelon Sugar", which is pinned. The pinned-wins rule in is_banned() covers
    # that too, but being precise here means the collision never has to be caught at all.
    "Hey Brother", "Rasputin", "Cola", "Tremor", "Fire Fire", "Water (Tyla)",
    "Animals", "Titanium", "Waiting For Love",
    # second round, same evening
    "Merrygo beat", "Levels", "Satisfaction", "In My Mind",
}


def is_pinned(name: str) -> bool:
    return any(p.lower() in name.lower() for p in PINNED)


def is_banned(name: str) -> bool:
    """PINNED BEATS BANNED, always.

    These are substring matches, and substrings collide: banning "Water" (the Tyla beat) also
    matches "WATERmelon Sugar", a vocal the founder had just asked to keep. Rather than rely on
    everyone spotting that, an explicit keep always wins over an explicit drop - the safe direction,
    since the worst case is a song appearing that someone wanted gone, not a requested song
    silently vanishing.
    """
    if is_pinned(name):
        return False
    return any(b.lower() in name.lower() for b in BANNED)


def bpm_of(song_id: str) -> int:
    p = _DATA / f"{song_id}.analysis.json"
    if not p.exists():
        return 0
    try:
        return round(json.loads(p.read_text(encoding="utf-8")).get("bpm") or 0)
    except (OSError, json.JSONDecodeError):
        return 0


def pairs(beat_bpm: int, vocal_bpm: int) -> bool:
    """Tempo-compatible if the vocal fits at 1:1, double-time or half-time within tolerance."""
    if not beat_bpm or not vocal_bpm:
        return False
    return any(abs(c - beat_bpm) / beat_bpm <= TOLERANCE
               for c in (vocal_bpm, vocal_bpm * 2, vocal_bpm / 2))


def spread(items, n):
    """Take n items spread evenly across a BPM-sorted list, so the menu is not all one tempo."""
    items = sorted(items, key=lambda s: s["bpm"])
    if len(items) <= n:
        return items
    step = len(items) / n
    return [items[int(i * step)] for i in range(n)]


def main() -> int:
    entries = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    for e in entries:
        e["bpm"] = bpm_of(e["song_id"])

    def group(role, lang=None):
        return [e for e in entries
                if e["role_hint"] == role
                and (lang is None or e.get("language") == lang)
                and not is_banned(e["name"])]

    beats_all = group("beat")
    # Pinned beats come FIRST and are never squeezed out — an earlier version appended them and then
    # truncated back to 25, which silently dropped the very beats that were pinned to make the
    # pinned vocals workable.
    beats = [b for b in beats_all if is_pinned(b["name"])]
    house = [b for b in beats_all if HOUSE_LO <= b["bpm"] <= HOUSE_HI and b not in beats]
    beats += spread(house or [b for b in beats_all if b not in beats], PER_LIST - len(beats))
    beats = beats[:PER_LIST]

    def pick_vocals(lang):
        pool = group("vocals", lang)
        if len(pool) <= PER_LIST:
            return pool, {}
        scored = {v["song_id"]: sum(1 for b in beats if pairs(b["bpm"], v["bpm"])) for v in pool}
        pinned = [v for v in pool if is_pinned(v["name"])]
        rest = sorted((v for v in pool if v not in pinned),
                      key=lambda v: (-scored[v["song_id"]], v["name"].lower()))
        return (pinned + rest)[:PER_LIST], scored

    eng, eng_scores = pick_vocals("english")
    boll, boll_scores = pick_vocals("bollywood")
    chosen = {e["song_id"] for e in beats + eng + boll}

    for label, sel, scores, pool in (
            ("BEATS", beats, {}, beats_all),
            ("ENGLISH VOCALS", eng, eng_scores, group("vocals", "english")),
            ("BOLLYWOOD VOCALS", boll, boll_scores, group("vocals", "bollywood"))):
        print(f"\n=== {label}: showing {len(sel)} of {len(pool)} ===")
        for s in sorted(sel, key=lambda x: x["bpm"]):
            note = f"  pairs with {scores[s['song_id']]}/{len(beats)} beats" if scores else ""
            print(f"   {s['bpm']:>4} BPM  {s['name'][:50]:<50}{note}")
        dropped = [p for p in pool if p["song_id"] not in chosen]
        if dropped:
            print(f"   -- not shown ({len(dropped)}): "
                  + ", ".join(sorted(d["name"][:24] for d in dropped)[:6])
                  + (" ..." if len(dropped) > 6 else ""))

    workable = sum(1 for b in beats for v in eng + boll if pairs(b["bpm"], v["bpm"]))
    print(f"\n  workable pairings inside this catalogue: {workable} of "
          f"{len(beats) * len(eng + boll)}")

    for e in entries:
        e.pop("bpm", None)
        if e["song_id"] in chosen:
            e["featured"] = True
        else:
            e.pop("featured", None)

    if not APPLY:
        print("\nDRY RUN - nothing written. Add --apply to write it.")
        return 0

    tmp = _MANIFEST.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, _MANIFEST)
    n = sum(1 for e in json.loads(_MANIFEST.read_text(encoding="utf-8")) if e.get("featured"))
    print(f"\nWRITTEN. {n} songs marked featured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
