"""HARD-RULE force-check: no code path may pitch a vocal beyond +/-2 semitones (2026-08-10).

The +/-2 cap (keys.CAP_SEMITONES, the CDJ-3000 / founder ceiling) is enforced at several independent
layers. This test proves EACH layer, so a future edit that loosens any single one fails CI loudly
instead of silently letting a vocal chipmunk again (the Silence x With You +3 st regression).
See docs/RULEBOOK.md 'Hard Rules'.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

import app.routes.mix as mix_route
from app.audio import chroma, pitch
from app.planner import keys

CAP = 2


def test_label_cap_is_two_and_fuzzy_never_exceeds_it():
    assert keys.CAP_SEMITONES == CAP
    # fuzzy_key_shift must never propose a shift larger than the cap, for ANY Camelot pair.
    for nv in range(1, 13):
        for nb in range(1, 13):
            for letter in ("A", "B"):
                s = keys.fuzzy_key_shift(f"{nv}{letter}", f"{nb}{letter}")
                assert s is None or abs(s) <= CAP, f"{nv}{letter}->{nb}{letter} gave {s}"


def test_empirical_executor_cap_is_the_label_cap():
    # SINGLE SOURCE OF TRUTH: the audio-measured fallback cap == the label-rule cap.
    assert mix_route.KEY_SHIFT_CAP == keys.CAP_SEMITONES == CAP


def test_chroma_default_caps_are_two():
    # even a caller that forgets to pass a cap cannot exceed +/-2.
    for fn in (chroma.rank_shifts, chroma.best_shift, chroma.empirical_shift):
        assert inspect.signature(fn).parameters["cap"].default == CAP, fn.__name__


def test_executor_refuses_to_over_shift():
    # the pitch EXECUTOR's own hard floor: it raises rather than render a shift beyond +/-2,
    # no matter what a caller passes (fires before any file read, so a dummy path is fine).
    for bad in (CAP + 1, -(CAP + 1), 12, -7):
        with pytest.raises(pitch.PitchError):
            pitch.shifted_vocal("0" * 64, Path("nonexistent.wav"), bad)
