import dataclasses
import subprocess
from pathlib import Path

from app import storage


def _wav(path: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(path)],
        check=True, capture_output=True,
    )


def _use_tmp_data_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "settings",
                        dataclasses.replace(storage.settings, data_dir=tmp_path))


def test_store_and_retrieve(tmp_path, monkeypatch):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    src = tmp_path / "clean.wav"
    _wav(src)

    sid = storage.store_wav(src)

    assert sid
    p = storage.path_for(sid)
    assert p is not None and p.exists()


def test_rejects_traversal_and_unknown_ids(tmp_path, monkeypatch):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    assert storage.path_for("../etc/passwd") is None       # traversal
    assert storage.path_for("..\\..\\windows") is None      # windows traversal
    assert storage.path_for("deadbeef") is None             # too short
    assert storage.path_for("a" * 64) is None               # valid format, not stored
