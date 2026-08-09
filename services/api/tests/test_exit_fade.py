"""Independent acceptance tests for Placement.exit_fade_ms — a musical fade-out on a
Song-2 vocal's tail so a sung line eases out instead of cutting abruptly (the existing
8 ms `_edge_fade` only kills clicks). Written FIRST, from the human-approved acceptance
criteria, BEFORE the engine applies the field — so criteria 1-3 must FAIL now for the
right reason (the fade isn't applied yet), and criteria 4-5 are guardrails that must
STAY green after the fix.

The fix contract (already decided): when a placement's `exit_fade_ms > 0`, render.py
applies a musical fade-out over the LAST `exit_fade_ms` ms of that placement's rendered
vocal — LENGTH-PRESERVING (only tapers existing samples; never lengthens a placement,
moves a placement end, or creates a new overlap). Default 0.0 => no musical fade =>
byte-identical to today.

Harness mirrors test_render.py: workers/ is put on the path, tiny synthetic stems are
built with soundfile, and the finished WAV is read back and measured. To ISOLATE the
Song-2 vocal, the bed stems (drums/bass/other) are SILENT, so all measured energy in the
placement region is the placed vocal itself.
"""

import hashlib
import sys
import types
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

_REPO = Path(__file__).resolve().parents[3]  # tests -> api -> services -> repo
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from workers import render  # noqa: E402

SR = render.SR


# ---------------------------------------------------------------- synthetic audio helpers
def _tone(path, freq=440.0, secs=8.0, amp=0.4, sr=SR):
    t = np.linspace(0, secs, int(sr * secs), endpoint=False)
    sf.write(path, (amp * np.sin(2 * np.pi * freq * t)).astype("float32"), sr)


def _silent(path, secs=8.0, sr=SR):
    sf.write(path, np.zeros(int(sr * secs), dtype="float32"), sr)


def _silent_bed_and_vocal(tmp_path, freq=440.0, bed_secs=8.0, vocal_secs=8.0):
    """Bed (drums/bass/other) + Song-1's own vocal stem SILENT; Song-2's vocal a steady tone.
    So the render isolates the placed Song-2 vocal — every bit of measured energy is IT, and any
    decay in the placement region comes from the exit fade (there is no other source)."""
    stems = {}
    for name in ("drums", "bass", "other"):
        p = tmp_path / f"{name}.wav"
        _silent(p, secs=bed_secs)
        stems[name] = p
    s1 = tmp_path / "vocals.wav"          # Song 1's own vocal stem — silent + unused (no s1_vocal_regions)
    _silent(s1, secs=bed_secs)
    stems["vocals"] = s1
    vocal = tmp_path / "s2vocal.wav"      # Song 2's vocal — the tone we place and fade
    _tone(vocal, freq=freq, secs=vocal_secs)
    return stems, vocal


def _one_placement_plan(anchor, vocal_src, exit_fade_ms=None):
    """A duck-typed single-placement plan. exit_fade_ms is left ABSENT (=> the engine's default 0.0,
    i.e. today's behaviour) unless a value is given, so a baseline render never carries the field."""
    pl = types.SimpleNamespace(anchor=anchor, vocal_src=vocal_src, beat_breath=False)
    if exit_fade_ms is not None:
        pl.exit_fade_ms = float(exit_fade_ms)
    return types.SimpleNamespace(master_bpm=120.0, vocal_stretch=1.0,
                                 vocal_src=vocal_src, anchor=anchor, beat_breath=False,
                                 placements=[pl])


def _render(plan, stems, vocal, out):
    """Render with the Windows temp/ffmpeg race retry test_render.py uses."""
    for _attempt in range(2):
        try:
            render.render_mix(plan, stems, vocal, out)
            break
        except Exception:
            if _attempt == 1:
                raise
    return out


def _read(path):
    y, _ = sf.read(str(path), dtype="float32", always_2d=True)
    return y


def _rms(seg):
    return float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0


