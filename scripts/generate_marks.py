"""Turn the founder's marking sheet into the app's generated mark table.

THE PROBLEM THIS SOLVES. `scripts/song_marks.csv` is where the founder's ear-marks land (exported
from `scripts/mark_drops.html`), but **nothing reads it** — a mark did not reach the app until it
was hand-copied into `planner/hooks.py` / `planner/main_drops.py` against the song's content id. On
2026-08-14 that gap was 410 marks recorded vs 40 wired, i.e. ~90% of the founder's listening work
was doing nothing. This closes it mechanically instead of by typing.

WHY CONTENT ID, NOT FILENAME. The CSV is keyed by FILENAME, which detaches silently on a rename —
measured 2026-08-14, three songs looked unmarked purely because the same audio was also saved under
a second name (`Lean On.mp3` vs `Major Lazer & DJ Snake - Lean On (feat. MØ)....mp3`). The app keys
on the song's content id, which cannot drift. Deriving one from the other means running the SAME
normalise step the app runs (44.1kHz/16-bit/stereo, peak-normalised) and hashing the result — local
ffmpeg only, no Replicate, no cost.

ADDITIVE ONLY — THE LOAD-BEARING RULE. Founder, 2026-08-14: _"Nothing, no single thing, has to
change."_ The shipped catalog sounds right because it runs on hand-marks confirmed by ear, and for
eight songs the CSV disagrees with what is already wired by 7-50 seconds. So this generator SKIPS
any song that already has a hand-marked entry, and `hook_for` / `main_drops_for` consult the
hand-written dict FIRST. Precedence is structural, not a promise: regenerating can never retune a
song that already works. `tests/test_marks_generated.py` pins that.

Songs not in the catalog manifest are skipped too — a mark for a song the app cannot load is inert.

Run it with the API venv (it imports `app.*`):
    services/api/.venv/Scripts/python.exe scripts/generate_marks.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_API = _REPO / "services" / "api"
sys.path.insert(0, str(_API))

# Catalog filenames carry "ā", "Ü", "ø", "São"… and on a Windows cp1252 console two things break:
# our own prints, and — less obviously — ffmpeg's stderr, which `normalize_audio` decodes in TEXT
# mode using the locale codec. One undecodable byte kills the reader thread, `p.stderr` comes back
# None, and the failure surfaces as a baffling TypeError deep in a regex. Python fixes the locale
# codec only at interpreter startup, so setting the vars here is too late — re-exec once instead.
# (`os.execv` would be the neat way to do this, but on Windows it detaches: the shell sees the
# original process exit and the replacement runs orphaned with its output lost. Relaunch instead.)
if os.environ.get("PYTHONUTF8") != "1":
    import subprocess

    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    raise SystemExit(subprocess.run([sys.executable, __file__, *sys.argv[1:]], env=env).returncode)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO / ".env")
from app.audio.normalize import AudioError, normalize_audio  # noqa: E402

CSV_PATH = _REPO / "scripts" / "song_marks.csv"
MANIFEST = _API / "data" / "library" / "manifest.json"
OUT = _API / "app" / "planner" / "marks_generated.py"
# Local-only, like the manifest: it is derived from audio that never enters git, and rebuilding it
# is free. Lives beside the catalog so a fresh clone simply recomputes.
CACHE = _API / "data" / "marks_id_cache.json"

# Where a marked file might physically live. Order matters only for reporting.
ROOTS = [
    "song-dropbox", "200 songs/Beat songs", "200 songs/English vocal songs", "200 songs/Hindi songs",
    "200 songs/_duplicates/already-loaded-identical", "200 songs/_duplicates/already-in-catalog-diff-rip",
    "200 songs/_duplicates/dup-in-both-folders", "200 songs/_duplicates/rejected-by-founder",
    "mark-these-songs/needs-marking",
]

_HEX64 = re.compile(r'"([0-9a-f]{64})"')


def read_marks() -> dict[str, dict]:
    """{filename: {'drop': [t, …], 'hook': [(start, end), …]}} — malformed rows are skipped, not fatal."""
    out: dict[str, dict] = defaultdict(lambda: {"drop": [], "hook": []})
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            key = (r.get("song_key") or "").strip()
            if not key:
                continue
            try:
                if r["kind"] == "drop" and r.get("t_start"):
                    out[key]["drop"].append(float(r["t_start"]))
                elif r["kind"] == "hook" and r.get("t_start") and r.get("t_end"):
                    out[key]["hook"].append((float(r["t_start"]), float(r["t_end"])))
            except (ValueError, KeyError):
                continue
    return dict(out)


def already_wired() -> tuple[set[str], set[str]]:
    """Content ids that already carry a HAND-marked hook / drop. Read from the source text rather
    than by importing, so this works even if the generated module is missing or half-written."""
    hooks_src = (_API / "app" / "planner" / "hooks.py").read_text(encoding="utf-8")
    drops_src = (_API / "app" / "planner" / "main_drops.py").read_text(encoding="utf-8")
    return set(_HEX64.findall(hooks_src)), set(_HEX64.findall(drops_src))


def song_ids_for(files: list[str]) -> dict[str, str]:
    """filename -> content id, normalising only what is not already cached."""
    cache: dict[str, str] = {}
    if CACHE.exists():
        try:
            cache = json.loads(CACHE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cache = {}

    on_disk: dict[str, str] = {}
    for r in ROOTS:
        d = _REPO / r
        if d.is_dir():
            for fn in os.listdir(d):
                on_disk.setdefault(fn, str(d / fn))

    todo = [f for f in files if f not in cache and f in on_disk]
    if todo:
        print(f"  hashing {len(todo)} file(s) not yet cached (local ffmpeg, no cost)…", flush=True)
    for i, fn in enumerate(todo, 1):
        try:
            with tempfile.TemporaryDirectory() as td:
                wav = Path(td) / "clean.wav"
                normalize_audio(Path(on_disk[fn]), wav)
                cache[fn] = hashlib.sha256(wav.read_bytes()).hexdigest()
        except Exception as e:  # noqa: BLE001 — one unreadable file must not lose the whole table
            print(f"    [{i}/{len(todo)}] SKIP {fn[:52]} — {type(e).__name__}: {str(e)[:80]}", flush=True)
    if todo:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache, indent=1, ensure_ascii=False), encoding="utf-8")
    return cache


def render(gen_hooks: dict, gen_drops: dict, names: dict[str, str], stats: dict) -> str:
    def block(d: dict, fmt) -> str:
        return "\n".join(
            f"    # {names.get(sid, '?')}\n    {json.dumps(sid)}: {fmt(v)},"
            for sid, v in sorted(d.items(), key=lambda kv: names.get(kv[0], "").lower())
        )

    return f'''"""GENERATED — do not edit by hand. Run `scripts/generate_marks.py` to rebuild.

