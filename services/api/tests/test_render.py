"""Tests for the render engine. These shell out to FFmpeg (as the real pipeline
does), so they build tiny synthetic stems and confirm the finished WAV is valid,
click-free-length-correct, and never clipping. workers/ lives at the repo root, so
we put it on the path before importing.
"""

import hashlib
import subprocess
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


# ---------------------------------------------------------------- Phase 0: the vocal chain, DISABLED
# GOLDEN-FILE GATE (written FIRST, against main, before the chain exists). With the vocal chain OFF
# (plan.vocal_moves == [] and plan.duck_moves == []), render_mix must produce a BYTE-IDENTICAL result
# to the pre-chain m6.0 engine. The hash below is captured on main; after the chain lands it MUST still
# match. This is what makes the tuning week's A/B honest: any difference heard is the chain, not an
# incidental change in the signal path. We hash the decoded SAMPLES (not the file) so WAV-header
# metadata can't cause a spurious mismatch.

# Captured on main (pre-chain). If this test fails after the chain lands, the enabled=False path is
# NOT byte-identical — a real regression, do not "update" the hash to make it pass.
_GOLDEN_ENABLED_FALSE = "0483b03e1214bad0e5175bd4962c772e84b780f53cf0062324b7da2ef928d475"


def _golden_plan():
    """A deterministic, feature-rich plan exercising the main render paths (two placements, a
    beat-breath, a produced build+echo, a bass stem-move, a Song-1 contrast region) — so any
    accidental change to the enabled=False path shifts the hash."""
    p = _arr_plan([(1.0, (0.0, 2.0), False), (5.0, (0.0, 1.5), True)])
    p.placements[1].build_bars = 2
    p.placements[1].echo = True
    p.stem_moves = [_stem_move("bass", 3.0, 5.0, 1.0, 0.0)]
    p.s1_vocal_regions = [(3.2, 4.8)]
    return p


def _golden_hash(tmp_path):
    stems, vocal = _stems(tmp_path)
    out = tmp_path / "golden.wav"
    render.render_mix(_golden_plan(), stems, vocal, out)
    y, _ = sf.read(out, dtype="float32", always_2d=True)
    return hashlib.sha256(y.tobytes()).hexdigest()


def test_golden_render_is_deterministic(tmp_path):
    """The golden render must be bit-stable run-to-run (FFmpeg decode/stretch is deterministic on a
    fixed build), or the byte-identity gate below would be meaningless."""
    da, db = tmp_path / "a", tmp_path / "b"
    da.mkdir()
    db.mkdir()
    assert _golden_hash(da) == _golden_hash(db), (
        "golden render is not deterministic run-to-run — the byte-identity gate can't hold")


def test_golden_enabled_false_is_byte_identical_to_m6_0(tmp_path):
    """THE GATE: with the vocal chain disabled, the render is byte-identical to the captured m6.0
    baseline. Fails loudly if the chain code ever alters the enabled=False path."""
    h = _golden_hash(tmp_path)
    assert h == _GOLDEN_ENABLED_FALSE, (
        f"enabled=False render changed vs m6.0 baseline!\n  got:      {h}\n  expected: {_GOLDEN_ENABLED_FALSE}")


def _has_rubberband():
    """rubberband is FFmpeg's GPL `librubberband` filter. The commercial build MUST stay LGPL (see
    CLAUDE.md), which does NOT link it — so the pitch tests skip rather than hard-require a GPL build.
    The pitch STAGE ships inert in Phase 0 (the planner pins pitch_semitones to 0), so nothing in the
    live pipeline depends on it; the licensing decision is owed before Slice 2d turns pitch on."""
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True, timeout=30)
        return "rubberband" in out.stdout
    except Exception:
        return False


_HAS_RUBBERBAND = _has_rubberband()
_needs_rubberband = pytest.mark.skipif(not _HAS_RUBBERBAND, reason="rubberband (GPL) not linked in this FFmpeg")


def _vm(pid="p0", **k):
    """A duck-typed VocalProcessMove (neutral dials by default -> a no-op stage set)."""
    d = dict(placement_id=pid, start_bar=0, end_bar=4, pitch_semitones=0.0, deess=0.0,
             highpass_hz=0, compress_ratio=1.0, saturate_wet=0.0, presence_gain_db=0.0, reverb_wet=0.0)
    d.update(k)
    return types.SimpleNamespace(**d)


