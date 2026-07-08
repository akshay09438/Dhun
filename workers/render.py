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
     Song 1's beat is ducked (to _BREATH_DUCK, never silenced) for one bar right
     before it, for a punchy — but never gappy — re-entry.
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
_XFADE_MS = 8.0  # equal-power crossfade at each bar join in a beat-locked (warped) vocal
# atempo handles 0.5–2.0 in a single pass; clamp a bar's ratio only to keep the FILTER
# valid. The MUSICAL safe band (~0.92–1.08, no warble) is enforced upstream by the
# planner's warp_map and the referee's R7 — so a real bar is never near these limits, and
# the engine honors each bar's target length exactly, which is what keeps the beat locked.
_ATEMPO_MIN, _ATEMPO_MAX = 0.5, 2.0
_BREATH_DUCK = 0.35  # the bed dips to this for one bar before a flagged entry (tension, not silence)
_SWEEP_LO_HZ = 300.0  # filter-sweep floor: the bed muffles to this cutoff, then opens up
_BUILD_GAIN_LO = 0.55  # a produced-drop BUILD starts at this volume and rises to 1.0 (energy climbing)
_ECHO_BEATS = 0.75  # produced-drop ECHO delay, in beats (a dotted-eighth — the classic vocal throw)
_ECHO_FEEDBACK = 0.42  # each echo repeat is this fraction of the previous (decaying tail)
_ECHO_TAPS = 4  # how many decaying repeats the echo throws
_ECHO_SEG_SECS = 1.2  # only the LAST ~1.2s (the last word or two) is thrown, not the whole vocal
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


def _vocal_take_warped(src: Path, warp: list) -> np.ndarray:
    """Render a beat-locked vocal: stretch each bar of the slice to its own target length
    (`out_secs`) and lay the bars back-to-back at their locked positions, joined by short
    equal-power crossfades so no bar boundary clicks.

    Because each bar starts exactly at the cumulative sum of the target lengths — which are
    Song 1's own bar lengths — every bar re-locks to Song 1's grid, so the vocal can't drift
    off the beat the way a single global stretch does. Each bar is rendered a hair long (a
    crossfade tail) so consecutive bars overlap only in the fade region; the bar *starts*
    (the downbeats) stay exact, so the crossfade smooths the seam without moving the beat.
    """
    xf = int(SR * _XFADE_MS / 1000)
    segs: list[np.ndarray] = []
    hops: list[int] = []
    n = len(warp)
    for i, (s0, s1, out_secs) in enumerate(warp):
        dur = max(float(s1) - float(s0), 0.0)
        if dur <= 0 or out_secs <= 0:
            continue
        ratio = dur / out_secs
        if not (_ATEMPO_MIN <= ratio <= _ATEMPO_MAX):
            # The planner (warp_map) and referee (R7) guarantee every bar ratio is in the
            # musical safe band, well inside atempo's range. If one ever isn't, a caller
            # bypassed those guards — fail loudly rather than clamp into a gap/overlap.
            raise RenderError(f"beat-lock bar ratio {ratio:.3f} outside atempo range (a bad warp reached the engine)")
        tail = 0.0 if i == n - 1 else (_XFADE_MS / 1000.0) * ratio  # extra source for the crossfade
        seg = _vocal_take(src, float(s0), dur + tail, ratio)
        segs.append(seg)
        hops.append(int(round(out_secs * SR)))
    if not segs:
        return np.zeros((0, 2), dtype=np.float32)

    # FFmpeg's seek/atempo rounding (real MP3 frame-boundary rounding, confirmed on the
    # Father Ocean x With You pair) can hand back a bar's stretched audio a little LONGER
    # than its ideal hop + crossfade window. The buffer below only reserves one
    # crossfade's worth of slack at the very end, not per bar, so that overshoot can
    # compound across bars until a later write runs past the buffer. Clamp every
    # non-final bar to its exact allotted window (padding if it ever came back short) so
    # every write always fits, and the crossfade always lands exactly where the next
    # bar's head begins.
    for i in range(len(segs) - 1):
        want = hops[i] + xf
        seg = segs[i]
        if len(seg) > want:
            segs[i] = seg[:want]
        elif len(seg) < want:
            segs[i] = np.vstack([seg, np.zeros((want - len(seg), 2), dtype=np.float32)])

    total = sum(hops[:-1]) + len(segs[-1])
    out = np.zeros((total + xf, 2), dtype=np.float32)
    t = np.linspace(0.0, 1.0, xf, dtype=np.float32)[:, None] if xf > 0 else None
    fade_in = np.sin(t * np.pi / 2) if t is not None else None   # equal-power pair (sin^2+cos^2=1)
    fade_out = np.cos(t * np.pi / 2) if t is not None else None
    pos = 0
    for i, (seg, hop) in enumerate(zip(segs, hops)):
        s = seg.copy()
        k = min(xf, len(s))
        if k > 0 and i > 0:          # crossfade this bar's head against the previous bar's tail
            s[:k] *= fade_in[:k]
        if k > 0 and i < len(segs) - 1:  # fade this bar's tail out into the next bar's head
            s[len(s) - k:] *= fade_out[:k]
        out[pos:pos + len(s)] += s
        pos += hop
    return out[:total]


