"""The render engine: turn a MixPlan into one finished, click-free WAV.

Deterministic DSP only — FFmpeg decodes and time-stretches, numpy mixes. This is a
dangerous surface: it is where a bad-sounding mix would ship, so it is deliberately
small, self-contained, and easy to test. It takes plain file paths in (no coupling
to the web app or the database), and never asks the LLM for anything — the plan is
already decided.

The M3 arrangement (the brain plans, the engine executes):
  1. Song 1's instrumental bed = drums + bass + other stems summed (its own vocal
     is simply never included — that is how "one vocal only" is guaranteed).
  2. Song 2's chosen vocal slice, time-stretched with FFmpeg `atempo` to Song 1's
     tempo (pitch preserved), faded at both edges so its entry and exit never click.
  3. The vocal is laid in at the anchor (a downbeat of Song 1); with beat_breath,
     Song 1's beat is silenced for one bar right before it, for a punchy re-entry.
  4. Peak-normalize to -1 dBFS with a hard safety ceiling so the master never clips.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Mapping

import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt

SR = 44100  # everything renders at CD rate, stereo
_TARGET_PEAK = 10 ** (-1.0 / 20)  # -1 dBFS headroom
_CEILING = 0.999  # brickwall safety — must stay below the validator's clip ceiling
_FADE_MS = 8.0  # edge fade that kills entry/exit clicks
_BREATH_DUCK = 0.35  # the bed dips to this for one bar before a flagged entry (tension, not silence)
_SWEEP_LO_HZ = 300.0  # filter-sweep floor: the bed muffles to this cutoff, then opens up
_FFMPEG_TIMEOUT = 180
# Bound decoded audio so a tiny-but-hours-long low-bitrate file can't balloon in
# memory (the upload cap is on bytes, not duration). A decoded stereo minute is
# ~10 MB; 12 minutes caps one buffer near ~130 MB — generous for any real song.
_MAX_DECODED_SECS = 12 * 60


class RenderError(Exception):
    """Raised when the audio engine cannot produce a mix."""


def _run_ffmpeg(cmd: list[str]) -> None:
    p = subprocess.run(cmd, capture_output=True, timeout=_FFMPEG_TIMEOUT)
    if p.returncode != 0:
        raise RenderError(p.stderr.decode(errors="ignore")[-300:] or "ffmpeg failed")


def _guard_duration(y: np.ndarray) -> np.ndarray:
    if len(y) > _MAX_DECODED_SECS * SR:
        raise RenderError(f"audio exceeds the {_MAX_DECODED_SECS // 60}-minute render limit")
    return y


def _decode(src: Path) -> np.ndarray:
    """Decode any audio file to stereo float32 at SR (extension-independent)."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        out = Path(td) / "d.wav"
        _run_ffmpeg(["ffmpeg", "-y", "-i", str(src), "-ar", str(SR), "-ac", "2", str(out)])
        y, _ = sf.read(out, dtype="float32", always_2d=True)
    return _guard_duration(y)


def _vocal_take(src: Path, start: float, dur: float, ratio: float) -> np.ndarray:
    """Extract [start, start+dur] of the vocal and stretch it to the master tempo.

    Slicing before stretching keeps the time math simple: we cut in the vocal's own
    time, then `atempo` rescales that clip. Ratios here are ~0.92–1.08 (one atempo
    stage covers 0.5–2.0), so a single filter pass is exact.
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        out = Path(td) / "v.wav"
        cmd = ["ffmpeg", "-y", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(src),
               "-ar", str(SR), "-ac", "2"]
        if abs(ratio - 1.0) >= 1e-3:
            cmd += ["-filter:a", f"atempo={ratio:.6f}"]
        cmd += [str(out)]
        _run_ffmpeg(cmd)
        y, _ = sf.read(out, dtype="float32", always_2d=True)
    return _guard_duration(y)


def _sum_stems(stem_paths: list[Path]) -> np.ndarray:
    """Sum stems into one bed, padding shorter ones with silence."""
    beds = [_decode(p) for p in stem_paths]
    if not beds:
        raise RenderError("no stems to build the bed from")
    length = max(len(b) for b in beds)
    acc = np.zeros((length, 2), dtype=np.float32)
    for b in beds:
        acc[: len(b)] += b
    return acc


def _edge_fade(y: np.ndarray) -> np.ndarray:
    k = min(int(SR * _FADE_MS / 1000), len(y) // 2)
    if k > 0:
        ramp = np.linspace(0.0, 1.0, k, dtype=np.float32)[:, None]
        y[:k] *= ramp
        y[-k:] *= ramp[::-1]
    return y


def _sweep_bed(seg: np.ndarray, sr: int) -> np.ndarray:
    """A rising low-pass 'filter sweep': the bed starts muffled (cut above ~300 Hz) and
    opens up across the segment, building anticipation into the next entry. A click-free
    crossfade from a low-passed copy to the original — bed-only, so it can't clip."""
    n = len(seg)
    if n < 64:
        return seg
    sos = butter(4, _SWEEP_LO_HZ / (sr / 2), btype="low", output="sos")
    muffled = sosfilt(sos, seg, axis=0).astype(np.float32)
    ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)[:, None]  # 0 = muffled -> 1 = open
    return muffled * (1.0 - ramp) + seg * ramp


