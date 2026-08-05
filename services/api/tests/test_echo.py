"""Acceptance tests for Rule 4 — a REAL echo: a tempo-synced feedback DELAY on the vocal (+ reverb bed).

Founder ear-approved (2026-08-05, variant d_quarter_long): the vocal echoes back spaced a musical note
apart, fading each pass — a normal echo, NOT a chop/stutter. These exercise the engine primitives
`render._delay_echo` (the delay itself) and `render._echo_overruns` (the render-side R1 net) directly,
with synthetic audio (no cached data, no network).

Criteria:
  A  IT IS A DELAY — the wet is the vocal delayed by k*delay, decaying by feedback^k (not overlapping
     chopped chunks): the first repeat appears AT the delay time, the second at 2x, each quieter.
  B  WET ONLY — nothing before the first delay (the dry vocal is added separately by the caller).
  C  TAIL BOUNDED — max_tail_secs caps how long the echo rings (so it can be kept off a Song-1 lead).
  D  LEVEL — the first repeat sits at ~feedback*wet of the vocal (audible, below the dry).
  E  CONTAINMENT — _echo_overruns flags an echoed length that reaches a Song-1 lead (R1: two voices).
"""

import sys
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from workers import render  # noqa: E402

SR = render.SR


def _tone(secs, freq=220.0, amp=0.4):
    n = int(round(secs * SR))
    t = np.linspace(0.0, secs, n, endpoint=False)
    m = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.stack([m, m], axis=1)


# ================================================================ A: it is a real DELAY
def test_wet_is_the_vocal_delayed_and_decaying():
    """CRITERION A: the wet holds the vocal delayed by delay, 2*delay, ... each scaled by feedback^k*wet
    — i.e. a delay line, not overlapping chopped chunks. Checked by correlating the wet window at k*delay
    against the (scaled) dry vocal."""
    voc = _tone(0.5)
    d, fb, wet = 0.5, 0.5, 0.6
    dsamp = int(d * SR)
    out = render._delay_echo(voc, d, fb, wet, max_tail_secs=5.0)
    n = len(voc)
    for k in (1, 2, 3):
        seg = out[dsamp * k: dsamp * k + n]
        expected = voc[:len(seg)] * (fb ** k) * wet
        # near-exact copy of the delayed, scaled vocal (a delay), allowing tiny float error
        assert np.allclose(seg, expected, atol=1e-4), f"tap {k} is not the vocal delayed*feedback^{k}*wet"


# ================================================================ B: wet only (no dry before the delay)
def test_nothing_rings_before_the_first_delay():
    """CRITERION B: _delay_echo returns the WET only — silence until the first repeat at `delay`. The dry
    vocal is laid separately by render_mix, so the echo must not duplicate it at t=0."""
    voc = _tone(0.5)
    d = 0.5
    out = render._delay_echo(voc, d, 0.5, 0.6, max_tail_secs=5.0)
    head = out[: int(d * SR) - 100]
    assert float(np.max(np.abs(head))) < 1e-5, "the echo has energy before the first delay — not wet-only"


# ================================================================ C: the tail is bounded
def test_max_tail_bounds_the_length():
    """CRITERION C: max_tail_secs caps how far the echo rings, so the tail can be kept off a Song-1 lead.
    A tiny cap => a short buffer; a generous cap => the natural decay length."""
    voc = _tone(1.0)
    short = render._delay_echo(voc, 0.5, 0.6, 0.6, max_tail_secs=0.6)
    assert len(short) <= len(voc) + int(0.6 * SR) + 2, "echo rang past its max_tail"
    # and a real tail exists within the cap
    assert float(np.max(np.abs(short[len(voc):]))) > 1e-4, "no echo tail rendered at all"


# ================================================================ D: level (audible, below the dry)
def test_first_repeat_sits_at_feedback_times_wet():
    """CRITERION D: the loudest repeat is ~feedback*wet of the vocal — clearly audible, below the dry."""
    voc = _tone(0.5)
    fb, wet = 0.55, 0.45
    out = render._delay_echo(voc, 0.5, fb, wet, max_tail_secs=5.0)
    voc_pk = float(np.max(np.abs(voc)))
    echo_pk = float(np.max(np.abs(out)))
    assert abs(echo_pk - voc_pk * fb * wet) < 0.03 * voc_pk, (
        f"echo peak {echo_pk:.3f} != feedback*wet*voc {voc_pk * fb * wet:.3f}")


def test_delay_echo_degenerate_inputs():
    """Edges: empty vocal or non-positive delay => empty wet, no crash."""
    empty = np.zeros((0, 2), np.float32)
    assert render._delay_echo(empty, 0.5, 0.5, 0.5, 5.0).shape[0] == 0
    assert float(np.max(np.abs(render._delay_echo(_tone(0.3), 0.0, 0.5, 0.5, 5.0)))) == 0.0


# ================================================================ E: containment vs Song-1 leads
def test_echo_overruns_guards_song1_leads():
    """CRITERION E: the echoed placement must not ring OVER a Song-1 lead trading in the gap (two voices,
    R1). _echo_overruns flags an echoed length that reaches a Song-1 lead start, passes one that stops
    before it. (Ringing over Song 2's OWN next line is just delay of the same voice — allowed.)"""
    # placement at 10s; Song 1 leads at 15s. Echoed length 5.5s -> ends 15.5 > 15.0 -> collides.
    assert render._echo_overruns(10.0, 5.5, s1_starts_after=[15.0]) is True
    assert render._echo_overruns(10.0, 4.5, s1_starts_after=[15.0]) is False   # ends 14.5 < 15.0
    assert render._echo_overruns(10.0, 99.0, s1_starts_after=[]) is False       # no Song-1 lead -> never
