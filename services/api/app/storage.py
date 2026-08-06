"""Content-addressed storage for cleaned audio.

Handle with care: this reads and writes files on disk. Two safety properties
it must always keep:
  1. Files are named by a server-computed content hash — NEVER by a
     user-supplied filename. This neutralizes filename/path attacks at the source.
  2. `path_for` only ever returns a path inside the data dir, and only for a
     strict 64-char lowercase-hex id — so a crafted id cannot escape the dir.
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import time
from pathlib import Path

from app.config import settings

log = logging.getLogger("promptdj.storage")

# A stored id is exactly a sha256 hexdigest: 64 lowercase hex chars, nothing else.
# fullmatch (not $) so a trailing newline can never sneak past the anchor.
_HEX_ID = re.compile(r"[0-9a-f]{64}")


def store_wav(wav_path: Path) -> str:
    """Copy a cleaned WAV into the data dir under its content hash; return the id.

    Idempotent: re-storing identical content is a no-op (same hash, same file),
    so retries / double-submits are safe and never duplicate.
    """
    data = wav_path.read_bytes()
    song_id = hashlib.sha256(data).hexdigest()
    dst = settings.data_dir / f"{song_id}.wav"
    if not dst.exists():
        shutil.copyfile(wav_path, dst)
    return song_id


def path_for(song_id: str) -> Path | None:
    """Return the stored path for a valid, existing id, else None.

    Rejects any id that is not a clean 64-char hex string — which blocks path
    traversal (``..``, ``/``, ``\\``, absolute paths) by construction.
    """
    if not _HEX_ID.fullmatch(song_id):
        return None
    p = settings.data_dir / f"{song_id}.wav"
    return p if p.exists() else None


# ---------------------------------------------------------------- Cache eviction (2026-08-05)
# The data dir mixes UNRECOVERABLE catalog (uploaded sources `<hash>.wav`, Replicate-cost stems
# `<hash>.<stem>.mp3` + analyses `<hash>.analysis.json`/`.structure.json`, the `library/` manifest, the
# approved config under `tuning_renders/`, and the `listening/` ear-test folders) with REGENERABLE render
# outputs. The sweep frees disk by deleting ONLY the regenerable outputs, chosen by a strict suffix
# ALLOWLIST — so any file NOT explicitly listed here (including any future/unknown type, the small
# `.mixplan.json`/`.mixname.txt`/`.setmanifest.json`/`.suggestions.json` metadata, and EVERYTHING inside a
# subdirectory) is KEPT by construction. Same fail-safe discipline as `path_for`: never guess, never a
# blacklist. Deleting a catalog file here would be unrecoverable, so the allowlist is the whole safety.
# `.pitchshift.wav` = key-shifted vocal cache (app/audio/pitch.py): regenerable, but re-creating one
# re-runs the pitch helper (~seconds, verified twice) — evictable, just not free.
_EVICTABLE_SUFFIXES = (".mix.wav", ".bestparts.wav", ".set.wav", ".livearr.wav", ".pitchshift.wav")
_MIN_FREE_GB = 2.0     # the auto-hook sweeps only when free disk is below this floor
_TARGET_FREE_GB = 3.0  # a sweep frees up to this much, then stops
# Grace period (F1, 2026-08-05): NEVER evict a render younger than this. A render being built (the
# set-builder crops each member seconds after rendering it), just served, or in-flight has a recent
# mtime — so this protects the sharp concurrency case (job B's sweep deleting job A's fresh output)
# without a cross-job lock. Mixes/sets are regenerable, so an OLDER one evicted mid-download just
# re-renders; the grace covers the realistic window at validation scale.
_EVICT_MIN_AGE_SECS = 300.0


def _free_gb(path: Path) -> float:
    return shutil.disk_usage(path).free / 1e9


def _evictable_files() -> list[Path]:
    """Top-level files in the data dir whose name ends with an evictable suffix AND are older than the
    grace period. Never recurses, so `listening/`, `tuning_renders/` and `library/` are untouched by
    construction; the age grace protects a just-rendered / in-flight render from a concurrent sweep."""
    d = settings.data_dir
    if not d.exists():
        return []
    now = time.time()
    out: list[Path] = []
    for p in d.iterdir():
        if not (p.is_file() and p.name.endswith(_EVICTABLE_SUFFIXES)):
            continue
        try:
            if now - p.stat().st_mtime < _EVICT_MIN_AGE_SECS:
                continue  # too fresh — may be in-flight / being served
        except OSError:
            continue
        out.append(p)
    return out


def sweep(target_free_gb: float = _TARGET_FREE_GB, dry_run: bool = False) -> dict:
    """Evict regenerable render outputs (least-recently-modified FIRST) until free disk reaches
    `target_free_gb`, or nothing evictable remains. Deletes ONLY `_EVICTABLE_SUFFIXES` files in the data
    dir (allowlist) — never a source, stem, analysis, manifest, approved-config file, or anything in a
    subdirectory. `dry_run` reports what WOULD be evicted without deleting. Returns (and logs) a report."""
    d = settings.data_dir
    files = sorted(_evictable_files(), key=lambda p: p.stat().st_mtime)  # oldest (LRU) first
    start_free = _free_gb(d)
    freed = 0
    evicted: list[str] = []
    for p in files:
        # stop once free disk has reached the target (projected, in dry-run; measured, when live)
        projected_free = (start_free + freed / 1e9) if dry_run else _free_gb(d)
        if projected_free >= target_free_gb:
            break
        try:
            size = p.stat().st_size
        except OSError:
            continue
        if not dry_run:
            try:
                p.unlink()
            except OSError:
                continue
        freed += size
        evicted.append(p.name)
    free_after = _free_gb(d)
    report = {"dry_run": dry_run, "evicted": len(evicted), "freed_gb": round(freed / 1e9, 3),
              "free_gb_after": round(free_after, 2), "candidates": len(files), "files": evicted}
    log.info("cache sweep %s", {k: report[k] for k in ("dry_run", "evicted", "freed_gb", "free_gb_after")})
    # F2 (2026-08-05): if we evicted EVERYTHING evictable and still didn't reach the target, the disk
    # pressure is coming from un-evictable data (the catalog, or an external writer) — say so loudly
    # rather than silently having wiped the whole render cache for nothing.
    if not dry_run and evicted and len(evicted) == len(files) and free_after < target_free_gb:
        log.warning("cache sweep evicted ALL %d regenerable renders and still only reached %.2f GB free "
                    "(< %.1f GB target) — remaining disk pressure is un-evictable (catalog/external)",
                    len(evicted), free_after, target_free_gb)
    return report


def maybe_sweep() -> dict | None:
    """Auto-eviction hook: sweep only when free disk is below the floor. Called at the START of a render
    job, so the not-yet-written output can't be evicted. NOTE: it evicts old regenerable renders across
    ALL jobs (not just this one) — a finished mix/set older than the grace period may be reclaimed even
    while another request is serving it; that render is regenerable (same-take re-render reproduces it),
    and the age grace in `_evictable_files` protects any render fresh enough to be in-flight. Returns the
    report if it swept, else None."""
    if _free_gb(settings.data_dir) < _MIN_FREE_GB:
        return sweep()
    return None
