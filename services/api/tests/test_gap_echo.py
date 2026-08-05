"""Acceptance tests for the SIMPLIFIED Rule 4 — gap-sized echo + continuous reverb (2026-08-05).

The vocal plays EXACTLY as Rule 1 places it (never cut / shortened / chopped / re-fired). On top, an
echo fires at the END of each vocal line, its tail sized to the GAP before the next line (longer gap ->
longer tail; no gap -> no echo), capped to a TEMPO-DERIVED length. A continuous reverb bed rings
underneath (kept from before). One variation, always both together.

These are hermetic (synthetic audio, no cached data, no network) and exercise the engine primitive
`render._gap_echo` and the render-side containment predicate `render._echo_overruns` directly.

Covers the human-approved criteria:
  A  DRY VOCAL UNTOUCHED — the sung spans are byte-for-byte the dry vocal; the echo only fills gaps.
  B  ECHO FIRES INTO A REAL GAP — a gap after a line gets audible echo energy.
  C  NO GAP -> NO ECHO — a wall-to-wall vocal with no trailing room is returned dry.
  D  TAIL SIZED TO THE GAP — a longer gap yields a longer tail (monotone), up to the cap.
  E  TEMPO-DERIVED CAP — one bar at 85 BPM is a LONGER tail cap than one bar at 127 BPM.
  F  CONTAINMENT — the echo never rings past the room it was given (independent predicate + engine).
"""

import sys
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[3]  # tests -> api -> services -> repo
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from workers import render  # noqa: E402

SR = render.SR


# ---------------------------------------------------------------- synthetic vocal helpers
def _tone(secs: float, freq: float = 220.0, amp: float = 0.4) -> np.ndarray:
    n = int(round(secs * SR))
    t = np.linspace(0.0, secs, n, endpoint=False)
    m = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.stack([m, m], axis=1)


def _silence(secs: float) -> np.ndarray:
    return np.zeros((int(round(secs * SR)), 2), dtype=np.float32)


def _voc(segments: list[tuple[str, float]]) -> np.ndarray:
    """Build a stereo vocal from ('v', secs) voiced tones and ('s', secs) silences, in order."""
    parts = [_tone(s) if kind == "v" else _silence(s) for kind, s in segments]
    return np.vstack(parts).astype(np.float32) if parts else np.zeros((0, 2), np.float32)


def _energy_at(y: np.ndarray, t0: float, t1: float) -> float:
    a, b = int(t0 * SR), int(t1 * SR)
    seg = y[a:min(b, len(y))]
    return float(np.sqrt(np.mean(np.square(seg)))) if seg.size else 0.0


def _last_energy_sample(y: np.ndarray, floor_frac: float = 0.02) -> int:
    """Index of the last sample above floor_frac x peak (the audible end of the buffer)."""
    a = np.abs(y).mean(axis=1)
    pk = float(a.max()) if a.size else 0.0
    if pk <= 0:
        return 0
    idx = np.where(a > floor_frac * pk)[0]
    return int(idx[-1]) if idx.size else 0


# ================================================================ A: the dry vocal is never touched
def test_sung_spans_are_identical_to_the_dry_vocal():
    """CRITERION A: the echo lays into the GAPS only — every sung span comes back byte-for-byte the dry
    vocal. This is the whole point of the simplification: Rule 1's vocal plays exactly as-is."""
    bpm = 120.0
    voc = _voc([("v", 2.0), ("s", 2.0), ("v", 2.0)])  # line, gap, line
    out = render._gap_echo(voc, bpm, tail_after_end_secs=0.0)
    # line 1 = [0,2), line 2 = [4,6): must equal the dry vocal exactly (echo only fills the gap)
    n = len(voc)
    line1 = out[: int(2.0 * SR)]
    line2 = out[int(4.0 * SR): min(int(6.0 * SR), n)]
    assert np.array_equal(line1, voc[: int(2.0 * SR)]), "echo altered the FIRST sung line — must be dry"
    assert np.array_equal(line2, voc[int(4.0 * SR): min(int(6.0 * SR), n)]), \
        "echo altered the SECOND sung line — must be dry"


# ================================================================ B: an echo fires into a real gap
def test_echo_fills_a_real_gap():
    """CRITERION B: the silent gap after a sung line gains audible echo energy (it was ~silent, now rings)."""
    bpm = 120.0
    voc = _voc([("v", 2.0), ("s", 2.0), ("v", 2.0)])
    dry_gap = _energy_at(voc, 2.2, 3.8)
    out = render._gap_echo(voc, bpm, tail_after_end_secs=0.0)
    wet_gap = _energy_at(out, 2.2, 3.8)
    assert dry_gap < 1e-4, "test setup: the gap should be silent in the dry vocal"
    assert wet_gap > 1e-3, f"no echo energy in the gap (wet_gap={wet_gap:.5f}) — the echo did not fire"


