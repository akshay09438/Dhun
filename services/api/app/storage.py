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
import math
import os
import re
import shutil
import time
from pathlib import Path

from app.config import settings
from app.envnum import env_float

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

# THE EMERGENCY FLOORS — DELIBERATELY LEFT AT 2.0 / 3.0 (re-affirmed 2026-08-13).
# These look too low, and a withdrawn change (`disk-sweep-floors-and-age`) tried to raise them to
# 4.0/6.0. They must stay UNDER `janitor.DEFAULT_CUSHION_GB` (6.0), because the two mechanisms are
# layered, not duplicated:
#   * the janitor defends the 6 GB cushion on a 60s timer and has a FUTILITY BRAKE — it asks
#     `sweep(dry_run=True)` first and deletes NOTHING when free+reclaimable still misses the cushion,
#     because the disk pressure is then somebody else's (measured: Windows Update holding 7.81 GB
#     while Prompt-DJ's folder was unchanged).
#   * `maybe_sweep` below is the last-ditch backstop UNDER that band, on the render path, with no
#     brake — which is only safe precisely because its target is low.
# Raising these to meet the cushion turns the brakeless backstop into a second, competing cushion
# policy that fires on every render and empties the whole cache chasing a target it cannot reach.
# If the cushion ever needs changing, change it in `janitor.py`, which is the file that owns it.
_MIN_FREE_GB = 2.0     # the auto-hook sweeps only when free disk is below this floor
_TARGET_FREE_GB = 3.0  # a sweep frees up to this much, then stops

# Grace period (F1, 2026-08-05): NEVER evict a render younger than this. A render being built (the
# set-builder crops each member seconds after rendering it), just served, or in-flight has a recent
# mtime — so this protects the sharp concurrency case (job B's sweep deleting job A's fresh output)
# without a cross-job lock. Mixes/sets are regenerable, so an OLDER one evicted mid-download just
# re-renders; the grace covers the realistic window at validation scale.
# 2026-08-13: this is now a FLOOR, not merely a default — see `sweep_old`.
_EVICT_MIN_AGE_SECS = 300.0

# ---------------------------------------------------------------- Routine age sweep (2026-08-13)
# The janitor above only ever REACTS to disk pressure, so nothing did routine tidying and stale
# renders accumulated until they became an emergency. This is the unhurried half: a finished render
# nobody has PLAYED in a week is dead weight — regenerable, and nothing in the app reads it.
#
# "Not played in a week", not "made a week ago": `mark_used` re-stamps a render when it is served,
# so a mix somebody keeps coming back to never ages out. That is the founder's decision of
# 2026-08-13 and it is what the plain-language promise always said.
_MAX_RENDER_AGE_DAYS = 7.0
_ENV_MAX_AGE = "PROMPTDJ_RENDER_MAX_AGE_DAYS"

# How stale a render's stamp must be before serving it re-stamps. `services/api/data` sits inside
# the OneDrive-synced tree, so stamping on EVERY play would re-upload a large WAV every time; once
# a day is plenty to keep a mix in active use alive, and costs one sync per file per day.
# CEILING, not a constant: see `_mark_used_interval`. A window shorter than this would otherwise
# make playing a mix stop protecting it, which is the one promise this whole feature rests on.
_MARK_USED_MIN_INTERVAL_SECS = 86400.0

# THE ANOMALY BRAKE — the most important line in this file.
# `sweep_old` trusts mtime alone, and mtime is not only set by us. A restored backup, a folder copy
# (`shutil.copy2`, robocopy, Explorer), a OneDrive re-materialisation, or a clock that jumps forward
# all hand back files that read as instantly ancient. Without a cap, ONE 60-second tick then deletes
# the entire render cache: adversarial review 2026-08-13 executed exactly that and lost 5 of 5
# brand-new renders. `sweep()` is bounded twice over (it only fires under 2 GB free and stops at its
# 3 GB target); `sweep_old` has no free-disk gate at all, so it needs its own bound.
#
# A cap does not make a wrong mtime right — it makes the consequence SLOW, VISIBLE and STOPPABLE
# instead of instant and total. A genuine backlog still drains (10 a minute = 600 an hour), while an
# accident becomes a warning in the log and a folder the founder still has time to rescue.
_SWEEP_OLD_MAX_PER_TICK = 10


# ---------------------------------------------------------------- Kept renders (2026-08-13)
# FOUNDER RULE, 2026-08-13: "the mixes which will be in the best mixes tab should not be removed,
# and other than that, everything should be removed."
#
# A mix pinned to #best-mixes is the community's own pick of what was worth keeping, and it is the
# one thing here that is NOT routine cache. Pinning already uploads an MP3 to Discord, so the pinned
# copy survives regardless — but two things did not: the local full-quality master, and the ability
# to pin an old grind at all (pinning re-reads the WAV off disk, so a swept grind can no longer be
# carried up to the showcase).
#
# The marker is a file under `keep/`, not a field in a database, deliberately:
#   * `_evictable_files` never recurses, so the markers can never be swept by the thing they guard;
#   * it needs no schema, no migration, and survives the SQLite store being rebuilt or moved;
#   * the Discord bot and the API are separate services on one machine — a marker on disk is the
#     one thing both can see without coupling either to the other's database.
_KEEP_DIR_NAME = "keep"