def test_saturate_is_a_bounded_soft_clip():
    x = np.linspace(-1.0, 1.0, 2000, dtype=np.float32).reshape(-1, 2)
    out = render._saturate(x, drive=2.0, wet=0.4)
    assert np.all(np.abs(out) <= 1.0 + 1e-6)          # tanh soft-clip stays bounded
    assert float(np.max(np.abs(out - x))) > 1e-3      # ...and it actually changed the signal


def test_saturate_wet_is_hard_capped_at_half():
    x = np.full((100, 2), 0.5, dtype=np.float32)
    assert np.allclose(render._saturate(x, 2.0, 0.9), render._saturate(x, 2.0, 0.5))  # 0.9 clamped to 0.5


def test_reverb_ir_is_deterministic():
    a, b = render._reverb_ir(render.SR), render._reverb_ir(render.SR)
    assert np.array_equal(a, b)                       # fixed seed -> identical IR every call (golden-safe)


def test_reverb_is_length_preserving_and_wet():
    voc = _voc_tone(render.SR)                         # 1s
    out = render._reverb(voc, wet=0.3, sr=render.SR)
    assert out.shape == voc.shape                      # tail truncated to dry length -> length unchanged
    assert float(np.max(np.abs(out - voc))) > 1e-4     # the wet path changed it


@_needs_rubberband
def test_pitch_shift_preserves_length_and_raises_pitch():
    voc = _voc_tone(render.SR, freq=300.0)
    out = render._pitch_shift(voc, semitones=4.0, sr=render.SR)
    assert out.shape == voc.shape                       # pitch-only -> length preserved
    fdom = lambda y: float(np.fft.rfftfreq(len(y), 1 / render.SR)[np.argmax(np.abs(np.fft.rfft(y[:, 0])))])
    assert fdom(out) > fdom(voc) + 10                   # dominant frequency moved up


