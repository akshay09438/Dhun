"""Acceptance tests for the phrase-throw + continuous-reverb feature (step 3) — the HERMETIC set.

Written independently of the implementation, from the human-approved acceptance criteria. These
exercise the engine primitives and the referee directly, with synthetic audio (no cached data, no
network), so they run everywhere and fast. The REAL-AUDIO criteria (throw rate on the real pair, the
Father Ocean x Der Lagi breath defect, real-render determinism) live in test_phrase_throw_e2e.py.

Criteria covered here:
  1  BYTE-IDENTICAL-OFF WITH Placement.echo=True (golden) — the OFF path still fires the old drop-echo.
  3  RATIO DISTINCTNESS on a LONG placement — 1:3 vs 4:4 give measurably different isolated-vocal audio.
  5  LENGTH-PRESERVING — _throw_at_moments and _reverb_bed never change a placement's length.
  6  CONTAINMENT / REFEREE — validate._throw_violations rejects the unsafe throws, passes the clean ones.

Measurement note (criterion 3): distinctness is measured on the ISOLATED vocal with scripts/audio_diff
(spectral difference), NOT on a full mix — per the module's own reasoning, full-mix correlation is too
blunt to see a vocal-only change.
"""

import hashlib
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

_REPO = Path(__file__).resolve().parents[3]  # tests -> api -> services -> repo
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
if str(_REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO / "scripts"))

import audio_diff  # noqa: E402  (scripts/audio_diff.py — the differs-check tool the task names)
from workers import render  # noqa: E402

SR = render.SR


