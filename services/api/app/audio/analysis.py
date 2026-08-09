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

# The analysis has two halves with very different costs to recompute:
#   CLOUD half (bpm/beats/downbeats/sections) — Replicate, real money per song. Keyed by song_id
#     (content hash) and cached in `{song_id}.structure.json`. NEVER invalidated.
#   LOCAL half (key/energy_curve/vocal_regions) — pure numpy/scipy on our box, FREE. Keyed by
#     song_id + LOCAL_ANALYSIS_VERSION, so improving the local analyzer recomputes the local half
#     WITHOUT re-paying for the cloud structure (it is reused from the structure cache, or seeded
#     from a legacy combined analysis.json — either way zero cloud calls).
# Bump this ONLY when the local analyzer changes; a bump then re-derives the local half for every
# song for free. (Cloud-half changes would need a model/version change, which is a separate concern.)
LOCAL_ANALYSIS_VERSION = "la2"  # la2: + fine-grained vocal_pauses (breath boundaries) for phrase-safe slice ends

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


def structure_path(song_id: str) -> Path:
    """The durable CLOUD-half cache (bpm/beats/downbeats/sections), keyed by song_id, never invalidated."""
    return settings.data_dir / f"{song_id}.structure.json"


def analysis_is_current(song_id: str) -> bool:
    """True iff a cached analysis exists AND its LOCAL half is the current version — so a version bump
    (an improved local analyzer) makes a cache look 'not ready' and gets re-derived on next access."""
    p = analysis_path(song_id)
    if not p.exists():
        return False
    try:
        return json.loads(p.read_text()).get("local_analysis_version") == LOCAL_ANALYSIS_VERSION
    except (OSError, json.JSONDecodeError):
        return False


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


def _normalize_structure(raw: dict) -> dict:
    """Normalize a raw cloud result into the durable structure shape (segments -> sections)."""
    return {
        "bpm": float(raw.get("bpm") or 0.0),
        "beats": [float(b) for b in raw.get("beats", [])],
        "downbeats": [float(d) for d in raw.get("downbeats", [])],
        "sections": [{"start": float(s["start"]), "end": float(s["end"]), "label": str(s["label"])}
                     for s in raw.get("segments", [])],
    }


def _structure_cached(song_id: str, wav_path: Path, legacy: dict | None = None) -> dict:
    """The CLOUD half — from the structure cache, or seeded from a legacy combined analysis.json, or
    (only when neither exists) a fresh Replicate call. Reusing/seeding is what makes a LOCAL version
    bump cost ZERO cloud."""
    sp = structure_path(song_id)
    if sp.exists():
        return json.loads(sp.read_text())
    if legacy is None and analysis_path(song_id).exists():
        legacy = json.loads(analysis_path(song_id).read_text())
    if legacy and legacy.get("beats"):  # a pre-split combined analysis already holds the cloud fields
        struct = {"bpm": float(legacy.get("bpm") or 0.0), "beats": legacy["beats"],
                  "downbeats": legacy.get("downbeats", []), "sections": legacy.get("sections", [])}
    else:  # genuinely first time — the one paid cloud call, then cached forever
        struct = _normalize_structure(_cloud_structure(wav_path))
    sp.write_text(json.dumps(struct))
    return struct


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


# A breath between sung phrases: this long of sustained quiet in the vocal, at or below this
# fraction of the median SINGING level. Tuned so a within-word gap doesn't count but a real
# phrase break does — the arranger ends a slice on one of these so a line never cuts mid-sentence.
_PAUSE_HOP_S = 0.03          # 30 ms envelope frames
_PAUSE_MIN_S = 0.18          # >= 180 ms of quiet = a real breath, not a consonant gap
_PAUSE_FLOOR_FRAC = 0.18     # "quiet" = below 18% of the median singing level