@_needs_rubberband
def test_pitch_shift_uses_formant_preserved_and_quality(monkeypatch):
    """DoD: formant=preserved and pitchq=quality must be EXPLICIT in every rubberband invocation
    (the default formant is `shifted` — the chipmunk mode)."""
    seen = []
    real = render._run_ffmpeg
    monkeypatch.setattr(render, "_run_ffmpeg", lambda cmd: (seen.append(" ".join(cmd)), real(cmd))[1])
    render._pitch_shift(_voc_tone(render.SR // 2), 2.0, render.SR)
    joined = " ".join(seen)
    assert "rubberband=pitch=" in joined
    assert "formant=preserved" in joined and "pitchq=quality" in joined


def test_apply_vocal_chain_is_length_preserving():
    voc = _voc_tone(render.SR)
    out = render._apply_vocal_chain(
        voc, _vm(deess=0.4, highpass_hz=90, compress_ratio=3.0, saturate_wet=0.25,
                 presence_gain_db=2.5, reverb_wet=0.12), render.SR)
    assert out.shape == voc.shape                       # the whole chain never changes the vocal's length


def test_enabled_chain_changes_the_render_but_not_its_length(tmp_path):
    stems, vocal = _stems(tmp_path)
    plain, chained = tmp_path / "plain.wav", tmp_path / "chain.wav"
    render.render_mix(_arr_plan([(1.0, (0.0, 2.0), False)]), stems, vocal, plain)
    p = _arr_plan([(1.0, (0.0, 2.0), False)])
    p.vocal_moves = [_vm(highpass_hz=90, compress_ratio=3.0, saturate_wet=0.4, presence_gain_db=3.0)]
    render.render_mix(p, stems, vocal, chained)
    ya, _ = sf.read(plain, dtype="float32", always_2d=True)
    yb, _ = sf.read(chained, dtype="float32", always_2d=True)
    assert ya.shape == yb.shape                          # length preserved -> placement_end unchanged
    assert float(np.max(np.abs(ya - yb))) > 1e-3         # ...but the chain audibly processed the vocal


def test_p2_pre_master_ceiling_rejects_overhot_chain(tmp_path):
    """Referee P2 (render-side): a chain that inflates the vocal's peak by more than +3 dB before the
    master is rejected loudly (over-processing), not silently normalized into mush. (P2 is a relative
    peak-gain guard, not the brief's literal -3 dBFS absolute ceiling — see the render.py flag.)"""
    stems, vocal = _stems(tmp_path)
    _tone(vocal, freq=3000.0, amp=0.9, secs=8.0)         # a loud tone right in the presence band
    p = _arr_plan([(1.0, (0.0, 2.0), False)])
    p.vocal_moves = [_vm(presence_gain_db=6.0)]           # +6 dB at 3 kHz -> ~1.8 peak, well over -3 dBFS
    with pytest.raises(render.RenderError):
        render.render_mix(p, stems, vocal, tmp_path / "x.wav")


def test_duck_bed_only_ducks_never_boosts():
    sr = render.SR
    bed = np.full((sr, 2), 0.5, dtype=np.float32)
    voc = np.zeros((sr, 2), dtype=np.float32)
    voc[: sr // 2] = 0.8                                  # the vocal is present only in the first half
    prepared = [(types.SimpleNamespace(anchor=0.0), voc)]
    dm = [types.SimpleNamespace(target_stems=["drums", "bass", "other"], key_placement_id="p0",
                                depth_db=6.0, attack_ms=1, release_ms=1)]
    out = render._duck_bed(bed, dm, prepared, sr)
    assert out.shape == bed.shape
    assert np.all(np.abs(out) <= np.abs(bed) + 1e-6)     # ONLY ducks — never boosts (P4 by construction)
    assert float(np.mean(np.abs(out[: sr // 4]))) < 0.95 * float(np.mean(np.abs(bed[: sr // 4])))  # ducked under the vocal
    assert float(np.mean(np.abs(out[-sr // 4:]))) > 0.99 * 0.5  # bed restored where the vocal is absent


def test_reverb_is_peak_neutral_across_signals():
    """Step 2: the IR is L2-normalized ONCE at generation, so convolution is peak-neutral as a FIXED
    property (no per-render normalization) — the +7 dB peak-inflation bug is gone, for ANY input. This
    is what makes reverb_wet song-independent."""
    for freq in (150.0, 1000.0, 4000.0):
        sig = _voc_tone(render.SR, freq=freq, amp=0.6)
        out = render._reverb(sig, 0.12, render.SR)
        peak_gain = float(np.max(np.abs(out))) / float(np.max(np.abs(sig)))
        assert peak_gain < 1.2, f"reverb inflated the peak ({freq} Hz): x{peak_gain:.2f}"


def test_duck_envelope_is_smoothed_not_stepped():
    """Step 5: stage 9's duck must ramp (a smoothed envelope), never a hard gain step at the vocal
    onset — a step on a downbeat clicks, and a click survives the master's peak-normalize + clip
    completely untouched. On a constant bed, any sample-to-sample jump IS the duck envelope, so a
    smooth ramp gives a tiny max jump; a hard step would give ~0.15."""
    sr = render.SR
    bed = np.full((3 * sr, 2), 0.3, dtype=np.float32)     # constant bed -> any jump is the duck
    voc = np.zeros((3 * sr, 2), dtype=np.float32)
    voc[sr:2 * sr] = 0.8                                    # vocal present 1-2s, HARD raw edges
    prepared = [(types.SimpleNamespace(anchor=0.0), voc)]
    dm = [types.SimpleNamespace(target_stems=["drums", "bass", "other"], key_placement_id="p0",
                                depth_db=6.0, attack_ms=5, release_ms=120)]
    out = render._duck_bed(bed, dm, prepared, sr)
    max_jump = float(np.max(np.abs(np.diff(out[:, 0]))))
    assert max_jump < 0.01, f"duck has a hard step (click risk): max sample jump {max_jump:.4f}"
    # ...and it genuinely ducked (the middle is pulled below the 0.3 bed)
    assert float(np.mean(np.abs(out[int(1.4 * sr):int(1.6 * sr)]))) < 0.28


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


# ---------------------------------------------------------------- good-parts window (plan.window crop)
# MixPlan.window (models.py) is a tuple[float,float] | None already carried by the plan (the planner's
# good-parts picker already sets it — app/planner/window.py, app/planner/plan.py:409) but render_mix
# never reads it: today the bed always decodes and plays Song 1's stems in full, regardless of window.
# These tests were written independently of the implementation, from the acceptance criteria: when
# plan.window=(win_start, win_end) is set, the rendered WAV must be built only from that span of Song
# 1's stems (~the window length, not the full track); plan.window=None must stay exactly today's full
# track render (the "old mixes still work" invariant).


def _long_stems(tmp_path, secs=120.0):
    """Same shape as _stems() but a realistic full-track length -- plan.window cropping only bites on
    tracks longer than the crop window, so the 8s tones the other render tests use can't exercise it."""
    paths = {}
    for name, f in (("drums", 110.0), ("bass", 55.0), ("other", 330.0), ("vocals", 660.0)):
        p = tmp_path / f"{name}.wav"
        _tone(p, freq=f, secs=secs)
        paths[name] = p
    vocal = tmp_path / "vocal.wav"
    _tone(vocal, freq=440.0, secs=8.0)  # Song 2's vocal source; short is fine, it is never cropped
    return paths, vocal


def test_render_window_crops_output_to_window_length(tmp_path):
    """AC1: plan.window=(30.0, 120.0) on a 120s track must crop the render to ~ the 90s window (allow
    ring-out slack, 88-96s) -- and be clearly shorter than the untouched 120s track. Fails today because
    render_mix never reads plan.window at all (the bed decodes and plays the FULL track regardless), so
    dur comes out ~120s, well outside the 88-96s band."""
    stems, vocal = _long_stems(tmp_path, secs=120.0)
    out = tmp_path / "mix.wav"
    plan = _plan(anchor=1.0, vocal_src=(0.0, 1.0))  # a short vocal near the window start; no placements
    plan.window = (30.0, 120.0)  # a 90s window
    render.render_mix(plan, stems, vocal, out)
    y, sr = sf.read(out, dtype="float32", always_2d=True)
    dur = len(y) / sr
    assert 88.0 <= dur <= 96.0, f"window did not crop the render: dur={dur:.2f}s (want ~90s, 88-96s)"
    assert dur < 110.0, f"render is not clearly shorter than the full 120s track: dur={dur:.2f}s"


def test_render_no_window_is_unchanged_full_length(tmp_path):
    """AC2 (the safety invariant): plan.window=None (the default) must render the FULL track, unaffected
    by the new crop path -- existing mixes must stay exactly as long as today. Passes now (the engine
    already ignores window) and must STAY green once the crop is gated on window being set."""
    stems, vocal = _long_stems(tmp_path, secs=120.0)
    out = tmp_path / "mix.wav"
    plan = _plan(anchor=1.0, vocal_src=(0.0, 1.0))  # plan.window defaults to None
    render.render_mix(plan, stems, vocal, out)
    y, sr = sf.read(out, dtype="float32", always_2d=True)
    dur = len(y) / sr
    assert dur >= 118.0, f"no-window render was unexpectedly shortened: dur={dur:.2f}s (want >=118s of 120s)"


def test_render_window_never_clips(tmp_path):
    """AC3: the windowed render keeps the same clip-safety guarantee as any other render -- peak stays
    <= _CEILING. (This guard is already unconditional in the engine, so it is expected to pass both
    before and after the crop lands; it pins that the new path must not regress it.)"""
    stems, vocal = _long_stems(tmp_path, secs=120.0)
    out = tmp_path / "mix.wav"
    plan = _plan(anchor=1.0, vocal_src=(0.0, 1.0))
    plan.window = (30.0, 120.0)
    render.render_mix(plan, stems, vocal, out)
    y, _ = sf.read(out, dtype="float32", always_2d=True)
    peak = float(np.max(np.abs(y)))
    assert 0.0 < peak <= render._CEILING, f"windowed render clipped or went silent: peak={peak:.4f}"


def test_render_window_places_vocal_within_the_cropped_output(tmp_path):
    """AC4: a placement anchored NEAR THE END of the window (window-relative anchor, matching how the
    planner already emits window-relative placements -- test_plan.py's
    test_long_song_vocal_spans_its_good_part_window) must still land inside the ~90s windowed output,
    not be stranded past the end of a still-full 120s render. Fails today on duration alone: the render
    stays ~120s because window is ignored, so a ~90s-bounded output containing the vocal does not exist."""
    stems, vocal = _long_stems(tmp_path, secs=120.0)
    out = tmp_path / "mix.wav"
    # window (20, 110) -> a 90s window; anchor 85.0 is window-relative, 5s before the window ends.
    plan = _arr_plan([(85.0, (0.0, 1.5), False)])
    plan.window = (20.0, 110.0)
    render.render_mix(plan, stems, vocal, out)
    y, sr = sf.read(out, dtype="float32", always_2d=True)
    dur = len(y) / sr
    assert dur <= 96.0, f"windowed placement pushed the render past the ~90s window: dur={dur:.2f}s"
    e = lambda a, b: float(np.mean(np.abs(y[int(a * sr):int(b * sr)])))
    # the vocal (440Hz) is audible right at its anchor, inside the windowed output
    assert e(85.0, 86.4) > e(10.0, 11.4), "vocal not landing at its expected position in the windowed output"


def test_render_malformed_window_fails_loud(tmp_path):
    """AC5 (adversarial): a REVERSED window (w1 <= w0) must FAIL LOUD with RenderError, not silently
    render an empty/garbage crop -- an unguarded empty crop would ship a beat-less mix. Fails today
    because render_mix never reads plan.window at all: no crop is attempted and no error is raised,
    so this render succeeds (wrongly) instead of raising."""
    stems, vocal = _long_stems(tmp_path, secs=120.0)
    out = tmp_path / "mix.wav"
    plan = _plan(anchor=1.0, vocal_src=(0.0, 1.0))
    plan.window = (120.0, 30.0)  # reversed -> w1 <= w0, an empty/negative crop
    with pytest.raises(render.RenderError):
        render.render_mix(plan, stems, vocal, out)


def test_render_window_with_bed_stretch(tmp_path):
    """AC6: the window crop must index the POST-bed_stretch (already atempo'd) bed, not the original-
    tempo one -- the movable-master path. window=(30,120) on 120s stems with bed_stretch=1.05 must
    still render a sane, clearly-cropped clip (well under the full ~114.3s stretched track: <=96s,
    allowing for atempo's duration/ratio scaling) and stay clip-safe. Fails today: window is ignored
    entirely, so the full stretched bed plays through and dur comes out ~114.3s (120/1.05), outside
    the expected crop."""
    stems, vocal = _long_stems(tmp_path, secs=120.0)
    out = tmp_path / "mix.wav"
    plan = _plan(anchor=1.0, vocal_src=(0.0, 1.0))
    plan.window = (30.0, 120.0)
    plan.bed_stretch = 1.05
    render.render_mix(plan, stems, vocal, out)
    y, sr = sf.read(out, dtype="float32", always_2d=True)
    dur = len(y) / sr
    assert dur <= 96.0, f"window+bed_stretch not cropped: dur={dur:.2f}s (want <=96s)"
    peak = float(np.max(np.abs(y)))
    assert 0.0 < peak <= render._CEILING, f"windowed+stretched render clipped or went silent: peak={peak:.4f}"


def _marked_tone_regions(path, secs, regions, sr=44100):
    """Write a `secs`-long mono WAV: silence everywhere except each (start, end, freq, amp) region,
    which carries a sine tone. Used to fingerprint WHICH slice of an uncropped file render_mix
    actually seeks into -- a wrong (un-offset) seek grabs the DECOY tone; the right (window-offset)
    seek grabs the marked one."""
    n = int(sr * secs)
    y = np.zeros(n, dtype="float32")
    for start, end, freq, amp in regions:
        s, e = int(start * sr), int(end * sr)
        t = np.linspace(0, (e - s) / sr, e - s, endpoint=False)
        y[s:e] = (amp * np.sin(2 * np.pi * freq * t)).astype("float32")
    sf.write(path, y, sr)


def test_render_window_offsets_s1_vocal_regions(tmp_path):
    """AC7 (the strongest one): plan.s1_vocal_regions are WINDOW-RELATIVE, but Song 1's "vocals" stem
    file on disk is never cropped -- so the seek into that file must be offset by win_start. Song 1's
    vocals stem is marked: a DECOY 1000Hz tone at ABSOLUTE 5-7s (what an un-offset seek wrongly grabs)
    and the REAL 2000Hz tone at ABSOLUTE 35-37s (window(30,120) + region (5,7) window-relative ->
    intends absolute 35-37s). Fails today: render_mix takes the region literally at s=5.0 with no
    window offset, so the rendered output's 5-7s segment carries the DECOY 1000Hz tone, not 2000Hz."""
    stems, vocal = _long_stems(tmp_path, secs=120.0)
    _marked_tone_regions(stems["vocals"], secs=120.0,
                          regions=[(5.0, 7.0, 1000.0, 0.4), (35.0, 37.0, 2000.0, 0.4)])
    out = tmp_path / "mix.wav"
    plan = _plan(anchor=1.0, vocal_src=(0.0, 1.0))
    plan.window = (30.0, 120.0)
    plan.s1_vocal_regions = [(5.0, 7.0)]  # window-relative -> intends absolute 35-37s in the file
    render.render_mix(plan, stems, vocal, out)
    y, sr = sf.read(out, dtype="float32", always_2d=True)
    seg = y[int(5.0 * sr):int(7.0 * sr)]
    mono = seg.mean(axis=1)
    mag = np.abs(np.fft.rfft(mono))
    freqs = np.fft.rfftfreq(len(mono), d=1.0 / sr)

    def _mag_near(freq):
        idx = int(np.argmin(np.abs(freqs - freq)))
        return float(mag[idx])

    m2000, m1000 = _mag_near(2000.0), _mag_near(1000.0)
    assert m2000 > m1000, (
        f"5-7s segment not offset by window start: 2000Hz mag={m2000:.1f} vs decoy 1000Hz mag={m1000:.1f} "
        "(the seek used the region literally instead of offsetting it by win_start)")