def _last_audible(y, floor=1e-3):
    """The sample index just past the last audible sample — the placed vocal's real end (the bed is
    silent, so nothing but the vocal is audible). Measured on the UNFADED render, so it is the true
    placement end for windowing BOTH renders (the fix is length-preserving => same end in both)."""
    mono = np.max(np.abs(y), axis=1)
    idx = np.where(mono > floor)[0]
    return int(idx[-1]) + 1 if len(idx) else 0


# =============================================================== Criterion 1: the tail actually fades
def test_exit_fade_tapers_the_vocal_tail(tmp_path):
    """AC1: with a large exit_fade_ms the vocal region's final ~150 ms carries MEANINGFULLY LESS energy
    than the same region with no musical fade, and the very last samples approach ~0. FAILS today
    because the engine ignores exit_fade_ms, so the faded render == the unfaded one and the tail energy
    is unchanged (the abrupt cut the founder reported)."""
    stems, vocal = _silent_bed_and_vocal(tmp_path)
    plain = _render(_one_placement_plan(1.0, (0.0, 2.0)), stems, vocal, tmp_path / "plain.wav")
    faded = _render(_one_placement_plan(1.0, (0.0, 2.0), exit_fade_ms=400.0), stems, vocal,
                    tmp_path / "faded.wav")
    ya, yb = _read(plain), _read(faded)
    assert ya.shape == yb.shape
    end = _last_audible(ya)                                  # the vocal's real end (unfaded)
    w = int(0.15 * SR)
    tail_plain = _rms(ya[end - w:end])
    tail_faded = _rms(yb[end - w:end])
    assert tail_faded < 0.6 * tail_plain, (
        f"the vocal tail did not fade: final-150ms RMS unfaded={tail_plain:.4f} faded={tail_faded:.4f} "
        "(exit_fade_ms not applied — the line still cuts abruptly)")
    # ...and the very end approaches ~0 relative to the vocal's body (a real fade-out, not a cliff).
    body_faded = _rms(yb[int(1.3 * SR):int(1.6 * SR)])
    end_faded = _rms(yb[end - int(0.05 * SR):end])
    assert end_faded < 0.2 * body_faded, (
        f"the faded tail does not approach zero: last-50ms RMS={end_faded:.4f} vs body={body_faded:.4f}")


# =============================================================== Criterion 2: length-preserving
def test_exit_fade_is_length_preserving_only_the_window_changes(tmp_path):
    """AC2: the faded and unfaded renders have the EXACT same number of samples, and every sample BEFORE
    the fade window is byte-identical — only the final exit_fade_ms window differs. This proves the fade
    can NEVER lengthen a placement, move a placement end, or create a new overlap. The 'window actually
    differs' assertion FAILS today (the two renders are identical because the fade isn't applied)."""
    stems, vocal = _silent_bed_and_vocal(tmp_path)
    plain = _render(_one_placement_plan(1.0, (0.0, 2.0)), stems, vocal, tmp_path / "plain.wav")
    faded = _render(_one_placement_plan(1.0, (0.0, 2.0), exit_fade_ms=400.0), stems, vocal,
                    tmp_path / "faded.wav")
    ya, yb = _read(plain), _read(faded)
    assert ya.shape == yb.shape, (
        f"exit_fade changed the render length: unfaded {ya.shape} vs faded {yb.shape} — not length-preserving")

    end = _last_audible(ya)
    fade_win = int(0.4 * SR)                                  # the last 400 ms — the fade window
    before = end - fade_win - int(0.02 * SR)                  # 20 ms guard in front of the fade
    assert np.array_equal(ya[:before], yb[:before]), (
        "samples BEFORE the fade window are not byte-identical — the fade reached back beyond its window "
        "(it may be moving a placement end / creating an overlap)")
    # The fade window itself MUST differ once the fade is applied (fails today: the renders are identical).
    d0, d1 = end - int(0.20 * SR), end - int(0.05 * SR)
    assert float(np.max(np.abs(ya[d0:d1] - yb[d0:d1]))) > 1e-4, (
        "the fade window is identical to the unfaded render — no musical fade was applied over the "
        "final exit_fade_ms")


