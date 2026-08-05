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

from workers import chain_guards  # standalone level/crest guards (P2 + mush); render never mutates it

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
_BED_STEMS = ("drums", "bass", "other")  # Song 1's bed, kept SEPARATE so a StemMove can ride one
_STEM_SLAM_MS = 8.0  # declick ramp at a stem move's edges so a 0->1 slam is crisp but never clicks
_SWEEP_LO_HZ = 300.0  # filter-sweep floor: the bed muffles to this cutoff, then opens up
_BUILD_GAIN_LO = 0.55  # a produced-drop BUILD starts at this volume and rises to 1.0 (energy climbing)
_ECHO_BEATS = 0.75  # produced-drop ECHO delay, in beats (a dotted-eighth — the classic vocal throw)
_ECHO_FEEDBACK = 0.42  # each echo repeat is this fraction of the previous (decaying tail)
_ECHO_TAPS = 4  # how many decaying repeats the echo throws
_ECHO_SEG_SECS = 1.2  # echo only the LAST ~1.2s (the last word or two) of each phrase, not the whole line
_ECHO_SILENCE_FRAC = 0.12  # a bar is "a pause" when the vocal envelope drops below this fraction of its peak
_ECHO_MIN_GAP_SECS = 0.15  # a pause this long or longer separates two sung phrases (each gets its own throw)
_CHOP_SECS = 0.22  # the hook ONSET fragment a vocal chop re-fires (~one syllable — "dum")
_CHOP_INTERVAL_BEATS = 0.5  # re-fire the chop every 8th note (rhythmic "dum-da-ra-dum" on the beat grid)
_FFMPEG_TIMEOUT = 180
# Bound decoded audio so a tiny-but-hours-long low-bitrate file can't balloon in
# memory (the upload cap is on bytes, not duration). A decoded stereo minute is
# ~10 MB; 12 minutes caps one buffer near ~130 MB — generous for any real song.
_MAX_DECODED_SECS = 12 * 60

# ---------------------------------------------------------------- Effect pool (2026-08-05)
# One optional SPACE effect + one optional WIDTH effect, layered on top of the base vocal chain and
# chosen per-take by the planner for regenerate variety. The engine OBEYS Placement.space/width; the
# planner decides (same brain-plans/engine-executes contract as the chain). None/None => byte-identical
# to the pre-pool path. Cumulative level is safe BY CONSTRUCTION: all added wet is summed and jointly
# trimmed (_max_wet_gain) so a placement's pooled peak never exceeds the dry by more than the headroom
# below — no matter what stacks. chain_guards (P2 + crest) stays as the independent render-side backstop.
# Near the P2 ceiling (+3 dB), leaving ~0.3 dB margin. Raised from the original +1.5 dB (2026-08-05):
# +1.5 was peak-neutral by design, which made every effect INAUDIBLE in the full mix (measured -17.6 dB
# below the mix). An effect the user should HEAR must spend real level budget — so the joint trim now
# lets the pooled vocal use most of the P2 headroom. Stacking (space+width) still measured P2-safe (+2.7).
_POOL_HEADROOM_DB = 2.7
# The bed ducks by this much under a placement that carries a pool effect, so the wet (reverb tail / echo
# throw) isn't masked by the drums+bass — the founder-chosen "duck the bed so it isn't masked". Fixed and
# far above silence (0.75 ≈ -2.5 dB), so it can never create a silent hole. No pool effect => no duck =>
# byte-identical to the pre-pool render.
_POOL_BED_DUCK = 10.0 ** (-2.5 / 20.0)
_POOL_SEED = 20260805  # 🔒 FIXED seed -> pool reverb IRs (and every render) are deterministic (golden-safe)
# SPACE reverbs — (ir_secs, decay, predelay_ms, bright). LENGTH-PRESERVING (wet truncated to dry length),
# so they are safe on ANY placement and never change placement_end / the referee's R1 overlap math.
_POOL_REVERBS = {
    "room":     (0.6, 6.0,  0.0, False),  # a subtle close space
    "hall":     (2.5, 2.0,  0.0, False),  # long hall
    "plate":    (1.2, 4.0,  0.0, True),   # bright plate
    "predelay": (1.0, 5.0, 60.0, False),  # pre-delayed room
}
_POOL_REVERB_WET = 0.55  # wet weight before joint level-comp — matches the harness wet/dry ratio (~0.42)
                         # the founder validated; raised from 0.28 (that was ~4 dB weaker, inaudible)
# TAIL-EXTENDERS — ring PAST the dry, so they are allowed only on the FINAL placement (referee-enforced),
# where nothing follows. throw = a stronger/darker echo than _echo; freeze = the last words dumped to a
# long 100%-wet tail.
_POOL_THROW_BEATS = 1.0
_POOL_THROW_TAPS = 16
_POOL_THROW_FEEDBACK = 0.68
_POOL_THROW_LP_HZ = 2200.0
_POOL_FREEZE_SEG_SECS = 2.0   # freeze the LAST ~2 s of the phrase
_POOL_FREEZE_IR_SECS = 3.0
_POOL_FREEZE_DECAY = 1.2
# WIDTH — two detuned copies panned L/R (mono-safe: chorus, not cancellation — verified 2026-08-05).
_POOL_DOUBLE_DETUNE = 0.003          # ± resample factor (~±5 cents)
_POOL_DOUBLE_DELAYS_MS = (16.0, 24.0)
_POOL_DOUBLE_MAX_COPY = 0.7          # copy gain ceiling before joint level-comp
# The vocabularies the engine implements (the referee & planner keep their own matching copies — a
# cross-check test asserts agreement, mirroring how validate.py hardcodes _KNOWN_FX independently).
_POOL_SPACE_LENGTH_PRESERVING = frozenset(_POOL_REVERBS)      # room/hall/plate/predelay
_POOL_SPACE_TAIL_EXTENDING = frozenset({"throw", "freeze"})   # final placement only
_POOL_WIDTH = frozenset({"double"})


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


def _atempo_file(src: Path, ratio: float, out: Path) -> Path:
    """Time-stretch a whole audio file by `ratio` (pitch-preserved atempo) to a WAV at `out`.

    Used by the movable master to retime Song 1's whole bed to the shared tempo before the
    arrangement is laid down — so the stretched stems sit on the same retimed grid the plan's
    anchors/warp already assume. `ratio` is the house bed_stretch (~0.96–1.08 in practice; the
    caller checks it is inside atempo's range)."""
    _run_ffmpeg(["ffmpeg", "-y", "-i", str(src), "-ar", str(SR), "-ac", "2",
                 "-filter:a", f"atempo={ratio:.6f}", str(out)])
    return out


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


