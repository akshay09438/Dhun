"""INDEPENDENT acceptance tests for Rule 4 — a REAL tempo-synced feedback-DELAY echo (+ reverb bed).

Written from the human-approved criteria and the primitives' stated contract in workers/render.py —
NOT from the sibling tests/test_echo.py (only its import/style header was read). Hermetic: synthetic
audio only (sine tones + silence), no cached data, no ffmpeg, no network.

Founder ear-approved 2026-08-05, variant "d_quarter_long".

Criteria under test:
  A  IT IS A DELAY, NOT A CHOP — repeat k is the WHOLE vocal delayed by k*delay at gain feedback**k,
     scaled by wet. First repeat AT the delay time, second at 2x, each quieter. An overlapping-chop
     (short repeated slice) would NOT reproduce the intact vocal at each tap.
  B  WET ONLY — the return is just the echo; nothing rings before the first delay (silence in [0, delay)).
  C  TAIL BOUNDED — max_tail_secs caps how long the echo rings (kept off a Song-1 lead), independent of
     the feedback floor.
  D  LEVEL — the loudest repeat sits at ~feedback*wet of the vocal (audible, below the dry).
  E  CONTAINMENT (R1) — _echo_overruns is True iff the echoed length rings over a Song-1 lead start;
     ringing over Song 2's OWN next line (empty s1_starts_after) is allowed and NOT flagged.
  F  REVERB BED — _reverb_bed is length-preserving (F1 containment: truncated to the vocal length).
  G  LIVE — deployed behind plan._RULE4_ENABLED = True (folded into ENGINE_VERSION).
"""

import sys
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from workers import render  # noqa: E402

SR = render.SR


# ----------------------------------------------------------------- synthetic-audio helpers
def _voc(secs: float, freq: float = 220.0, peak: float = 0.8) -> np.ndarray:
    """A recognizable stereo vocal stand-in: an amplitude-ramped sine so every sample is distinct
    (a chopped/stuttered repeat of a short slice could NOT reproduce it tap-for-tap)."""
    n = int(secs * SR)
    t = np.arange(n) / SR
    ramp = np.linspace(0.2, 1.0, n)  # distinct envelope => intact-vocal check is non-vacuous
    # phase offset so sample 0 is NON-zero: lets the "echo begins exactly at the delay" check be exact
    # (a plain sine has voc[0]==sin(0)==0, which would hide the true tap offset by one sample).
    mono = (peak * ramp * np.sin(2 * np.pi * freq * t + np.pi / 4)).astype(np.float32)
    return np.stack([mono, mono], axis=1).astype(np.float32)


def _expected_tap(voc: np.ndarray, g: float, wet: float) -> np.ndarray:
    """The engine writes (voc*g).astype(f32) into the buffer, then multiplies the whole buffer by wet.
    Reproduce that exact float32 path so the tap comparison is exact, not approximate."""
    return ((voc * g).astype(np.float32) * wet).astype(np.float32)


# =========================================================================================
# A — IT IS A DELAY, NOT A CHOP
# =========================================================================================
def test_A_each_tap_is_the_whole_vocal_delayed_and_decayed():
    """The wet at offset k*delay must equal the INTACT vocal * feedback**k * wet. delay > vocal length
    so taps do not overlap => each region isolates one tap. A chop/stutter would put a repeated short
    slice here, not the full ramped vocal, and would fail np.allclose."""
    delay = 0.1
    d = int(delay * SR)                     # 4410 samples
    voc = _voc(0.05)                        # n = 2205 < d  => taps are cleanly separated
    n = len(voc)
    assert n < d, "test setup: vocal must be shorter than the delay so taps do not overlap"
    fb, wet = 0.5, 0.5

    out = render._delay_echo(voc, delay, fb, wet, max_tail_secs=1.0)

    # tap 1 sits AT the delay, is the whole vocal, gain fb*wet
    tap1 = out[d:d + n]
    assert np.allclose(tap1, _expected_tap(voc, fb, wet), atol=1e-6)
    # tap 2 sits at 2*delay, quieter by another factor of fb
    tap2 = out[2 * d:2 * d + n]
    assert np.allclose(tap2, _expected_tap(voc, fb * fb, wet), atol=1e-6)
    # tap 3 at 3*delay, quieter again
    tap3 = out[3 * d:3 * d + n]
    assert np.allclose(tap3, _expected_tap(voc, fb ** 3, wet), atol=1e-6)

    # each repeat is strictly quieter than the previous
    assert np.max(np.abs(tap1)) > np.max(np.abs(tap2)) > np.max(np.abs(tap3)) > 0.0

    # the gaps BETWEEN taps are silence (delay, not a continuous smear)
    assert np.max(np.abs(out[d + n:2 * d])) == 0.0


# =========================================================================================
# B — WET ONLY (nothing before the first delay; the dry is laid separately by render_mix)
# =========================================================================================
def test_B_wet_only_silence_before_first_delay():
    delay = 0.1
    d = int(delay * SR)
    voc = _voc(0.05)
    out = render._delay_echo(voc, delay, 0.55, 0.45, max_tail_secs=1.0)

    # nothing rings in [0, delay): no dry copy at t=0, no pre-ring
    assert np.max(np.abs(out[:d])) == 0.0
    # the echo DOES begin exactly at the delay time
    first_nonzero = int(np.argmax(np.any(out != 0.0, axis=1)))
    assert first_nonzero == d