# ================================================================ C: no gap -> no echo
def test_wall_to_wall_vocal_gets_no_echo():
    """CRITERION C: a fully voiced vocal with no trailing room (tail_after_end=0) is returned dry —
    'no gap -> no echo'. This is the correct output on wall-to-wall vocals, not a failure."""
    bpm = 120.0
    voc = _voc([("v", 6.0)])  # one unbroken sung line, no internal gap
    out = render._gap_echo(voc, bpm, tail_after_end_secs=0.0)
    assert out.shape == voc.shape, "a gapless vocal with no room must not grow"
    assert np.array_equal(out, voc), "a gapless vocal with no room must be returned dry (no echo)"


# ================================================================ D: tail sized to the gap (monotone)
def test_longer_gap_yields_a_longer_tail():
    """CRITERION D: a longer gap after the SAME line produces a longer echo tail (the tail is sized to
    the gap), until the cap. Measured as the audible end of the echo in the gap."""
    bpm = 60.0  # slow, so the 1-bar cap (~4s) does not clip these gaps
    short = render._gap_echo(_voc([("v", 2.0), ("s", 1.0), ("v", 2.0)]), bpm, 0.0)
    long = render._gap_echo(_voc([("v", 2.0), ("s", 3.0), ("v", 2.0)]), bpm, 0.0)
    # audible end of the echo that follows line 1 (starts at t=2.0s); compare within each own gap
    end_short = _last_energy_sample(short[int(2.0 * SR): int(3.0 * SR)])
    end_long = _last_energy_sample(long[int(2.0 * SR): int(5.0 * SR)])
    assert end_long > end_short, (
        f"a 3s gap did not ring longer than a 1s gap (end_long={end_long} <= end_short={end_short})")


# ================================================================ E: the cap is tempo-derived
def test_tail_cap_is_tempo_derived():
    """CRITERION E: the cap is ONE BAR, tempo-derived — a bar at 85 BPM is longer than at 127 BPM, so an
    over-long gap rings measurably LONGER at the slower tempo. (One bar: 85->~2.82s, 127->~1.89s.)"""
    voc = _voc([("v", 2.0), ("s", 8.0)])  # an 8s gap -> the cap governs the tail at both tempos
    slow = render._gap_echo(voc, 85.0, tail_after_end_secs=0.0)
    fast = render._gap_echo(voc, 127.0, tail_after_end_secs=0.0)
    tail_slow = _last_energy_sample(slow[int(2.0 * SR):]) / SR
    tail_fast = _last_energy_sample(fast[int(2.0 * SR):]) / SR
    assert tail_slow > tail_fast + 0.3, (
        f"cap is not tempo-derived: 85 BPM tail {tail_slow:.2f}s not clearly longer than "
        f"127 BPM tail {tail_fast:.2f}s")


# ================================================================ F: containment (the safety net)
def test_echo_overruns_predicate_is_independent_and_correct():
    """CRITERION F: the render-side containment predicate flags a placement whose ECHOED length would
    reach the next vocal's entry, and passes one that ends before it. This is the independent net (kept
    even though the tail is sized to the gap BY CONSTRUCTION — clamp AND referee, like today)."""
    # placement at anchor=10s, next vocal enters at 20s; a 9.5s echoed length ends at 19.5 < 20 -> ok
    assert render._echo_overruns(anchor=10.0, placed_secs=9.5, next_anchor=20.0) is False
    # a 10.5s echoed length would reach 20.5 > 20 -> overrun (two voices) -> flagged
    assert render._echo_overruns(anchor=10.0, placed_secs=10.5, next_anchor=20.0) is True
    # no next vocal (last placement) -> never an overrun
    assert render._echo_overruns(anchor=10.0, placed_secs=99.0, next_anchor=None) is False


def test_echo_overruns_also_guards_song1_leads_in_the_gap():
    """CRITERION F (cross-song R1): the echo must not ring into SONG 1's own vocal that trades in the gap.
    `_echo_overruns` also flags an echoed span that reaches a Song-1 lead start passed in `s1_starts_after`
    — the 'next vocal' the tail must respect is whichever sings next, Song 2 OR Song 1. (The 3-arg form
    stays valid: no Song-1 starts => Song-2-only behaviour, unchanged.)"""
    # last placement (no next Song-2 entry), but Song 1 leads at t=15s; an echoed length reaching 15.5 collides
    assert render._echo_overruns(10.0, 5.5, None, s1_starts_after=[15.0]) is True   # ends 15.5 > 15.0
    # an echoed length that stops before the Song-1 lead is fine
    assert render._echo_overruns(10.0, 4.5, None, s1_starts_after=[15.0]) is False  # ends 14.5 < 15.0
    # the 3-arg form (no Song-1 starts) is unchanged
    assert render._echo_overruns(10.0, 9.9, 20.0) is False


def test_gap_echo_output_never_exceeds_the_room_given():
    """CRITERION F: the echoed buffer never rings past (dry length + tail_after_end) — its final tail is
    contained within the inter-placement gap it was told about."""
    bpm = 120.0
    voc = _voc([("v", 2.0), ("s", 0.5), ("v", 2.0)])  # ends voiced -> final tail rings into tail_after_end
    tail_after = 3.0
    out = render._gap_echo(voc, bpm, tail_after_end_secs=tail_after)
    max_allowed = len(voc) + int(tail_after * SR)
    assert len(out) <= max_allowed, (
        f"echo rang past its room: {len(out)} > {max_allowed} (dry {len(voc)} + gap {tail_after}s)")