# =============================================================== Criterion 3: never swallow a short clip
def test_exit_fade_does_not_swallow_a_short_vocal(tmp_path):
    """AC3: a placement whose vocal (0.2 s) is SHORTER than exit_fade_ms (400 ms) must still contain
    audible vocal energy — the fade is CAPPED so it can't taper the whole line into silence. The tail is
    still reduced (proving the fade IS applied — this half FAILS today), while the line's start survives
    and the render passes the not-silent referee (proving the cap)."""
    stems, vocal = _silent_bed_and_vocal(tmp_path, bed_secs=2.0)  # short bed => the 0.2s clip is a healthy
    plain = _render(_one_placement_plan(1.0, (0.0, 0.2)), stems, vocal,   # fraction of the render, so the
                    tmp_path / "plain.wav")                                # not-silent check is a real cap test
    faded = _render(_one_placement_plan(1.0, (0.0, 0.2), exit_fade_ms=400.0), stems, vocal,
                    tmp_path / "faded.wav")
    ya, yb = _read(plain), _read(faded)
    end = _last_audible(ya)

    from app.planner import validate
    # (cap) the short faded line is NOT swallowed: still audible (not silent), never clipping.
    assert validate.validate_render(faded) == [], (
        "the capped exit fade left the short clip silent/near-silent (R6) — it swallowed the whole line")
    # (cap) the START of the line survives at near-full level (a fade capped away from the head).
    h0, h1 = 1 * SR + int(0.01 * SR), 1 * SR + int(0.05 * SR)  # 10-50 ms after the entry (past the edge fade)
    head_plain, head_faded = _rms(ya[h0:h1]), _rms(yb[h0:h1])
    assert head_faded > 0.3 * head_plain, (
        f"the line's start was swallowed by the fade: head RMS unfaded={head_plain:.4f} faded={head_faded:.4f}")
    # (fade applied) the tail is meaningfully reduced — FAILS today (the renders are identical).
    tw = int(0.04 * SR)
    tail_plain, tail_faded = _rms(ya[end - tw:end]), _rms(yb[end - tw:end])
    assert tail_faded < 0.6 * tail_plain, (
        f"the short clip's tail did not fade: final-40ms RMS unfaded={tail_plain:.4f} faded={tail_faded:.4f} "
        "(exit_fade_ms not applied)")


# =============================================================== Criterion 4: the referee still passes
def test_referee_passes_a_plan_and_render_with_exit_fade(tmp_path):
    """AC4 (guardrail — may pass today, must STAY green): a plan carrying exit_fade_ms > 0 passes the
    plan referee (validate_plan / assert_plan) and the finished-audio referee (validate_render /
    assert_render) — no clip, not silent, R1 no-overlap. exit_fade is additive + length-preserving, so it
    must never trip a hard rule."""
    from app.models import MixPlan, Placement
    from app.planner import validate
    from tests.test_fence import make_analysis

    a1, a2 = make_analysis(), make_analysis()  # Song-1 downbeats every 2s
    plan = MixPlan(
        mix_id="m" * 64, song1_id="a" * 64, song2_id="b" * 64, master_bpm=120.0,
        vocal_stretch=1.0, vocal_src=(0.0, 8.0), anchor=16.0,
        placements=[Placement(anchor=16.0, vocal_src=(0.0, 8.0), exit_fade_ms=400.0)])
    assert validate.validate_plan(plan, a1, a2) == [], "a plan with exit_fade_ms was wrongly flagged"
    validate.assert_plan(plan, a1, a2)  # must not raise

    # ...and the finished audio a plan with exit_fade produces passes the render referee.
    stems, vocal = _silent_bed_and_vocal(tmp_path)
    out = _render(_one_placement_plan(1.0, (0.0, 2.0), exit_fade_ms=400.0), stems, vocal,
                  tmp_path / "faded.wav")
    assert validate.validate_render(out) == [], "the exit-faded render failed the finished-audio referee"
    validate.assert_render(out)  # must not raise


