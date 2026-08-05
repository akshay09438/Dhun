"""INDEPENDENT acceptance tests for the simplified Rule 4 — gap-sized echo + continuous reverb.

Written from the human-approved founder spec (below), NOT from the sibling test_gap_echo.py — a
separate context on purpose. Hermetic: synthetic audio only, no cached data, no network, no ffmpeg.
Exercises the engine primitives in workers/render.py directly:
  _gap_echo(voc, bpm, tail_after_end_secs), _voiced_runs(voc), _echo_overruns(anchor, placed, next),
  _reverb_bed(voc), plus the ships-OFF gate (plan._RULE4_ENABLED / Placement.reverb_bed).

Human-approved criteria each test encodes:
  A  DRY VOCAL UNTOUCHED — sung spans are byte-for-byte the dry vocal; the echo only fills gaps,
     and _gap_echo never mutates the caller's buffer.
  B  ECHO FIRES AT THE END OF EACH LINE — every line-end followed by a real gap gets audible echo.
  C  NO GAP -> NO ECHO — wall-to-wall vocal (and a below-min-gap gap) is returned dry, unchanged.
  D  TAIL SIZED TO THE GAP — a longer gap yields a proportionally longer tail (below the cap).
  E  TEMPO-DERIVED CAP — an over-long gap saturates at ONE BAR, which is LONGER at 85 than 127 BPM.
  F  CONTAINMENT — the echoed length never reaches the next entry: via _echo_overruns (the referee),
     via output length never exceeding dry + room, and via the next voiced line staying byte-identical.
  G  DEGENERATE INPUTS — empty / silent / non-positive-BPM are safe no-ops.
  H  CONTINUOUS REVERB underneath, length-preserving, rings into the gaps (the kept _reverb_bed).
  I  SHIPS OFF — the flag defaults False and Placement.reverb_bed defaults False (the byte-identical gate).
"""

import sys
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[3]  # tests -> api -> services -> repo
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from workers import render  # noqa: E402

SR = render.SR


# ---------------------------------------------------------------- synthetic-audio helpers
def _tone(dur_s, freq=220.0, amp=0.5):
    """A stereo float32 sine burst — a clearly-voiced 'sung line' well above the onset threshold."""
    n = int(round(dur_s * SR))
    t = np.arange(n) / SR
    w = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.stack([w, w], axis=1)


def _silence(dur_s):
    return np.zeros((int(round(dur_s * SR)), 2), dtype=np.float32)


def _cat(*parts):
    return np.concatenate(parts, axis=0).astype(np.float32)


def _energized_mask(y, thr=1e-3):
    """Per-sample boolean: is either channel above thr here (i.e. some audio, not silence)."""
    return np.abs(y).max(axis=1) > thr


def _last_energized(y, thr=1e-3):
    idx = np.where(_energized_mask(y, thr))[0]
    return int(idx[-1]) if idx.size else -1


# ---------------------------------------------------------------- A. dry vocal untouched
def test_sung_spans_are_byte_for_byte_dry_and_buffer_not_mutated():
    """A: every DETECTED voiced span in the output equals the dry vocal bit-for-bit, the gap between
    the two lines gains echo energy (so the assertion is not vacuous), and _gap_echo does not mutate
    the caller's array."""
    voc = _cat(_tone(0.8, freq=220.0), _silence(1.2), _tone(0.8, freq=330.0))
    voc_before = voc.copy()
    n = len(voc)

    runs = render._voiced_runs(voc)
    assert len(runs) == 2, f"detector should see two lines, saw {runs}"

    out = render._gap_echo(voc, bpm=120.0, tail_after_end_secs=0.0)

    # dry vocal never touched inside a sung span
    for s, e in runs:
        assert np.array_equal(out[s:e], voc_before[s:e]), f"sung span [{s},{e}) was altered"

    # non-vacuous: the gap between the two lines actually received echo energy
    e1, s2 = runs[0][1], runs[1][0]
    assert np.any(_energized_mask(out[e1:s2])), "no echo landed in the gap — test would be vacuous"

    # _gap_echo must not mutate the buffer it was handed
    assert np.array_equal(voc, voc_before), "_gap_echo mutated the caller's vocal buffer"
    # output at least as long as the dry vocal (echo only ever adds)
    assert len(out) >= n


# ---------------------------------------------------------------- B. echo fires at the end of EACH line
def test_echo_fires_after_every_line_with_a_gap():
    """B: with three lines separated by real gaps, echo energy appears in BOTH inter-line gaps —
    an echo at the end of each line, not just the first."""
    voc = _cat(_tone(0.7, 220.0), _silence(1.0), _tone(0.7, 330.0), _silence(1.0), _tone(0.7, 440.0))
    runs = render._voiced_runs(voc)
    assert len(runs) == 3, f"expected three lines, saw {runs}"

    out = render._gap_echo(voc, bpm=120.0, tail_after_end_secs=0.0)

    gap1 = out[runs[0][1]:runs[1][0]]
    gap2 = out[runs[1][1]:runs[2][0]]
    assert np.any(_energized_mask(gap1)), "no echo after line 1"
    assert np.any(_energized_mask(gap2)), "no echo after line 2"