def _vocal_pauses(song_id: str) -> list[float]:
    """Fine-grained breath/phrase boundaries (secs) — where the singing PAUSES — from a ~30 ms RMS
    envelope of the split vocal stem (much finer than the bar-level vocal_regions). A pause is the
    envelope staying below a floor (a fraction of the median singing level) for >= _PAUSE_MIN_S; the
    time returned is where singing STOPS (a phrase END). Pure numpy on our box (no cloud). [] if there
    is no stem or it can't be read — the arranger then keeps its prior fixed-length behaviour."""
    vocal_mp3 = stem_path(song_id, "vocals")
    if not vocal_mp3.exists():
        return []
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "v.wav"
        p = subprocess.run(["ffmpeg", "-y", "-i", str(vocal_mp3), "-ac", "1", str(wav)],
                           capture_output=True, timeout=120)
        if p.returncode != 0:
            return []
        mono, sr = _load_mono(wav)
    hop = int(sr * _PAUSE_HOP_S)
    if hop < 1 or len(mono) < hop * 4:
        return []
    n = len(mono) // hop
    env = np.sqrt(np.mean(mono[:n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)
    active = env[env > 0.05 * env.max()] if env.size else env
    if active.size == 0:
        return []
    floor = _PAUSE_FLOOR_FRAC * float(np.median(active))
    min_frames = max(1, int(round(_PAUSE_MIN_S / _PAUSE_HOP_S)))
    pauses: list[float] = []
    run = 0
    for i, e in enumerate(env):
        if e < floor:
            run += 1
        else:
            if run >= min_frames:  # a sustained quiet run just ended — the phrase stopped where it began
                pauses.append(round((i - run) * hop / sr, 3))
            run = 0
    if run >= min_frames:  # a trailing pause running to the end of the stem
        pauses.append(round((n - run) * hop / sr, 3))
    return pauses


def _beat_regularity(beats: list[float]) -> float:
    """How steady the beat grid is (0..1) — a proxy for grid confidence."""
    if len(beats) < 8:
        return 0.3
    gaps = np.diff(np.asarray(beats))
    spread = float(np.std(gaps) / (np.mean(gaps) + 1e-9))
    return float(np.clip(1.0 - spread * 4.0, 0.1, 0.98))


# ---------------------------------------------------------------- entrypoint


def analyze_track(song_id: str, wav_path: Path) -> dict:
    """Full analysis for one song. The CLOUD half is cached by content id (run once, ever); the LOCAL
    half is re-derived for free whenever LOCAL_ANALYSIS_VERSION changes (zero cloud)."""
    cache = analysis_path(song_id)
    legacy: dict | None = None
    if cache.exists():
        legacy = json.loads(cache.read_text())
        if legacy.get("local_analysis_version") == LOCAL_ANALYSIS_VERSION:
            return legacy  # both halves fresh — nothing to do

    # Reuse (or seed) the cloud half; recompute ONLY the local half. Passing the legacy analysis lets
    # `_structure_cached` seed the structure cache from it, so a version bump never re-calls Replicate.
    structure = _structure_cached(song_id, wav_path, legacy=legacy)
    beats = [float(b) for b in structure.get("beats", [])]
    downbeats = [float(d) for d in structure.get("downbeats", [])]
    vocal_regions, vocal_conf = _vocal_regions(song_id, downbeats)
    vocal_pauses = _vocal_pauses(song_id)

    result = {
        "song_id": song_id,
        "bpm": float(structure.get("bpm") or 0.0),
        "bpm_confidence": _beat_regularity(beats),
        "beats": beats,
        "downbeats": downbeats,
        "phrase_starts": downbeats[::8],  # 8-bar blocks (4/4 assumed in V1)
        "key": detect_key(wav_path),
        "sections": structure.get("sections", []),
        "sections_confidence": 0.6,  # the industry-wide weak link — never trust blindly
        "energy_curve": _rms_per_bar(wav_path, downbeats),
        "vocal_regions": vocal_regions,
        "vocal_confidence": vocal_conf,
        "vocal_pauses": vocal_pauses,
        "local_analysis_version": LOCAL_ANALYSIS_VERSION,
    }
    cache.write_text(json.dumps(result))
    return result
