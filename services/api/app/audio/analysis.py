"""Analyze a song: beat grid + structure (cloud) and key/energy/vocals (local).

The rhythm/structure brain (BPM, every beat, downbeats, sections) runs in the
cloud via Replicate's all-in-one music structure analyzer — the same "can't run
locally on this ARM machine" story as stem separation. Everything else is
computed here with pure numpy/scipy, which is free:

  - musical key  -> chromagram + Krumhansl–Kessler profiles -> Camelot code
  - energy curve -> loudness (RMS) per bar
  - vocal map    -> loudness of the (already-split) vocal stem per bar

Results are cached as JSON next to the audio, keyed by content id — a song is
analyzed once, ever. Confidence rides along with every field the DJ rules lean
on: analysis being wrong, not the rules, is the enemy (DJ Handbook Part 9).
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import urllib.request
from pathlib import Path

import numpy as np
import replicate
import soundfile as sf

from app.audio.stems import stem_path
from app.config import settings

_MODEL = "sakemin/all-in-one-music-structure-analyzer"

# Krumhansl–Kessler key profiles (perceptual weight of each pitch class).
_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
_NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_CAMELOT_MAJOR = {"C": "8B", "G": "9B", "D": "10B", "A": "11B", "E": "12B", "B": "1B",
                  "F#": "2B", "C#": "3B", "G#": "4B", "D#": "5B", "A#": "6B", "F": "7B"}
_CAMELOT_MINOR = {"A": "8A", "E": "9A", "B": "10A", "F#": "11A", "C#": "12A", "G#": "1A",
                  "D#": "2A", "A#": "3A", "F": "4A", "C": "5A", "G": "6A", "D": "7A"}


class AnalysisError(Exception):
    """Raised when a song cannot be analyzed."""


def analysis_path(song_id: str) -> Path:
    return settings.data_dir / f"{song_id}.analysis.json"


# ---------------------------------------------------------------- cloud part


def _model_ref() -> str:
    version = replicate.models.get(_MODEL).latest_version.id
    return f"{_MODEL}:{version}"


def _cloud_structure(wav_path: Path) -> dict:
    """BPM + beats + downbeats + sections from the cloud analyzer."""
    try:
        with open(wav_path, "rb") as audio:
            out = replicate.run(_model_ref(), input={"music_input": audio})
    except Exception as e:
        raise AnalysisError(str(e)[:200])

    items = list(out) if isinstance(out, (list, tuple)) else [out]
    for item in items:
        data = item.read() if hasattr(item, "read") else urllib.request.urlopen(str(item)).read()
        parsed = json.loads(data)
        if isinstance(parsed, dict) and "beats" in parsed:
            return parsed
    raise AnalysisError("analyzer returned no usable result")


# ---------------------------------------------------------------- local math


def _load_mono(wav_path: Path, max_seconds: float | None = None) -> tuple[np.ndarray, int]:
    y, sr = sf.read(wav_path, dtype="float32", always_2d=True)
    mono = y.mean(axis=1)
    if max_seconds is not None and len(mono) > int(max_seconds * sr):
        # take a centered slice — the musical heart of the track
        start = (len(mono) - int(max_seconds * sr)) // 2
        mono = mono[start : start + int(max_seconds * sr)]
    return mono, sr


def _chroma(mono: np.ndarray, sr: int) -> np.ndarray:
    """Average pitch-class energy across the track (simple FFT chromagram)."""
    frame, hop = 8192, 4096
    n_frames = max(1, (len(mono) - frame) // hop)
    freqs = np.fft.rfftfreq(frame, 1 / sr)
    # map each FFT bin to a pitch class (ignore <55Hz and >5kHz noise)
    valid = (freqs > 55) & (freqs < 5000)
    midi = 69 + 12 * np.log2(np.maximum(freqs, 1e-6) / 440.0)
    pitch_class = np.mod(np.round(midi), 12).astype(int)
    window = np.hanning(frame)

    chroma = np.zeros(12)
    for i in range(n_frames):
        seg = mono[i * hop : i * hop + frame]
        if len(seg) < frame:
            break
        mag = np.abs(np.fft.rfft(seg * window))
        for pc in range(12):
            chroma[pc] += mag[valid & (pitch_class == pc)].sum()
    total = chroma.sum()
    return chroma / total if total > 0 else chroma


def detect_key(wav_path: Path) -> dict:
    """Best-fit key via profile correlation. Confidence = winner's margin."""
    mono, sr = _load_mono(wav_path, max_seconds=180)
    chroma = _chroma(mono, sr)

    scores: list[tuple[float, str, str]] = []
    for shift in range(12):
        rolled = np.roll(chroma, -shift)
        for profile, mode in ((_MAJOR, "major"), (_MINOR, "minor")):
            r = float(np.corrcoef(rolled, profile)[0, 1])
            scores.append((r, _NOTES[shift], mode))
    scores.sort(reverse=True)
    best, second = scores[0], scores[1]
    tonic, mode = best[1], best[2]
    camelot = (_CAMELOT_MAJOR if mode == "major" else _CAMELOT_MINOR)[tonic]
    # margin between the top two candidates, squashed into 0..1
    confidence = float(np.clip(0.5 + (best[0] - second[0]) * 2.5, 0.05, 0.95))
    return {"camelot": camelot, "tonic": tonic, "mode": mode, "confidence": round(confidence, 2)}


