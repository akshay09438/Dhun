"""Tests for the render engine. These shell out to FFmpeg (as the real pipeline
does), so they build tiny synthetic stems and confirm the finished WAV is valid,
click-free-length-correct, and never clipping. workers/ lives at the repo root, so
we put it on the path before importing.
"""

import sys
import types
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from scipy.signal import butter, sosfilt

_REPO = Path(__file__).resolve().parents[3]  # tests -> api -> services -> repo
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from workers import render  # noqa: E402


def _tone(path, freq=220.0, secs=4.0, amp=0.4, sr=44100):
    t = np.linspace(0, secs, int(sr * secs), endpoint=False)
    sf.write(path, (amp * np.sin(2 * np.pi * freq * t)).astype("float32"), sr)


def _stems(tmp_path):
    paths = {}
    for name, f in (("drums", 110.0), ("bass", 55.0), ("other", 330.0), ("vocals", 660.0)):
        p = tmp_path / f"{name}.wav"
        _tone(p, freq=f, secs=8.0)  # bed long enough to hold placements out to ~6s
        paths[name] = p  # "vocals" here is Song 1's own vocal stem (used for contrast)
    vocal = tmp_path / "vocal.wav"
    _tone(vocal, freq=440.0, secs=8.0)
    return paths, vocal


def _plan(anchor=1.0, stretch=1.0, vocal_src=(0.0, 2.0), beat_breath=False, master_bpm=120.0):
    return types.SimpleNamespace(
        master_bpm=master_bpm, vocal_stretch=stretch, vocal_src=vocal_src,
        anchor=anchor, beat_breath=beat_breath,
    )


def _arr_plan(placements, breath=False):
    """A duck-typed arrangement plan. placements = [(anchor, (start,end), beat_breath), ...]."""
    return types.SimpleNamespace(
        master_bpm=120.0, vocal_stretch=1.0,
        vocal_src=placements[0][1], anchor=placements[0][0], beat_breath=breath,
        placements=[types.SimpleNamespace(anchor=a, vocal_src=v, beat_breath=b)
                    for a, v, b in placements],
    )


def test_render_produces_valid_wav(tmp_path):
    stems, vocal = _stems(tmp_path)
    out = tmp_path / "mix.wav"
    render.render_mix(_plan(anchor=1.0, vocal_src=(0.0, 2.0)), stems, vocal, out)

    y, sr = sf.read(out, dtype="float32", always_2d=True)
    assert sr == render.SR
    assert y.shape[1] == 2  # stereo
    peak = float(np.max(np.abs(y)))
    assert 0.0 < peak <= render._CEILING  # audible, never clipping
    assert len(y) / sr >= 1.0 + 2.0 - 0.05  # bed holds anchor + the ~2s vocal


def test_render_applies_time_stretch(tmp_path):
    stems, vocal = _stems(tmp_path)
    out = tmp_path / "mix.wav"
    # a real (safe) stretch exercises the atempo path without warble
    render.render_mix(_plan(stretch=0.95, vocal_src=(0.0, 2.0)), stems, vocal, out)
    y, _ = sf.read(out, dtype="float32", always_2d=True)
    assert float(np.max(np.abs(y))) <= render._CEILING


def test_render_places_vocal_in_multiple_spots(tmp_path):
    stems, vocal = _stems(tmp_path)
    out = tmp_path / "mix.wav"
    render.render_mix(_arr_plan([(1.0, (0.0, 1.5), False), (4.0, (0.0, 1.5), False)]),
                      stems, vocal, out)
    y, sr = sf.read(out, dtype="float32", always_2d=True)
    e = lambda a, b: float(np.mean(np.abs(y[int(a * sr):int(b * sr)])))
    # both vocal windows carry more energy than the beat-only gap between them
    assert e(1.0, 2.5) > e(2.6, 3.9) and e(4.0, 5.5) > e(2.6, 3.9)


def test_beat_breath_ducks_the_bar_not_silences_it(tmp_path):
    stems, vocal = _stems(tmp_path)
    out = tmp_path / "mix.wav"
    # anchor 2.0s, 120bpm -> one bar = 2.0s; the bar before is DUCKED, not dead air
    render.render_mix(_arr_plan([(2.0, (0.0, 1.0), True)], breath=True), stems, vocal, out)
    y, sr = sf.read(out, dtype="float32", always_2d=True)
    bar_before = float(np.max(np.abs(y[int(0.2 * sr):int(1.9 * sr)])))
    assert bar_before > 1e-3  # NOT dead air (the M3 gap bug stays fixed)


def test_render_mixes_song1_vocal_in_contrast_span(tmp_path):
    stems, vocal = _stems(tmp_path)
    out = tmp_path / "mix.wav"
    plan = _arr_plan([(1.0, (0.0, 1.5), False)])
    plan.s1_vocal_regions = [(4.0, 6.0)]  # Song 1's own vocal answers 4-6s
    render.render_mix(plan, stems, vocal, out)
    y, sr = sf.read(out, dtype="float32", always_2d=True)
    e = lambda a, b: float(np.mean(np.abs(y[int(a * sr):int(b * sr)])))
    # the contrast span carries more energy than the beat-only stretch just before it
    assert e(4.0, 6.0) > e(2.5, 3.9)