# =============================================================== Criterion 5: default 0.0 changes nothing
# The golden byte-identity gate rests on the 0.0 path being a true no-op. These duplicate test_render.py's
# golden helpers LOCALLY (do NOT edit test_render.py) to prove that (a) the 0.0 path is deterministic
# run-to-run and (b) an explicit exit_fade_ms=0.0 renders BYTE-IDENTICALLY to a plan with no such field —
# i.e. adding the field with default 0.0 changed nothing.
def _stems(tmp_path):
    paths = {}
    for name, f in (("drums", 110.0), ("bass", 55.0), ("other", 330.0), ("vocals", 660.0)):
        p = tmp_path / f"{name}.wav"
        _tone(p, freq=f, secs=8.0)
        paths[name] = p
    vocal = tmp_path / "vocal.wav"
    _tone(vocal, freq=440.0, secs=8.0)
    return paths, vocal


def _arr_plan(placements, breath=False):
    return types.SimpleNamespace(
        master_bpm=120.0, vocal_stretch=1.0,
        vocal_src=placements[0][1], anchor=placements[0][0], beat_breath=breath,
        placements=[types.SimpleNamespace(anchor=a, vocal_src=v, beat_breath=b)
                    for a, v, b in placements])


def _stem_move(stem, start, end, gain_from=1.0, gain_to=0.0):
    return types.SimpleNamespace(stem=stem, start=start, end=end,
                                 gain_from=gain_from, gain_to=gain_to)


def _golden_style_plan():
    """A feature-rich duck-typed plan (two placements, a beat-breath, a build+echo, a bass stem-move, a
    Song-1 contrast region) — mirrors test_render._golden_plan so multiple render paths are exercised. It
    does NOT set exit_fade_ms, so every placement defaults to 0.0."""
    p = _arr_plan([(1.0, (0.0, 2.0), False), (5.0, (0.0, 1.5), True)])
    p.placements[1].build_bars = 2
    p.placements[1].echo = True
    p.stem_moves = [_stem_move("bass", 3.0, 5.0, 1.0, 0.0)]
    p.s1_vocal_regions = [(3.2, 4.8)]
    return p


def _sha(plan, tmp_dir):
    tmp_dir.mkdir(parents=True, exist_ok=True)
    stems, vocal = _stems(tmp_dir)
    out = _render(plan, stems, vocal, tmp_dir / "g.wav")
    y = _read(out)
    return hashlib.sha256(y.tobytes()).hexdigest()


def test_zero_exit_fade_is_a_noop_and_deterministic(tmp_path):
    """AC5 (guardrail — passes today, must STAY green): the default-0.0 exit_fade path is deterministic
    run-to-run AND an explicit exit_fade_ms=0.0 is byte-identical to a plan without the field. This is
    what keeps the golden byte-identity gate honest — adding the field (default 0.0) changed nothing."""
    h_absent_a = _sha(_golden_style_plan(), tmp_path / "a")
    h_absent_b = _sha(_golden_style_plan(), tmp_path / "b")
    assert h_absent_a == h_absent_b, "the default (no-exit_fade) render is not deterministic run-to-run"

    zero = _golden_style_plan()
    for pl in zero.placements:
        pl.exit_fade_ms = 0.0
    h_zero = _sha(zero, tmp_path / "c")
    assert h_zero == h_absent_a, (
        "an explicit exit_fade_ms=0.0 is NOT byte-identical to the field-absent render — the 0.0 default "
        "is not a true no-op (the golden gate would break)")


# =============================================================== Two adjacent placements (regression)
# Added after the adversarial safety review flagged that the acceptance tests only exercised a SINGLE
# placement. This pins the reviewer's manual repro: with TWO placements both fading, the fade on the
# first must stay inside its own tail and never bleed forward into the next voice (which would be a
# two-voices R1 overlap). Guards against a future change that makes the fade reach past its placement.
def _two_placement_plan(exit_fade_ms=None):
    def _pl(anchor, src):
        pl = types.SimpleNamespace(anchor=anchor, vocal_src=src, beat_breath=False)
        if exit_fade_ms is not None:
            pl.exit_fade_ms = float(exit_fade_ms)
        return pl
    return types.SimpleNamespace(master_bpm=120.0, vocal_stretch=1.0,
                                 vocal_src=(0.0, 2.0), anchor=1.0, beat_breath=False,
                                 placements=[_pl(1.0, (0.0, 2.0)), _pl(4.0, (0.0, 2.0))])