def _stem_envelope(length: int, moves, stem: str, sr: int) -> np.ndarray:
    """The per-sample gain curve for one bed stem (Step 3): 1.0 everywhere, except inside each
    StemMove on THIS stem, where it linearly ramps gain_from -> gain_to across [start, end]. A
    short declick ramp returns it to 1.0 at the trailing edge (so a 0->1 slam is crisp but never
    clicks), and eases it down from 1.0 at the leading edge if the move starts already ducked. The
    curve is continuous by construction, so multiplying a stem by it never introduces a click.

    Multiplied in (not assigned), so overlapping moves compose sensibly; moves not on this stem, or
    with a non-positive window, contribute nothing. No moves => all ones => the stem is untouched.
    """
    env = np.ones(length, dtype=np.float32)
    slam = max(1, int(sr * _STEM_SLAM_MS / 1000))
    for m in moves:
        if getattr(m, "stem", None) != stem:
            continue
        s = max(0, int(m.start * sr))
        e = min(length, int(m.end * sr))
        if e <= s:
            continue
        gf, gt = float(m.gain_from), float(m.gain_to)
        env[s:e] *= np.linspace(gf, gt, e - s, dtype=np.float32)  # the ramp
        e2 = min(e + slam, length)
        if e2 > e:  # trailing declick: gain_to -> 1.0 (the slam), so the return never clicks
            env[e:e2] *= np.linspace(gt, 1.0, e2 - e, dtype=np.float32)
        s0 = max(0, s - slam)
        if s > s0 and gf < 1.0:  # leading declick: 1.0 -> gain_from (only if the move starts ducked)
            env[s0:s] *= np.linspace(1.0, gf, s - s0, dtype=np.float32)
    return env


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


def _phrase_ends(voc: np.ndarray) -> list[int]:
    """The sample index where each sung PHRASE ends — the vocal is 3-4 phrases with pauses between,
    so we split on the pauses. A phrase ends where the vocal envelope drops into a pause of at least
    _ECHO_MIN_GAP_SECS; the final phrase ends where the vocal itself ends (if it ends voiced)."""
    n = len(voc)
    mono = np.abs(voc).mean(axis=1) if voc.ndim == 2 else np.abs(voc)
    win = max(1, int(0.02 * SR))
    env = np.convolve(mono, np.ones(win, dtype=np.float32) / win, mode="same")
    peak = float(env.max())
    if peak <= 0:
        return []
    voiced = env > (_ECHO_SILENCE_FRAC * peak)
    min_gap = max(1, int(_ECHO_MIN_GAP_SECS * SR))
    ends: list[int] = []
    i = 1
    while i < n:
        if voiced[i - 1] and not voiced[i]:  # a falling edge: the vocal just stopped
            j = i
            while j < n and not voiced[j]:  # measure the pause
                j += 1
            if j - i >= min_gap:  # a real pause -> the phrase ended at i
                ends.append(i)
            i = j
        else:
            i += 1
    if voiced[n - 1]:  # the vocal ends mid-word -> the final phrase ends at the very end
        ends.append(n)
    return ends


def _echo(voc: np.ndarray, bpm: float) -> np.ndarray:
    """Throw a decaying ECHO after EACH sung phrase — echo the last word or two of every phrase into
    the pause that follows it (delay ~a dotted-eighth of the beat), the way a DJ throws a vocal.
    The dry vocal plays through untouched; only each phrase's tail is repeated, decaying. The dry
    vocal is already edge-faded, so the repeated segment is faded too (no clicks). Peaks fold into
    the downstream normalize + clip guard; the tail past the vocal (from the final phrase) extends
    delay*_ECHO_TAPS beyond the dry slice. NOTE (2026-08-05): this tail is NOT accounted for by
    placement_end (fence.py) or the R1 overlap check (validate.py) — both measure ONLY the dry
    rendered length, so a long echo tail runs past the placement end UNPOLICED. (An earlier version
    of this docstring claimed an "R1 echo-tail guard" that does not exist in validate.py.)"""
    n = len(voc)
    if bpm <= 0 or n == 0:
        return voc
    delay = max(1, int((60.0 / bpm) * _ECHO_BEATS * SR))
    ends = _phrase_ends(voc) or [n]  # a steady, gap-less vocal is one phrase (echo its end)
    seg_max = int(_ECHO_SEG_SECS * SR)
    out = np.zeros((n + delay * _ECHO_TAPS, 2), dtype=np.float32)
    out[:n] += voc  # the dry vocal, unchanged — no echo THROUGHOUT a phrase
    for end in ends:
        seg_len = min(seg_max, end)  # this phrase's last word(s)
        seg = voc[end - seg_len:end]
        g = _ECHO_FEEDBACK
        for k in range(1, _ECHO_TAPS + 1):
            off = (end - seg_len) + delay * k  # each repeat, a beat further into the pause, decaying
            m = min(seg_len, len(out) - off)
            if m > 0:
                out[off:off + m] += seg[:m] * g
            g *= _ECHO_FEEDBACK
    return _guard_duration(out)  # a tiny/octave-halved bpm can't balloon the tail buffer


def _chop_pattern(voc: np.ndarray, out_len: int, bpm: float) -> np.ndarray:
    """A VOCAL CHOP: fill `out_len` samples (one bar of the drop) with the hook ONSET of `voc`
    re-fired on the beat grid — "dum-da-ra-dum". The fragment is the first `_CHOP_SECS` of the
    vocal (its first syllable), edge-faded so each hit is click-free, laid every
    `_CHOP_INTERVAL_BEATS` of the beat. Returns exactly `out_len` samples, so it REPLACES the
    vocal's first bar without changing the placement's total length (the referee's overlap math is
    untouched). Peaks fold into the downstream peak-normalize + clip guard, so it never clips.

    Returns the vocal's own first `out_len` samples unchanged if there's no usable fragment or tempo
    (a graceful no-op — never worse than the un-chopped bar)."""
    frag = _edge_fade(voc[: int(_CHOP_SECS * SR)].copy())
    out = np.zeros((out_len, 2), dtype=np.float32)
    if len(frag) == 0 or bpm <= 0 or out_len <= 0:
        return voc[:out_len].copy() if len(voc) else out
    step = max(1, int((60.0 / bpm) * _CHOP_INTERVAL_BEATS * SR))  # 8th-note spacing on Song 1's grid
    pos = 0
    while pos < out_len:
        m = min(len(frag), out_len - pos)
        out[pos: pos + m] += frag[:m]
        pos += step
    return out


def _placements_of(plan):
    """The plan's vocal placements — or the scalar anchor/vocal_src as a one-element
    arrangement, so a legacy (M3) single-placement plan still renders."""
    if getattr(plan, "placements", None):
        return plan.placements
    return [type("P", (), {"anchor": plan.anchor, "vocal_src": plan.vocal_src,
                           "beat_breath": getattr(plan, "beat_breath", False)})()]