# ---------------------------------------------------------------- C. no gap -> no echo
def test_wall_to_wall_vocal_is_returned_dry():
    """C: a single continuous line with NO trailing room has no gap anywhere -> the output is the dry
    vocal, byte-for-byte and the same length (nothing added)."""
    voc = _tone(3.0, 220.0)
    out = render._gap_echo(voc, bpm=120.0, tail_after_end_secs=0.0)
    assert out.shape == voc.shape
    assert np.array_equal(out, voc), "a gapless vocal must ring no echo"


def test_gap_below_min_threshold_gets_no_echo():
    """C: an inter-line gap shorter than _GAP_ECHO_MIN_GAP_SECS is too tight to echo into (it would
    smear the next line). With no trailing room either, the whole thing comes back dry."""
    tight = render._GAP_ECHO_MIN_GAP_SECS - 0.2   # 0.30 s < 0.50 s floor
    assert tight > 0
    voc = _cat(_tone(0.8, 220.0), _silence(tight), _tone(0.8, 330.0))
    runs = render._voiced_runs(voc)
    assert len(runs) == 2, "the tight silence must still read as two separate lines"
    detected_gap = (runs[1][0] - runs[0][1]) / SR
    assert detected_gap < render._GAP_ECHO_MIN_GAP_SECS, "fixture no longer exercises the min-gap guard"

    out = render._gap_echo(voc, bpm=120.0, tail_after_end_secs=0.0)
    assert np.array_equal(out, voc), "a sub-min gap must produce no echo"


# ---------------------------------------------------------------- D. longer gap -> longer tail
def test_longer_gap_yields_proportionally_longer_tail():
    """D: on the SAME single line at the SAME tempo, a larger trailing room (below the cap) produces a
    strictly longer output, and the extra length equals the extra room (the tail is sized to the gap)."""
    line = _tone(0.8, 220.0)
    n = len(line)
    bpm = 120.0
    out_short = render._gap_echo(line, bpm, tail_after_end_secs=0.7)
    out_long = render._gap_echo(line, bpm, tail_after_end_secs=1.5)

    assert len(out_short) > n, "short room still added a tail beyond the dry vocal"
    assert len(out_long) > len(out_short), "a longer gap must give a longer tail"

    # the growth tracks the gap growth sample-for-sample (guard + line-length cancel)
    expected_delta = int(1.5 * SR) - int(0.7 * SR)
    assert abs((len(out_long) - len(out_short)) - expected_delta) <= 3


# ---------------------------------------------------------------- E. tempo-derived cap
def test_tail_cap_is_one_bar_and_rings_longer_at_slower_bpm():
    """E: an over-long gap saturates the tail at ONE BAR. One bar is 2.82 s at 85 BPM but 1.89 s at
    127 BPM, so the same huge gap must ring longer at the slower tempo. A fixed-seconds cap would make
    these equal — this test would fail."""
    line = _tone(0.8, 220.0)
    n = len(line)
    huge_room = 10.0  # far larger than a bar at either tempo -> forces saturation at the cap

    out_85 = render._gap_echo(line, bpm=85.0, tail_after_end_secs=huge_room)
    out_127 = render._gap_echo(line, bpm=127.0, tail_after_end_secs=huge_room)

    tail_85 = (len(out_85) - n) / SR
    tail_127 = (len(out_127) - n) / SR

    bar_85 = (60.0 / 85.0) * 4.0    # 2.8235 s
    bar_127 = (60.0 / 127.0) * 4.0  # 1.8898 s

    # each capped tail is one bar at its tempo
    assert abs(tail_85 - bar_85) < 0.02, f"85 BPM tail {tail_85:.3f}s != one bar {bar_85:.3f}s"
    assert abs(tail_127 - bar_127) < 0.02, f"127 BPM tail {tail_127:.3f}s != one bar {bar_127:.3f}s"
    # slower BPM rings longer, and by the tempo ratio
    assert tail_85 > tail_127 + 0.5
    assert abs((tail_85 / tail_127) - (bar_85 / bar_127)) < 0.03


# ---------------------------------------------------------------- F. containment
def test_echo_overruns_referee_boundary_semantics():
    """F: the independent containment referee. It is True exactly when a placement's echoed end passes
    the next entry; the last placement (next=None) can never overrun; landing exactly on the next entry
    is allowed (not an overrun)."""
    assert render._echo_overruns(10.0, 5.0, None) is False        # last placement never overruns
    assert render._echo_overruns(0.0, 5.0, 6.0) is False          # ends at 5.0, before 6.0
    assert render._echo_overruns(0.0, 6.0, 6.0) is False          # lands exactly on the entry -> ok
    assert render._echo_overruns(0.0, 6.5, 6.0) is True           # passes the entry -> overrun
    assert render._echo_overruns(2.0, 3.0, 6.0) is False          # anchor-offset, ends at 5.0
    assert render._echo_overruns(2.0, 4.5, 6.0) is True           # anchor-offset, ends at 6.5


