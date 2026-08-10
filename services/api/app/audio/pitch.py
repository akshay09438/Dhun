"""Pitch EXECUTOR: shift a vocal stem by N semitones (formant-preserved) via the offline Signalsmith
helper. Three guarantees, per the founder's hard conditions:
  - VERIFIED: two INDEPENDENT helper renders (separate engine launches) must be byte-identical before
    a result is trusted (the engine is deterministic within a launch but had a rare cold-start hiccup
    across launches; agreeing runs prove CONSISTENCY — the referee proves CORRECTNESS).
  - CACHED: keyed by (song content-id + shift + formant + HELPER_VERSION) → airtight cache identity;
    a future helper upgrade bumps HELPER_VERSION and never serves stale-engine audio.
  - LOUD-FAILING: crash / hang(timeout) / can't-get-two-to-agree within a bounded retry → raise
    PitchError, so the mix DECLINES visibly and never ships un-shifted audio labelled key-matched.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from app.config import settings

_HELPER = Path(__file__).parent / "pitch_helper"
HELPER_VERSION = "sig1.3.2"      # signalsmith-stretch version; bump on ANY helper change (invalidates cache)
CACHE_SUFFIX = ".pitchshift.wav"  # filename ENDS with this — storage.py's endswith() eviction allowlist
_LATENCY_S = 0.0146             # the helper's constant leading latency (measured); trimmed for alignment
_MAX_ATTEMPTS = 3              # verify-retry bound: no two renders agree in this many → decline
_RENDER_TIMEOUT_S = 180        # a hang IS the loud-failure case
_PITCH_HARD_CAP = 2           # ±2 st — the ABSOLUTE pitch ceiling (== keys.CAP_SEMITONES). The decision layer
#                              caps first; this is the EXECUTOR's own floor, so it can never render a bigger
#                              shift than the rule whatever a caller passes. Hard pitch rule — see RULEBOOK.md.


class PitchError(RuntimeError):
    """The vocal could not be key-shifted SAFELY → the caller must DECLINE the mix (never ship un-shifted)."""


def _render_once(y: np.ndarray, sr: int, semitones: float, formant: bool, workdir: Path) -> np.ndarray:
    """One independent helper render of the whole stem (a fresh engine launch). Raises PitchError on
    crash or timeout (both are the loud-failure case)."""
    y = np.asarray(y, dtype=np.float32)
    if y.ndim == 1:
        y = y[:, None]
    n, ch = y.shape
    inp, out = workdir / "in.f32", workdir / "out.f32"
    np.ascontiguousarray(y.reshape(-1), dtype=np.float32).tofile(inp)
    jobs = [dict(id=0, **{"in": str(inp)}, out=str(out), sr=int(sr), ch=int(ch),
                 semitones=float(semitones), rate=1.0, formant=bool(formant), formantBaseHz=0.0, pad=1.0)]
    jf = workdir / "jobs.json"
    jf.write_text(json.dumps(jobs))
    if out.exists():
        out.unlink()
    try:
        r = subprocess.run(["node", str(_HELPER / "bridge.mjs"), "--jobs", str(jf)],
                           capture_output=True, text=True, timeout=_RENDER_TIMEOUT_S)
    except subprocess.TimeoutExpired as e:
        raise PitchError(f"pitch helper hung (> {_RENDER_TIMEOUT_S}s) — declining") from e
    except FileNotFoundError as e:
        raise PitchError("pitch helper unavailable (node not found) — declining") from e
    if r.returncode != 0 or not out.exists():
        tail = (r.stderr or r.stdout or "")[-400:]
        raise PitchError(f"pitch helper failed — declining: {tail}")
    o = np.fromfile(out, dtype=np.float32).reshape(-1, ch)
    lat = round(_LATENCY_S * sr)
    o = o[lat:]
    if len(o) >= n:
        o = o[:n]
    else:
        o = np.pad(o, ((0, n - len(o)), (0, 0)))
    return np.ascontiguousarray(o, dtype=np.float32)


def cache_path(song_id: str, semitones: int, formant: bool = True) -> Path:
    """Content-addressed cache path: (song content-id, shift, formant, helper version) → one file."""
    tag = f"{int(semitones):+d}{'F' if formant else 'N'}.{HELPER_VERSION}"
    return settings.data_dir / f"{song_id}.{tag}{CACHE_SUFFIX}"


def shifted_vocal(song_id: str, vocal_wav: Path, semitones: int, formant: bool = True) -> Path:
    """Return the path to the key-shifted vocal stem — from cache, or computed→verified→cached.
    semitones == 0 → the original stem, untouched. Raises PitchError (→ decline the mix) if a stable,
    verified render cannot be produced within the retry bound."""
    if int(semitones) == 0:
        return Path(vocal_wav)
    if abs(int(semitones)) > _PITCH_HARD_CAP:  # defensive floor: the decision layer caps at ±2 first, so this
        raise PitchError(                       # never fires in practice — but the executor will NOT over-shift.
            f"pitch shift {int(semitones):+d} st exceeds the ±{_PITCH_HARD_CAP} st hard cap — declining")
    cache = cache_path(song_id, int(semitones), formant)
    if cache.exists():
        return cache  # airtight: same (content-id, shift, helper) always yields the same bytes
    y, sr = sf.read(str(vocal_wav), dtype="float32", always_2d=True)
    work = Path(tempfile.mkdtemp(prefix="pitch_", dir=str(settings.data_dir)))
    try:
        renders: list[np.ndarray] = []
        last_err: PitchError | None = None
        for _ in range(_MAX_ATTEMPTS):
            try:
                cur = _render_once(y, sr, semitones, formant, work)
            except PitchError as e:  # a TRANSIENT crash/hang — retry within the bound, don't give up yet
                last_err = e
                continue
            for prev in renders:  # two INDEPENDENT renders byte-identical ⇒ consistent ⇒ trust
                if cur.shape == prev.shape and np.array_equal(cur, prev):
                    tmp = work / "shifted.wav"
                    sf.write(str(tmp), cur, sr)
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(tmp), str(cache))  # publish only a verified result
                    return cache
            renders.append(cur)
        # Bounded retries exhausted with no two-agreeing result -> decline LOUD (never ship unverified).
        if len(renders) >= 2:
            raise PitchError(f"pitch helper non-deterministic after {_MAX_ATTEMPTS} renders — declining")
        raise PitchError(f"pitch helper failed after {_MAX_ATTEMPTS} attempts — declining"
                         + (f": {last_err}" if last_err else ""))
    finally:
        shutil.rmtree(work, ignore_errors=True)