def test_render_sweep_opens_up_before_entry(tmp_path):
    stems, vocal = _stems(tmp_path)
    out = tmp_path / "mix.wav"
    plan = _arr_plan([(3.0, (0.0, 1.0), False)])  # 120bpm bar=2s -> sweep over 1.0-3.0s
    plan.placements[0].fx = "sweep_in"
    render.render_mix(plan, stems, vocal, out)
    y, sr = sf.read(out, dtype="float32", always_2d=True)
    hf = lambda a, b: float(np.mean(np.abs(np.diff(y[int(a * sr):int(b * sr)], axis=0))))
    # early part of the swept bar is muffled (low brightness), later part opens up
    assert hf(1.1, 1.6) < hf(2.4, 2.9)


def test_sweep_bed_leading_edge_is_continuous():
    t = np.linspace(0, 400, 4410, endpoint=False)
    mono = (0.5 * np.sin(2 * np.pi * 5 * t)).astype("float32")
    seg = np.stack([mono, mono], axis=1)  # stereo
    out = render._sweep_bed(seg, render.SR)
    assert abs(float(out[0, 0]) - float(seg[0, 0])) < 1e-6  # starts on the original -> no click


def test_guard_duration_caps_over_long_audio(monkeypatch):
    monkeypatch.setattr(render, "_MAX_DECODED_SECS", 1)  # pretend the cap is 1s
    too_long = np.zeros((2 * render.SR, 2), dtype="float32")  # 2s > 1s
    with pytest.raises(render.RenderError):
        render._guard_duration(too_long)


def test_render_rejects_nonpositive_tempo(tmp_path):
    stems, vocal = _stems(tmp_path)
    with pytest.raises(render.RenderError):
        render.render_mix(_plan(master_bpm=0.0), stems, vocal, tmp_path / "x.wav")


def test_render_clamps_negative_anchor(tmp_path):
    stems, vocal = _stems(tmp_path)
    out = tmp_path / "mix.wav"
    render.render_mix(_plan(anchor=-5.0), stems, vocal, out)  # must not crash
    y, _ = sf.read(out, dtype="float32", always_2d=True)
    assert len(y) > 0


def test_build_bed_climbs_muffled_to_open():
    """The produced-drop BUILD: a bed segment goes muffled+quiet -> open+loud across its span,
    so the listener feels the drop coming (recipe: real energy dynamics)."""
    sr = render.SR
    t = np.linspace(0, 1.0, sr, endpoint=False)  # 1s
    mono = (0.4 * np.sin(2 * np.pi * 220 * t)).astype("float32")
    seg = np.stack([mono, mono], axis=1)
    out = render._build_bed(seg, sr)
    assert out.shape == seg.shape
    q = len(out) // 4
    assert float(np.sqrt(np.mean(out[:q] ** 2))) < float(np.sqrt(np.mean(out[-q:] ** 2)))  # louder into the drop
    # and brighter into the drop (the low-pass opens up): more high-freq motion at the end
    hf = lambda a: float(np.mean(np.abs(np.diff(out[a[0]:a[1]], axis=0))))
    assert hf((0, q)) < hf((len(out) - q, len(out)))


def test_echo_throws_only_the_last_segment_not_the_whole_vocal():
    """A real throw echoes only the LAST word(s) so it rings out AFTER the line ends — it must NOT
    stack echoes across the whole vocal (which smears repeats throughout the lyrics)."""
    sr = render.SR
    voc = np.ones((3 * sr, 2), dtype=np.float32) * 0.3  # a 3s vocal at a steady level
    out = render._echo(voc, 120.0)
    # the FIRST part of the line is only the dry vocal — no stacked echoes making it louder
    assert float(np.max(np.abs(out[: int(1.5 * sr)]))) < 0.3 + 0.02
    # ...but the echo rings out AFTER the vocal ends (past 3s)
    assert float(np.max(np.abs(out[3 * sr:]))) > 1e-3


def test_echo_throws_after_each_phrase_into_its_pause():
    """The vocal is 3-4 sung phrases with pauses between; the throw must ring after EACH phrase
    (in its pause), not only once at the very end of the whole slice."""
    sr = render.SR
    voc = np.zeros((4 * sr, 2), dtype=np.float32)
    voc[0 * sr:1 * sr] = 0.4          # phrase 1 (0-1s)
    voc[2 * sr:3 * sr] = 0.4          # phrase 2 (2-3s), a 1s pause between them
    out = render._echo(voc, 120.0)
    peak = lambda a, b: float(np.max(np.abs(out[int(a * sr):int(b * sr)])))
    assert peak(1.1, 1.9) > 1e-3   # an echo rings in the pause AFTER phrase 1
    assert peak(3.1, 3.9) > 1e-3   # ...and after phrase 2 (the tail)


def test_echo_tail_length_stays_bounded():
    """SAFETY: the throw must not ring LONGER than _ECHO_TAPS delays past the vocal — the R1
    echo-tail guard (in plan.py) depends on this bound."""
    sr = render.SR
    voc = np.ones((2 * sr, 2), dtype=np.float32) * 0.3
    out = render._echo(voc, 120.0)
    delay = int((60.0 / 120.0) * render._ECHO_BEATS * sr)
    assert len(out) <= 2 * sr + delay * render._ECHO_TAPS + 2  # bounded to taps*delay past the vocal