# =========================================================================================
# C — TAIL BOUNDED by max_tail_secs (independent of the feedback floor)
# =========================================================================================
def test_C_max_tail_caps_the_ring_before_feedback_would():
    delay = 0.1
    d = int(delay * SR)
    voc = _voc(0.05)
    n = len(voc)
    fb, wet = 0.5, 0.5  # feedback alone would allow ~5 taps (0.5**5 ~ 0.03 > floor 0.02)

    long = render._delay_echo(voc, delay, fb, wet, max_tail_secs=1.0)
    short = render._delay_echo(voc, delay, fb, wet, max_tail_secs=0.15)

    # with a large tail, tap 2 (offset 2*delay) rings
    assert np.max(np.abs(long[2 * d:2 * d + n])) > 0.0
    # a small tail (0.15s < 2*delay) cuts the ring to a single tap: tap 2 is gone
    assert np.max(np.abs(short[2 * d:])) == 0.0
    # tap 1 still present (the cap trims the tail, does not silence the echo)
    assert np.max(np.abs(short[d:d + n])) > 0.0
    # the buffer length itself is bounded by max_tail (n + max_off + 1)
    assert len(short) < len(long)
    assert len(short) == n + int(0.15 * SR) + 1


# =========================================================================================
# D — LEVEL: the loudest repeat sits at ~feedback*wet of the vocal
# =========================================================================================
def test_D_loudest_repeat_at_feedback_times_wet():
    delay = 0.1
    voc = _voc(0.05, peak=0.8)          # taps do not overlap => no constructive summing
    fb = render._DELAY_ECHO_FEEDBACK    # shipped approved value (0.55)
    wet = render._DELAY_ECHO_WET        # shipped approved value (the boldest level, 1.10)

    out = render._delay_echo(voc, delay, fb, wet, max_tail_secs=1.0)

    peak_voc = float(np.max(np.abs(voc)))
    peak_out = float(np.max(np.abs(out)))
    # loudest tap is the first, at gain fb*wet of the vocal — audible but below the dry (fb*wet < 1)
    assert np.isclose(peak_out, fb * wet * peak_voc, rtol=1e-4)
    assert peak_out < peak_voc


def test_D_approved_constants_have_not_drifted():
    """The founder ear-approved sound: 1/4-note spacing, long musical tail, and the BOLDEST echo level
    (wet 1.10, chosen 2026-08-05). Guards the approved SOUND against a silent constant change."""
    assert render._DELAY_ECHO_BEATS == 1.0
    assert render._DELAY_ECHO_FEEDBACK == 0.55
    assert render._DELAY_ECHO_WET == 1.10


# =========================================================================================
# E — CONTAINMENT (R1): _echo_overruns semantics
# =========================================================================================
def test_E_flags_echo_ringing_over_a_song1_lead():
    # echoed placement ends at 15.0; a Song-1 lead trades in the gap starting at 14.0 => two voices => flag
    assert render._echo_overruns(anchor=10.0, placed_secs=5.0, s1_starts_after=[14.0]) is True
    # one of several Song-1 starts lands before the echo end => still flagged
    assert render._echo_overruns(10.0, 5.0, [20.0, 14.5]) is True


def test_E_does_not_flag_when_echo_ends_before_the_song1_lead():
    # echo ends at 15.0, Song-1 lead starts at 16.0 => contained
    assert render._echo_overruns(10.0, 5.0, [16.0]) is False
    # exactly abutting (end == start, within the 1e-9 epsilon) is not an overrun
    assert render._echo_overruns(10.0, 5.0, [15.0]) is False


def test_E_song2_own_next_line_is_allowed_not_flagged():
    """Ringing over Song 2's OWN next line is delay of the SAME voice — allowed. Those starts are not
    passed in s1_starts_after; with no Song-1 lead in the gap the net never flags, however long the ring."""
    assert render._echo_overruns(10.0, 100.0, s1_starts_after=()) is False
    assert render._echo_overruns(anchor=0.0, placed_secs=999.0) is False  # default empty tuple


# =========================================================================================
# F — REVERB BED is length-preserving (F1 containment)
# =========================================================================================
def test_F_reverb_bed_preserves_length_and_alters_signal():
    voc = _voc(0.2)
    out = render._reverb_bed(voc)
    # TRUNCATED to the vocal length: never rings PAST the placement (would be longer if IR tail appended)
    assert out.shape == voc.shape
    # it actually adds reverb (not a pass-through)
    assert not np.array_equal(out, voc)


def test_F_reverb_bed_empty_vocal():
    empty = np.zeros((0, 2), dtype=np.float32)
    out = render._reverb_bed(empty)
    assert len(out) == 0


# =========================================================================================
# G — LIVE: Rule 4 is deployed (flag ON) and folded into the cache id
# =========================================================================================
def test_G_rule4_is_live():
    """Rule 4 was deployed 2026-08-05 — the flag is ON and its tag rides in ENGINE_VERSION so every mix
    re-renders WITH the echo (the cache auto-invalidates)."""
    from app.planner import plan
    from app.routes import mix as mix_route

    assert plan._RULE4_ENABLED is True
    assert plan.rule4_enabled() is True
    assert "+m8echo" in mix_route.ENGINE_VERSION