def test_output_length_never_exceeds_dry_plus_room():
    """F: containment by construction — the total echoed length never rings past (dry length + the room
    it was given), for any tempo. A broken clamp that ignored the gap and always tailed a full bar
    would exceed this whenever the room is smaller than a bar."""
    voc = _cat(_tone(0.8, 220.0), _silence(1.0), _tone(0.8, 330.0))
    n = len(voc)
    for bpm in (85.0, 120.0, 127.0):
        for room in (0.6, 1.0, 3.0):   # 0.6 s < a bar at every tempo here -> the clamp must bind
            out = render._gap_echo(voc, bpm=bpm, tail_after_end_secs=room)
            assert len(out) <= n + int(room * SR), (
                f"echo overran the room at bpm={bpm}, room={room}: "
                f"len={len(out)} > {n + int(room * SR)}"
            )


def test_internal_gap_echo_stops_before_the_next_voice():
    """F (R1 — never two voices): echo thrown into an inter-line gap ends before the next line starts,
    and the next sung line receives ZERO added echo (stays byte-for-byte dry)."""
    voc = _cat(_tone(0.8, 220.0), _silence(1.2), _tone(0.8, 330.0))
    voc_before = voc.copy()
    runs = render._voiced_runs(voc)
    e1, s2, e2 = runs[0][1], runs[1][0], runs[1][1]

    out = render._gap_echo(voc, bpm=120.0, tail_after_end_secs=0.0)

    # some echo landed in the gap...
    assert np.any(_energized_mask(out[e1:s2])), "no echo in the gap — test vacuous"
    # ...but the LAST echo sample sits strictly before the next line's onset
    last_in_gap = e1 + _last_energized(out[e1:s2])
    assert last_in_gap < s2, "echo tail reached the next line's entry (R1 break)"
    # the next voice is untouched by any echo
    assert np.array_equal(out[s2:e2], voc_before[s2:e2]), "echo bled into the next sung line"


# ---------------------------------------------------------------- G. degenerate inputs
def test_empty_input_is_a_shape_preserving_noop():
    empty = np.zeros((0, 2), dtype=np.float32)
    out = render._gap_echo(empty, bpm=120.0, tail_after_end_secs=1.0)
    assert out.shape == (0, 2)
    assert render._voiced_runs(empty) == []


def test_silent_input_produces_no_echo():
    """A buffer with a peak of zero has no voiced runs -> nothing to echo -> returned unchanged."""
    silent = _silence(2.0)
    assert render._voiced_runs(silent) == []
    out = render._gap_echo(silent, bpm=120.0, tail_after_end_secs=1.0)
    assert np.array_equal(out, silent)


def test_non_positive_bpm_is_a_noop():
    voc = _cat(_tone(0.8, 220.0), _silence(1.0), _tone(0.8, 330.0))
    for bad_bpm in (0.0, -5.0):
        out = render._gap_echo(voc, bpm=bad_bpm, tail_after_end_secs=1.0)
        assert np.array_equal(out, voc), f"bpm={bad_bpm} should be a no-op"


# ---------------------------------------------------------------- H. continuous reverb bed (the kept half)
def test_reverb_bed_is_length_preserving():
    voc = _cat(_tone(0.8, 220.0), _silence(1.0), _tone(0.8, 330.0))
    out = render._reverb_bed(voc)
    assert out.shape == voc.shape, "the reverb bed must never change length (F1 containment)"


def test_reverb_bed_rings_underneath_into_a_gap():
    """H: the continuous reverb rings past a word-end into the silence that follows (audible underneath
    the echo), while staying the same length."""
    voc = _cat(_tone(0.8, 220.0), _silence(1.5))
    out = render._reverb_bed(voc)
    tail_region = out[int(0.9 * SR):]        # just after the tone ends
    assert np.any(_energized_mask(tail_region)), "reverb did not ring into the gap"
    assert not np.array_equal(out, voc), "reverb bed added nothing"


def test_reverb_bed_empty_is_a_noop():
    empty = np.zeros((0, 2), dtype=np.float32)
    assert render._reverb_bed(empty).shape == (0, 2)


# ---------------------------------------------------------------- I. ships OFF (the byte-identical gate)
def test_rule4_ships_off_behind_the_flag():
    """I: the shipped default is OFF. plan._RULE4_ENABLED is False and rule4_enabled() reports False —
    the planner never flags a placement, so render_mix never enters the Rule-4 branch."""
    from app.planner import plan
    assert plan._RULE4_ENABLED is False
    assert plan.rule4_enabled() is False


def test_placement_reverb_bed_defaults_off():
    """I: a placement with nothing set has reverb_bed False, so render_mix takes the legacy else branch
    (neither _gap_echo nor _reverb_bed runs) -> byte-identical to the pre-Rule-4 render."""
    from app.models import Placement
    p = Placement(anchor=0.0, vocal_src=(0.0, 1.0))
    assert p.reverb_bed is False