def test_echo_adds_a_decaying_tail():
    """The vocal ECHO throw: the vocal rings out with decaying repeats into the drop."""
    sr = render.SR
    voc = np.zeros((int(0.2 * sr), 2), dtype=np.float32)
    voc[: int(0.05 * sr)] = 0.5  # a short burst
    out = render._echo(voc, 120.0)
    assert len(out) > len(voc)  # the echo tail extends the vocal
    tail = out[len(voc):]
    assert float(np.max(np.abs(tail))) > 1e-3  # audible echoes after the dry vocal
    assert float(np.max(np.abs(tail))) < float(np.max(np.abs(voc)))  # ...but quieter (decayed)


def test_render_applies_build_and_echo(tmp_path):
    """Integration: a placement flagged build_bars + echo renders a valid, non-clipping mix
    whose energy climbs into the entry."""
    stems, vocal = _stems(tmp_path)
    out = tmp_path / "mix.wav"
    plan = _arr_plan([(4.0, (0.0, 1.5), False)])
    plan.placements[0].build_bars = 2  # 120bpm bar=2s -> a 4s build into 4.0s
    plan.placements[0].echo = True
    render.render_mix(plan, stems, vocal, out)
    y, sr = sf.read(out, dtype="float32", always_2d=True)
    assert 0.0 < float(np.max(np.abs(y))) <= render._CEILING  # valid, never clipping
    e = lambda a, b: float(np.mean(np.abs(y[int(a * sr):int(b * sr)])))
    assert e(0.3, 1.0) < e(3.0, 3.9)  # the build climbs into the drop


def test_build_does_not_muffle_a_close_previous_vocal(tmp_path):
    """Adversarial-review finding: a 3-bar build must not reach back over a PREVIOUS vocal's tail
    and low-pass/duck it. The build start is clamped to where the previous vocal ended."""
    stems, vocal = _stems(tmp_path)  # 8s tones; the vocal is a 440Hz tone (above the sweep floor)
    out = tmp_path / "mix.wav"
    # placement 1 at 1.0s (vocal 0-2 -> plays 1.0-3.0); placement 2 at 5.0s with a 3-bar build
    # (120bpm bar=2s -> an un-clamped build would start at 0 and swallow placement 1's vocal).
    plan = _arr_plan([(1.0, (0.0, 2.0), False), (5.0, (0.0, 1.0), False)])
    plan.placements[1].build_bars = 3
    render.render_mix(plan, stems, vocal, out)
    y, sr = sf.read(out, dtype="float32", always_2d=True)
    e = lambda a, b: float(np.mean(np.abs(y[int(a * sr):int(b * sr)])))
    # placement 1's vocal tail (2.0-2.9s) stays full & bright; the built beat-only region after it
    # (3.2-4.0s) is muffled+ramped-quiet. Un-clamped, the vocal would sit inside the build and this
    # flips (the later build region would be louder than the muffled vocal).
    assert e(2.0, 2.9) > e(3.2, 4.0)


def test_echo_tail_guard_covers_the_real_echo_tail():
    """GUARDRAIL DRIFT-GUARD: plan._produce_drops suppresses the echo when a Song-1 vocal falls
    within its echo-tail guard; that guard (in beats) must be >= the render's actual echo tail, or
    an echo could ring over a later lead vocal (R1) the referee can't see."""
    from app.planner import plan
    assert plan._ECHO_TAIL_BEATS >= render._ECHO_BEATS * render._ECHO_TAPS


def test_vocal_take_warped_survives_ffmpeg_length_overshoot(monkeypatch):
    """Reproduces the real "Father Ocean x With You" crash: FFmpeg's seek/atempo
    rounding (real MP3 frame-boundary rounding, confirmed on the actual pair) hands
    back each stretched bar a few hundred samples LONGER than its ideal hop +
    crossfade length. The output buffer only ever reserved one crossfade's worth of
    slack at the very end, not per bar, so that overshoot compounded across bars
    until a later write ran past the buffer -> ValueError: could not broadcast.
    `_vocal_take` is faked so the test is hermetic (no real ffmpeg/audio needed) but
    reproduces the exact overshoot-per-bar shape that triggered the real crash.
    """
    # The exact warp (7 bars + one near-zero trailing partial, the vocal's own tail) and
    # per-bar overshoot measured on the real Father Ocean x With You pair. The tiny last
    # bar is what removes the buffer's usual slack: `total` is anchored to the LAST
    # segment's actual (near-zero) length, so there's almost no cushion left to absorb
    # the middle bars' overshoot.
    warp = [(53.73, 55.78, 1.97), (55.78, 57.83, 1.97), (57.83, 59.89, 1.96),
            (59.89, 61.94, 1.97), (61.94, 63.99, 1.97), (63.99, 66.04, 1.97),
            (66.04, 68.09, 1.96), (68.09, 68.1, 0.0097)]
    overshoots = [513, 460, 247, 213, 217, 201, 736]  # measured per bar, one per non-final bar
    calls = {"i": 0}

    def fake_take(src, start, dur, ratio):
        i = calls["i"]
        calls["i"] += 1
        ideal = int(round(dur * render.SR / ratio))
        extra = overshoots[i] if i < len(overshoots) else 0
        return np.zeros((max(ideal + extra, 0), 2), dtype=np.float32)  # ffmpeg overshoot

    monkeypatch.setattr(render, "_vocal_take", fake_take)
    out = render._vocal_take_warped(Path("unused"), warp)
    assert len(out) > 0


