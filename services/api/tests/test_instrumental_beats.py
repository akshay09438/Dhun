"""Which beats contribute MUSIC ONLY (no contrast vocal woven) is a HAND-PICKED, founder-chosen list —
never an automatic guess. A beat is silenced only if it's on the list. This exists because the vocal
SEPARATOR can mis-hear instrumental bleed/pads as "singing": e.g. Rapture (Black Coffee) has no real
lyrics, yet its analysis reads a single vocal region spanning the whole song. That false read must NOT
auto-silence a beat — only a human ear decides a beat is instrumental. (Founder 2026-08-07: an earlier
auto-rule that silenced any beat reading ≥90% vocal was removed — it wrongly muted 'I Adore You', which
sings fine.)"""

from app.planner import instrumental_beats
from app.planner import validate
from app.planner.plan import build_mix_plan
from tests.test_fence import make_analysis

RAPTURE = "7f0b66c94d2be61f18a64485dba0a33b5f4387ccce2ff1b5d23aa7da469076eb"


def test_an_unlisted_beat_sings_even_if_its_analysis_reads_whole_song_vocal():
    """THE REGRESSION GUARD: a beat with a degenerate 'sings the whole song' read that is NOT hand-listed
    must still trade its vocal (it is NOT auto-silenced). This is the 'I Adore You' case."""
    a1 = make_analysis(bpm=120, vocal_regions=[(0.25, 63.0)])  # reads ~99% vocal, but not hand-listed
    a1.song_id = "d" * 64
    assert instrumental_beats.is_instrumental_only(a1) is False


def test_a_hand_listed_beat_is_music_only():
    a1 = make_analysis(bpm=120, vocal_regions=[(0.25, 63.0)])
    a1.song_id = RAPTURE
    assert instrumental_beats.is_instrumental_only(a1) is True


def test_a_normal_beat_trades_its_vocal():
    a1 = make_analysis(bpm=120, vocal_regions=[(20.0, 40.0)])
    a1.song_id = "e" * 64
    assert instrumental_beats.is_instrumental_only(a1) is False


def test_vocal_coverage_still_measures_the_read_for_reporting():
    # The coverage helper stays — it feeds the backend anomaly report (flagging a suspicious analysis),
    # it just no longer DECIDES silencing.
    high = make_analysis(bpm=120, vocal_regions=[(0.25, 63.0)])
    low = make_analysis(bpm=120, vocal_regions=[(20.0, 26.0)])
    assert instrumental_beats.vocal_coverage(high) > 0.9
    assert instrumental_beats.vocal_coverage(low) < 0.3


def test_hand_listed_beat_weaves_no_contrast_vocal():
    a1 = make_analysis(bpm=120, vocal_regions=[(0.25, 63.0)])
    a2 = make_analysis(bpm=120, vocal_regions=[(2.0, 10.0), (20.0, 30.0), (40.0, 52.0)])
    a1.song_id, a2.song_id = RAPTURE, "c" * 64
    plan = build_mix_plan("t", a1, a2, "", take=1, rule=1)
    assert plan.s1_vocal_regions == []
    validate.assert_plan(plan, a1, a2)
