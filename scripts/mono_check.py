"""Mono fold-down check for the width-bearing effects — throwaway experiment, NOT a shipped feature.

Part 2 of the effect-pool work (2026-08-05). Most of the target audience listens on phone speakers,
which are effectively MONO. Stereo-width effects can collapse or partially cancel when summed to mono.
This measures, on the ISOLATED processed vocal (where the effect lives), for the four founder-named
variants across both catalog pairs:

  - L/R correlation           (+1 = mono-safe, 0 = decorrelated, negative = cancelling)
  - side/mid energy (dB)      how much of the sound is stereo WIDTH — ALL of it is lost in mono
  - mono-vs-stereo level (dB) net loudness change of the vocal when summed to mono (cancellation)

and writes a MONO fold-down of the full mastered mix (what a phone actually plays) so the ear can
confirm. Read-only w.r.t. product code; reuses the harness builders (which reuse the real engine).

Run: services/api/.venv/Scripts/python.exe scripts/mono_check.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import soundfile as sf

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# the harness sets up sys.path for workers.* / app.* at import and defines the builders + real helpers
import echo_reverb_harness as H  # noqa: E402
from echo_reverb_harness import (  # noqa: E402
    SR, PAIRS, build_slices, _load_analysis, master,
    doubler, feedback_delay, convolve_reverb, make_ir,
)

OUT = REPO / "services" / "api" / "data" / "listening" / "echo_reverb_mono"
OUT.mkdir(parents=True, exist_ok=True)


def _rms(x):
    return float(np.sqrt(np.mean(np.square(x.astype(np.float64))))) if x.size else 0.0


def mono_metrics(voc):
    """Phase-cancellation metrics on a stereo (processed) vocal."""
    L, R = voc[:, 0].astype(np.float64), voc[:, 1].astype(np.float64)
    mid = 0.5 * (L + R)
    side = 0.5 * (L - R)
    rms_chan = np.sqrt(0.5 * (_rms(L) ** 2 + _rms(R) ** 2))   # per-channel stereo level
    rms_mono = _rms(mid)                                       # summed-to-mono level
    denom = np.sqrt(np.sum(L * L) * np.sum(R * R))
    corr = float(np.sum(L * R) / denom) if denom > 0 else 1.0
    mid_rms, side_rms = _rms(mid), _rms(side)
    side_mid_db = 20 * np.log10(side_rms / mid_rms) if mid_rms > 0 and side_rms > 0 else -99.0
    mono_loss_db = 20 * np.log10(rms_mono / rms_chan) if rms_chan > 0 and rms_mono > 0 else 0.0
    return corr, side_mid_db, mono_loss_db


def full_mix(processed_vocal, bed):
    total = max(len(processed_vocal), len(bed))
    v = np.zeros((total, 2), dtype=np.float32); v[:len(processed_vocal)] += processed_vocal
    b = np.zeros((total, 2), dtype=np.float32); b[:len(bed)] += bed
    return master(v + b)


def run_pair(pair, sid1, sid2):
    print(f"\n=== {pair} ===")
    a1, a2 = _load_analysis(sid1), _load_analysis(sid2)
    bpm, ratio, dry, dry_short, bed = build_slices(a1, a2, sid1, sid2)
    beat = 60.0 / bpm

    variants = {
        "n_doubler":     ("width",   doubler(dry)),
        "e_pingpong":    ("width",   feedback_delay(dry, beat * 0.75, taps=6, fb=0.55, pingpong=True)[0]),
        "j_long-hall":   ("reverb",  convolve_reverb(dry, make_ir(2.5, 2.0), wet=0.30)),
        "o4_throw-4bar": ("throw",   feedback_delay(dry_short, beat * 1.0, taps=16, fb=0.68, lp_hz=2200)[0]),
    }

    print(f"  {'variant':<16}{'kind':<8}{'L/R corr':>10}{'side/mid dB':>13}{'mono loss dB':>14}   verdict")
    for name, (kind, pv) in variants.items():
        corr, side_mid_db, mono_loss_db = mono_metrics(pv)
        # verdict: width mostly LOST if a lot of energy is in side (>-6 dB) and mono loss is real (< -1 dB)
        if side_mid_db > -6.0 and mono_loss_db < -1.0:
            verdict = "WIDTH COLLAPSES in mono"
        elif mono_loss_db < -0.5 or side_mid_db > -12.0:
            verdict = "some width lost, core survives"
        else:
            verdict = "mono-safe"
        print(f"  {name:<16}{kind:<8}{corr:>+10.2f}{side_mid_db:>+13.1f}{mono_loss_db:>+14.2f}   {verdict}")

        mono = (0.5 * (full_mix(pv, bed)[:, 0] + full_mix(pv, bed)[:, 1])).astype(np.float32)
        peak = float(np.max(np.abs(mono))) if mono.size else 0.0
        if peak > 0:
            mono = mono / peak * H._TARGET_PEAK
        sf.write(OUT / f"{pair}__{name}__MONO.wav", mono, SR, subtype="PCM_16")


def main():
    for pair, sid1, sid2 in PAIRS:
        run_pair(pair, sid1, sid2)
    print(f"\nWrote mono fold-down WAVs to:\n  {OUT}")


if __name__ == "__main__":
    main()
