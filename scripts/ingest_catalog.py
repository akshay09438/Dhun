"""Operator-side catalog ingestion — turn dropped song files into catalog entries.

This is the repeatable "founder drops files in song-dropbox/, tell me, I load them"
flow (see song-dropbox/READ-ME.txt). For each song it runs the exact same pipeline
the app uses, then adds a manifest entry so the song appears in the pick-a-song
dropdown:

    clean/normalize -> store by content hash (song_id)
    -> split stems on Replicate (cached by song_id; free if already split)
    -> analyze on Replicate + local key/energy/vocals (cached; free if already done)
    -> upsert data/library/manifest.json  {name, song_id, role_hint}

Idempotent: everything is cached by the song's content hash, so re-running costs no
cloud money and never double-adds a manifest entry.

Input: a JSON array on stdin, e.g.
    [{"name": "Jugni Ji", "path": "song-dropbox/Jugni Ji.mp3", "role_hint": "vocals"}]
Paths are resolved relative to the repo root.

Run with the API venv so `app.*` imports and the Replicate token (.env) are available:
    services/api/.venv/Scripts/python.exe scripts/ingest_catalog.py < list.json
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

# --- make `app.*` importable and load the repo-root .env (Replicate/Anthropic keys) ---
_REPO = Path(__file__).resolve().parent.parent
_API = _REPO / "services" / "api"
sys.path.insert(0, str(_API))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO / ".env")

from app.audio.analysis import analyze_track  # noqa: E402
from app.audio.normalize import AudioError, normalize_audio  # noqa: E402
from app.audio.stems import separate_stems  # noqa: E402
from app.storage import path_for, store_wav  # noqa: E402

_MANIFEST = _API / "data" / "library" / "manifest.json"


def _load_manifest() -> list[dict]:
    if not _MANIFEST.exists():
        return []
    try:
        data = json.loads(_MANIFEST.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save_manifest(entries: list[dict]) -> None:
    _MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    _MANIFEST.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")


def _upsert(entries: list[dict], name: str, song_id: str, role_hint: str) -> str:
    """Add or update the manifest entry for this song_id. Returns a status word."""
    for e in entries:
        if str(e.get("song_id", "")) == song_id:
            e["name"], e["role_hint"] = name, role_hint
            return "updated"
    entries.append({"name": name, "song_id": song_id, "role_hint": role_hint})
    return "added"


def ingest_one(name: str, rel_path: str, role_hint: str, entries: list[dict]) -> dict:
    src = (_REPO / rel_path).resolve()
    result: dict = {"name": name, "path": rel_path, "role_hint": role_hint}
    if not src.exists():
        result["error"] = f"file not found: {src}"
        return result

    print(f"\n=== {name}  <-  {rel_path}", flush=True)

    # 1) normalize -> a clean wav in a temp dir, then store by content hash.
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "clean.wav"
        try:
            print("  [1/4] cleaning/normalizing audio...", flush=True)
            normalize_audio(src, wav)
        except AudioError as e:
            result["error"] = f"could not read as audio: {e}"
            return result
        song_id = store_wav(wav)
    result["song_id"] = song_id
    print(f"        song_id = {song_id}", flush=True)

    stored_wav = path_for(song_id)
    if stored_wav is None:
        result["error"] = "stored wav missing after store_wav"
        return result

    # 2) stems (Replicate, cached by song_id) — MUST run before analysis (analysis reads the vocal stem).
    try:
        print("  [2/4] splitting stems on Replicate (cached if already done)...", flush=True)
        separate_stems(song_id, stored_wav)
    except Exception as e:  # SeparationError etc.
        result["error"] = f"stem separation failed: {e}"
        return result

    # 3) analysis (Replicate structure + local key/energy/vocals, cached by song_id).
    try:
        print("  [3/4] analyzing (beat grid / key / vocals)...", flush=True)
        analysis = analyze_track(song_id, stored_wav)
    except Exception as e:  # AnalysisError etc.
        result["error"] = f"analysis failed: {e}"
        return result
    result["bpm"] = round(float(analysis.get("bpm") or 0.0), 1)
    result["key"] = (analysis.get("key") or {}).get("camelot", "?")
    result["vocal_regions"] = len(analysis.get("vocal_regions") or [])

    # 4) manifest upsert.
    print("  [4/4] adding to catalog manifest...", flush=True)
    result["manifest"] = _upsert(entries, name, song_id, role_hint)
    _save_manifest(entries)  # save after each song so a mid-run stop still keeps finished work
    print(f"        {result['manifest']}  |  {result['bpm']} BPM  |  key {result['key']}  |  "
          f"{result['vocal_regions']} vocal regions", flush=True)
    return result


def main() -> int:
    raw = sys.stdin.read()
    try:
        jobs = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"FATAL: stdin is not valid JSON: {e}", file=sys.stderr)
        return 2
    if not isinstance(jobs, list) or not jobs:
        print("FATAL: expected a non-empty JSON array of {name, path, role_hint}", file=sys.stderr)
        return 2

    entries = _load_manifest()
    results = []
    for job in jobs:
        results.append(ingest_one(
            str(job.get("name", "")).strip(),
            str(job.get("path", "")).strip(),
            str(job.get("role_hint", "vocals")).strip() or "vocals",
            entries,
        ))

    print("\n================ SUMMARY ================", flush=True)
    ok = [r for r in results if "error" not in r]
    bad = [r for r in results if "error" in r]
    for r in ok:
        print(f"  OK   {r['name']:<28} {r.get('bpm','?')} BPM  key {r.get('key','?')}  "
              f"{r.get('vocal_regions','?')} vocal regions  ({r.get('manifest','?')})", flush=True)
    for r in bad:
        print(f"  FAIL {r['name']:<28} {r['error']}", flush=True)
    print(f"\n{len(ok)} ingested, {len(bad)} failed. Catalog now has "
          f"{len(entries)} entries.", flush=True)
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
