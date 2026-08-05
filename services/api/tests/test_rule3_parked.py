"""Regression test for the PARKED Rule-3 breath-safe re-fire helper (workers/rule3_parked.py).

`punchy_bar` was cut from Rule 4 (it is chop-and-repeat = Rule 3) but PARKED intact because it carries
the hard-won Father Ocean 3:56 fix: it must return None for a BREATH fragment (never re-fire a breath)
and a real fragment for a VOICED bar. This preserves that coverage on the REAL Der Lagi vocal stem — the
exact audio that killed the drop — so the fix cannot silently rot before Rule 3 is built.

(Retargeted from the deleted test_phrase_throw_e2e.py criterion 4, which tested render._punchy_bar.)
"""

import sys
from pathlib import Path

import numpy as np
import pytest

from app.audio.analysis import analysis_path
from app.audio.stems import stem_path
from app.routes.mix import _load_analysis

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from workers import render, rule3_parked  # noqa: E402

# The ACTUAL Father Ocean (beat) x Der Lagi Lekin (vocal) case (3:56).
FATHER_OCEAN_ID = "ac59f8c4af7e89e916dc825690ade5dbc2b9c6f221c5a7ef863eb9863f3826e1"
DER_LAGI_ID = "bbab7b9f875f071f8e3b53aa73e64c02b3f39730d0a1feec48af6b54de501430"

_DER_LAGI_READY = stem_path(DER_LAGI_ID, "vocals").exists() and analysis_path(FATHER_OCEAN_ID).exists()
_needs_der_lagi = pytest.mark.skipif(
    not _DER_LAGI_READY, reason="real Father Ocean x Der Lagi cached audio not present under data/")


@_needs_der_lagi
def test_punchy_bar_skips_a_breath_and_keeps_a_voiced_bar_on_real_der_lagi():
    """On the REAL Der Lagi vocal stem, rule3_parked.punchy_bar returns None for a low-energy BREATH bar
    and a real fragment for a VOICED bar — so a future Rule-3 re-fire can never grab a breath (the Father
    Ocean 3:56 defect). Fragments are LOCATED from the real audio: quietest bar (breath), loudest (sung)."""
    voc = render._decode(stem_path(DER_LAGI_ID, "vocals"))
    assert len(voc) > 0, "decoded Der Lagi vocal is empty"

    a1 = _load_analysis(FATHER_OCEAN_ID)
    bpm = a1.bpm if (a1 and a1.bpm) else 120.0
    bar = (60.0 / bpm) * 4.0 * render.SR           # one bar in samples (the re-fire fragment length)
    b = int(bar)
    assert b > 0 and len(voc) >= 2 * b, "vocal too short to hold two bar-length windows"

    peak = float(np.max(np.abs(voc)))
    assert peak > 0.0, "decoded vocal is silent"

    # scan non-overlapping bar windows; rms of each, as a fraction of the global sample peak
    ends, ratios = [], []
    pos = b
    while pos <= len(voc):
        frag = voc[pos - b:pos]
        rms = float(np.sqrt(np.mean(np.square(frag))))
        ends.append(pos)
        ratios.append(rms / peak)
        pos += b
    ratios = np.array(ratios)

    voiced_i = int(np.argmax(ratios))              # the loudest bar -> a sung phrase
    voiced_end = ends[voiced_i]
    # prefer a genuine BREATH sitting JUST BELOW the voiced floor (the adversarial boundary case — the
    # breath most likely to be mistaken for a sung bar, which is exactly what the 3:56 defect grabbed);
    # fall back to the quietest window (near-silence) if no in-band breath exists.
    floor = rule3_parked.VOICED_FLOOR
    breath_band = [(r, e) for r, e in zip(ratios, ends) if 0.003 < r < floor]
    if breath_band:
        breath_ratio, breath_end = max(breath_band, key=lambda x: x[0])  # loudest breath under the floor
    else:
        quiet_i = int(np.argmin(ratios))
        breath_ratio, breath_end = float(ratios[quiet_i]), ends[quiet_i]

    assert float(ratios[voiced_i]) >= floor, (
        f"no clearly-voiced bar found (loudest rms/peak={ratios[voiced_i]:.3f} < floor {floor}) — "
        "cannot prove the voiced side")
    assert breath_ratio < floor, f"selected breath bar is not below the voiced floor (rms/peak={breath_ratio:.3f})"

    voiced_frag = rule3_parked.punchy_bar(voc, voiced_end, bar)
    breath_frag = rule3_parked.punchy_bar(voc, breath_end, bar)
    assert voiced_frag is not None and len(voiced_frag) > 0, (
        f"punchy_bar dropped a VOICED bar (rms/peak={ratios[voiced_i]:.3f}) — a Rule-3 re-fire would be lost")
    assert breath_frag is None, (
        f"punchy_bar RE-FIRED a breath (rms/peak={breath_ratio:.3f} < {floor}) — this is the Father Ocean "
        "3:56 defect: a breath grabbed as the re-fire kills the drop")


def test_punchy_bar_voiced_floor_matches_the_rule4_detector():
    """The parked helper's voiced floor must stay in lock-step with the Rule-4 detector's — both encode
    the same 'below this RMS fraction of peak = a breath' judgement (a synthetic, hermetic check)."""
    assert rule3_parked.VOICED_FLOOR == render._VOICED_FLOOR, (
        "parked voiced floor drifted from the engine's — the breath judgement would diverge")