# ---------------------------------------------------------------- movable master (bed_stretch)
# When bed_stretch != 1.0 the engine must pre-stretch Song 1's stems (drums, bass, other, and
# Song 1's own vocal) by bed_stretch, so the whole bed lands at the retimed tempo. bed_stretch
# == 1.0 must skip that step entirely and render byte-for-byte as today (the old-mixes proof).


def test_render_bed_stretch_unity_is_byte_identical(tmp_path):
    # B1 (regression guard): bed_stretch == 1.0 must render IDENTICALLY to a plan WITHOUT the field
    # — the "every existing mix renders identically" guarantee. Same shape, within 1e-6. Green now
    # (the engine ignores the field today) and must STAY green after the gated step is added.
    stems, vocal = _stems(tmp_path)
    out_a, out_b = tmp_path / "a.wav", tmp_path / "b.wav"
    render.render_mix(_plan(anchor=1.0, vocal_src=(0.0, 2.0)), stems, vocal, out_a)
    p = _plan(anchor=1.0, vocal_src=(0.0, 2.0))
    p.bed_stretch = 1.0
    render.render_mix(p, stems, vocal, out_b)
    ya, _ = sf.read(out_a, dtype="float32", always_2d=True)
    yb, _ = sf.read(out_b, dtype="float32", always_2d=True)
    assert ya.shape == yb.shape
    assert float(np.max(np.abs(ya - yb))) <= 1e-6


def test_render_bed_stretch_speeds_up_and_shortens_the_bed(tmp_path):
    # B2: a bed_stretch > 1.0 plan must (a) not clip and not be silent, and (b) yield a mix whose
    # length reflects the SHORTER, sped-up bed — Song 1's 8s stems stretched by 1.05 become ~7.62s
    # (atempo duration = input / ratio). Today the engine ignores bed_stretch, so the bed stays 8s
    # and this fails: the duration comes out ~8.0s, outside the ~7.62s window.
    stems, vocal = _stems(tmp_path)  # 8s stems; the placed vocal ends ~3s, so the bed sets the length
    out = tmp_path / "mix.wav"
    p = _plan(anchor=1.0, vocal_src=(0.0, 2.0))
    p.bed_stretch = 1.05
    render.render_mix(p, stems, vocal, out)
    y, sr = sf.read(out, dtype="float32", always_2d=True)
    dur = len(y) / sr
    expected = 8.0 / 1.05  # ~7.619s
    assert expected - 0.15 <= dur <= expected + 0.15, f"bed not sped up: {dur:.3f}s (want ~{expected:.3f}s)"
    peak = float(np.max(np.abs(y)))
    assert 0.0 < peak <= render._CEILING  # audible, never clipping


def test_render_has_a_pitch_preserving_file_stretch_helper(tmp_path):
    # B3: there must be a helper that time-stretches a whole audio FILE by a ratio (pitch-preserved),
    # scaling its duration by 1/ratio (atempo semantics, matching B2 and the design) — a 4s clip at
    # ratio 1.05 becomes ~3.81s. The implementer names it; we probe the plausible names the design
    # implies (an atempo pass over a stem file) and both plausible signatures.
    #
    # ASSUMPTION (flagged): the helper is one of _CANDIDATES below and takes (src, ratio) -> path|array
    # or (src, ratio, out_path). If the implementer picks another name/shape, extend this list — the
    # asserted CONTRACT (duration scales by 1/ratio, pitch preserved via atempo) is what must hold.
    src = tmp_path / "in.wav"
    _tone(src, freq=220.0, secs=4.0)
    candidates = ["_stretch_file", "_atempo_file", "_stretch_stem", "_prestretch_stem",
                  "_prestretch", "_stretch_bed", "_time_stretch_file", "_atempo", "_bed_stretch"]
    fn = next((getattr(render, n) for n in candidates if hasattr(render, n)), None)
    assert fn is not None, f"no file-stretch helper found on render among {candidates}"
    try:
        result = fn(src, 1.05)
    except TypeError:
        outp = tmp_path / "stretched.wav"
        result = fn(src, 1.05, outp) or outp
    if isinstance(result, (str, Path)):
        y, sr = sf.read(str(result), dtype="float32", always_2d=True)
        dur = len(y) / sr
    else:
        dur = len(np.asarray(result)) / render.SR
    assert 4.0 / 1.05 - 0.1 <= dur <= 4.0 / 1.05 + 0.1  # ~3.81s (duration = input / ratio)


