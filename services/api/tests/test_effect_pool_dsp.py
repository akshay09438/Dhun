"""Acceptance tests for the effect-pool ENGINE (render.py DSP primitives).

Independent of the implementation and mostly network-free: synthetic numpy vocals with KNOWN
peaks/lengths, so the level-safety and length-preservation guarantees are proven directly on
_apply_pool / _max_wet_gain, not inferred from a full render. The two render-level tests
(determinism, variety-OFF byte-identity) use tiny synthetic stems + FFmpeg, exactly like
tests/test_render.py's golden helper.

Criteria covered here:
  3 LEVEL SAFETY BY CONSTRUCTION — _apply_pool never exceeds dry peak by more than ~1.5 dB even
    stacked; _max_wet_gain trims a hot input so chain_guards passes. Doubler + freeze/throw, each
    alone and stacked.
  5 LENGTH PRESERVATION — interior length-preserving reverb / width=double keep length; a final
    throw/freeze may be longer.
  1 (part) DETERMINISM — a rendered take is byte-identical when rendered twice.
  6 (part) VARIETY OFF — a None/None (pre-pool) render is byte-identical to a plan with no
    space/width fields at all.
"""

import hashlib
import sys
import types
from pathlib import Path

import numpy as np
import soundfile as sf

_REPO = Path(__file__).resolve().parents[3]  # tests -> api -> services -> repo
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from workers import chain_guards, render  # noqa: E402

SR = render.SR
_HEADROOM = 10.0 ** (render._POOL_HEADROOM_DB / 20.0)  # linear peak factor for ~1.5 dB


