"""Echo/reverb LISTENING harness — throwaway experiment, NOT a shipped feature.

Renders the founder's variant matrix (delay / tail-treatment / reverb / width /
throw-mode) on 2 catalog pairs so the ear can pick a direction. It reuses the REAL
render functions for the baselines (a, i) so those match the product exactly, and
implements the rest with honest DSP (no faking) — building the wet SEPARATELY where
the product currently can't (echo/reverb are inserts). Every file is labelled in its
name: __PR__ = reachable in today's product architecture, __WB__ = needs the wet-bus
build first.

Read-only w.r.t. product code. No cloud, no cache writes, no re-ingest. Reads cached
stems + analyses in services/api/data. Writes WAVs to a gitignored listening folder.
Runs chain_guards on every variant (their first real test) and reports margins.

Run: services/api/.venv/Scripts/python.exe scripts/echo_reverb_harness.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, fftconvolve, sosfilt

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))                       # so `workers.*` imports resolve
sys.path.insert(0, str(REPO / "services" / "api"))  # so `app.*` imports resolve
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from workers.render import (  # noqa: E402  — reuse the REAL engine helpers
    SR, _TARGET_PEAK, _CEILING, _decode, _echo, _edge_fade, _reverb, _pitch_shift,
    _sum_stems, _vocal_take,
)
from workers import chain_guards  # noqa: E402
from app.audio.stems import stem_path  # noqa: E402
from app.audio.analysis import analysis_path  # noqa: E402

OUT = REPO / "services" / "api" / "data" / "listening" / "echo_reverb"
OUT.mkdir(parents=True, exist_ok=True)

PAIRS = [
    ("iadoreyou-x-tujhe",
     "b8696c4dec8a4d50c2ee493360a868d46ffcc915a43b0fdfdbe30241d9962bef",   # I Adore You (beat)
     "fedc95c90aff7c957f398f302a6a3ed4c7dbf48d7a6667c8294e0b4030355e20"),  # Tujhe Bhula Diya (vocals)
    ("anchorpoint-x-derlagi",
     "2c17fc64b6928f0499a306402b676bc62e3118588e42494c8ec7063a7a948267",   # Anchor Point (beat)
     "bbab7b9f875f071f8e3b53aa73e64c02b3f39730d0a1feec48af6b54de501430"),  # Der Lagi Lekin (vocals)
]

REPORT: list[dict] = []


# ---------------------------------------------------------------- small dsp helpers

def _load_analysis(sid):
    return json.loads(analysis_path(sid).read_text(encoding="utf-8"))


def _lp(x, hz):
    sos = butter(4, min(hz, SR / 2 - 1) / (SR / 2), btype="low", output="sos")
    return sosfilt(sos, x, axis=0).astype(np.float32)


def _hp(x, hz):
    sos = butter(4, hz / (SR / 2), btype="high", output="sos")
    return sosfilt(sos, x, axis=0).astype(np.float32)


def _pan(mono2, side):  # collapse to mono, place hard L or R
    m = mono2.mean(axis=1)
    out = np.zeros_like(mono2)
    out[:, 0 if side == "L" else 1] = m
    return out


def _amp_env(x, smooth_ms=40.0):
    a = np.abs(x).mean(axis=1)
    k = max(1, int(SR * smooth_ms / 1000))
    env = np.convolve(a, np.ones(k) / k, mode="same")
    peak = env.max() if env.size else 1.0
    return (env / peak if peak > 0 else env).astype(np.float32)


def master(mix):
    peak = float(np.max(np.abs(mix))) if mix.size else 0.0
    if peak > 0:
        mix = mix / peak * _TARGET_PEAK
    return np.clip(mix, -_CEILING, _CEILING).astype(np.float32)


def _max_wet_gain(dry_buf, wet_buf, pk_in, headroom_db=1.5, g_max=1.0):
    """Largest gain g in [0, g_max] such that peak(dry_buf + g*wet_buf) stays within `headroom_db`
    of `pk_in` (the dry peak). INPUT-DEPENDENT, deterministic (bisection) — the Part-1 (2026-08-05)
    level-compensation primitive shared by the doubler and the reverb-freeze. It keeps the dry at
    UNITY and trims only the ADDED component (detuned copies / frozen tail), so vocal-vs-bed balance
    is untouched and only the excess peak is removed. peak() is ~monotonic in g (adding the correlated
    wet raises the peak), so bisection converges; g=0 is always feasible since pk_in <= target."""
    if pk_in <= 0.0:
        return g_max
    target = pk_in * (10.0 ** (headroom_db / 20.0))

    def pk(g):
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


def feedback_delay(dry, delay_secs, taps, fb, lp_hz=None, pingpong=False,
                   hp_wet_hz=None, duck_vs_dry=False):
    """A dub feedback delay with a SEPARATE wet buffer (so we can filter/duck/pan it).
    Returns (mix=dry+wet, wet_only). LP applied cumulatively per repeat = progressive darkening."""
    n = len(dry)
    d = max(1, int(delay_secs * SR))
    total = n + d * taps + int(0.2 * SR)
    wet = np.zeros((total, 2), dtype=np.float32)
    seg = dry.copy()
    for k in range(1, taps + 1):
        seg = seg * fb
        if lp_hz:
            seg = _lp(seg, lp_hz)  # each successive repeat gets darker
        placed = _pan(seg, "L" if k % 2 else "R") if pingpong else seg
        off = d * k
        m = min(len(placed), total - off)
        if m > 0:
            wet[off:off + m] += placed[:m]
    if hp_wet_hz:
        wet = _hp(wet, hp_wet_hz)
    if duck_vs_dry:
        env = np.zeros(total, dtype=np.float32)
        de = _amp_env(dry)
        env[:len(de)] = de
        wet = wet * (1.0 - env)[:, None]
    mix = np.zeros((total, 2), dtype=np.float32)
    mix[:n] += dry
    mix += wet
    return mix, wet


def make_ir(secs, decay, seed=20260710, bright=False):
    rng = np.random.default_rng(seed)
    n = int(secs * SR)
    t = np.linspace(0.0, secs, n, endpoint=False)
    ir = rng.standard_normal(n).astype(np.float32) * np.exp(-decay * t).astype(np.float32)
    if bright:  # plate: emphasise highs
        ir = _hp(np.stack([ir, ir], axis=1), 1200)[:, 0]
    l2 = float(np.sqrt(np.sum(ir ** 2)))
    return (ir / l2).astype(np.float32) if l2 > 0 else ir


def convolve_reverb(dry, ir, predelay_ms=0.0, freeze=False, wet=0.25):
    pre = int(predelay_ms / 1000 * SR)
    n = len(dry)
    wetsig = np.zeros((n + len(ir) + pre, 2), dtype=np.float32)
    for ch in range(2):
        conv = fftconvolve(dry[:, ch], ir)
        wetsig[pre:pre + len(conv), ch] += conv
    if freeze:  # 100% wet, let the tail hang past the dry — with INPUT-DEPENDENT tail gain (Part 1 fix)
        dry_buf = np.zeros_like(wetsig)
        dry_buf[:n] += dry  # keep the dry phrase, then the frozen tail rings on
        pk_in = float(np.max(np.abs(dry))) if dry.size else 0.0
        # trim the frozen tail so the phrase+tail peak stays within +1.5 dB of the dry phrase (P2-safe)
        g = _max_wet_gain(dry_buf, wetsig, pk_in, headroom_db=1.5)
        return (dry_buf + g * wetsig).astype(np.float32)
    wetsig = wetsig[:n]
    return ((1.0 - wet) * dry + wet * wetsig).astype(np.float32)


def _resample_detune(x, factor):
    """Cheap detune via linear resample (changes pitch+length a hair) — avoids rubberband,
    which throws std::bad_alloc on this ARM ffmpeg build. ADT-style doubling, no ML."""
    n = len(x)
    idx = np.arange(0, n, factor)
    out = np.zeros((len(idx), 2), dtype=np.float32)
    for ch in range(2):
        out[:, ch] = np.interp(idx, np.arange(n), x[:, ch])
    return out


def doubler(dry, headroom_db=1.5, max_copy=0.7):
    """Stereo ADT doubler with INPUT-DEPENDENT level compensation on the copies (Part 1 fix, 2026-08-05).
    Two detuned copies panned hard L/R sum with the dry and stack the peak (raw = +3.2 dB on pair 1,
    over the P2 3 dB ceiling). The dry stays at UNITY, so vocal-vs-bed balance is untouched; only the
    COPIES are trimmed, by the largest gain (<= max_copy) that keeps the summed peak within
    `headroom_db` of the dry peak. Not a fixed trim — solved per input, so a pair that already passes
    keeps the full copies and a hot pair is trimmed exactly as much as it needs. The stereo-width
    character (two detuned voices) is preserved; only the excess peak is removed."""
    up = _resample_detune(dry, 1.003)   # ~+5 cents-ish, slightly shorter
    dn = _resample_detune(dry, 0.997)   # ~-5 cents-ish, slightly longer
    d1 = int(0.016 * SR)
    d2 = int(0.024 * SR)
    n = len(dry)
    total = n + d2
    dry_buf = np.zeros((total, 2), dtype=np.float32)
    dry_buf[:n] += dry
    copies = np.zeros((total, 2), dtype=np.float32)
    Lp = _pan(up, "L"); Rp = _pan(dn, "R")
    copies[d1:d1 + len(Lp)] += Lp[:total - d1]
    copies[d2:d2 + len(Rp)] += Rp[:total - d2]
    pk_in = float(np.max(np.abs(dry))) if dry.size else 0.0
    g = _max_wet_gain(dry_buf, copies, pk_in, headroom_db=headroom_db, g_max=max_copy)
    return (dry_buf + g * copies).astype(np.float32)


# ---------------------------------------------------------------- per-file bookkeeping

def _tail_decay_secs(wet_or_mix, ref_peak):
    """Roughly how long until energy falls below -40 dB of peak (audible tail length)."""
    a = np.abs(wet_or_mix).mean(axis=1)
    thr = ref_peak * (10 ** (-40 / 20))
    idx = np.where(a > thr)[0]
    return float(idx[-1] / SR) if idx.size else 0.0


def emit(pair, letter, short, reach, dry, processed_vocal, bed, params, notes=""):
    """Mix processed vocal over the bed, master, write, and record guard margins."""
    total = max(len(processed_vocal), len(bed))
    v = np.zeros((total, 2), dtype=np.float32); v[:len(processed_vocal)] += processed_vocal
    b = np.zeros((total, 2), dtype=np.float32); b[:len(bed)] += bed
    mix = master(v + b)

    reason = chain_guards.check_vocal_chain_output(dry, processed_vocal)
    pk_in = float(np.max(np.abs(dry))) if dry.size else 0.0
    pk_out = float(np.max(np.abs(processed_vocal))) if processed_vocal.size else 0.0
    gain_db = 20 * np.log10(pk_out / pk_in) if pk_in > 0 and pk_out > 0 else 0.0
    cf_in = chain_guards.crest_factor(dry)
    cf_out = chain_guards.crest_factor(processed_vocal)
    ratio = (cf_out / cf_in) if np.isfinite(cf_in) and cf_in > 0 else float("inf")
    tail = _tail_decay_secs(processed_vocal, pk_out)

    fname = f"{pair}__{letter}_{short}__{reach}.wav"
    sf.write(OUT / fname, mix, SR, subtype="PCM_16")
    rec = dict(file=fname, pair=pair, letter=letter, reach=reach, params=params, notes=notes,
               p2_gain_db=round(gain_db, 2), p2_margin_db=round(3.0 - gain_db, 2),
               crest_in=round(cf_in, 2), crest_out=round(cf_out, 2),
               crest_ratio=round(ratio, 2), crest_margin=round(ratio - 0.60, 2),
               guard=reason or "pass", out_secs=round(len(processed_vocal) / SR, 2),
               tail_secs=round(tail, 2))
    REPORT.append(rec)
    tagg = "GUARD-FAIL" if reason else "ok"
    print(f"  [{letter:<2}] {reach}  {short:<22} P2 {gain_db:+.2f}dB (margin {3.0-gain_db:+.2f})  "
          f"crest {ratio:.2f}x (margin {ratio-0.60:+.2f})  tail {tail:.1f}s  {tagg}")


# ---------------------------------------------------------------- placement picker

def build_slices(a1, a2, sid1, sid2):
    master_bpm = float(a1["bpm"]) or 120.0
    ratio = master_bpm / (float(a2["bpm"]) or master_bpm)
    ratio = float(np.clip(ratio, 0.5, 2.0))
    # strongest/longest vocal region of Song 2
    regions = [tuple(r) for r in a2.get("vocal_regions", []) if r[1] - r[0] >= 3.0] or [(20.0, 32.0)]
    regions.sort(key=lambda r: r[1] - r[0], reverse=True)
    vs, ve = regions[0]
    full_dur = min(ve - vs, 10.0)
    bar_secs2 = (60.0 / (float(a2["bpm"]) or 120.0)) * 4.0
    short_dur = min(max(bar_secs2, 1.5), 2.5)  # ~1 bar phrase for throw mode
    dry_full = _edge_fade(_vocal_take(stem_path(sid2, "vocals"), vs, full_dur, ratio))
    dry_short = _edge_fade(_vocal_take(stem_path(sid2, "vocals"), vs, short_dur, ratio))
    # a Song-1 anchor with room: first energy-ish downbeat ~1/3 in
    db = a1.get("downbeats", []) or [0.0]
    anchor = db[max(0, len(db) // 3)]
    bed_full = _sum_stems([stem_path(sid1, s) for s in ("drums", "bass", "other")])
    room = int((full_dur + 10.0) * SR)
    a0 = int(anchor * SR)
    bed = bed_full[a0:a0 + room]
    if len(bed) < room:
        bed = np.vstack([bed, np.zeros((room - len(bed), 2), dtype=np.float32)])
    return master_bpm, ratio, dry_full, dry_short, bed


# ---------------------------------------------------------------- the matrix

def run_pair(pair, sid1, sid2):
    print(f"\n=== {pair} ===")
    a1, a2 = _load_analysis(sid1), _load_analysis(sid2)
    bpm, ratio, dry, dry_short, bed = build_slices(a1, a2, sid1, sid2)
    beat = 60.0 / bpm
    bar = beat * 4

    # DELAY -----------------------------------------------------------------
    emit(pair, "a", "echo-baseline", "PR", dry, _echo(dry, bpm), bed,
         "real _echo: dotted-8th, 4 taps, fb 0.42 (phrase-throw)")
    mix, _ = feedback_delay(dry, beat * 0.75, taps=8, fb=0.60, lp_hz=2500)
    emit(pair, "b", "long-dub-lp", "WB", dry, mix, bed,
         "8 taps, fb 0.60, dotted-8th, LP feedback 2500Hz (needs wet path)")
    mix, _ = feedback_delay(dry, beat * 3, taps=4, fb=0.50)
    emit(pair, "c", "delay-3q-bar", "PR", dry, mix, bed, "3/4-bar delay, 4 taps, fb 0.50")
    mix, _ = feedback_delay(dry, beat * 1, taps=4, fb=0.45)
    emit(pair, "d", "delay-quarter", "PR", dry, mix, bed, "quarter-note delay, 4 taps, fb 0.45")
    mix, _ = feedback_delay(dry, beat * 0.75, taps=6, fb=0.55, pingpong=True)
    emit(pair, "e", "pingpong", "WB", dry, mix, bed, "ping-pong L/R, 6 taps, fb 0.55")
    mix, _ = feedback_delay(dry, 0.10, taps=1, fb=0.60)
    emit(pair, "f", "slapback", "PR", dry, mix, bed, "single repeat ~100ms, no feedback")

    # TAIL TREATMENT (on the long dub = best long-tail candidate) ------------
    mix, _ = feedback_delay(dry, beat * 0.75, taps=8, fb=0.60, lp_hz=2500, hp_wet_hz=600)
    emit(pair, "g", "hp-wet-600", "WB", dry, mix, bed, "long dub + HP wet path @600Hz")
    mix, _ = feedback_delay(dry, beat * 0.75, taps=8, fb=0.60, lp_hz=2500, duck_vs_dry=True)
    emit(pair, "h", "duck-wet-vs-dry", "WB", dry, mix, bed,
         "long dub + wet ducked by dry envelope (tails bloom in gaps)")

    # REVERB ----------------------------------------------------------------
    emit(pair, "i", "reverb-baseline", "PR", dry, _reverb(dry, 0.12, SR), bed,
         "real _reverb, wet 0.12, 0.6s IR")
    emit(pair, "j", "reverb-long-hall", "PR", dry, convolve_reverb(dry, make_ir(2.5, 2.0), wet=0.30), bed,
         "2.5s IR, decay 2.0, wet 0.30")
    emit(pair, "k", "reverb-plate", "PR", dry, convolve_reverb(dry, make_ir(1.2, 4.0, bright=True), wet=0.28), bed,
         "1.2s bright IR (plate), wet 0.28")
    emit(pair, "l", "reverb-predelay", "PR", dry, convolve_reverb(dry, make_ir(1.0, 5.0), predelay_ms=60, wet=0.25), bed,
         "1.0s IR, 60ms pre-delay, wet 0.25")
    frozen = convolve_reverb(dry_short, make_ir(3.0, 1.2), freeze=True)
    emit(pair, "m", "reverb-freeze", "PR", dry_short, frozen, bed,
         "final short phrase -> 100% wet 3s IR, tail hangs (insert append)")

    # WIDTH -----------------------------------------------------------------
    emit(pair, "n", "doubler", "PR", dry, doubler(dry), bed,
         "dup L/R, 16/24ms, +-10 cents, no feedback")

    # THROW MODE — short slice, best long-tail, THREE tail lengths -----------
    for letter, bars, taps in (("o1", 1, 4), ("o2", 2, 8), ("o4", 4, 16)):
        mix, _ = feedback_delay(dry_short, beat * 1.0, taps=taps, fb=0.68, lp_hz=2200)
        emit(pair, letter, f"throw-{bars}bar", "WB", dry_short, mix, bed,
             f"~1-bar slice, quarter-note delay, {taps} taps fb 0.68 LP2200 -> ~{bars} bar tail")
    # reference: the SAME section done the normal (full-length) way, dry
    emit(pair, "o0", "full-placement-ref", "PR", dry, dry, bed,
         "reference: full-length phrase, no throw (A/B against o1/o2/o4)")


def main():
    for pair, sid1, sid2 in PAIRS:
        run_pair(pair, sid1, sid2)
    (OUT / "_report.json").write_text(json.dumps(REPORT, indent=2), encoding="utf-8")
    print(f"\nWrote {len(REPORT)} files + _report.json to:\n  {OUT}")
    fails = [r for r in REPORT if r["guard"] != "pass"]
    print(f"\nGUARD FAILURES: {len(fails)}")
    for r in fails:
        print(f"  {r['file']}: {r['guard']}")


if __name__ == "__main__":
    main()