def _hold(buf: np.ndarray, need: int) -> np.ndarray:
    """Extend a stereo buffer with silence so it can hold audio out to `need` samples."""
    if need > len(buf):
        return np.vstack([buf, np.zeros((need - len(buf), 2), dtype=np.float32)])
    return buf


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
    opens up across the segment, building anticipation into the next entry — a crossfade
    from a low-passed copy to the original. The filter can overshoot the input peak, but
    that is folded into the final peak-normalize + clip guard downstream, so the master
    never clips."""
    n = len(seg)
    if n < 64:
        return seg
    sos = butter(4, _SWEEP_LO_HZ / (sr / 2), btype="low", output="sos")
    muffled = sosfilt(sos, seg, axis=0).astype(np.float32)
    ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)[:, None]  # 0 = muffled -> 1 = open
    swept = muffled * (1.0 - ramp) + seg * ramp
    # Ease the leading edge from the original bed into the muffled sweep over ~10 ms so the
    # start of the sweep can't click against the un-muffled bed sample just before it.
    k = min(int(sr * 0.01), n // 2)
    if k > 0:
        lead = np.linspace(0.0, 1.0, k, dtype=np.float32)[:, None]
        swept[:k] = seg[:k] * (1.0 - lead) + swept[:k] * lead
    return swept


def _build_bed(seg: np.ndarray, sr: int) -> np.ndarray:
    """A produced-drop BUILD: across this (multi-bar) segment the bed goes muffled+quiet ->
    open+loud, so the drop is felt coming (real energy dynamics, not a flat beat). Reuses the
    low-pass sweep for the 'opening up' and adds a rising volume ramp. Any level overshoot folds
    into the downstream peak-normalize + clip guard, so the master never clips."""
    n = len(seg)
    if n < 64:
        return seg
    swept = _sweep_bed(seg, sr)  # muffled -> open across the span
    ramp = np.linspace(_BUILD_GAIN_LO, 1.0, n, dtype=np.float32)[:, None]  # quiet -> loud into the drop
    return (swept * ramp).astype(np.float32)


def _echo(voc: np.ndarray, bpm: float) -> np.ndarray:
    """Throw a decaying ECHO of only the LAST word or two of the vocal (delay ~a dotted-eighth of
    the beat), so the repeats ring out AFTER the line ends — the classic vocal throw — rather than
    smearing echoes across the whole lyric. The dry vocal plays through untouched; only its tail
    segment is repeated, decaying, past the end. The dry vocal is already edge-faded, so the
    repeated segment is faded too (no clicks). Peaks fold into the downstream normalize + clip
    guard; the total tail past the vocal stays delay*_ECHO_TAPS (the R1 echo-tail guard bound)."""
    n = len(voc)
    if bpm <= 0 or n == 0:
        return voc
    delay = max(1, int((60.0 / bpm) * _ECHO_BEATS * SR))
    seg_len = min(int(_ECHO_SEG_SECS * SR), n)  # the last word(s) — the only part that echoes
    seg = voc[n - seg_len:]
    out = np.zeros((n + delay * _ECHO_TAPS, 2), dtype=np.float32)
    out[:n] += voc  # the dry vocal, unchanged — no echo THROUGHOUT the line
    g = _ECHO_FEEDBACK
    for k in range(1, _ECHO_TAPS + 1):
        off = (n - seg_len) + delay * k  # each repeat of the last word, a beat further out, decaying
        out[off:off + seg_len] += seg * g
        g *= _ECHO_FEEDBACK
    return _guard_duration(out)  # a tiny/octave-halved bpm can't balloon the tail buffer


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

    prev_voc_end = 0  # sample where the last placed vocal ended — a build never reaches back over it
    for p in _placements_of(plan):
        warp = getattr(p, "warp", None)
        if warp:  # M4d: per-bar beat-lock — each bar re-locked to Song 1's grid (no drift)
            voc = _edge_fade(_vocal_take_warped(song2_vocal, warp))
        else:  # legacy single global stretch (M3/M4a–c cached plans, or a thin-grid fallback)
            start, end = p.vocal_src
            voc = _edge_fade(_vocal_take(song2_vocal, start, max(end - start, 0.0), plan.vocal_stretch))
        if getattr(p, "echo", False):  # ring the (already edge-faded) vocal out into the drop
            voc = _echo(voc, plan.master_bpm)
        anchor = max(0, int(p.anchor * SR))  # never place before the start
        b0 = max(0, anchor - bar)
        build_bars = getattr(p, "build_bars", 0)
        if build_bars > 0:  # produced drop: a multi-bar filter+volume BUILD into the entry
            bstart = max(0, prev_voc_end, anchor - build_bars * bar)  # never reach back over a prior vocal
            if bstart < anchor:
                bed[bstart:anchor] = _build_bed(bed[bstart:anchor], SR)
        else:  # the plain-entry moves (unchanged): one-bar breath duck and/or one-bar sweep
            if getattr(p, "beat_breath", False):  # DUCK the bed for one bar (tension), never silence it
                bed[b0:anchor] *= _BREATH_DUCK
            if getattr(p, "fx", None) == "sweep_in":  # muffled -> open across the bar before the entry
                bed[b0:anchor] = _sweep_bed(bed[b0:anchor], SR)
        need = anchor + len(voc)
        bed = _hold(bed, need)
        bed[anchor:need] += voc
        prev_voc_end = need

    # Slice B contrast: Song 1's OWN vocal answers in the beat-only gaps (never overlapping
    # Song 2's vocal — the referee guarantees it). No stretch — it is already Song 1's tempo.
    s1_vocals = song1_stems.get("vocals")
    for s, e in getattr(plan, "s1_vocal_regions", []):
        if s1_vocals is None:
            break
        # Song 1 leads its own vocal here, played as recorded (its natural phrase-end decay is the
        # blend into Song 2 — we don't impose a fade); only an edge fade guards against a click.
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