def _rms_per_bar(wav_path: Path, downbeats: list[float]) -> list[float]:
    """Loudness (0..1) of each bar; the energy curve the planner reads."""
    mono, sr = _load_mono(wav_path)
    out: list[float] = []
    for i, start in enumerate(downbeats):
        end = downbeats[i + 1] if i + 1 < len(downbeats) else len(mono) / sr
        seg = mono[int(start * sr) : int(end * sr)]
        out.append(float(np.sqrt(np.mean(seg**2))) if len(seg) else 0.0)
    peak = max(out) if out else 1.0
    return [round(v / peak, 3) if peak > 0 else 0.0 for v in out]


def _vocal_regions(song_id: str, downbeats: list[float]) -> tuple[list[list[float]], float]:
    """Where the singer sings, from the already-split vocal stem (if present)."""
    vocal_mp3 = stem_path(song_id, "vocals")
    if not vocal_mp3.exists() or not downbeats:
        return [], 0.3  # no stem yet — low confidence, planner stays cautious

    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "v.wav"
        p = subprocess.run(
            ["ffmpeg", "-y", "-i", str(vocal_mp3), "-ac", "1", str(wav)],
            capture_output=True, timeout=120,
        )
        if p.returncode != 0:
            return [], 0.3
        per_bar = _rms_per_bar(wav, downbeats)

    threshold = 0.25  # of the loudest vocal bar
    regions: list[list[float]] = []
    for i, level in enumerate(per_bar):
        bar_start = downbeats[i]
        bar_end = downbeats[i + 1] if i + 1 < len(downbeats) else bar_start + 2.0
        if level >= threshold:
            if regions and abs(regions[-1][1] - bar_start) < 1e-6:
                regions[-1][1] = bar_end  # extend the open region
            else:
                regions.append([bar_start, bar_end])
    return regions, 0.8


def _beat_regularity(beats: list[float]) -> float:
    """How steady the beat grid is (0..1) — a proxy for grid confidence."""
    if len(beats) < 8:
        return 0.3
    gaps = np.diff(np.asarray(beats))
    spread = float(np.std(gaps) / (np.mean(gaps) + 1e-9))
    return float(np.clip(1.0 - spread * 4.0, 0.1, 0.98))


# ---------------------------------------------------------------- entrypoint


def analyze_track(song_id: str, wav_path: Path) -> dict:
    """Full analysis for one song, cached by content id (run once, ever)."""
    cache = analysis_path(song_id)
    if cache.exists():
        return json.loads(cache.read_text())

    structure = _cloud_structure(wav_path)
    beats = [float(b) for b in structure.get("beats", [])]
    downbeats = [float(d) for d in structure.get("downbeats", [])]
    sections = [
        {"start": float(s["start"]), "end": float(s["end"]), "label": str(s["label"])}
        for s in structure.get("segments", [])
    ]
    vocal_regions, vocal_conf = _vocal_regions(song_id, downbeats)

    result = {
        "song_id": song_id,
        "bpm": float(structure.get("bpm") or 0.0),
        "bpm_confidence": _beat_regularity(beats),
        "beats": beats,
        "downbeats": downbeats,
        "phrase_starts": downbeats[::8],  # 8-bar blocks (4/4 assumed in V1)
        "key": detect_key(wav_path),
        "sections": sections,
        "sections_confidence": 0.6,  # the industry-wide weak link — never trust blindly
        "energy_curve": _rms_per_bar(wav_path, downbeats),
        "vocal_regions": vocal_regions,
        "vocal_confidence": vocal_conf,
    }
    cache.write_text(json.dumps(result))
    return result
