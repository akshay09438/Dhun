"""The ~180s highlight must contain the singing, not just end at it.

THE BUG, FOUND IN A REAL USER MIX (Rapture x God's Plan, 2026-08-15 20:36). Drake was placed three
times across the 8-minute mix - 1:04, 2:56 and 7:28 - and the founder heard him only at the very
end. Measured: the crop kept 4:48-8:00, so the first two sections were thrown away and the third
landed 2m40s into a 3m mix.

THE CAUSE, in the code's own words: "end just after the last sung phrase; start ~target earlier".
The window is anchored to the LAST moment anyone sings and then walks back `target` seconds. On a
normal-length beat everything fits inside that and it is fine. On an 8-minute one whose vocals are
spread from 1:04 to 7:28, ending at 7:28 and reeling back three minutes bins the rest.

NOT singles-vs-sets, which is what it looked like: both routes call the same `crop_and_arc` with the
same target, and a SET member on Rapture lost 59s of singing exactly like a single did. It is beat
LENGTH - 4 of the 25 menu beats are over 5 minutes.

THE FIX IS DELIBERATELY THE SMALLEST ONE THAT WORKS (founder: "none of the logic of where the vocal
comes in and sector should be changed, but only that part which you pointed out"). Today's window is
still computed first and still used **unchanged whenever it already keeps all the singing** - so
every mix that sounds right today is byte-identical. Only when that window would throw singing away
does it look for a better one. Nothing about arrangement, vocal placement, target length or the
vocal-silent edges changes.
"""
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from workers.best_parts import choose_window  # noqa: E402

TARGET = 192.0


def _phrases(end: float, step: float = 8.0):
    """A phrase grid every `step` seconds, like a real 4-bar grid."""
    n = int(end // step) + 1
    return [round(i * step, 3) for i in range(n)]


def _silent_outside(sung):
    """Silent everywhere except inside a sung stretch - the real predicate's shape."""
    def silent(t):
        return not any(a - 1e-6 <= t <= b + 1e-6 for a, b in sung)
    return silent


def _kept(window, sung):
    s, e = window
    return sum(max(0.0, min(b, e) - max(a, s)) for a, b in sung)


# --- the real failing case -------------------------------------------------------------------

def test_the_rapture_mix_keeps_the_singing_instead_of_only_the_last_bit():
    """The founder's actual mix: 8 minutes, Drake at 1:04, 2:56 and 7:28."""
    sung = [(64.2, 69.0), (176.2, 207.6), (448.2, 479.5)]
    phrases = _phrases(482.3)
    win = choose_window(phrases, _silent_outside(sung), sung, TARGET)
    kept = _kept(win, sung)
    old_kept = 31.3          # what the shipped crop kept, measured on the real render
    assert kept > old_kept, (
        f"the window still keeps only {kept:.1f}s of singing (was {old_kept}s) - window={win}")
    assert kept >= 36.0, f"it should capture the two early sections (36.1s), kept {kept:.1f}s"


def test_it_does_not_simply_move_the_problem_to_the_other_end():
    """Capturing the early sections must not silently drop a LONGER later one."""
    sung = [(30.0, 40.0), (400.0, 460.0)]        # a small early one, a big late one
    phrases = _phrases(480.0)
    win = choose_window(phrases, _silent_outside(sung), sung, TARGET)
    assert _kept(win, sung) >= 60.0, f"it took the 10s section over the 60s one: {win}"


# --- and every mix that is fine today must not move ------------------------------------------

def test_a_mix_that_already_keeps_everything_is_left_exactly_as_it_was():
    """THE SAFETY PROPERTY. Mixes on normal-length beats sound right today and have been ear-checked;
    this change must not touch a single one of them. Today's rule: end just after the last sung
    phrase, start `target` before it."""
    sung = [(30.0, 60.0), (120.0, 200.0)]
    phrases = _phrases(270.0)
    silent = _silent_outside(sung)
    end_today = next(p for p in phrases if p > 200.0 and silent(p))
    start_today = [p for p in phrases if silent(p) and p <= end_today - TARGET][-1]

    win = choose_window(phrases, silent, sung, TARGET)
    assert win == (start_today, end_today), (
        f"a mix that was already fine moved: {win} instead of {(start_today, end_today)}")


def test_a_short_mix_is_untouched_too():
    sung = [(20.0, 100.0)]
    phrases = _phrases(180.0)
    silent = _silent_outside(sung)
    win = choose_window(phrases, silent, sung, TARGET)
    assert _kept(win, sung) == 80.0, "a short mix lost singing that used to survive"


# --- the rules the crop already had, which must still hold ------------------------------------

def test_both_edges_still_land_where_nobody_is_singing():
    """The crop's existing promise: never chop a lyric in half. Unchanged by this."""
    sung = [(64.2, 69.0), (176.2, 207.6), (448.2, 479.5)]
    phrases = _phrases(482.3)
    silent = _silent_outside(sung)
    s, e = choose_window(phrases, silent, sung, TARGET)
    assert silent(s), f"the window starts mid-word at {s}"
    assert silent(e), f"the window ends mid-word at {e}"
    assert s in phrases and e in phrases, "edges must stay on the phrase grid"


def test_the_window_is_still_about_the_target_length():
    """Not longer - the highlight is meant to be ~180s, and a set chains several of them."""
    sung = [(64.2, 69.0), (176.2, 207.6), (448.2, 479.5)]
    phrases = _phrases(482.3)
    s, e = choose_window(phrases, _silent_outside(sung), sung, TARGET)
    assert e - s <= TARGET + 8.0, f"the window grew to {e - s:.0f}s"
    assert e - s >= TARGET - 32.0, f"the window shrank to {e - s:.0f}s"


def test_an_instrumental_mix_does_not_crash():
    phrases = _phrases(300.0)
    win = choose_window(phrases, lambda t: True, [], TARGET)
    assert win[1] > win[0]
