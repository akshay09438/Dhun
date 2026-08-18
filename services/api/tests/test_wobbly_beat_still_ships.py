"""A song with a loose, drifting pulse must still produce a mix.

THE REPORT, 2026-08-18 17:08. The founder uploaded `Circle_With_Me`, used it as the beat, waited
four minutes and got "This pair didn't come out clean, so it wasn't shipped." Their question was
the right one: *"we have the hard rule that every song which goes in has to generate"*.

WHAT THE ENGINE LOG SHOWED - the first real incident the engine's own log ever explained:

    beat-grid song1/beat: {'regularity': 0.112, 'bpm_agreement': 0.996, 'health': 0.112, 'ok': False}
    beat-grid song2/vocal: {'regularity': 0.981, 'bpm_agreement': 1.0,  'health': 0.981, 'ok': True}
    failed (quality): ValidationError: a forced placement could not beat-lock (single-stretch drift) (R7)

The song's beats average 103 BPM but drift about a TENTH OF A SECOND each, back and forth. So the
never-decline path forced a bar-by-bar lock onto a grid that cannot hold one, and R7 - correctly -
refused to ship a vocal that would wander off the beat. TWO RULES FIGHTING: one insisted the mix be
made, the other refused the thing the first one built.

THE REFEREE WAS RIGHT AND IS NOT TOUCHED. The bug is upstream, in `_attach_warp`, whose own
docstring already describes the escape hatch: "With no usable grid on either side, leave warp empty
- the engine then uses the legacy global stretch." It only ever asked whether downbeats EXIST.
Circle_With_Me had 107 of them, all wobbly, so the check passed and the lock was forced anyway.

Asking whether the grid is TRUSTWORTHY (`beatgrid.grid_health`, already computed and already logged
per mix) is the fix. No warp means no bar-by-bar lock, which means R7 has nothing to reject: the
vocal sits over the beat on one global stretch. Looser, and it comes out - which is the founder's
rule, chosen explicitly over refusing.

MEASURED BEFORE THE FIX: as the BEAT it failed; as the VOCAL it shipped over all three catalogue
beats tried (Rapture, Anchor Point, Wake Me Up). The song was never the problem - the forced lock was.
"""

from __future__ import annotations

from app.models import Section, TrackAnalysis
from app.planner import beatgrid, plan as planner


def _steady(bpm=120.0, secs=180.0):
    """A grid a real 4/4 track would produce: bars exactly where they should be."""
    bar = 4 * 60.0 / bpm
    downs = [round(i * bar, 3) for i in range(int(secs / bar))]
    return TrackAnalysis(
        song_id="steady", status="ready", bpm=bpm, bpm_confidence=0.9,
        beats=[round(i * 60.0 / bpm, 3) for i in range(int(secs * bpm / 60.0))],
        downbeats=downs, phrase_starts=downs[::8], energy_curve=[0.5] * len(downs),
        sections=[Section(start=0.0, end=secs, label="verse")], vocal_regions=[])


def _wobbly(bpm=103.0, secs=180.0, drift=0.10):
    """Circle_With_Me's shape: the right average tempo, but every bar lands late or early.

    `drift` of 0.10s per beat is what the founder's song actually measured."""
    bar = 4 * 60.0 / bpm
    downs, t = [], 0.0
    for i in range(int(secs / bar)):
        downs.append(round(t, 3))
        t += bar + (drift * 4 if i % 2 else -drift * 4)   # alternately late, then early
    return TrackAnalysis(
        song_id="wobbly", status="ready", bpm=bpm, bpm_confidence=0.105,
        beats=[round(i * 60.0 / bpm, 3) for i in range(int(secs * bpm / 60.0))],
        downbeats=downs, phrase_starts=downs[::8], energy_curve=[0.5] * len(downs),
        sections=[Section(start=0.0, end=secs, label="verse")], vocal_regions=[])


# --- the measurement the fix leans on ----------------------------------------------------------

def test_a_wobbly_grid_is_recognised_as_untrustworthy():
    """The signal already exists and is already logged per mix. Nothing was reading it here."""
    assert beatgrid.grid_health(103.0, _wobbly().downbeats)["ok"] is False


def test_a_steady_grid_is_still_trusted():
    assert beatgrid.grid_health(120.0, _steady().downbeats)["ok"] is True


# --- the fix ------------------------------------------------------------------------------------

def _placed(a1, a2, anchor=None):
    from app.models import Placement
    if anchor is None:
        anchor = a1.downbeats[4] if len(a1.downbeats) > 4 else 8.0
    ps = [Placement(anchor=anchor, vocal_src=[8.0, 24.0])]
    return planner._attach_warp(ps, a1, a2, stretch=1.0, forced=True)


def test_a_wobbly_beat_is_not_forced_into_a_lock_it_cannot_hold():
    """THE BUG. A bar-by-bar lock onto a drifting grid is exactly what R7 then refuses, so forcing
    one turns "always make a mix" into "never make this mix"."""
    out = _placed(_wobbly(), _steady())
    assert not out[0].warp, (
        "a drifting grid was still given a bar-by-bar lock - R7 will reject the render and the "
        "person gets nothing")


def test_a_steady_beat_still_gets_its_tight_lock():
    """THE REGRESSION GUARD, and it matters more than the fix. Beat-locking is what stops a vocal
    drifting on every NORMAL pair; this must only stand down when the grid genuinely cannot hold."""
    out = _placed(_steady(), _steady())
    assert out[0].warp, "a healthy grid lost its beat-lock - every ordinary mix would now drift"


def test_a_beat_with_no_grid_at_all_is_unchanged():
    """The pre-existing escape hatch keeps working."""
    a1 = _steady()
    a1.downbeats = []
    out = _placed(a1, _steady())
    assert not out[0].warp