def _keep_dir() -> Path:
    return settings.data_dir / _KEEP_DIR_NAME


def keep(render_id: str) -> bool:
    """Protect every render belonging to `render_id` from routine tidying, permanently.

    Idempotent, and never raises: pinning a grind must not fail because a marker could not be
    written. Returns True if the render is protected when this returns (already or newly).
    Rejects anything that is not a clean 64-hex id, exactly as `path_for` does — the id reaches the
    filesystem as a name, so it gets the same treatment as every other id in this module."""
    if not _HEX_ID.fullmatch(render_id):
        log.warning("keep: refusing a malformed render id")
        return False
    try:
        d = _keep_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / render_id).touch()
        return True
    except OSError:
        log.warning("keep: could not write the marker for %s", render_id, exc_info=True)
        return False


def is_kept(render_id: str) -> bool:
    """Whether this render is protected from routine tidying."""
    if not _HEX_ID.fullmatch(render_id):
        return False
    try:
        return (_keep_dir() / render_id).exists()
    except OSError:
        return False


def _kept_ids() -> set[str]:
    """Every protected id, read once per sweep rather than once per file.

    FAILS CLOSED: if the marker directory cannot be read, this raises rather than returning an
    empty set. An unreadable `keep/` must stop the sweep, not silently un-protect the founder's
    best mixes — the whole point of the directory is that its absence is never assumed."""
    d = _keep_dir()
    if not d.exists():
        return set()
    return {p.name for p in d.iterdir() if p.is_file()}


def max_render_age_days() -> float:
    """The age window, resolved from the environment at CALL time (never a default argument)."""
    return env_float(_ENV_MAX_AGE, _MAX_RENDER_AGE_DAYS)


def _free_gb(path: Path) -> float:
    return shutil.disk_usage(path).free / 1e9


def _mark_used_interval() -> float:
    """How stale a stamp must be before serving re-stamps it — COUPLED to the age window.

    Flat 86400 was a silent trap. `PROMPTDJ_RENDER_MAX_AGE_DAYS` is a documented knob, and setting
    it under a day (say 0.5) left the stamp interval longer than the whole window: playing a mix
    refused to re-stamp it, so the very next tick deleted the file somebody was listening to.
    Adversarial review 2026-08-13 executed that. Quartering the window keeps "playing it keeps it"
    true at every setting, and at the 7-day default this is unchanged (86400 < 151200)."""
    return min(_MARK_USED_MIN_INTERVAL_SECS, max_render_age_days() * 86400.0 / 4.0)


def mark_used(*paths: Path, min_interval_secs: float | None = None) -> list[Path]:
    """Record that a render is still wanted, by moving its mtime to now. Returns what it stamped.

    This is what makes the age sweep mean "not played in a week" rather than "rendered a week ago".
    It only re-stamps a file whose stamp is ALREADY older than `min_interval_secs`, so playing the
    same mix ten times in an evening writes once, not ten times (see `_MARK_USED_MIN_INTERVAL_SECS`).

    Never creates a file, never raises: this is bookkeeping on the serving path, and a mix must play
    even if its timestamp cannot be written (a read-only mount, a file held open by another process,
    a path that has just been swept). Failing to stamp costs at worst one avoidable re-render.
    """
    if min_interval_secs is None:
        min_interval_secs = _mark_used_interval()  # resolved per call, never frozen at import
    now = time.time()
    stamped: list[Path] = []
    for p in paths:
        try:
            if now - p.stat().st_mtime < min_interval_secs:
                continue  # stamped recently enough — leave it alone
            os.utime(p, (now, now))
        except OSError:
            continue  # missing, locked, or read-only — never fatal on the serving path
        stamped.append(p)
    return stamped


