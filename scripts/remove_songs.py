"""Remove songs from the catalog completely - manifest entry, master, stems and analysis.

    services/api/.venv/Scripts/python.exe scripts/remove_songs.py            # DRY RUN
    services/api/.venv/Scripts/python.exe scripts/remove_songs.py --apply

THIS IS THE IRREVERSIBLE ONE. The stems and the analysis were PAID FOR on Replicate, and they are
cached by the song's content hash - so deleting them means re-paying to get that song back, and at
the time of writing the account balance is zero. Everything else in this repo can be rebuilt for
free; this cannot. Hence: dry run by default, exact-name matching only, and a printed list before
anything is touched.

MATCHING IS EXACT-ISH ON PURPOSE. Elsewhere a substring match was enough, and it bit twice in one
evening: "Water" also matches "WATERmelon Sugar", and "Stay" also matches "Habits (STAY High)".
Getting that wrong when the operation is a delete would destroy a song nobody asked to lose, so a
name here must match the START of the catalog name and be listed under the right role. Anything
that matches nothing, or matches more than one song, is REPORTED and skipped.

Founder's list, 2026-08-14 - songs they do not want, cleared both to tidy the catalog and to get
free disk back above the 6 GB line where the app stops deleting its own pitch-shift caches (which
is what made mixes take 37s instead of 20s).
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

REMOVE_BEATS = [
    "Levels", "Satisfaction", "Rasputin", "Cola", "Titanium", "Tremor",
    "Turn Down for What", "In My Mind", "Animals", "Don't Let Me Down", "Roses",
    "Water (Tyla)", "Waiting For Love",
]
REMOVE_VOCALS = [
    "In Da Club", "Gimme! Gimme! Gimme!", "I Want It That Way", "Pretty Little Baby",
    "Houdini", "abcdefu", "Flowers", "We Found Love", "Espresso", "greedy", "Cruel Summer",
]

# Every file a song owns. `.wav` is the master; the four stems and the analyses are the paid work.
SUFFIXES = (".wav", ".vocals.mp3", ".drums.mp3", ".bass.mp3", ".other.mp3",
            ".analysis.json", ".structure.json", ".f0shift.json")


def resolve(entries, wanted, role):
    """Name -> the single catalog entry it means. Ambiguity is an error, never a guess."""
    hits, misses, ambiguous = [], [], []
    for name in wanted:
        found = [e for e in entries
                 if e["role_hint"] == role and e["name"].lower().startswith(name.lower())]
        if len(found) == 1:
            hits.append((name, found[0]))
        elif not found:
            misses.append(name)
        else:
            ambiguous.append((name, [f["name"] for f in found]))
    return hits, misses, ambiguous


def files_of(song_id):
    out = []
    for suf in SUFFIXES:
        p = _DATA / f"{song_id}{suf}"
        if p.exists():
            out.append(p)
    for p in _DATA.glob(f"{song_id}.*.pitchshift.wav"):
        out.append(p)
    return out


def main() -> int:
    entries = json.loads(_MANIFEST.read_text(encoding="utf-8"))

    hb, mb, ab = resolve(entries, REMOVE_BEATS, "beat")
    hv, mv, av = resolve(entries, REMOVE_VOCALS, "vocals")
    hits = hb + hv

    total = 0
    print(f"=== BEATS to remove: {len(hb)} of {len(REMOVE_BEATS)} named ===")
    for name, e in hb:
        sz = sum(p.stat().st_size for p in files_of(e["song_id"]))
        total += sz
        print(f"   {sz/2**20:6.0f} MB  {e['name'][:52]}")
    print(f"\n=== VOCALS to remove: {len(hv)} of {len(REMOVE_VOCALS)} named ===")
    for name, e in hv:
        sz = sum(p.stat().st_size for p in files_of(e["song_id"]))
        total += sz
        print(f"   {sz/2**20:6.0f} MB  {e['name'][:52]}")

    for label, misses, ambiguous in (("beats", mb, ab), ("vocals", mv, av)):
        if misses:
            print(f"\n  NOT FOUND among {label} (skipped, nothing deleted): {misses}")
        for name, opts in ambiguous:
            print(f"\n  AMBIGUOUS - '{name}' matches {len(opts)} songs, skipped: {opts}")

    import shutil
    free_before = shutil.disk_usage(str(_REPO.drive) + "\\").free / 2**30
    print(f"\n  {len(hits)} songs, {total/2**30:.2f} GB")
    print(f"  free disk {free_before:.2f} GB  ->  {free_before + total/2**30:.2f} GB "
          f"(the app stops deleting its own caches above 6.00 GB)")

    if not APPLY:
        print("\nDRY RUN - nothing deleted. Add --apply to do it.")
        return 0

    gone_ids = {e["song_id"] for _n, e in hits}
    removed_files = 0
    for _n, e in hits:
        for p in files_of(e["song_id"]):
            try:
                p.unlink()
                removed_files += 1
            except OSError as err:
                print(f"   could not delete {p.name}: {err}")
    kept = [e for e in entries if e["song_id"] not in gone_ids]
    tmp = _MANIFEST.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(kept, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, _MANIFEST)

    free_after = shutil.disk_usage(str(_REPO.drive) + "\\").free / 2**30
    print(f"\nDONE. {len(hits)} songs removed, {removed_files} files deleted.")
    print(f"  catalog {len(entries)} -> {len(kept)} songs")
    print(f"  free disk {free_before:.2f} GB -> {free_after:.2f} GB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
