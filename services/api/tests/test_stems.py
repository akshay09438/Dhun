import dataclasses

import pytest

from app.audio import stems as stems_mod
from app.audio.stems import STEMS, SeparationError, separate_stems, stem_path


def _use_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(stems_mod, "settings",
                        dataclasses.replace(stems_mod.settings, data_dir=tmp_path))


class _FakeFile:
    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data


def test_separate_downloads_and_stores(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    monkeypatch.setattr(stems_mod, "_model_ref", lambda: "model:v")
    calls = {"n": 0}

    def fake_run(ref, input):
        calls["n"] += 1
        return {s: _FakeFile(f"{s}-data".encode()) for s in STEMS}

    monkeypatch.setattr(stems_mod.replicate_client, "run", fake_run)
    wav = tmp_path / "song.wav"
    wav.write_bytes(b"RIFFfake")

    result = separate_stems("a" * 64, wav)

    assert set(result) == set(STEMS)
    for s in STEMS:
        assert result[s].exists()
        assert result[s].read_bytes() == f"{s}-data".encode()
    assert calls["n"] == 1


def test_cache_hit_makes_no_api_call(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    sid = "b" * 64
    for s in STEMS:
        stem_path(sid, s).write_bytes(b"cached")

    def boom(*a, **k):
        raise AssertionError("must not call the API on a cache hit")

    monkeypatch.setattr(stems_mod.replicate_client, "run", boom)

    result = separate_stems(sid, tmp_path / "unused.wav")
    assert set(result) == set(STEMS)


def test_separation_error_is_wrapped(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    monkeypatch.setattr(stems_mod, "_model_ref", lambda: "model:v")

    def fail(*a, **k):
        raise RuntimeError("insufficient credit")

    monkeypatch.setattr(stems_mod.replicate_client, "run", fail)
    wav = tmp_path / "song.wav"
    wav.write_bytes(b"x")

    with pytest.raises(SeparationError):
        separate_stems("c" * 64, wav)