The founder's ear-marks from `scripts/song_marks.csv`, re-keyed from filename to the song's content
id so a rename cannot detach a song from its marks.

This table is a FALLBACK ONLY. `planner/hooks.py` and `planner/main_drops.py` hold the hand-marked,
ear-confirmed entries and are consulted FIRST; a song appearing there is deliberately absent here.
That ordering is what lets this file be regenerated safely — it can never retune a song that is
already working. See `tests/test_marks_generated.py`.

Built from {stats['csv_rows']} marks across {stats['csv_files']} files:
{stats['in_catalog']} of those songs are in the catalog, {stats['skipped_hand']} already carry a
hand-mark (left alone), {stats['not_in_catalog']} are for songs the app has never loaded.
"""

from __future__ import annotations

# song content id -> (hook_start_secs, hook_end_secs) on the song's own native timeline.
GEN_HOOKS: dict[str, tuple[float, float]] = {{
{block(gen_hooks, lambda v: f"({v[0]}, {v[1]})")}
}}

# song content id -> [main drop time(s), secs, native timeline]. A listed beat uses these INSTEAD of
# automatic energy detection (which measured ~36% precision on the songs that were checked).
GEN_MAIN_DROPS: dict[str, list[float]] = {{
{block(gen_drops, lambda v: "[" + ", ".join(str(x) for x in v) + "]")}
}}
'''


def main() -> int:
    marks = read_marks()
    hand_hooks, hand_drops = already_wired()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    names = {e["song_id"]: e["name"] for e in manifest}

    ids = song_ids_for(sorted(marks))
    gen_hooks: dict[str, tuple[float, float]] = {}
    gen_drops: dict[str, list[float]] = {}
    in_catalog = skipped_hand = not_in_catalog = 0

    for fn, mk in marks.items():
        sid = ids.get(fn)
        if sid is None or sid not in names:
            not_in_catalog += 1
            continue
        in_catalog += 1
        touched = False
        if mk["hook"]:
            if sid in hand_hooks:
                skipped_hand += 1
            else:
                start, end = sorted(mk["hook"])[0]
                if 0.0 <= start < end:
                    gen_hooks[sid] = (round(start, 2), round(end, 2))
                    touched = True
        if mk["drop"]:
            if sid in hand_drops:
                if not touched:
                    skipped_hand += 1
            else:
                times = sorted({round(t, 2) for t in mk["drop"] if t >= 0.0})
                if times:
                    gen_drops[sid] = times

    stats = {
        "csv_rows": sum(len(m["drop"]) + len(m["hook"]) for m in marks.values()),
        "csv_files": len(marks), "in_catalog": in_catalog,
        "skipped_hand": skipped_hand, "not_in_catalog": not_in_catalog,
    }
    OUT.write_text(render(gen_hooks, gen_drops, names, stats), encoding="utf-8")

    print(f"\n  marks in sheet        : {stats['csv_rows']} across {stats['csv_files']} files")
    print(f"  songs in the catalog  : {in_catalog}")
    print(f"  left alone (hand-marked): {skipped_hand}")
    print(f"  song never loaded     : {not_in_catalog}")
    print(f"\n  GENERATED -> {OUT.relative_to(_REPO)}")
    print(f"     {len(gen_hooks)} hooks  +  {len(gen_drops)} main-drops")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
