"""Tests for the arranged-vocal-bus renderer. Like test_render, these shell out to
FFmpeg and build tiny synthetic stems; they confirm the bus carries the vocal only
where the plan places it and is silent (no bed) everywhere else."""

import sys
import types
from pathlib import Path

import numpy as np
import soundfile as sf

_REPO = Path(__file__).resolve().parents[3]  # tests -> api -> services -> repo
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from workers import live_stems  # noqa: E402
from workers.render import SR, _apply_vocal_chain, _edge_fade, _vocal_take  # noqa: E402

sys.path.insert(0, str(_REPO / "services" / "api"))
from app.models import VocalProcessMove  # noqa: E402


def _tone(path, freq=440.0, secs=8.0, amp=0.4, sr=SR):
    t = np.linspace(0, secs, int(sr * secs), endpoint=False)
    sf.write(path, (amp * np.sin(2 * np.pi * freq * t)).astype("float32"), sr)


def _stems(tmp_path):
    paths = {}
    for name, f in (("drums", 110.0), ("bass", 55.0), ("other", 330.0), ("vocals", 660.0)):
        p = tmp_path / f"{name}.wav"
        _tone(p, freq=f, secs=8.0)
        paths[name] = p
    vocal = tmp_path / "vocal.wav"
    _tone(vocal, freq=440.0, secs=8.0)
    return paths, vocal


def _arr_plan(placements, s1_regions=()):
    """placements = [(anchor, (start,end)), ...]; s1_regions = [(s,e), ...]."""
    return types.SimpleNamespace(
        master_bpm=120.0, vocal_stretch=1.0,
        vocal_src=placements[0][1], anchor=placements[0][0], beat_breath=False,
        placements=[types.SimpleNamespace(anchor=a, vocal_src=v, beat_breath=False)
                    for a, v in placements],
        s1_vocal_regions=list(s1_regions),
    )


def _rms(y, a, b):
    seg = y[int(a * SR):int(b * SR)]
    return float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0


def test_vocal_bus_is_valid_stereo_wav(tmp_path):
    stems, vocal = _stems(tmp_path)
    out = tmp_path / "bus.wav"
    live_stems.render_vocal_bus(_arr_plan([(2.0, (0.0, 2.0))]), stems, vocal, out)
    y, sr = sf.read(out, dtype="float32", always_2d=True)
    assert sr == SR and y.shape[1] == 2
    peak = float(np.max(np.abs(y)))
    assert 0.0 < peak <= 0.999  # audible, never clipping


def test_vocal_bus_silent_before_placement_and_loud_inside(tmp_path):
    stems, vocal = _stems(tmp_path)
    out = tmp_path / "bus.wav"
    live_stems.render_vocal_bus(_arr_plan([(2.0, (0.0, 2.0))]), stems, vocal, out)
    y, _ = sf.read(out, dtype="float32", always_2d=True)
    # Before the anchor (2.0s) the bus is silence — proves the bed is NOT summed in.
    assert _rms(y, 0.2, 1.7) < 1e-3
    # Inside the placement it is loud (the vocal is present).
    assert _rms(y, 2.3, 3.7) > 1e-2


def test_vocal_bus_includes_song1_contrast_region(tmp_path):
    stems, vocal = _stems(tmp_path)
    out = tmp_path / "bus.wav"
    # No Song 2 placement near 5s; a Song 1 contrast region at [5,6] must still be audible.
    live_stems.render_vocal_bus(_arr_plan([(0.5, (0.0, 1.0))], s1_regions=[(5.0, 6.0)]),
                                stems, vocal, out)
    y, _ = sf.read(out, dtype="float32", always_2d=True)
    assert _rms(y, 5.2, 5.8) > 1e-2


def _two_tone(path, f1=440.0, f2=2000.0, secs=8.0, amp=0.3, sr=SR):
    t = np.linspace(0, secs, int(sr * secs), endpoint=False)
    y = amp * (np.sin(2 * np.pi * f1 * t) + np.sin(2 * np.pi * f2 * t))
    sf.write(path, y.astype("float32"), sr)


def _arr_plan_with_moves(placements, moves):
    """Like _arr_plan but carries vocal_moves (Phase-0 chain) + empty duck_moves."""
    plan = _arr_plan(placements)
    plan.vocal_moves = list(moves)
    plan.duck_moves = []
    return plan


def test_vocal_bus_APPLIES_the_chain_matching_export_pass1(tmp_path):
    """Parity blocker: the Play/steer vocal bus must carry the SAME per-placement vocal chain that
    Export (`render_mix` Pass 1) applies — else Play previews a dry vocal while Download is tuned.
    A guard-safe highpass move (removes energy -> can't inflate the peak or trip the crest guard)
    that still changes bytes; the bus region at the anchor must equal `_apply_vocal_chain` output."""
    stems, _ = _stems(tmp_path)
    vocal = tmp_path / "voc2.wav"
    _two_tone(vocal)
    anchor, src = 2.0, (0.0, 2.0)
    move = VocalProcessMove(placement_id="p0", start_bar=0, end_bar=4, highpass_hz=1000)  # kill the 440Hz

    out = tmp_path / "bus_chain.wav"
    live_stems.render_vocal_bus(_arr_plan_with_moves([(anchor, src)], [move]), stems, vocal, out)
    y, _ = sf.read(out, dtype="float32", always_2d=True)

    # Independently reproduce Export's Pass-1 vocal for this placement and compare byte-for-byte.
    voc = _edge_fade(_vocal_take(vocal, src[0], src[1] - src[0], 1.0))
    expected = _apply_vocal_chain(voc, move, SR)
    a0 = int(anchor * SR)
    seg = y[a0:a0 + len(expected)]
    assert seg.shape[0] == len(expected)
    assert np.allclose(seg, expected, atol=2e-4)  # PCM_16 quantization only

    # And prove the chain actually did something: the same bus WITHOUT the move is the raw vocal,
    # which must differ from the processed one (a highpass removes the 440Hz tone).
    out0 = tmp_path / "bus_nochain.wav"
    live_stems.render_vocal_bus(_arr_plan([(anchor, src)]), stems, vocal, out0)
    y0, _ = sf.read(out0, dtype="float32", always_2d=True)
    seg0 = y0[a0:a0 + len(expected)]
    assert not np.allclose(seg0, expected, atol=2e-4)  # dry != tuned
    assert np.allclose(seg0, _edge_fade(_vocal_take(vocal, src[0], src[1] - src[0], 1.0)), atol=2e-4)


def test_vocal_bus_with_no_placements_is_valid_silence(tmp_path):
    stems, vocal = _stems(tmp_path)
    out = tmp_path / "bus.wav"
    plan = types.SimpleNamespace(master_bpm=120.0, vocal_stretch=1.0,
                                 vocal_src=(0.0, 0.0), anchor=0.0, beat_breath=False,
                                 placements=[], s1_vocal_regions=[])
    # _placements_of falls back to the scalar anchor/vocal_src (a zero-length slice) -> silence.
    live_stems.render_vocal_bus(plan, stems, vocal, out)
    y, sr = sf.read(out, dtype="float32", always_2d=True)
    assert sr == SR and len(y) >= 1