# ---------------------------------------------------------------- Phase 0: the vocal chain (stages 1-9)
# The planner decides; the renderer OBEYS. Every stage below is driven by a VocalProcessMove / DuckMove
# the planner emitted — the renderer NEVER reads VocalChainConfig. With no moves (the chain disabled),
# nothing here runs and the render is byte-identical to m6.0 (the golden-file gate).
#
# The values below are fixed effect-SHAPE constants (like _SWEEP_LO_HZ etc. already in this file) — the
# CURVE of each effect, not a per-mix decision. The tunable per-stage AMOUNTS all come from the move's
# dials (deess / highpass_hz / compress_ratio / saturate_wet / presence_gain_db / reverb_wet /
# pitch_semitones). A neutral dial => that stage is a no-op (this is the per-stage kill switch: the
# planner emits a neutral dial when the config disables a stage).
_SATURATE_DRIVE = 2.0          # tanh input gain (shape); saturation AMOUNT is move.saturate_wet
_SATURATE_WET_CAP = 0.5        # 🔒 hard cap (also enforced by referee P3)
_COMPRESS_THRESHOLD_DB = -18.0  # acompressor threshold (shape); AMOUNT is move.compress_ratio
_PRESENCE_HZ = 3000.0          # presence bell centre (shape); AMOUNT is move.presence_gain_db
_PRESENCE_Q = 0.8
_REVERB_SECS = 0.6             # convolution IR length; the wet tail is TRUNCATED to the dry length
_REVERB_DECAY = 6.0            # exponential decay of the synthetic IR
_REVERB_SEED = 20260710        # 🔒 FIXED seed -> the IR (and every render) is deterministic (golden-safe)
# Referee P2 (pre-master ceiling) AND the crest-factor mush guard live in the standalone
# `workers.chain_guards` module (imported above) — deliberately NOT inline here, so the guard cannot
# silently drift when this chain code changes. render_mix calls it after the chain; it never mutates it.


def _fit_length(y: np.ndarray, n: int) -> np.ndarray:
    """Trim or zero-pad a stereo array to exactly `n` samples. The whole vocal chain is length-
    preserving by construction, so a placed vocal's length — and thus `placement_end` and the
    referee's R1 overlap math — is NEVER changed by processing."""
    if len(y) > n:
        return y[:n]
    if len(y) < n:
        return np.vstack([y, np.zeros((n - len(y), 2), dtype=np.float32)])
    return y