def _voc(n_secs=2.0, freq=330.0, amp=0.4):
    """A stereo float32 vocal-ish tone with a syllable envelope (so it has a realistic, non-trivial
    crest factor — a flat tone would make the crest guard vacuous)."""
    n = int(n_secs * SR)
    t = np.linspace(0.0, n_secs, n, endpoint=False)
    env = 0.5 + 0.5 * np.abs(np.sin(2 * np.pi * 3.0 * t))  # ~3 Hz syllables
    m = (amp * env * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.stack([m, m], axis=1)


def _p(space=None, width=None):
    return types.SimpleNamespace(space=space, width=width)


def _peak(y):
    return float(np.max(np.abs(y))) if y.size else 0.0


# ---------------------------------------------------------------- Criterion 3: level safety
_ALL_SPACES = ["room", "hall", "plate", "predelay", "throw", "freeze"]


def test_apply_pool_never_exceeds_headroom_for_every_space_alone():
    """AC3: each SPACE effect, applied alone on the final placement, keeps the output peak within
    ~1.5 dB of the DRY peak (level safety by construction — the dry stays at unity, only the wet is
    trimmed)."""
    voc = _voc()
    dry_pk = _peak(voc)
    for sp in _ALL_SPACES:
        out = render._apply_pool(voc, _p(space=sp), bpm=120.0, is_final=True)
        assert _peak(out) <= dry_pk * _HEADROOM + 1e-4, f"space '{sp}' exceeded headroom: {_peak(out):.4f} > {dry_pk * _HEADROOM:.4f}"


def test_apply_pool_doubler_alone_stays_within_headroom():
    """AC3: the WIDTH doubler alone stays within the ~1.5 dB headroom."""
    voc = _voc()
    out = render._apply_pool(voc, _p(width="double"), bpm=120.0, is_final=False)
    assert _peak(out) <= _peak(voc) * _HEADROOM + 1e-4


def test_apply_pool_space_and_width_stacked_stays_within_headroom():
    """AC3 (the hard case): a SPACE and the WIDTH doubler STACKED — each near its own ceiling — must
    STILL stay within ~1.5 dB of the dry peak, because all added wet is summed and JOINTLY trimmed.
    Checked for every space, incl. the tail-extenders on the final placement."""
    voc = _voc()
    dry_pk = _peak(voc)
    for sp in _ALL_SPACES:
        out = render._apply_pool(voc, _p(space=sp, width="double"), bpm=120.0, is_final=True)
        assert _peak(out) <= dry_pk * _HEADROOM + 1e-4, f"stacked '{sp}'+double exceeded headroom: {_peak(out):.4f}"


def test_apply_pool_on_a_hot_input_passes_chain_guards():
    """AC3: on a DELIBERATELY HOT vocal (peak ~1.0, near 0 dBFS) the joint trim keeps the pooled
    output inside chain_guards (P2 peak-gain <= 3 dB and the crest floor) — the independent render-side
    backstop. Every space, alone and stacked with the doubler."""
    hot = _voc(amp=1.0)  # peaks at ~1.0
    assert _peak(hot) > 0.9
    for sp in _ALL_SPACES:
        for width in (None, "double"):
            out = render._apply_pool(hot, _p(space=sp, width=width), bpm=120.0, is_final=True)
            # trim the dry portion back out for the guard's before/after (the guard compares the SAME
            # region); the pool pads with a tail, so compare the guard on padded-dry vs output.
            before = np.zeros_like(out)
            before[: len(hot)] += hot
            reason = chain_guards.check_vocal_chain_output(before, out)
            assert reason is None, f"chain_guards rejected legal pool space={sp} width={width}: {reason}"


def test_max_wet_gain_trims_when_unity_would_clip_and_is_full_when_safe():
    """AC3 (the primitive): _max_wet_gain returns g<1 (trimmed) when adding the wet at unity would
    push the peak past the headroom target, and g==g_max when the wet is small enough to be safe.
    The trimmed result must sit AT/under the target."""
    n = SR // 2
    dry = np.full((n, 2), 0.5, dtype=np.float32)   # dry peak 0.5
    pk_in = 0.5
    target = pk_in * _HEADROOM
    hot_wet = np.full((n, 2), 0.5, dtype=np.float32)   # unity would give peak 1.0 >> target
    g = render._max_wet_gain(dry, hot_wet, pk_in)
    assert g < 1.0, f"hot wet was not trimmed (g={g})"
    assert _peak(dry + g * hot_wet) <= target + 1e-4
    tiny_wet = np.full((n, 2), 0.001, dtype=np.float32)  # negligible -> full gain
    assert render._max_wet_gain(dry, tiny_wet, pk_in) == 1.0


# ---------------------------------------------------------------- Criterion 5: length preservation
def test_interior_length_preserving_reverbs_keep_length():
    """AC5: an INTERIOR (non-final) placement with any length-preserving reverb keeps the processed
    vocal length == input length, so a following vocal's overlap math (referee R1) is unchanged."""
    voc = _voc()
    for sp in ("room", "hall", "plate", "predelay"):
        out = render._apply_pool(voc, _p(space=sp), bpm=120.0, is_final=False)
        assert len(out) == len(voc), f"interior reverb '{sp}' changed length: {len(out)} != {len(voc)}"


def test_interior_width_double_keeps_length():
    """AC5: width=double on an interior placement is length-preserving."""
    voc = _voc()
    out = render._apply_pool(voc, _p(width="double"), bpm=120.0, is_final=False)
    assert len(out) == len(voc)


def test_interior_tail_extender_is_fit_back_to_length():
    """AC5 (defense-in-depth): a tail-extender on a NON-final placement (is_final=False) is fit back
    to input length as a safe fallback — the engine never lets a throw/freeze overrun a following
    vocal even if the referee somehow passed one through."""
    voc = _voc()
    for sp in ("throw", "freeze"):
        out = render._apply_pool(voc, _p(space=sp), bpm=120.0, is_final=False)
        assert len(out) == len(voc), f"non-final '{sp}' was not fit back to length: {len(out)} != {len(voc)}"


def test_final_tail_extender_may_be_longer():
    """AC5: a FINAL placement with a tail-extender (throw/freeze) is ALLOWED to ring past the dry —
    the output is longer than the input (nothing follows it)."""
    voc = _voc()
    for sp in ("throw", "freeze"):
        out = render._apply_pool(voc, _p(space=sp), bpm=120.0, is_final=True)
        assert len(out) > len(voc), f"final '{sp}' did not extend the tail: {len(out)} <= {len(voc)}"


def test_none_none_is_the_untouched_vocal():
    """AC5/AC6 boundary: space=None, width=None returns the vocal unchanged (same object contents,
    same length) — the pre-pool path."""
    voc = _voc()
    out = render._apply_pool(voc, _p(), bpm=120.0, is_final=True)
    assert len(out) == len(voc)
    assert np.array_equal(out, voc)


# ---------------------------------------------------------------- render-level: helpers (golden pattern)
def _tone(path, freq=220.0, secs=8.0, amp=0.4):
    t = np.linspace(0, secs, int(SR * secs), endpoint=False)
    sf.write(path, (amp * np.sin(2 * np.pi * freq * t)).astype("float32"), SR)


def _stems(tmp_path):
    paths = {}
    for name, f in (("drums", 110.0), ("bass", 55.0), ("other", 330.0), ("vocals", 660.0)):
        p = tmp_path / f"{name}.wav"
        _tone(p, freq=f, secs=8.0)
        paths[name] = p
    vocal = tmp_path / "vocal.wav"
    _tone(vocal, freq=440.0, secs=8.0)
    return paths, vocal


def _arr_plan(placements):
    """placements = [(anchor, (start,end), space, width), ...]. Duck-typed, like test_render."""
    return types.SimpleNamespace(
        master_bpm=120.0, vocal_stretch=1.0,
        vocal_src=placements[0][1], anchor=placements[0][0], beat_breath=False,
        placements=[types.SimpleNamespace(anchor=a, vocal_src=v, beat_breath=False, space=s, width=w)
                    for a, v, s, w in placements],
    )


def _hash(path):
    y, _ = sf.read(path, dtype="float32", always_2d=True)
    return hashlib.sha256(y.tobytes()).hexdigest()


# ---------------------------------------------------------------- Criterion 1: deterministic render
def test_pooled_render_is_byte_identical_rendered_twice(tmp_path):
    """AC1: a take carrying pool effects (a final throw + doubler, plus an interior hall) renders
    byte-for-byte identically when rendered twice — the pool RNG is fixed-seeded, never wall-clock,
    so the content-addressed mix cache holds. We hash the decoded SAMPLES (not the file)."""
    stems, vocal = _stems(tmp_path)
    plan = _arr_plan([(1.0, (0.0, 1.5), "hall", "double"),
                      (5.0, (0.0, 1.5), "throw", "double")])  # 5.0 is the final (latest) anchor
    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    render.render_mix(plan, stems, vocal, a)
    render.render_mix(plan, stems, vocal, b)
    assert _hash(a) == _hash(b), "a pooled render is not deterministic run-to-run"


# ---------------------------------------------------------------- Criterion 6: variety-OFF byte-identity
def test_none_none_render_is_byte_identical_to_absent_fields(tmp_path):
    """AC6 (render side): a plan whose placements carry space=None/width=None renders byte-for-byte
    identically to the SAME plan with no space/width fields at all — proving the pool's None/None path
    is the exact pre-pool render (the golden guarantee). Mirrors test_render's absent-field no-op
    proof."""
    stems, vocal = _stems(tmp_path)
    with_fields = _arr_plan([(1.0, (0.0, 2.0), None, None), (5.0, (0.0, 1.5), None, None)])
    # a matching plan whose placements have NO space/width attributes at all
    absent = types.SimpleNamespace(
        master_bpm=120.0, vocal_stretch=1.0, vocal_src=(0.0, 2.0), anchor=1.0, beat_breath=False,
        placements=[types.SimpleNamespace(anchor=1.0, vocal_src=(0.0, 2.0), beat_breath=False),
                    types.SimpleNamespace(anchor=5.0, vocal_src=(0.0, 1.5), beat_breath=False)])
    a, b = tmp_path / "fields.wav", tmp_path / "absent.wav"
    render.render_mix(with_fields, stems, vocal, a)
    render.render_mix(absent, stems, vocal, b)
    assert _hash(a) == _hash(b), "None/None pool path is NOT byte-identical to the pre-pool render"