def test_render_tiny_bed_stretch_still_engages(tmp_path):
    """ADVERSARIAL-REVIEW REGRESSION (F1): a bed_stretch in the tiny gap band (1e-4 .. 1e-3) must
    STILL stretch the bed — the engine engages on the same 1e-6 threshold the planner/referee use.
    An earlier draft gated the engine at 1e-3, which would leave the bed un-stretched while the plan
    and referee assumed the retimed grid → an off-beat mix the referee couldn't see. A 1.0005 bed
    must render measurably SHORTER than a 1.0 bed (it was atempo'd), proving the gate is closed."""
    stems, vocal = _stems(tmp_path)  # 8s stems set the length
    native, tiny = tmp_path / "native.wav", tmp_path / "tiny.wav"
    p0 = _plan(anchor=1.0, vocal_src=(0.0, 2.0)); p0.bed_stretch = 1.0
    p1 = _plan(anchor=1.0, vocal_src=(0.0, 2.0)); p1.bed_stretch = 1.0005
    render.render_mix(p0, stems, vocal, native)
    render.render_mix(p1, stems, vocal, tiny)
    n = len(sf.read(native, dtype="float32", always_2d=True)[0])
    t = len(sf.read(tiny, dtype="float32", always_2d=True)[0])
    assert n - t > 50, f"tiny bed_stretch did not engage: native {n} vs stretched {t} samples"


# ---------------------------------------------------------------- Step 3: stem dynamics (the mixing board)
# The engine gains per-stem gain envelopes so the arrangement can RIDE one of Song 1's bed stems'
# volume across an on-beat window (Wave 1 = the bass pull-and-slam: bass ramps 1.0 -> 0.0 into the
# drop, then slams back to 1.0 on the downbeat). Contract agreed with the implementer:
#   - render_mix reads plan.stem_moves (default [] when the attr is absent — duck-typed plans render).
#   - each StemMove has .stem / .start / .end / .gain_from / .gain_to.
#   - a short declick ramp (render._STEM_SLAM_MS ~8ms) keeps the 0->1 slam click-free.
# A no-move plan must render exactly today's mix (the "old mixes still work" invariant).


def _stem_move(stem, start, end, gain_from=1.0, gain_to=0.0):
    """A duck-typed StemMove for a duck-typed plan (matches the real StemMove field names)."""
    return types.SimpleNamespace(stem=stem, start=start, end=end,
                                 gain_from=gain_from, gain_to=gain_to)


def _lowband(y, sr, hz=70.0):
    """Isolate the 55Hz bass stem: an 8th-order low-pass at 70Hz leaves 110Hz drums ~-30dB down and
    kills 330/440/660Hz entirely, so low-band RMS tracks the bass envelope alone."""
    sos = butter(8, hz / (sr / 2), btype="low", output="sos")
    return sosfilt(sos, y, axis=0)


def test_bass_pull_and_slam_dips_then_returns(tmp_path):
    """AC1: with a bass StemMove 1.0->0.0 over a window into the drop, the BASS-BAND energy FALLS
    across the window and RETURNS after the anchor (the slam). Fails today: the engine ignores
    stem_moves, so the bass plays flat throughout and the band never dips."""
    stems, vocal = _stems(tmp_path)  # 8s tones; bass = 55Hz
    out = tmp_path / "mix.wav"
    plan = _arr_plan([(1.0, (0.0, 0.5), False)])  # a short vocal early, clear of the bass window
    plan.stem_moves = [_stem_move("bass", start=4.0, end=6.0, gain_from=1.0, gain_to=0.0)]
    render.render_mix(plan, stems, vocal, out)
    y, sr = sf.read(out, dtype="float32", always_2d=True)
    low = _lowband(y, sr)
    lf = lambda a, b: float(np.sqrt(np.mean(low[int(a * sr):int(b * sr)] ** 2)))
    early = lf(4.05, 4.55)  # bass near full at the window start
    late = lf(5.40, 5.90)   # bass ramped ~to 0 just before the drop
    after = lf(6.10, 6.60)  # slam: bass back to full
    assert late < 0.5 * early, f"bass did not fall across the build: early={early:.4f} late={late:.4f}"
    assert after > 2.0 * late, f"bass did not slam back after the drop: late={late:.4f} after={after:.4f}"
    peak = float(np.max(np.abs(y)))
    assert 0.0 < peak <= render._CEILING  # audible, never clipping


def test_bass_slam_is_click_free(tmp_path):
    """AC2: the 0->1 slam does not click — the largest sample step across the slam boundary is not a
    spike vs the signal's typical step. It first asserts the slam actually happened (low-band energy
    jumps up on the downbeat), so this FAILS today for the right reason (no slam at all), and after
    the feature lands it fails ONLY if the declick ramp is missing."""
    stems, vocal = _stems(tmp_path)
    out = tmp_path / "mix.wav"
    plan = _arr_plan([(1.0, (0.0, 0.5), False)])
    plan.stem_moves = [_stem_move("bass", 4.0, 6.0, 1.0, 0.0)]
    render.render_mix(plan, stems, vocal, out)
    y, sr = sf.read(out, dtype="float32", always_2d=True)
    low = _lowband(y, sr)
    lf = lambda a, b: float(np.sqrt(np.mean(low[int(a * sr):int(b * sr)] ** 2)))
    assert lf(6.02, 6.30) > 2.0 * lf(5.60, 5.95), "no slam: bass did not jump back on the downbeat"
    d = np.abs(np.diff(y, axis=0))
    w = int(0.005 * sr)  # +-5ms around the slam
    slam = int(6.0 * sr)
    near = float(np.max(d[slam - w:slam + w]))
    typical = float(np.max(d[int(6.5 * sr):int(7.5 * sr)]))  # a steady full-bed stretch after the slam
    assert near <= 2.0 * typical, f"click at the slam: step {near:.4f} vs typical {typical:.4f}"


