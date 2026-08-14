"""Give every catalog VOCAL a language tag, so the Discord picker can actually show it.

    services/api/.venv/Scripts/python.exe scripts/backfill_language.py            # DRY RUN
    services/api/.venv/Scripts/python.exe scripts/backfill_language.py --apply

WHY. `bot.py::_vocals_for` filters vocals by `language` and defaults to English, so an untagged
vocal appears in NEITHER list - loaded, analysed, paid for, and invisible. On 2026-08-14 that hid
55 of 73 vocals: 53 freshly ingested plus Location and Old Town Road, which were added on 08-13 and
never tagged either. `scripts/ingest_catalog.py` now carries the field end-to-end so new songs
arrive tagged; this repairs what is already in the manifest.

HOW A LANGUAGE IS DECIDED - from the song's own source folder, never from the title. The founder
sorted these by hand into `200 songs/English vocal songs` and `200 songs/Hindi songs`, which is a
far better signal than guessing from a name (half the Bollywood catalog is romanised Latin script,
and "Tere Bin" vs "Better" is exactly the kind of near-match that goes wrong). Anything that cannot
be traced to a folder is listed for a human rather than assumed.

BEATS ARE SKIPPED ON PURPOSE: they are instrumental beds and are never language-filtered.
The manifest is local-only (gitignored), so this repairs data on this machine, not in git.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_MANIFEST = _REPO / "services" / "api" / "data" / "library" / "manifest.json"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
APPLY = "--apply" in sys.argv

# Folder -> language. The founder's own sorting is the source of truth.
FOLDER_LANGUAGE = {
    "English vocal songs": "english",
    "Hindi songs": "bollywood",
}

# Songs whose source folder is not knowable from a load log, tagged by hand. Each one is a plainly
# English-language track added before the folders existed; listed explicitly so the reasoning is
# visible rather than buried in a heuristic.
BY_HAND = {
    "Location": "english",          # Khalid
    "Old Town Road": "english",     # Lil Nas X
}


def load_ingest_logs() -> dict[str, str]:
    """song_id -> language, derived from any ingest log we can find (path tells us the folder)."""
    out: dict[str, str] = {}
    for log in _REPO.glob("**/ingested.jsonl"):
        try:
            for line in log.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                folder = Path(row.get("path", "")).parent.name
                lang = FOLDER_LANGUAGE.get(folder)
                if lang and row.get("song_id"):
                    out[row["song_id"]] = lang
        except (OSError, json.JSONDecodeError):
            continue
    return out


def main() -> int:
    entries = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    from_logs = load_ingest_logs()

    planned, unknown, already = [], [], 0
    for e in entries:
        if e.get("role_hint") != "vocals":
            continue
        if e.get("language"):
            already += 1
            continue
        lang = from_logs.get(e.get("song_id", "")) or BY_HAND.get(e.get("name", ""))
        (planned if lang else unknown).append((e, lang))

    print(f"catalog vocals        : {sum(1 for e in entries if e.get('role_hint') == 'vocals')}")
    print(f"  already tagged      : {already}")
    print(f"  will tag now        : {len(planned)}")
    print(f"  CANNOT determine    : {len(unknown)}\n")

    for e, lang in planned:
        print(f"   {lang:<10} {e['name'][:56]}")
    if unknown:
        print("\n  NOT TAGGED - decide these by hand rather than guessing:")
        for e, _ in unknown:
            print(f"   {e['name'][:56]}")

    if not APPLY:
        print("\nDRY RUN - nothing written. Add --apply to write it.")
        return 0

    for e, lang in planned:
        e["language"] = lang
    tmp = _MANIFEST.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, _MANIFEST)      # atomic: never leave a half-written catalog

    check = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    vocals = [e for e in check if e.get("role_hint") == "vocals"]
    missing = [e for e in vocals if not e.get("language")]
    print(f"\nWRITTEN. {len(vocals)} vocals, {len(vocals) - len(missing)} tagged, "
          f"{len(missing)} still untagged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