# ---------------------------------------------------------------- synthetic vocal helpers
def _phrasey_voc(n_bars: int, bpm: float, freq: float = 220.0, amp: float = 0.4) -> np.ndarray:
    """A stereo, VOICED synthetic vocal of `n_bars` bars at `bpm` — a tone with a per-bar amplitude
    wobble so it reads as several phrases with quieter seams (enough structure for the echo/re-fire to
    have real content to grab, without any cached audio)."""
    bar = (60.0 / bpm) * 4.0
    n = int(round(n_bars * bar * SR))
    t = np.linspace(0.0, n / SR, n, endpoint=False)
    # a slow amplitude envelope (0.5..1.0) so the signal has phrase-like dynamics, never silent
    env = 0.75 + 0.25 * np.sin(2 * np.pi * (0.5 / bar) * t)
    m = (amp * env * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.stack([m, m], axis=1)


# ================================================================ Criterion 1: byte-identical OFF path
# The engine OFF path is selected per-placement: `if p.throws or p.reverb_bed: <throw path> else:
# <old echo/chop/pool path>`. So a plan whose drop carries Placement.echo=True, with the NEW throw
# fields OFF (throws=[] / reverb_bed=False), MUST render byte-for-byte the pre-throw m6.0 baseline —
# i.e. the old produced-drop echo fires unchanged. We reuse the golden helper + the m6.0 hash captured
# in tests/test_render.py (the single source of truth for that baseline), exactly as the task asks.


def test_echo_plan_with_throw_fields_absent_matches_m6_0_baseline(tmp_path):
    """Baseline leg: the golden plan (its drop uses Placement.echo=True) with the throw fields ABSENT
    renders to the captured m6.0 hash. This is the reference the OFF-path leg below must match."""
    from tests.test_render import _golden_hash, _GOLDEN_ENABLED_FALSE

    assert _golden_hash(tmp_path) == _GOLDEN_ENABLED_FALSE, (
        "golden echo-carrying plan no longer matches the m6.0 baseline hash — the OFF path drifted")


def test_echo_plan_with_throw_fields_off_is_byte_identical_to_pre_throw(tmp_path):
    """CRITERION 1: adding the phrase-throw fields, set OFF (throws=[], reverb_bed=False), to a plan
    whose drop fires the produced-drop echo must not change a single byte vs the pre-throw m6.0 render.
    Fails for the RIGHT reason if the throw code ever touches the echo/OFF path."""
    from tests.test_render import _golden_plan, _stems, _GOLDEN_ENABLED_FALSE

    p = _golden_plan()
    for pl in p.placements:            # the new fields, present but OFF
        pl.throws = []
        pl.reverb_bed = False
    stems, vocal = _stems(tmp_path)
    out = tmp_path / "off.wav"
    # render.py uses TemporaryDirectory(ignore_cleanup_errors=True) internally; on Windows a full-file
    # run can raise a transient "No such file <stem>.wav" from that temp/ffmpeg race. Retry once so an
    # ENVIRONMENTAL flake can't turn this byte-identity gate red (the stems on disk are unchanged).
    for _attempt in range(2):
        try:
            render.render_mix(p, stems, vocal, out)
            break
        except Exception:
            if _attempt == 1:
                raise
    y, _ = sf.read(out, dtype="float32", always_2d=True)
    h = hashlib.sha256(y.tobytes()).hexdigest()
    assert h == _GOLDEN_ENABLED_FALSE, (
        f"throws=[]/reverb_bed=False changed the echo render vs m6.0!\n  got:      {h}\n"
        f"  expected: {_GOLDEN_ENABLED_FALSE}")


# ================================================================ Criterion 3: ratio distinctness (LONG)
# On a placement long enough to hold BOTH cut cycles (>= 16 bars), a tight 1:3 throw and a balanced 4:4
# throw cut the vocal at DIFFERENT bars, so the isolated-vocal audio must measurably differ. A SHORT
# placement would clamp/collapse the cuts and prove nothing — so this MUST use a long placement.


def test_long_placement_ratios_produce_distinct_vocal_audio():
    """CRITERION 3: 1:3 vs 4:4 on a >=16-bar placement give measurably different ISOLATED-vocal audio
    (audio_diff.distinct). Non-vacuous: the same tool reports an identical signal as NOT distinct, so a
    True here is a real difference, not a metric that always fires."""
    bpm = 120.0
    voc = _phrasey_voc(n_bars=17, bpm=bpm)          # >= 16 bars: both cut cycles fit
    a = render._throw_at_moments(voc, [(0, 1, 3)], bpm)   # tight: sing 1, carry 3 (cut after bar 1)
    b = render._throw_at_moments(voc, [(0, 4, 4)], bpm)   # balanced: sing 4, carry 4 (cut after bar 4)
    # length-preserving even here (guards that "distinct" isn't just a length mismatch)
    assert len(a) == len(voc) and len(b) == len(voc)
    # the metric can say "same" — proves the assertion below is meaningful, not always-true
    assert not audio_diff.distinct(a, a), "distinct() fired on an identical signal — metric is vacuous"
    d = audio_diff.compare(a, b)
    assert audio_diff.distinct(a, b), (
        f"1:3 and 4:4 rendered the SAME isolated vocal on a 17-bar placement "
        f"(spectral_diff={d['spectral_diff']:.4f} <= {audio_diff.DISTINCT_SPECTRAL}) — ratios collapsed")


def test_short_placement_would_collapse_ratios_documenting_why_long_is_required():
    """CRITERION 3 (why-long guard): on a placement too short to hold a 4:4 cycle (4 bars), the 4:4
    throw finds no room and no-ops back to the dry vocal — so comparing 4:4 to the DRY vocal there is
    NOT distinct. This documents the trap the criterion warns about (a short placement proves nothing)
    and pins that the engine leaves a too-short moment singing rather than faking a cut."""
    bpm = 120.0
    voc = _phrasey_voc(n_bars=4, bpm=bpm)           # 4 bars: a 4:4 cycle (8 bars) cannot fit
    b = render._throw_at_moments(voc, [(0, 4, 4)], bpm)
    assert len(b) == len(voc)
    assert not audio_diff.distinct(b, voc), (
        "a 4:4 throw altered a 4-bar placement — it should have found no room and left it singing")


# ================================================================ Criterion 5: length-preserving
def test_throw_at_moments_is_length_preserving_across_throws_and_bpm():
    """CRITERION 5: _throw_at_moments output length == input length for a variety of throws and tempos —
    so a placement's rendered length (and thus placement_end / the referee's R1 math) never moves."""
    for bpm in (90.0, 120.0, 174.0):
        voc = _phrasey_voc(n_bars=8, bpm=bpm)
        cases = [
            [],                                   # no throws -> untouched
            [(0, 1, 1)],                          # one small contained throw
            [(0, 1, 3), (4, 1, 3)],               # two contained throws
            [(0, 4, 4)],                          # a large throw
            [(6, 4, 8)],                          # a throw whose span RUNS PAST the vocal (clamped)
        ]
        for throws in cases:
            out = render._throw_at_moments(voc, throws, bpm)
            assert out.shape == voc.shape, f"bpm={bpm} throws={throws}: {out.shape} != {voc.shape}"


def test_throw_at_moments_degenerate_inputs_keep_length():
    """CRITERION 5 (edges): a non-positive tempo or an empty vocal is a graceful no-op that still
    returns the input unchanged in length."""
    voc = _phrasey_voc(n_bars=2, bpm=120.0)
    assert render._throw_at_moments(voc, [(0, 1, 1)], 0.0).shape == voc.shape      # bpm<=0 -> voc
    assert render._throw_at_moments(voc, [(0, 1, 1)], -120.0).shape == voc.shape
    empty = np.zeros((0, 2), dtype=np.float32)
    assert render._throw_at_moments(empty, [(0, 1, 1)], 120.0).shape == empty.shape


def test_reverb_bed_is_length_preserving():
    """CRITERION 5: _reverb_bed truncates its wet tail to the dry length, so the placement's length is
    unchanged (the continuous reverb never rings PAST the placement into the next vocal — F1 contained)."""
    base = _phrasey_voc(n_bars=4, bpm=120.0)          # ~8s at 120 bpm -> long enough to slice from
    for n in (100, SR // 2, SR, 3 * SR):
        voc = base[:n].copy()
        out = render._reverb_bed(voc)
        assert out.shape == voc.shape, f"n={n}: reverb bed changed length {out.shape} != {voc.shape}"
        # ...and it is actually WET (the bed changed the signal) except on the empty edge
        if len(voc) > 0:
            assert float(np.max(np.abs(out - voc))) > 1e-5, f"n={n}: reverb bed was a silent no-op"


def test_reverb_bed_empty_is_noop():
    """CRITERION 5 (edge): an empty vocal returns empty (length preserved, no crash)."""
    empty = np.zeros((0, 2), dtype=np.float32)
    assert render._reverb_bed(empty).shape == empty.shape


# ================================================================ Criterion 6: containment / referee
from app.models import MixPlan, Placement  # noqa: E402
from app.planner import validate  # noqa: E402


def _plan_with_throws(throws, anchor=16.0, vocal_src=(0.0, 16.0), bpm=120.0, stretch=1.0):
    """A real MixPlan with ONE placement carrying `throws`. At 120 bpm a bar is 2s and a 16s vocal
    from anchor 16.0 ends at 32.0 -> length 8 bars, so a throw ending past bar 8 runs past the
    placement. (validate._throw_violations reads only these fields + placement_end.)"""
    p = Placement(anchor=anchor, vocal_src=vocal_src, throws=throws)
    return MixPlan(mix_id="m" * 64, song1_id="a" * 64, song2_id="b" * 64,
                   master_bpm=bpm, vocal_stretch=stretch, vocal_src=vocal_src,
                   anchor=anchor, placements=[p])


def test_referee_passes_a_clean_throw():
    """CRITERION 6: a well-formed, contained throw (sing>=1, carry>=1, ends within the placement) is
    accepted — the referee must not reject legal punctuation."""
    v = validate._throw_violations(_plan_with_throws([(0, 1, 3)]))  # ends bar 4 <= 8
    assert v == [], f"referee rejected a clean throw: {v}"


def test_referee_passes_empty_throws():
    """CRITERION 6: no throws => no checks => no violations (the pre-throw behaviour)."""
    assert validate._throw_violations(_plan_with_throws([])) == []


def test_referee_rejects_carry_running_past_the_placement():
    """CRITERION 6 (the F1 failure class): a throw whose sing+carry runs past the placement's last bar
    is rejected — its tail would overrun the next sung phrase / the next vocal (R1)."""
    v = validate._throw_violations(_plan_with_throws([(6, 2, 4)]))  # 6+2+4=12 > 8 bars
    assert any("past the placement" in s for s in v), f"carry-overrun not rejected: {v}"


def test_referee_rejects_two_overlapping_throws():
    """CRITERION 6: two throws whose spans overlap within a placement are rejected (two throws firing
    at once is not one-at-a-time punctuation, R1)."""
    v = validate._throw_violations(_plan_with_throws([(0, 2, 3), (1, 2, 3)]))  # spans (0,5) & (1,6)
    assert any("overlap" in s for s in v), f"overlapping throws not rejected: {v}"


def test_referee_rejects_nonpositive_sing_or_carry():
    """CRITERION 6: a throw with a zero/negative sing or carry is malformed and rejected."""
    v = validate._throw_violations(_plan_with_throws([(0, 0, 3)]))  # sing = 0
    assert any("non-positive" in s for s in v), f"non-positive sing not rejected: {v}"
