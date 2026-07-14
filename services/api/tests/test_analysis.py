import dataclasses
import json

import numpy as np
import soundfile as sf

from app.audio import analysis as an


def _use_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(an, "settings",
                        dataclasses.replace(an.settings, data_dir=tmp_path))


def _write_chord(path, freqs, seconds=6.0, sr=22050):
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    y = sum(np.sin(2 * np.pi * f * t) for f in freqs) / len(freqs)
    sf.write(path, y.astype("float32"), sr)


def test_detect_key_c_major(tmp_path):
    # C4 + E4 + G4 = a C major chord; the detector should name it C major (8B).
    wav = tmp_path / "cmaj.wav"
    _write_chord(wav, [261.63, 329.63, 392.00])

    key = an.detect_key(wav)

    assert key["tonic"] == "C"
    assert key["mode"] == "major"
    assert key["camelot"] == "8B"
    assert 0 < key["confidence"] <= 1


def test_energy_curve_quiet_vs_loud(tmp_path):
    sr = 22050
    quiet = 0.05 * np.sin(2 * np.pi * 220 * np.linspace(0, 2, sr * 2))
    loud = 0.9 * np.sin(2 * np.pi * 220 * np.linspace(0, 2, sr * 2))
    wav = tmp_path / "dyn.wav"
    sf.write(wav, np.concatenate([quiet, loud]).astype("float32"), sr)

    curve = an._rms_per_bar(wav, [0.0, 2.0])  # two "bars": quiet then loud

    assert len(curve) == 2
    assert curve[1] == 1.0  # loud bar is the peak
    assert curve[0] < 0.2  # quiet bar is far below it


def test_beat_regularity_confidence():
    steady = [i * 0.5 for i in range(64)]
    assert an._beat_regularity(steady) > 0.9
    assert an._beat_regularity([0.0, 0.5, 0.7]) == 0.3  # too few beats


def test_analyze_track_is_cached(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    sid = "a" * 64
    # a FRESH cache (current local version) is returned as-is, no cloud, no local recompute
    cached = {"song_id": sid, "bpm": 120.0, "local_analysis_version": an.LOCAL_ANALYSIS_VERSION}
    an.analysis_path(sid).write_text(json.dumps(cached))

    def boom(*a, **k):
        raise AssertionError("must not call the cloud on a cache hit")

    monkeypatch.setattr(an, "_cloud_structure", boom)

    assert an.analyze_track(sid, tmp_path / "unused.wav") == cached


def test_local_reanalysis_costs_zero_cloud(tmp_path, monkeypatch):
    """0.1: a stale LOCAL half (a legacy analysis with no version, or a bumped version) recomputes the
    local fields (key/energy/vocal_regions) WITHOUT any cloud call — the cloud structure is reused
    (seeded from the legacy analysis). Rig BOTH the cloud helper and replicate.run to crash to prove it."""
    _use_tmp(monkeypatch, tmp_path)
    sid = "a" * 64
    sr = 22050
    t = np.linspace(0, 4, sr * 4, endpoint=False)
    sf.write(tmp_path / f"{sid}.wav", (0.5 * np.sin(2 * np.pi * 220 * t)).astype("float32"), sr)
    sf.write(tmp_path / f"{sid}.vocals.mp3", (0.5 * np.sin(2 * np.pi * 440 * t)).astype("float32"), sr)
    # a LEGACY combined analysis (no local_analysis_version) that already holds the cloud fields
    legacy = {"song_id": sid, "bpm": 120.0,
              "beats": [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5], "downbeats": [0.0, 2.0],
              "sections": [{"start": 0.0, "end": 4.0, "label": "verse"}]}
    an.analysis_path(sid).write_text(json.dumps(legacy))

    def boom(*a, **k):
        raise AssertionError("a LOCAL re-analysis must not call the cloud")

    monkeypatch.setattr(an, "_cloud_structure", boom)
    monkeypatch.setattr(an.replicate, "run", boom)

    result = an.analyze_track(sid, tmp_path / f"{sid}.wav")

    assert result["local_analysis_version"] == an.LOCAL_ANALYSIS_VERSION
    assert result["beats"] == legacy["beats"]                 # cloud fields reused, not recomputed
    assert result["bpm"] == 120.0 and result["sections"][0]["label"] == "verse"
    assert an.structure_path(sid).exists()                    # cloud cache seeded from the legacy analysis
    assert "camelot" in result["key"] and result["energy_curve"]  # local half genuinely recomputed
    assert an.analysis_is_current(sid)                        # the rewritten cache is now current