def test_exit_fade_on_two_adjacent_placements_stays_length_preserving(tmp_path):
    """Two placements (first ends ~3.0s, second enters 4.0s), both faded: the render length is unchanged
    vs unfaded, the SECOND placement's body is byte-identical (the first's fade never bleeds forward into
    it → it cannot create a two-voices overlap), the first placement's tail is attenuated, and the finished
    render passes the referee (R6)."""
    stems, vocal = _silent_bed_and_vocal(tmp_path)
    plain = _render(_two_placement_plan(), stems, vocal, tmp_path / "plain.wav")
    faded = _render(_two_placement_plan(exit_fade_ms=400.0), stems, vocal, tmp_path / "faded.wav")
    ya, yb = _read(plain), _read(faded)
    assert ya.shape == yb.shape, "two-placement exit_fade changed the render length — not length-preserving"

    # The second placement enters at 4.0s; its body (4.2–5.0s, before its OWN tail fade) must be
    # byte-identical between faded and unfaded — the first placement's fade cannot reach across the gap.
    b0, b1 = int(4.2 * SR), int(5.0 * SR)
    assert np.array_equal(ya[b0:b1], yb[b0:b1]), (
        "the first placement's fade bled forward into the second placement's body — a possible overlap")

    # The first placement's tail (vocal ends ~3.0s) is attenuated by the fade.
    tw, e = int(0.15 * SR), int(3.0 * SR)
    assert _rms(yb[e - tw:e]) < 0.6 * _rms(ya[e - tw:e]), "the first placement's tail did not fade"

    from app.planner import validate
    assert validate.validate_render(faded) == [], "the two-placement exit-faded render failed the referee"


# =============================================================== Standalone Song-1 answer (guest-verse hand-off)
def test_exit_fade_eases_a_standalone_song1_answer(tmp_path):
    """The exit-fade must ALSO ease a STANDALONE Song-1 contrast answer's tail out — the beat's own lyric
    ending (e.g. a vocal-rich beat's guest-verse hand-off: "even if it plays, it plays under the upcoming
    vocal"). Build a plan whose Song-1 answer [1..4s] has NO Song-2 entry landing in it (the Song-2
    placement is far away at 8s), render feature-off vs on, and assert the answer's tail is attenuated and
    the render length is unchanged (length-preserving)."""
    stems = {}
    for name in ("drums", "bass", "other"):
        p = tmp_path / f"{name}.wav"; _silent(p, secs=12.0); stems[name] = p
    s1v = tmp_path / "s1vocals.wav"; _tone(s1v, freq=330.0, secs=12.0); stems["vocals"] = s1v
    s2v = tmp_path / "s2vocal.wav"; _tone(s2v, freq=550.0, secs=12.0)

    def _plan(exit_ms=None):
        pl = types.SimpleNamespace(anchor=8.0, vocal_src=(0.0, 2.0), beat_breath=False)
        if exit_ms is not None:
            pl.exit_fade_ms = float(exit_ms)
        pn = types.SimpleNamespace(master_bpm=120.0, vocal_stretch=1.0, vocal_src=(0.0, 2.0),
                                   anchor=8.0, beat_breath=False, placements=[pl])
        pn.s1_vocal_regions = [(1.0, 4.0)]  # standalone: the Song-2 entry (8.0s) never lands inside [1,4]
        return pn

    plain = _render(_plan(), stems, s2v, tmp_path / "plain.wav")
    faded = _render(_plan(400.0), stems, s2v, tmp_path / "faded.wav")
    ya, yb = _read(plain), _read(faded)
    assert ya.shape == yb.shape, "the Song-1 exit-fade changed the render length — not length-preserving"
    e, tw = int(4.0 * SR), int(0.3 * SR)  # the S1 answer ends ~4.0s; its final 300 ms is the fade window
    assert _rms(yb[e - tw:e]) < 0.6 * _rms(ya[e - tw:e]), (
        "the standalone Song-1 answer's tail did not fade — the beat's own lyric still cuts abruptly")