# --- Old-mix invariant (the "old mixes still work" proof) ---
# Proven two ways below: (1) a no-move plan is a no-op vs a plan with no stem_moves field at all, and
# (2) the bed treatments are LINEAR, so applying them per-stem and summing last is identical to
# filtering the summed bed. (During the build a no-move render was ALSO confirmed byte-identical to
# the pre-change engine; that one-time check needs no committed audio — the repo keeps no *.wav in
# git — so it lives in the change's review notes, not as a fixture here. The whole existing no-move
# render suite above is the ongoing behavioural regression guard.)


def test_no_stem_moves_is_a_noop_vs_absent_field(tmp_path):
    """AC4: stem_moves == [] renders IDENTICALLY to a plan with no stem_moves attribute at all — proving
    the engine's default-[] duck-typing is a true no-op. Passes now (engine ignores the field) and must
    STAY green after the change (guards the `getattr(plan, 'stem_moves', [])` contract)."""
    stems, vocal = _stems(tmp_path)
    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    p_absent = _arr_plan([(1.0, (0.0, 1.5), False)])  # no stem_moves attribute set
    render.render_mix(p_absent, stems, vocal, a)
    p_empty = _arr_plan([(1.0, (0.0, 1.5), False)])
    p_empty.stem_moves = []
    render.render_mix(p_empty, stems, vocal, b)
    ya, _ = sf.read(a, dtype="float32", always_2d=True)
    yb, _ = sf.read(b, dtype="float32", always_2d=True)
    assert ya.shape == yb.shape
    assert float(np.max(np.abs(ya - yb))) <= 1e-6


def test_build_bed_is_linear_sum_then_filter_equals_filter_then_sum():
    """AC3 (the WHY): the old-mix invariant holds by construction because the bed treatments are LINEAR
    — summing the stems then filtering == filtering each stem then summing. Proven directly on the
    build helper: _build_bed(a) + _build_bed(b) ~= _build_bed(a + b). (Exercises existing behaviour, so
    it passes today; it is the math the per-stem refactor relies on and must keep true.)"""
    rng = np.random.default_rng(0)
    n = render.SR // 8
    a = (0.3 * rng.standard_normal((n, 2))).astype("float32")
    b = (0.3 * rng.standard_normal((n, 2))).astype("float32")
    lhs = render._build_bed(a, render.SR) + render._build_bed(b, render.SR)
    rhs = render._build_bed((a + b).astype("float32"), render.SR)
    assert float(np.max(np.abs(lhs - rhs))) <= 1e-3


def test_sweep_bed_is_linear_sum_then_filter_equals_filter_then_sum():
    """AC3 (the WHY, cont.): same linearity for the filter sweep — _sweep_bed(a) + _sweep_bed(b) ~=
    _sweep_bed(a + b). Together with the build linearity, this is why moving the treatments onto the
    separate stems cannot change a no-move mix."""
    rng = np.random.default_rng(1)
    n = render.SR // 8
    a = (0.3 * rng.standard_normal((n, 2))).astype("float32")
    b = (0.3 * rng.standard_normal((n, 2))).astype("float32")
    lhs = render._sweep_bed(a, render.SR) + render._sweep_bed(b, render.SR)
    rhs = render._sweep_bed((a + b).astype("float32"), render.SR)
    assert float(np.max(np.abs(lhs - rhs))) <= 1e-3


def test_prior_vocal_tail_is_ducked_by_a_later_breath(tmp_path):
    """OLD-MIX IDENTITY (adversarial-review regression, Reviewer 1): a later beat_breath ducks the BED
    for its bar — and, exactly as the pre-Step-3 engine did, that duck also lands on a PRIOR vocal's
    tail sitting in that bar. An earlier Step-3 draft deferred all vocal placement until AFTER the bed
    treatments, so the tail escaped the duck and old mixes rendered differently. This asserts the tail
    IS still ducked, so that identity regression can't come back."""
    stems, vocal = _stems(tmp_path)  # vocal tone = 440Hz; bed = 110/55/330Hz
    out = tmp_path / "mix.wav"
    # placement 1 sings 1.0-5.0 (a 4s vocal); placement 2 enters at 6.0 with a breath bar [4.0,6.0]
    # (120bpm bar=2s), so placement 1's tail (4.0-5.0) sits inside placement 2's breath duck.
    plan = _arr_plan([(1.0, (0.0, 4.0), False), (6.0, (0.0, 1.0), True)])
    render.render_mix(plan, stems, vocal, out)
    y, sr = sf.read(out, dtype="float32", always_2d=True)
    sos = butter(4, [400 / (sr / 2), 490 / (sr / 2)], btype="band", output="sos")  # isolate the 440Hz vocal
    voc = sosfilt(sos, y, axis=0)
    vf = lambda a, b: float(np.sqrt(np.mean(voc[int(a * sr):int(b * sr)] ** 2)))
    ducked = vf(4.2, 4.8)   # vocal tail INSIDE the breath bar -> must be pulled down
    full = vf(2.2, 2.8)     # the same vocal, before the breath bar -> full level
    assert ducked < 0.6 * full, f"prior vocal tail not ducked by the breath: {ducked:.4f} vs full {full:.4f}"