# ================================================================ edges: degenerate inputs are no-ops
def test_gap_echo_degenerate_inputs():
    """A non-positive tempo or an empty vocal is a graceful no-op (returns the input, no crash)."""
    voc = _voc([("v", 1.0)])
    assert np.array_equal(render._gap_echo(voc, 0.0, 0.0), voc), "bpm<=0 must be a dry no-op"
    empty = np.zeros((0, 2), dtype=np.float32)
    assert render._gap_echo(empty, 120.0, 0.0).shape == empty.shape, "empty vocal must stay empty"


# ================================================================ loudness: echo send level + bed duck
def test_echo_first_tap_is_at_the_wet_send_level():
    """The loudest echo tap is at _GAP_ECHO_WET x the sung line (not the decay ratio) — so the echo is a
    bold, clearly-heard throw. Guards the 'can't feel the echo' fix: a regression back to the quieter
    feedback-level first tap would drop this below _GAP_ECHO_WET."""
    bpm = 120.0
    voc = _voc([("v", 2.0), ("s", 3.0)])  # one line then a long gap (final tail rings into it)
    seg_peak = float(np.max(np.abs(voc[: int(2.0 * SR)])))
    out = render._gap_echo(voc, bpm, tail_after_end_secs=0.0)
    gap = out[int(2.05 * SR): int(4.5 * SR)]           # inside the gap, past the line end
    echo_peak = float(np.max(np.abs(gap)))
    # the first tap ~ _GAP_ECHO_WET x seg peak (taps overlap so it can be a touch higher, never below)
    assert echo_peak >= render._GAP_ECHO_WET * seg_peak * 0.9, (
        f"echo too quiet: peak {echo_peak:.3f} < wet {render._GAP_ECHO_WET} x seg {seg_peak:.3f}")


def test_gap_echo_events_marks_line_ends_with_real_gaps():
    """_gap_echo_events returns one (line_end, tail) per sung line that has a big-enough gap — the shared
    source of truth the echo AND the beat-duck both use. A gapless vocal yields no events."""
    bpm = 120.0
    ev = render._gap_echo_events(_voc([("v", 2.0), ("s", 2.0), ("v", 2.0)]), bpm, 0.0)
    assert len(ev) >= 1, "a vocal with a real inter-line gap must yield an echo event"
    assert all(tail > 0 for _e, tail in ev)
    assert render._gap_echo_events(_voc([("v", 4.0)]), bpm, 0.0) == [], "a gapless vocal -> no events"


def test_duck_bed_under_echoes_lowers_the_beat_only_in_the_gap():
    """_duck_bed_under_echoes attenuates the beat inside an echo region and leaves it untouched outside —
    so the echo pokes through the gap and the beat snaps back for the next line. Empty events => no-op."""
    bed = np.ones((int(4.0 * SR), 2), dtype=np.float32)
    events = [(int(1.0 * SR), int(1.0 * SR))]           # an echo from 1.0s to 2.0s
    out = render._duck_bed_under_echoes(bed.copy(), anchor=0, events=events)
    mid = float(np.abs(out[int(1.5 * SR)]).mean())      # well inside the ducked region
    before = float(np.abs(out[int(0.5 * SR)]).mean())   # outside, before
    after = float(np.abs(out[int(3.0 * SR)]).mean())    # outside, after
    assert mid < 0.5, f"beat not ducked under the echo (mid={mid:.3f}, expected << 1.0)"
    assert before > 0.95 and after > 0.95, "beat changed OUTSIDE the echo region — duck must be local"
    # empty events => bed untouched
    assert np.array_equal(render._duck_bed_under_echoes(bed.copy(), 0, []), bed)


# ================================================================ the KEPT reverb bed (Rule 4's other half)
def test_reverb_bed_is_length_preserving():
    """The continuous reverb bed truncates its wet tail to the dry length, so it never rings PAST the
    placement into the next vocal (F1 containment). (Preserved from the deleted phrase-throw suite —
    _reverb_bed is kept as Rule 4's 'always both together' reverb half.)"""
    base = _voc([("v", 4.0)])
    for n in (100, SR // 2, SR, 3 * SR):
        voc = base[:n].copy()
        out = render._reverb_bed(voc)
        assert out.shape == voc.shape, f"n={n}: reverb bed changed length {out.shape} != {voc.shape}"
        if len(voc) > 0:
            assert float(np.max(np.abs(out - voc))) > 1e-5, f"n={n}: reverb bed was a silent no-op"


def test_reverb_bed_empty_is_noop():
    """An empty vocal returns empty (length preserved, no crash)."""
    empty = np.zeros((0, 2), dtype=np.float32)
    assert render._reverb_bed(empty).shape == empty.shape