def _evictable_files(min_age_secs: float | None = None) -> list[Path]:
    """Top-level files in the data dir whose name ends with an evictable suffix AND whose stamp is
    older than `min_age_secs` (default: the module's grace period).

    `None` rather than `= _EVICT_MIN_AGE_SECS`, deliberately: a default argument is bound once at
    import, so spelling it that way would freeze the grace at its import-time value and silently
    ignore any later change to it. Resolved inside the call, so the knob stays a real knob.

    Never recurses, so `listening/`, `tuning_renders/` and `library/` are untouched by construction;
    the age grace protects a just-rendered / in-flight render from a concurrent sweep."""
    if min_age_secs is None:
        min_age_secs = _EVICT_MIN_AGE_SECS
    d = settings.data_dir
    if not d.exists():
        return []
    kept = _kept_ids()   # deliberately NOT wrapped: an unreadable keep/ must stop the sweep
    now = time.time()
    out: list[Path] = []
    for p in d.iterdir():
        if not (p.is_file() and p.name.endswith(_EVICTABLE_SUFFIXES)):
            continue
        # A render is `<id>.mix.wav`, `<id>.bestparts.wav`, … — so the id is everything before the
        # first dot. A set's cropped members are `<set_id>_<n>.bestparts.wav`, so split the index
        # off too: protecting a set has to protect the pieces it is joined from.
        stem = p.name.split(".", 1)[0].split("_", 1)[0]
        if stem in kept:
            continue  # pinned to #best-mixes — never routine-tidied (founder rule 2026-08-13)
        try:
            if now - p.stat().st_mtime < min_age_secs:
                continue  # too fresh — may be in-flight / being served
        except OSError:
            continue
        out.append(p)
    return out


def sweep_old(max_age_days: float | None = None, dry_run: bool = False) -> dict:
    """Evict regenerable renders not used in `max_age_days`, REGARDLESS of how much disk is free.

    The routine half of the disk story, run from the janitor's timer — never from the render path.
    It takes only what is stale, so the emergency sweep below rarely needs to fire, and when it does
    it has less useful work to undo. Same suffix allowlist and same top-level-only scan as `sweep`:
    a source, stem, analysis, manifest or anything in a subdirectory is never a candidate.

    THE GRACE IS A FLOOR, NOT A DEFAULT. The threshold is `max(window, _EVICT_MIN_AGE_SECS)`, so no
    caller — including `sweep_old(0)` from an ops script — can reach a render written seconds ago
    and still being written. An earlier draft passed the window straight through, which quietly
    turned the in-flight protection into something any caller could step over.

    Deliberately does not look at free space at all. Tying stale-render cleanup to disk pressure is
    what produced the old failure mode, where nothing was ever tidied until the machine was already
    in trouble."""
    if max_age_days is None:
        max_age_days = max_render_age_days()  # resolved here, not frozen at import (see above)
    if not math.isfinite(max_age_days):
        max_age_days = _MAX_RENDER_AGE_DAYS   # NaN/inf can never become a deletion threshold
    min_age_secs = max(max_age_days * 86400.0, _EVICT_MIN_AGE_SECS)
    # OLDEST FIRST, like `sweep()`. Arbitrary `iterdir` order was tolerable while every candidate
    # was deleted anyway; with the per-tick cap below it decides WHICH ten go, and the deadest
    # weight is the only defensible answer.
    try:
        files = sorted(_evictable_files(min_age_secs=min_age_secs), key=lambda p: p.stat().st_mtime)
    except OSError:  # a file vanished between listing and sorting — fall back to unordered
        files = _evictable_files(min_age_secs=min_age_secs)
    freed = 0
    evicted: list[str] = []
    for p in files:
        if len(evicted) >= _SWEEP_OLD_MAX_PER_TICK:
            log.warning(
                "age sweep stopped at its per-tick cap of %d (%d candidates were eligible). This is "
                "normal while a genuine backlog drains, and DELIBERATE if it is not: %d stale "
                "renders appearing at once looks more like restored/copied timestamps or a clock "
                "change than a week of real disuse. Check the data folder before the next ticks "
                "take the rest.",
                _SWEEP_OLD_MAX_PER_TICK, len(files), len(files))
            break
        try:
            st = p.stat()
            # RE-READ THE STAMP AT THE MOMENT OF DELETION, not just when the list was built.
            # Somebody can press play in between: `mark_used` stamps the file fresh, and without
            # this second look the sweep would delete the very mix they are listening to. Found by
            # adversarial review 2026-08-13 — the window is small but it runs every 60 seconds, and
            # an unlink while the file is being streamed succeeds on both Windows and Linux here.
            if time.time() - st.st_mtime < min_age_secs:
                continue
            size = st.st_size
        except OSError:
            continue
        if not dry_run:
            try:
                p.unlink()
            except OSError:
                continue
        freed += size
        evicted.append(p.name)
    report = {"dry_run": dry_run, "evicted": len(evicted), "freed_gb": round(freed / 1e9, 3),
              "free_gb_after": round(_free_gb(settings.data_dir), 2),
              "candidates": len(files), "files": evicted}
    if evicted:
        log.info("age sweep (%.1f days) %s", min_age_secs / 86400.0,
                 {k: report[k] for k in ("dry_run", "evicted", "freed_gb", "free_gb_after")})
    return report


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
    report if it swept, else None.

    UNCHANGED ON PURPOSE (2026-08-13): the routine age sweep is NOT wired in here. Routine tidying
    belongs on the janitor's timer, not on the path that makes a mix — putting it here would make
    deletion a side effect of every single grind."""
    if _free_gb(settings.data_dir) < _MIN_FREE_GB:
        return sweep()
    return None