# ---------------------------------------------------------------- Step 4: vocal chop (chop on the drop)
# _chop_pattern(voc, out_len, bpm) fills out_len samples with the vocal's first _CHOP_SECS onset,
# edge-faded, re-fired every _CHOP_INTERVAL_BEATS (an 8th note) on Song 1's grid -- "dum-da-ra-dum".
# The call site replaces only the placement's FIRST BAR: k = min(bar, len(voc)); voc[:k] =
# _chop_pattern(voc[:k], k, master_bpm). So len(voc) -- and thus placement_end and the referee's R1
# overlap math -- must be UNCHANGED. These tests were written independently of the implementation,
# from the acceptance criteria, to catch a length change, a clip, or a lost rhythmic pattern.


def _voc_tone(n, freq=440.0, amp=0.4):
    """A stereo float32 tone of n samples (for direct _chop_pattern unit tests, no ffmpeg)."""
    t = np.linspace(0, n / render.SR, n, endpoint=False)
    m = (amp * np.sin(2 * np.pi * freq * t)).astype("float32")
    return np.stack([m, m], axis=1)


def _onsets(y, thresh_frac=0.3):
    """Count rhythmic onsets: rising edges of a smoothed abs-envelope through thresh_frac of its peak.
    A continuous tone gives 1 (one rise); a re-fired chop gives one per hit (bursts split by silence)."""
    mono = np.abs(y).mean(axis=1) if y.ndim == 2 else np.abs(y)
    win = max(1, int(0.005 * render.SR))
    env = np.convolve(mono, np.ones(win, dtype="float32") / win, mode="same")
    peak = float(env.max()) if env.size else 0.0
    if peak <= 0:
        return 0
    voiced = env > thresh_frac * peak
    return int(np.sum((~voiced[:-1]) & voiced[1:])) + (1 if voiced[0] else 0)


def test_chop_pattern_returns_exactly_out_len_across_range():
    """AC1 (load-bearing): _chop_pattern must return EXACTLY out_len samples for any out_len/bpm, so
    replacing bar 1 never changes the vocal's length -> placement_end and the referee's overlap math
    are untouched. Would fail the instant the helper returned a different length. Vocal is always at
    least out_len long here, exactly as the call site guarantees (out_len == len(voc[:k]) == k)."""
    for out_len in (1, 500, 44100, 88200, 132300):
        v = _voc_tone(max(out_len, 90000))  # voc >= out_len, the call-site shape
        for bpm in (60.0, 90.0, 120.0, 174.0):
            r = render._chop_pattern(v, out_len, bpm)
            assert r.shape == (out_len, 2), f"out_len={out_len} bpm={bpm} -> {r.shape}, want ({out_len}, 2)"


def test_render_chop_does_not_change_placement_length(tmp_path):
    """AC1 at the render level: a plan WITH a chop placement renders to the EXACT same total length as
    the same plan WITHOUT the chop. If the chop ever grew/shrank the vocal, placement_end would move
    and the referee's overlap math would be wrong -- this catches that regression."""
    stems, vocal = _stems(tmp_path)
    a, b = tmp_path / "nochop.wav", tmp_path / "chop.wav"
    p_plain = _arr_plan([(1.0, (0.0, 2.0), False)])  # 120bpm bar = 2.0s; the 2.0s vocal fills bar 1
    render.render_mix(p_plain, stems, vocal, a)
    p_chop = _arr_plan([(1.0, (0.0, 2.0), False)])
    p_chop.placements[0].chop = True
    render.render_mix(p_chop, stems, vocal, b)
    ya, _ = sf.read(a, dtype="float32", always_2d=True)
    yb, _ = sf.read(b, dtype="float32", always_2d=True)
    assert len(ya) == len(yb), f"chop changed the render length: {len(ya)} vs {len(yb)} samples"


def test_chop_absent_field_is_byte_identical_to_chop_false(tmp_path):
    """AC2 (old mixes still work): a plan with no `chop` attribute renders byte-for-byte identically to
    a plan with chop=False -- proving `getattr(p, 'chop', False)` is a true no-op and existing mixes are
    untouched. Same shape, max sample diff exactly 0.0."""
    stems, vocal = _stems(tmp_path)
    a, b = tmp_path / "absent.wav", tmp_path / "false.wav"
    p_absent = _arr_plan([(1.0, (0.0, 2.0), False)])  # no chop attribute at all
    render.render_mix(p_absent, stems, vocal, a)
    p_false = _arr_plan([(1.0, (0.0, 2.0), False)])
    p_false.placements[0].chop = False
    render.render_mix(p_false, stems, vocal, b)
    ya, _ = sf.read(a, dtype="float32", always_2d=True)
    yb, _ = sf.read(b, dtype="float32", always_2d=True)
    assert ya.shape == yb.shape
    assert float(np.max(np.abs(ya - yb))) == 0.0, "chop=False / absent must be byte-identical"