def _ffmpeg_filter_array(voc: np.ndarray, filtergraph: str, sr: int) -> np.ndarray:
    """Run one FFmpeg audio filtergraph on a stereo float array and return it at the SAME length.
    Used for the stages FFmpeg does well (de-ess / high-pass / compress / presence EQ in one pass, and
    rubberband pitch in another). A 32-bit float intermediate WAV keeps precision between stages."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        i, o = Path(td) / "i.wav", Path(td) / "o.wav"
        sf.write(i, voc, sr, subtype="FLOAT")
        _run_ffmpeg(["ffmpeg", "-y", "-i", str(i), "-filter:a", filtergraph,
                     "-ar", str(sr), "-ac", "2", "-c:a", "pcm_f32le", str(o)])
        y, _ = sf.read(o, dtype="float32", always_2d=True)
    return _fit_length(y, len(voc))


def _pitch_shift(voc: np.ndarray, semitones: float, sr: int) -> np.ndarray:
    """Stage 3 — rubberband pitch shift with formants PRESERVED (never the `shifted` chipmunk default)
    and pitch quality set explicitly. Pitch-only (tempo=1) -> length-preserving."""
    ratio = 2.0 ** (semitones / 12.0)
    return _ffmpeg_filter_array(voc, f"rubberband=pitch={ratio:.6f}:formant=preserved:pitchq=quality", sr)


def _saturate(x: np.ndarray, drive: float, wet: float) -> np.ndarray:
    """Stage 6 — tanh soft-clip, dry/wet blended. `wet` is hard-capped at 0.5 (not a suggestion)."""
    wet = min(wet, _SATURATE_WET_CAP)
    return ((1.0 - wet) * x + wet * np.tanh(x * drive)).astype(np.float32)


def _reverb_ir(sr: int) -> np.ndarray:
    """A short, DETERMINISTIC exponentially-decaying-noise impulse response, L2-normalized.

    FFmpeg has no native algorithmic reverb (only `aecho`, a delay, and `afir`, which needs an IR
    asset). This is a small deterministic convolution reverb chosen for testability and zero binary
    assets — NOT because convolution is the ideal reverb here. Placeholder-grade. Revisit if it sounds
    thin. The FIXED seed makes the IR — and therefore every render — reproducible (golden-file safe).

    ⭐ The IR is normalized ONCE HERE, by its L2 (energy) norm, so convolution is peak-neutral as a
    FIXED PROPERTY of the IR (measured -0.9 dB peak gain on a real vocal; energy-preserving, so the
    reverb is audible). That is what makes `reverb_wet` a TRANSFERABLE, SONG-INDEPENDENT number — the
    tuning week's winning value must mean the same thing on every pair. (Normalizing the WET per render
    instead — the first fix — made the effect signal-dependent: a spiky vocal got less reverb than a
    squashed one at the same dial. That is exactly the property we must NOT have while a dial is tuned.)"""
    rng = np.random.default_rng(_REVERB_SEED)
    n = int(_REVERB_SECS * sr)
    t = np.linspace(0.0, _REVERB_SECS, n, endpoint=False)
    ir = (rng.standard_normal(n).astype(np.float32)) * np.exp(-_REVERB_DECAY * t).astype(np.float32)
    l2 = float(np.sqrt(np.sum(np.square(ir))))
    return (ir / l2).astype(np.float32) if l2 > 0 else ir


def _reverb(voc: np.ndarray, wet: float, sr: int) -> np.ndarray:
    """Stage 8 — a convolution-reverb SEND (dry/wet blend). Length-preserving: the wet tail is
    truncated to the dry length so the vocal's length (and R1 overlap math) is unchanged. The IR is
    L2-normalized at generation (`_reverb_ir`), so the wet is peak-neutral and `reverb_wet` is
    song-independent — there is deliberately NO per-render normalization here."""
    from scipy.signal import fftconvolve

    ir = _reverb_ir(sr)
    wetsig = np.empty_like(voc)
    for ch in range(voc.shape[1]):
        wetsig[:, ch] = fftconvolve(voc[:, ch], ir)[: len(voc)]
    return ((1.0 - wet) * voc + wet * wetsig).astype(np.float32)


# ---------------------------------------------------------------- Effect pool DSP primitives
def _max_wet_gain(dry_buf: np.ndarray, wet_buf: np.ndarray, pk_in: float,
                  headroom_db: float = _POOL_HEADROOM_DB, g_max: float = 1.0) -> float:
    """Largest gain g in [0, g_max] such that peak(dry_buf + g*wet_buf) stays within `headroom_db`
    of `pk_in` (the dry peak). The pool's by-construction level guarantee: the dry stays at UNITY
    (vocal-vs-bed balance untouched) and ONLY the added wet is trimmed, exactly as much as needed.
    Deterministic bisection. peak(g)=max_i|dry_i + g*wet_i| is CONVEX in g (a max of affine terms), so
    its sub-level set {g: peak(g)<=target} is a single interval; g=0 is always in it (peak(0)=pk_in <=
    target since headroom_db>=0), so bisecting from [0, g_max] converges to the true upper bound. (This
    rests on g=0 being feasible — keep headroom_db >= 0 and the lower bound at 0.)"""
    if pk_in <= 0.0:
        return g_max
    target = pk_in * (10.0 ** (headroom_db / 20.0))

    def pk(g: float) -> float:
        return float(np.max(np.abs(dry_buf + g * wet_buf)))

    if pk(g_max) <= target:
        return g_max
    lo, hi = 0.0, g_max
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if pk(mid) <= target:
            lo = mid
        else:
            hi = mid
    return lo


def _pool_lp(x: np.ndarray, hz: float) -> np.ndarray:
    sos = butter(4, min(hz, SR / 2 - 1) / (SR / 2), btype="low", output="sos")
    return sosfilt(sos, x, axis=0).astype(np.float32)


def _pool_pan(mono2: np.ndarray, side: str) -> np.ndarray:
    """Collapse a stereo array to mono and place it hard L or R (the width doubler's copies)."""
    m = mono2.mean(axis=1)
    out = np.zeros_like(mono2)
    out[:, 0 if side == "L" else 1] = m
    return out


def _pool_detune(x: np.ndarray, factor: float) -> np.ndarray:
    """Cheap ADT-style detune via linear resample (shifts pitch+length a hair). Deliberately avoids
    the rubberband filter, which throws std::bad_alloc on this ARM ffmpeg build (verified 2026-08-05)."""
    n = len(x)
    idx = np.arange(0, n, factor)
    out = np.zeros((len(idx), 2), dtype=np.float32)
    for ch in range(2):
        out[:, ch] = np.interp(idx, np.arange(n), x[:, ch])
    return out


def _pool_ir(secs: float, decay: float, bright: bool) -> np.ndarray:
    """A deterministic exponentially-decaying-noise IR, L2-normalized (peak-neutral, like _reverb_ir).
    FIXED seed => reproducible (golden-safe)."""
    rng = np.random.default_rng(_POOL_SEED)
    n = int(secs * SR)
    t = np.linspace(0.0, secs, n, endpoint=False)
    ir = rng.standard_normal(n).astype(np.float32) * np.exp(-decay * t).astype(np.float32)
    if bright:
        sos = butter(4, 1200.0 / (SR / 2), btype="high", output="sos")
        ir = sosfilt(sos, ir).astype(np.float32)
    l2 = float(np.sqrt(np.sum(np.square(ir))))
    return (ir / l2).astype(np.float32) if l2 > 0 else ir


def _pool_reverb_wet(dry: np.ndarray, name: str) -> np.ndarray:
    """The WET signal of a SPACE reverb preset, TRUNCATED to the dry length (length-preserving, so a
    placement's length / the referee's R1 overlap math never changes)."""
    from scipy.signal import fftconvolve

    secs, decay, predelay_ms, bright = _POOL_REVERBS[name]
    ir = _pool_ir(secs, decay, bright)
    pre = int(predelay_ms / 1000.0 * SR)
    n = len(dry)
    wet = np.zeros((n, 2), dtype=np.float32)
    if pre < n:
        for ch in range(2):
            conv = fftconvolve(dry[:, ch], ir)
            m = min(n - pre, len(conv))
            wet[pre:pre + m, ch] += conv[:m]
    return wet


def _pool_throw_wet(voc: np.ndarray, bpm: float) -> np.ndarray:
    """A darkening feedback-echo tail that rings PAST the dry (stronger than _echo). Returns a wet
    buffer longer than `voc` by delay*taps — used ONLY on the final placement."""
    n = len(voc)
    if bpm <= 0 or n == 0:
        return np.zeros((n, 2), dtype=np.float32)
    d = max(1, int((60.0 / bpm) * _POOL_THROW_BEATS * SR))
    total = n + d * _POOL_THROW_TAPS
    wet = np.zeros((total, 2), dtype=np.float32)
    seg = voc.copy()
    for k in range(1, _POOL_THROW_TAPS + 1):
        seg = _pool_lp(seg * _POOL_THROW_FEEDBACK, _POOL_THROW_LP_HZ)  # each repeat darker + quieter
        off = d * k
        m = min(len(seg), total - off)
        if m > 0:
            wet[off:off + m] += seg[:m]
    return wet


def _pool_freeze_wet(voc: np.ndarray) -> np.ndarray:
    """Dump the LAST ~_POOL_FREEZE_SEG_SECS of the vocal into a long 100%-wet tail ringing past the
    dry. Returns a wet buffer longer than `voc` — used ONLY on the final placement."""
    from scipy.signal import fftconvolve

    n = len(voc)
    if n == 0:
        return np.zeros((0, 2), dtype=np.float32)
    ir = _pool_ir(_POOL_FREEZE_IR_SECS, _POOL_FREEZE_DECAY, False)
    seg_len = min(int(_POOL_FREEZE_SEG_SECS * SR), n)
    start = n - seg_len
    seg = voc[start:]
    total = n + len(ir)
    wet = np.zeros((total, 2), dtype=np.float32)
    for ch in range(2):
        conv = fftconvolve(seg[:, ch], ir)
        m = min(len(conv), total - start)
        wet[start:start + m, ch] += conv[:m]
    return wet


def _pool_double_wet(voc: np.ndarray) -> np.ndarray:
    """The width doubler's two detuned, hard-panned copies (WET only — the caller adds the dry and
    fits to length, keeping width length-preserving). Mono-safe: chorus, not cancellation."""
    up = _pool_detune(voc, 1.0 + _POOL_DOUBLE_DETUNE)
    dn = _pool_detune(voc, 1.0 - _POOL_DOUBLE_DETUNE)
    d1 = int(_POOL_DOUBLE_DELAYS_MS[0] / 1000.0 * SR)
    d2 = int(_POOL_DOUBLE_DELAYS_MS[1] / 1000.0 * SR)
    total = len(voc) + d2
    copies = np.zeros((total, 2), dtype=np.float32)
    Lp, Rp = _pool_pan(up, "L"), _pool_pan(dn, "R")
    copies[d1:d1 + len(Lp)] += Lp[:total - d1]
    copies[d2:d2 + len(Rp)] += Rp[:total - d2]
    return copies


def _apply_pool(voc: np.ndarray, p, bpm: float, is_final: bool) -> np.ndarray:
    """Layer a placement's pool SPACE + WIDTH effects on the (already base-chained) vocal.

    Dry stays at unity; every added wet component is summed and JOINTLY trimmed to within
    _POOL_HEADROOM_DB of the dry peak — cumulative-level safety by construction (this is what lets the
    pool stack effects that were each near the P2 ceiling alone). Interior placements use only
    length-preserving effects; TAIL-EXTENDERS (throw/freeze) ring past the dry and run ONLY when
    is_final (else they are fit back to length as a safe fallback — the referee also rejects a
    tail-extender on a non-final placement, so this is defense-in-depth). None/None => voc unchanged."""
    space = getattr(p, "space", None)
    width = getattr(p, "width", None)
    if not space and not width:
        return voc
    n = len(voc)
    pk_in = float(np.max(np.abs(voc))) if voc.size else 0.0

    tail_extending = space in _POOL_SPACE_TAIL_EXTENDING and is_final
    space_wet = None
    if space in _POOL_SPACE_LENGTH_PRESERVING:
        space_wet = _POOL_REVERB_WET * _pool_reverb_wet(voc, space)
    elif space == "throw":
        space_wet = _pool_throw_wet(voc, bpm)
    elif space == "freeze":
        space_wet = _pool_freeze_wet(voc)
    if space_wet is not None and not tail_extending and len(space_wet) != n:
        space_wet = _fit_length(space_wet, n)  # interior fallback: never overrun a following vocal

    width_wet = None
    if width == "double":
        width_wet = _fit_length(_POOL_DOUBLE_MAX_COPY * _pool_double_wet(voc), n)  # length-preserving

    total = n
    for w in (space_wet, width_wet):
        if w is not None:
            total = max(total, len(w))
    dry_buf = np.zeros((total, 2), dtype=np.float32)
    dry_buf[:n] += voc
    wet_buf = np.zeros((total, 2), dtype=np.float32)
    for w in (space_wet, width_wet):
        if w is not None:
            wet_buf[:len(w)] += w
    g = _max_wet_gain(dry_buf, wet_buf, pk_in)
    return (dry_buf + g * wet_buf).astype(np.float32)


def _apply_vocal_chain(voc: np.ndarray, m, sr: int) -> np.ndarray:
    """Apply the vocal chain (stages 1,2,3,5,6,7,8) to a placed vocal, per the planner's move `m`.

    LENGTH-PRESERVING by construction (`_fit_length` at the end), so a placed vocal's length —
    `placement_end` and the referee's R1 overlap math — is never changed by processing. De-ess (stage
    1) precedes saturate (stage 6) by construction (a fixed-order pipeline, not a user-orderable list):
    saturation is non-linear and amplifies the separation artifacts de-ess removes. Each stage is a
    no-op when its dial is neutral (the per-stage kill switch). Stage 4 (time-stretch) already ran
    upstream in `_vocal_take*` and is NOT touched here.

    Two engine boundaries: stages 1,2,5,7 in ONE FFmpeg filtergraph (single decode/encode), then
    rubberband (3), then numpy saturate (6) and numpy reverb (8). Order note: the grouping runs presence
    (7) before saturate (6); the one hard rule (1 before 6) holds regardless.

    KNOWN COST (flagged, not fixed here): stages 3 (pitch) and 4 (stretch) are two sequential resampling
    passes, each adding artifacts. rubberband can do pitch+tempo in ONE call, but stage 4 uses a per-bar
    `warp_map` (variable ratio per bar) while pitch is constant across the placement, so they can't be
    trivially merged. A real future optimisation, not a Phase 0 task."""
    n0 = len(voc)
    if n0 == 0:
        return voc
    fg: list[str] = []
    if m.deess > 0.0:                                             # stage 1
        fg.append(f"deesser=i={min(max(m.deess, 0.0), 1.0):.4f}")
    if m.highpass_hz > 0:                                         # stage 2
        fg.append(f"highpass=f={int(m.highpass_hz)}")
    if m.compress_ratio > 1.0:                                    # stage 5
        fg.append(f"acompressor=threshold={_COMPRESS_THRESHOLD_DB}dB:ratio={float(m.compress_ratio):.4f}")
    if m.presence_gain_db != 0.0:                                 # stage 7
        fg.append(f"equalizer=f={_PRESENCE_HZ}:t=q:w={_PRESENCE_Q}:g={float(m.presence_gain_db):.4f}")
    if fg:
        voc = _ffmpeg_filter_array(voc, ",".join(fg), sr)
    if abs(m.pitch_semitones) > 1e-9:                             # stage 3
        voc = _pitch_shift(voc, float(m.pitch_semitones), sr)
    if m.saturate_wet > 0.0:                                      # stage 6 (after stage 1, always)
        voc = _saturate(voc, _SATURATE_DRIVE, float(m.saturate_wet))
    if m.reverb_wet > 0.0:                                        # stage 8
        voc = _reverb(voc, min(float(m.reverb_wet), 1.0), sr)
    return _fit_length(voc, n0)


def _smooth_env(env: np.ndarray, attack_ms: float, release_ms: float, sr: int) -> np.ndarray:
    """Smooth a 0..1 presence envelope with a single-pole filter (release-dominated; attack
    approximated). Vectorized + deterministic. Only used by the stage-9 duck."""
    from scipy.signal import lfilter

    tau = max(float(attack_ms), float(release_ms)) * 0.001 * sr
    a = float(np.exp(-1.0 / max(1.0, tau)))
    return lfilter([1.0 - a], [1.0, -a], env).astype(np.float32)


def _duck_bed(bed: np.ndarray, duck_moves: list, prepared: list, sr: int) -> np.ndarray:
    """Stage 9 — a BED-side sidechain duck, keyed by the ALREADY-PLACED vocal (NOT a vocal stage).
    For each DuckMove, the bed is attenuated by up to `depth_db` while its keyed placement's vocal is
    present, smoothed over attack/release. ONLY DUCKS (gain <= 1) -> can never push the master toward
    clipping (referee P4). Runs at mix time, on the bed, before the master.

    DEVIATION FROM THE BRIEF (flagged per rule 6): the brief suggested FFmpeg `sidechaincompress`. We
    use a deterministic numpy envelope ducker instead — same reasoning as the reverb: it is exactly
    depth-accurate (a compressor can't hit "duck by 1.5 dB"), provably only-attenuating (so the P2/P4
    safety properties hold by construction), and byte-deterministic for the golden-file gate. The
    architecture the brief cares about is preserved exactly: it operates on the BED, keyed by the PLACED
    vocal, and only ducks. `target_stems` is honored for the common all-three case (the bed here is the
    summed drums+bass+other); a stem-SUBSET duck would need the stems kept separate downstream — noted,
    not needed while the chain ships disabled."""
    by_id = {f"p{i}": (max(0, int(p.anchor * sr)), voc) for i, (p, voc) in enumerate(prepared)}
    gain = np.ones(len(bed), dtype=np.float32)
    for d in duck_moves:
        key = by_id.get(getattr(d, "key_placement_id", None))
        if key is None:
            continue
        a0, voc = key
        vlen = min(len(voc), len(bed) - a0)
        if vlen <= 0:
            continue
        depth = 10.0 ** (-abs(float(d.depth_db)) / 20.0)          # linear floor, <= 1 (only ducks)
        env = np.zeros(len(bed), dtype=np.float32)
        vmono = np.abs(voc[:vlen]).mean(axis=1)
        env[a0:a0 + vlen] = vmono / (float(vmono.max()) or 1.0)
        env = _smooth_env(env, d.attack_ms, d.release_ms, sr)
        gain = np.minimum(gain, 1.0 - (1.0 - depth) * env)        # duck toward the floor where the vocal is loud
    return (bed * gain[:, None]).astype(np.float32)


# ---------------------------------------------------------------- Continuous reverb bed (Rule 4, 2026-08-05)
# A convolution reverb blended UNDER the placed vocal, rings into the gaps between lines, TRUNCATED to the
# vocal length so it never rings past the placement itself. Paired with the delay echo (_delay_echo, below)
# as Rule 4's "always both together" treatment; with the Rule-4 flag OFF (no reverb_bed) this never runs
# => byte-identical to the pre-Rule-4 render.
_REVERB_BED_SECS = 1.2        # IR length of the continuous reverb bed
_REVERB_BED_DECAY = 3.0
_REVERB_BED_WET = 0.45        # bed level (audible where it matters: ringing into the gaps)
_REVERB_BED_HEADROOM_DB = 2.0  # cap the bed's peak contribution (joint-trimmed) so it never trips P2 (+3 dB)
# NOTE: the phrase-throw / cut-ratio / re-fire machinery AND the later gap-sized echo (both earlier Rule-4
# attempts, founder-rejected by ear) were removed. The breath-safe re-fire helper is PARKED, intact, in
# workers/rule3_parked.py for a future Rule 3. Rule 4 is now _delay_echo + this reverb bed (see below).


def _reverb_bed(voc: np.ndarray) -> np.ndarray:
    """Continuous reverb bed, LENGTH-PRESERVING. A convolution reverb blended under the vocal: the wet
    rings past word-ends INTO the gaps between lines (where the gap-sized echo also lives), but is
    TRUNCATED to the vocal length so it never rings PAST the placement into the next vocal (F1
    containment). Additive at `_REVERB_BED_WET`; the master normalize + chain_guards handle level."""
    from scipy.signal import fftconvolve

    n = len(voc)
    if n == 0:
        return voc
    ir = _pool_ir(_REVERB_BED_SECS, _REVERB_BED_DECAY, bright=False)
    wet = np.empty_like(voc)
    for ch in range(voc.shape[1]):
        wet[:, ch] = fftconvolve(voc[:, ch], ir)[:n]
    # Additive reverb can inflate the peak (adversarial review 2026-08-05: +2.41 dB alone, a thin 0.59 dB
    # under the +3 dB P2 guard). JOINTLY TRIM the wet (the same `_max_wet_gain` primitive the pool uses)
    # so the bed's peak contribution never exceeds `_REVERB_BED_HEADROOM_DB` over the dry — chain_guards
    # can't spuriously RenderError a legal mix on a hotter vocal, and the bed level stays song-independent.
    wet = (_REVERB_BED_WET * wet).astype(np.float32)
    pk = float(np.max(np.abs(voc))) if voc.size else 0.0
    g = _max_wet_gain(voc, wet, pk, headroom_db=_REVERB_BED_HEADROOM_DB)
    return (voc + g * wet).astype(np.float32)


# ---------------------------------------------------------------- Rule 4: a real echo (delay) — 2026-08-05
# Take Rule 1's vocal EXACTLY as placed. On top, a REAL echo — a tempo-synced feedback DELAY on the vocal:
# the words echo back spaced a musical note apart, each pass quieter (a normal echo, NOT a chop/stutter).
# A continuous reverb bed (_reverb_bed, above) rings underneath. One variation, always both together.
# Founder EAR-APPROVED 2026-08-05 (prototyped as variant "d_quarter_long"). Ships OFF behind the flag =>
# byte-identical to main. The echo/reverb are jointly level-trimmed and the tail is kept off a Song-1
# lead, so R1 (one lead voice at a time) and the pre-master ceiling hold.
#
# ===================== TASTE KNOBS — tune BY EAR; expect these to MOVE after a listen =====================
# (Named _DELAY_ECHO_* to avoid colliding with the legacy produced-drop `_ECHO_*` constants above.)
_DELAY_ECHO_BEATS = 1.0     # delay time = a 1/4 note — the approved spacing (repeats well separated)
_DELAY_ECHO_FEEDBACK = 0.55  # each repeat is this fraction of the previous (0.55 => a long, musical tail)
_DELAY_ECHO_WET = 0.45      # how loud the echo sits vs the dry vocal (the approved level)
_DELAY_ECHO_HEADROOM_DB = 2.5  # joint-trim the echo+reverb so a placement's peak stays within this of the dry
_DELAY_ECHO_GUARD_SECS = 0.05  # keep the echo tail this far short of a Song-1 lead (never ring over it)
# =========================================================================================================
_DELAY_ECHO_MAX_TAPS = 16   # hard cap on repeats (belt-and-braces; the tail also stops at the floor below)
_DELAY_ECHO_TAP_FLOOR = 0.02  # stop adding repeats once feedback**k drops below this (inaudible, ~ -34 dB)
# How many repeats are actually AUDIBLE (feedback**k >= the floor) — the REAL tail length. Bound max_tail by
# this, not by _DELAY_ECHO_MAX_TAPS, so a placement never carries trailing silence past the echo's own decay
# (which would push the next placement's build off / cause heavy overlap). ~7 taps at feedback 0.55.
_DELAY_ECHO_DECAY_TAPS = min(_DELAY_ECHO_MAX_TAPS,
                             int(np.ceil(np.log(_DELAY_ECHO_TAP_FLOOR) / np.log(_DELAY_ECHO_FEEDBACK))))
_VOICED_FLOOR = 0.08        # RMS-below-this-of-peak = a breath, not singing (shared with rule3_parked)


def _delay_echo(voc: np.ndarray, delay_secs: float, fb: float, wet: float,
                max_tail_secs: float) -> np.ndarray:
    """A REAL feedback-delay echo of the vocal — the WET ONLY (the dry is laid separately by render_mix).
    Repeat k is the WHOLE vocal delayed by k*delay_secs at gain fb**k; summed and scaled by `wet`, so the
    words echo back spaced a musical note apart and fade. NOT a chop — every repeat is the intact vocal,
    delayed. The tail is bounded by `max_tail_secs` (so it can be kept off a Song-1 lead) AND by the
    feedback dropping below `_DELAY_ECHO_TAP_FLOOR` / `_DELAY_ECHO_MAX_TAPS`. Length = len(voc) + tail."""
    n = len(voc)
    if n == 0:
        return np.zeros((0, 2), dtype=np.float32)
    if delay_secs <= 0.0:
        return np.zeros_like(voc)
    d = max(1, int(delay_secs * SR))
    max_off = min(d * _DELAY_ECHO_MAX_TAPS, max(0, int(max_tail_secs * SR)))
    out = np.zeros((n + max_off + 1, 2), dtype=np.float32)
    g = fb
    k = 1
    while g >= _DELAY_ECHO_TAP_FLOOR:
        off = d * k
        if off > max_off:
            break
        m = min(n, len(out) - off)
        if m > 0:
            out[off:off + m] += (voc[:m] * g).astype(np.float32)
        g *= fb
        k += 1
    return _guard_duration((out * wet).astype(np.float32))


def _echo_overruns(anchor: float, placed_secs: float,
                   s1_starts_after: "list[float] | tuple[float, ...]" = ()) -> bool:
    """The independent containment NET: True if a placement's ECHOED length would ring OVER a Song-1 lead
    that trades in the gap (`s1_starts_after` = Song-1 lead starts after this placement's dry end). That is
    two DIFFERENT voices at once (R1). The echo ringing over Song 2's OWN next line is just delay of the
    same voice — allowed, and NOT flagged. Re-derives the containment the engine already bounds by
    `max_tail` (clamp AND referee), the same layered defence the validator runs plan-side."""
    end = anchor + placed_secs
    return any(end > s + 1e-9 for s in s1_starts_after)


def render_mix(plan, song1_stems: Mapping[str, Path], song2_vocal: Path,
               out_path: Path) -> Path:
    """Render `plan` to a WAV at out_path.

    song1_stems maps drums/bass/other to Song 1's stem files; song2_vocal is Song 2's
    isolated vocal file. `plan` exposes master_bpm, vocal_stretch, and either a list of
    `placements` (each with anchor / vocal_src / beat_breath) or the scalar anchor /
    vocal_src fallback. Song 1's beat runs continuously; each placement lays the vocal
    on top; beat_breath ducks the bed for one bar before that entry (never silence).

    Step 3: `plan.stem_moves` (optional) auto-performs the bed — each move rides one stem
    (drums/bass/other) by a gain envelope over an on-beat window (e.g. the bass pull-and-
    slam into a drop). No stem_moves => the bed plays flat, exactly as before.
    """
    if plan.master_bpm <= 0:
        raise RenderError("plan has a non-positive tempo")
    # Movable master: retime Song 1's WHOLE bed to the shared tempo before the arrangement is laid
    # down, so the stretched stems sit on the same retimed grid the plan's anchors/warp assume. We
    # engage on the SAME 1e-6 threshold the planner and referee use, so the bed can never be left
    # un-stretched while they assume the retimed grid (that gap would ship an off-beat mix the
    # referee couldn't see). bed_stretch is 4-dp rounded, so any real move is >= 1e-4; exactly 1.0
    # skips the stretch and renders byte-identical to today.
    bed_stretch = float(getattr(plan, "bed_stretch", 1.0) or 1.0)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as _td:
        if abs(bed_stretch - 1.0) >= 1e-6:
            if not (_ATEMPO_MIN <= bed_stretch <= _ATEMPO_MAX):
                raise RenderError(f"bed stretch {bed_stretch:.4f} outside atempo range")
            song1_stems = {name: _atempo_file(sp, bed_stretch, Path(_td) / f"{name}.wav")
                           for name, sp in song1_stems.items()}
        bar = int((60.0 / plan.master_bpm) * 4 * SR)
        # Step 3: ride each bed stem by its own gain envelope (1.0 outside its moves), then SUM the
        # three into one bed — the bass pull-and-slam is baked in HERE (the bass is enveloped down
        # across its window, and slams back at the anchor). With NO stem_moves every envelope is
        # all-ones, so this is exactly `_sum_stems([drums,bass,other])` (same stems, same order) —
        # and everything below is the ORIGINAL pipeline verbatim, so a no-move plan renders byte-for-
        # byte the same mix as before, by construction (the "old mixes still work" invariant). Doing
        # the sum first (rather than carrying the stems through the arrangement) is what keeps that
        # invariant exact: the treatments and vocal placement below operate on the bed identically to
        # the pre-Step-3 engine.
        moves = getattr(plan, "stem_moves", []) or []
        decoded = {name: _decode(song1_stems[name]) for name in _BED_STEMS}
        # Good-parts window: crop the (already retimed) bed to [win_start, win_end]. The plan's
        # anchors/stem_moves/s1_vocal_regions are window-relative (start at 0), so cropping the
        # decoded stems here aligns sample 0 with win_start. window is on the SAME retimed grid the
        # bed is on (bed_stretch already applied above), so win*SR indexes the decoded arrays directly.
        # FAIL LOUD on a malformed window (w1<=w0 -> an EMPTY bed -> a beat-less mix the render would
        # otherwise ship silently, since validate_render's audible check still sees the vocal). This
        # mirrors this file's own convention (master_bpm<=0, bed_stretch range): a bad plan is a loud
        # error, never a quiet bad mix. w1 is clamped to the bed length so a legit window ending a hair
        # past the last sample (float/atempo rounding) is fine, not a false error.
        window = getattr(plan, "window", None)
        if window:
            dec_len = max(len(a) for a in decoded.values())
            w0, w1 = int(window[0] * SR), min(int(window[1] * SR), dec_len)
            if not (0 <= w0 < w1):
                raise RenderError(f"plan.window {window} is malformed (empty or reversed crop)")
            decoded = {name: arr[w0:w1] for name, arr in decoded.items()}
        length = max(len(s) for s in decoded.values())
        bed = np.zeros((length, 2), dtype=np.float32)
        for name in _BED_STEMS:
            bed += _hold(decoded[name], length) * _stem_envelope(length, moves, name, SR)[:, None]

        # Phase 0: the planner's vocal-processing instructions. Empty when the chain is disabled -> the
        # chain and the duck are both skipped -> the render is byte-identical to m6.0 (the golden gate).
        # The renderer OBEYS these moves; it never reads VocalChainConfig. placement_id is positional
        # ("p{i}"), matching the planner's emission.
        vmoves = {getattr(m, "placement_id", None): m for m in getattr(plan, "vocal_moves", []) or []}
        duck_moves = getattr(plan, "duck_moves", []) or []

        # Pass 1 — build each placement's finished vocal. This touches ONLY the vocal (never the bed),
        # so lifting it out of the lay loop below leaves the bed's arithmetic order — and therefore the
        # rendered bytes — unchanged. The vocal chain (stages 1-8) applies HERE, length-preserving.
        prepared: list = []  # [(placement, voc_array), ...]
        all_placements = _placements_of(plan)
        # Effect pool: the FINAL placement (latest anchor) is the only one whose tail may ring past the
        # dry (throw/freeze) — nothing follows it. -1 when there are no placements.
        _final_idx = (max(range(len(all_placements)), key=lambda k: all_placements[k].anchor)
                      if all_placements else -1)
        for i, p in enumerate(all_placements):
            warp = getattr(p, "warp", None)
            if warp:  # M4d: per-bar beat-lock — each bar re-locked to Song 1's grid (no drift)
                voc = _edge_fade(_vocal_take_warped(song2_vocal, warp))
            else:  # legacy single global stretch (M3/M4a–c cached plans, or a thin-grid fallback)
                start, end = p.vocal_src
                voc = _edge_fade(_vocal_take(song2_vocal, start, max(end - start, 0.0), plan.vocal_stretch))
            vm = vmoves.get(f"p{i}")
            if vm is not None:  # Phase 0 vocal chain (stages 1-8); no move -> skipped -> byte-identical
                before = voc
                voc = _apply_vocal_chain(voc, vm, SR)
                bad = chain_guards.check_vocal_chain_output(before, voc)  # P2 peak-gain + crest mush guard
                if bad is not None:
                    raise RenderError(bad)
            # Rule 4 (simplified, 2026-08-05): when the planner set reverb_bed (flag ON), the vocal plays
            # EXACTLY as placed and we add, ON TOP, a gap-sized echo at each line-end + a continuous reverb
            # bed — always both together. MUTUALLY EXCLUSIVE with the old produced-drop echo / chop / pool
            # path below, so with the flag OFF (no reverb_bed) the ELSE branch runs exactly as today =>
            # byte-identical (incl. Placement.echo at drops).
            if getattr(p, "reverb_bed", False):
                before_r4 = voc
                dry_end = p.anchor + len(voc) / SR                      # placement_end of the DRY vocal
                beat = (60.0 / plan.master_bpm) if plan.master_bpm else 0.5
                delay_secs = _DELAY_ECHO_BEATS * beat
                # Keep the echo tail off a Song-1 lead trading in the gap (R1 — two DIFFERENT voices).
                # Ringing over Song 2's OWN next line is just delay of the same voice, so it is allowed.
                s1_starts_after = [s for s, _e in getattr(plan, "s1_vocal_regions", []) or [] if s > dry_end + 1e-6]
                natural = _DELAY_ECHO_DECAY_TAPS * delay_secs          # the echo's own AUDIBLE decay length
                max_tail = (max(0.0, min(natural, min(s1_starts_after) - dry_end - _DELAY_ECHO_GUARD_SECS))
                            if s1_starts_after else natural)
                echo = _delay_echo(voc, delay_secs, _DELAY_ECHO_FEEDBACK, _DELAY_ECHO_WET, max_tail)  # WET only
                voc = _reverb_bed(voc)                                  # dry + continuous reverb (kept)
                if len(echo) > 0:                                       # add the echo, jointly level-trimmed
                    L = max(len(voc), len(echo))
                    drybuf = np.zeros((L, 2), dtype=np.float32); drybuf[:len(voc)] += voc
                    wetbuf = np.zeros((L, 2), dtype=np.float32); wetbuf[:len(echo)] += echo
                    pk = float(np.max(np.abs(before_r4))) if before_r4.size else 0.0
                    g = _max_wet_gain(drybuf, wetbuf, pk, headroom_db=_DELAY_ECHO_HEADROOM_DB)
                    voc = (drybuf + g * wetbuf).astype(np.float32)
                bad = chain_guards.check_vocal_chain_output(before_r4, voc)  # independent level backstop
                if bad is not None:
                    raise RenderError(bad)
                # INDEPENDENT containment net: the echoed length must not ring OVER a Song-1 lead (R1).
                # Bounded by max_tail BY CONSTRUCTION; re-derived here (clamp AND referee).
                if _echo_overruns(p.anchor, len(voc) / SR, s1_starts_after):
                    raise RenderError("Rule 4 echo tail would ring over Song 1's vocal (R1)")
            else:
                if getattr(p, "chop", False):  # Step 4: re-fire the hook onset over this entry's FIRST bar
                    k = min(bar, len(voc))       # (a vocal chop). Replaces bar 1 -> voc length is unchanged,
                    if k > 0:                    # so placement_end / the referee's overlap math don't move.
                        voc[:k] = _chop_pattern(voc[:k], k, plan.master_bpm)
                # Produced-drop echo: skip when the pool put a tail-extender here (throw/freeze) so the two
                # echo mechanisms never double up. No pool space => unchanged => byte-identical.
                if getattr(p, "echo", False) and getattr(p, "space", None) not in _POOL_SPACE_TAIL_EXTENDING:
                    voc = _echo(voc, plan.master_bpm)  # ring the (already edge-faded) vocal out into the drop
                # Effect pool (2026-08-05): SPACE + WIDTH variety, jointly level-compensated. None/None =>
                # voc untouched => byte-identical. chain_guards re-runs here as the independent backstop.
                if getattr(p, "space", None) or getattr(p, "width", None):
                    before_pool = voc
                    voc = _apply_pool(voc, p, plan.master_bpm, is_final=(i == _final_idx))
                    bad = chain_guards.check_vocal_chain_output(before_pool, voc)
                    if bad is not None:
                        raise RenderError(bad)
            prepared.append((p, voc))

        # Stage 9 — sidechain-duck the BED under the placed vocals (only when the planner emitted
        # DuckMoves; disabled -> skipped -> byte-identical). Bed-side, keyed by the placed vocal.
        if duck_moves:
            bed = _duck_bed(bed, duck_moves, prepared, SR)

        # Pass 2 — lay each vocal on the bed with its entry moves (build / breath / sweep). Same order
        # and same arithmetic as before the split.
        prev_voc_end = 0  # sample where the last placed vocal ended — a build never reaches back over it
        for p, voc in prepared:
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
            # Effect pool: duck the bed under a placement carrying a pool effect so its wet (reverb
            # tail / echo throw) isn't masked by the drums+bass. No pool effect => no duck => the bed
            # arithmetic (and the rendered bytes) are unchanged.
            if getattr(p, "space", None) or getattr(p, "width", None):
                bed[anchor:need] *= _POOL_BED_DUCK
            bed[anchor:need] += voc
            prev_voc_end = need

        # Slice B contrast: Song 1's OWN vocal answers in the beat-only gaps. It may ring INTO the
        # next Song-2 entry by up to the bounded R1 hand-off (the referee permits that overlap).
        s1_vocals = song1_stems.get("vocals")
        s2_anchors = [max(0, int(p.anchor * SR)) for p, _ in prepared]  # where each Song-2 vocal ENTERS
        for s, e in getattr(plan, "s1_vocal_regions", []):
            if s1_vocals is None:
                break
            # Song 1 leads its own vocal here, played as recorded; only an edge fade guards against a click.
            off = window[0] if window else 0.0  # s1 regions are window-relative; the file is not cropped
            take = _edge_fade(_vocal_take(s1_vocals, s + off, max(e - s, 0.0), 1.0))
            a0 = max(0, int(s * SR))
            # R1 hand-off safety (2026-07-14): where this outgoing S1 vocal rings INTO a later Song-2
            # entry, fade its tail out across the overlap so it ducks UNDER the incoming vocal — the
            # decay the R1 relaxation assumes, now made TRUE BY CONSTRUCTION (never two full leads,
            # for any pair). A standalone contrast answer (no entry within its span) is left untouched,
            # keeping its natural body. As Song 2 edge-fades IN, Song 1 ramps OUT → a real crossfade.
            over = [anc for anc in s2_anchors if a0 < anc < a0 + len(take)]
            if over:
                start = min(over) - a0
                ramp = np.linspace(1.0, 0.0, len(take) - start, dtype=np.float32)
                take[start:] *= ramp[:, None]
            bed = _hold(bed, a0 + len(take))
            bed[a0:a0 + len(take)] += take

        peak = float(np.max(np.abs(bed))) if bed.size else 0.0
        if peak > 0.0:
            bed *= _TARGET_PEAK / peak
        np.clip(bed, -_CEILING, _CEILING, out=bed)

        sf.write(out_path, bed, SR, subtype="PCM_16")
        return out_path
