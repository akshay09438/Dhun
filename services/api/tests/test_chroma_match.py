"""Empirical chroma key-matcher (AutoMashUpper) — pure scoring tests (no audio).

Covers: the winning shift aligns the vocal's pitch-class peak onto the beat's; ties break toward
the smaller |shift| (least pitch move); the baseline is the no-shift score; the cap is honoured.
"""
import numpy as np

from app.audio import chroma


def _peak(pc: int) -> np.ndarray:
    """A chroma vector strongly peaked at pitch-class `pc` (with a little spread, L2-normed)."""
    v = np.full(12, 0.05)
    v[pc] = 1.0
    v[(pc + 7) % 12] = 0.4  # a fifth above — realistic tonal content
    return v / np.linalg.norm(v)


def test_best_shift_aligns_peaks():
    beat = _peak(0)                      # beat centred on C
    voc = _peak(2)                       # vocal centred on D
    shift, score, baseline = chroma.best_shift(beat, voc, cap=3)
    assert shift == -2                   # roll D down 2 semitones -> C: best harmonic overlap
    assert score > baseline              # the shift improves on no-shift
    assert score > 0.9


def test_no_shift_when_already_aligned():
    beat = _peak(5)
    voc = _peak(5)
    shift, score, baseline = chroma.best_shift(beat, voc, cap=3)
    assert shift == 0
    assert abs(score - baseline) < 1e-9


def test_tie_breaks_toward_smaller_shift():
    # A perfectly flat vocal makes every rotation score identically -> the tie-break must pick s=0.
    beat = _peak(3)
    voc = np.ones(12) / np.linalg.norm(np.ones(12))
    shift, _score, _baseline = chroma.best_shift(beat, voc, cap=3)
    assert shift == 0


def test_cap_is_respected():
    beat = _peak(0)
    voc = _peak(5)                       # needs -5 (or +7) to align — both outside a ±3 cap
    ranked = chroma.rank_shifts(beat, voc, cap=3)
    assert all(-3 <= s <= 3 for s, _ in ranked)
    assert len(ranked) == 7              # -3..+3 inclusive


def test_rank_is_sorted_best_first():
    beat = _peak(0)
    voc = _peak(1)
    ranked = chroma.rank_shifts(beat, voc, cap=3)
    scores = [round(c, 6) for _s, c in ranked]     # sort key rounds to 6dp; ties then break on |shift|
    assert scores == sorted(scores, reverse=True)
    assert ranked[0][0] == -1            # roll C#/Db down 1 -> C