def test_chop_pattern_fires_multiple_rhythmic_onsets():
    """AC3: the chopped bar carries the rhythmic 're-fire' -- multiple distinct onsets ('dum-da-ra-dum'),
    strictly more than the un-chopped (continuous) bar. Detected by counting rising envelope edges. The
    fragment (0.22s) is shorter than the 8th-note step (0.25s @120bpm), so hits are split by silence and
    are individually detectable."""
    bar = int((60.0 / 120.0) * 4 * render.SR)          # one bar @120bpm
    step = max(1, int((60.0 / 120.0) * render._CHOP_INTERVAL_BEATS * render.SR))
    expected_hits = len(range(0, bar, step))            # 8 eighth-notes in a 4/4 bar
    v = _voc_tone(bar)
    chopped = render._chop_pattern(v, bar, 120.0)
    n_chop = _onsets(chopped)
    n_plain = _onsets(v[:bar])
    assert n_chop >= 2, f"chopped bar is not rhythmic: only {n_chop} onset(s)"
    assert n_chop > n_plain, f"chop added no rhythm: chopped={n_chop} vs un-chopped={n_plain}"
    assert n_chop >= expected_hits - 1, f"chop lost hits: {n_chop} onsets, expected ~{expected_hits}"


def test_render_chop_does_not_clip(tmp_path):
    """AC4: the full render with a chop placement stays inside [-1, 1] -- the downstream peak-normalize +
    clip guard holds even with the re-fired onset stacking. Audible and never clipping."""
    stems, vocal = _stems(tmp_path)
    out = tmp_path / "mix.wav"
    p = _arr_plan([(1.0, (0.0, 2.0), False)])
    p.placements[0].chop = True
    render.render_mix(p, stems, vocal, out)
    y, _ = sf.read(out, dtype="float32", always_2d=True)
    peak = float(np.max(np.abs(y)))
    assert 0.0 < peak <= render._CEILING, f"chop render clipped or went silent: peak={peak:.4f}"


def test_chop_pattern_edge_cases_are_graceful_and_keep_length():
    """AC5: _chop_pattern must never crash and must keep the length invariant on degenerate inputs. Each
    case mirrors the call site, where out_len == len(voc[:k]) (out_len never exceeds the vocal), so the
    'exactly out_len' invariant is the one the engine actually relies on. See the separate shortfall test
    for the one input shape where the no-op branch returns fewer than out_len."""
    cases = [
        ("empty vocal", np.zeros((0, 2), dtype="float32"), 100, 120.0),      # len(voc)=0 -> zeros(out_len)
        ("1-sample vocal", _voc_tone(1), 1, 120.0),                          # call-site k=1
        ("1-sample, longer bar", _voc_tone(1), 100, 120.0),                  # fires the 1-sample frag
        ("bpm = 0", _voc_tone(200), 200, 0.0),                               # no tempo -> no-op, voc>=out_len
        ("bpm < 0", _voc_tone(200), 200, -120.0),                            # negative tempo -> no-op
        ("out_len = 0", _voc_tone(200), 0, 120.0),                           # empty bar -> zeros(0)
        ("voc shorter than one hit", _voc_tone(1000), 1000, 120.0),          # frag < _CHOP_SECS*SR
        ("voc shorter than one bar", _voc_tone(500), 500, 120.0),            # k = len(voc) < bar
    ]
    for name, v, out_len, bpm in cases:
        r = render._chop_pattern(v, out_len, bpm)
        assert r.ndim == 2 and r.shape[1] == 2, f"{name}: not stereo -> {r.shape}"
        assert len(r) == out_len, f"{name}: length {len(r)} != out_len {out_len}"
        assert np.isfinite(r).all(), f"{name}: produced non-finite samples"


def test_chop_pattern_noop_shortfall_when_out_len_exceeds_voc():
    """AC5 (documented discrepancy, flagged): the docstring promises 'Returns exactly out_len samples',
    but the graceful no-op branch returns `voc[:out_len]`, which is SHORTER than out_len when the vocal
    is shorter than out_len AND there's no tempo (bpm <= 0). This pins that current behaviour so it is
    visible, not silent. It is not reachable through render_mix today (render rejects bpm <= 0 up front,
    and the call site always passes out_len == len(voc)), but a future caller that passes out_len >
    len(voc) with bpm <= 0 would get a short buffer and silently move placement_end. Reported as a gap."""
    v = _voc_tone(50)          # 50 samples of vocal
    out_len = 100              # ask for more than the vocal has
    r = render._chop_pattern(v, out_len, 0.0)  # bpm <= 0 -> the no-op branch
    # Current (buggy) behaviour: returns len(voc), NOT out_len. If a fix ever makes this return out_len,
    # this assertion flips red on purpose -- delete it and remove the shortfall note from the docstring.
    assert len(r) == len(v) < out_len, (
        f"no-op branch length changed: got {len(r)} (was {len(v)}, out_len {out_len})")