def _placements_of(plan):
    """The plan's vocal placements — or the scalar anchor/vocal_src as a one-element
    arrangement, so a legacy (M3) single-placement plan still renders."""
    if getattr(plan, "placements", None):
        return plan.placements
    return [type("P", (), {"anchor": plan.anchor, "vocal_src": plan.vocal_src,
                           "beat_breath": getattr(plan, "beat_breath", False)})()]


def render_mix(plan, song1_stems: Mapping[str, Path], song2_vocal: Path,
               out_path: Path) -> Path:
    """Render `plan` to a WAV at out_path.

    song1_stems maps drums/bass/other to Song 1's stem files; song2_vocal is Song 2's
    isolated vocal file. `plan` exposes master_bpm, vocal_stretch, and either a list of
    `placements` (each with anchor / vocal_src / beat_breath) or the scalar anchor /
    vocal_src fallback. Song 1's beat runs continuously; each placement lays the vocal
    on top; beat_breath ducks the bed for one bar before that entry (never silence).
    """
    if plan.master_bpm <= 0:
        raise RenderError("plan has a non-positive tempo")
    bed = _sum_stems([song1_stems["drums"], song1_stems["bass"], song1_stems["other"]])
    bar = int((60.0 / plan.master_bpm) * 4 * SR)

    def _hold(buf: np.ndarray, need: int) -> np.ndarray:
        if need > len(buf):  # extend the bed with silence so it can hold this audio
            return np.vstack([buf, np.zeros((need - len(buf), 2), dtype=np.float32)])
        return buf

    for p in _placements_of(plan):
        start, end = p.vocal_src
        voc = _edge_fade(_vocal_take(song2_vocal, start, max(end - start, 0.0), plan.vocal_stretch))
        anchor = max(0, int(p.anchor * SR))  # never place before the start
        b0 = max(0, anchor - bar)
        if getattr(p, "beat_breath", False):  # DUCK the bed for one bar (tension), never silence it
            bed[b0:anchor] *= _BREATH_DUCK
        if getattr(p, "fx", None) == "sweep_in":  # muffled -> open across the bar before the entry
            bed[b0:anchor] = _sweep_bed(bed[b0:anchor], SR)
        need = anchor + len(voc)
        bed = _hold(bed, need)
        bed[anchor:need] += voc

    # Slice B contrast: Song 1's OWN vocal answers in the beat-only gaps (never overlapping
    # Song 2's vocal — the referee guarantees it). No stretch — it is already Song 1's tempo.
    s1_vocals = song1_stems.get("vocals")
    for s, e in getattr(plan, "s1_vocal_regions", []):
        if s1_vocals is None:
            break
        take = _edge_fade(_vocal_take(s1_vocals, s, max(e - s, 0.0), 1.0))
        a0 = max(0, int(s * SR))
        bed = _hold(bed, a0 + len(take))
        bed[a0:a0 + len(take)] += take

    peak = float(np.max(np.abs(bed))) if bed.size else 0.0
    if peak > 0.0:
        bed *= _TARGET_PEAK / peak
    np.clip(bed, -_CEILING, _CEILING, out=bed)

    sf.write(out_path, bed, SR, subtype="PCM_16")
    return out_path
