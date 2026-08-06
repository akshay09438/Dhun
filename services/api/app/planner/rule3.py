"""Rule 3 — CHOP & REPEAT — the PLANNER brain (deterministic, no audio).

The architecture principle holds: the brain PLANS (structured data), the engine EXECUTES (samples).
This module decides, for a chop-and-repeat mix, WHICH chop fires WHERE — it never touches audio.

The finalized rules (see docs/RULEBOOK.md), all encoded here:
  - The chop is a hand-picked HOOK line (curated `hooks.py`, or a founder-given timestamp).
  - Two blocks: A = the short "tease" (2-3 words); C = the full "payoff" sentence (looped).
    B (the second half) only ever lives inside C — never scheduled alone.
  - Cut on the VOCAL's own downbeats (whole bars); the renderer warps each bar to a BEAT bar so it
    beat-locks and can't drift. Every fire starts on a beat downbeat.
  - Word-safe endings: a chop's last word FINISHES past the bar line, then fades (the renderer fades;
    here we just carry `word_end`, the natural end of that word, so nothing is hard-cut).
  - TRADE: the beat song's own vocal is kept; chops fire only in the beat's instrumental GAPS
    (call & response). For a vocal-heavy/short beat, `keep_beat_vocal=False` opens the whole track.
  - Not too tight: fires are spaced on the grid with on-grid pauses between.

The BPM+key foundation is upstream (build_mix_plan already stretches the vocal to the beat and
key-shifts it); Rule 3 inherits it and simply schedules chops on the shared grid.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field

import numpy as np

# --- taste knobs (ONE named block; tempo-derived where it matters) --------------------------
VOICED_FLOOR = 0.08          # RMS below this fraction of the local peak is a breath / silence
PHRASE_GAP_SECS = 0.40       # word-gaps shorter than this stay inside one sung phrase
WORD_TAIL_MAX_SECS = 2.2     # a chop's last word may ring at most this long past the bar, then fades
CLEAN_OPEN_FRAC = 0.15       # keep the first slice of the track chop-free (max 40 s) so it opens clean
MIN_GAP_SECS = 7.0           # a beat-song instrumental gap must be at least this long to host a chop
A_MAX_BARS = 2               # the short tease is at most this many vocal bars
C_MAX_BARS = 8               # the full sentence is at most this many vocal bars


@dataclass(frozen=True)
class ChopBlock:
    """One beat-locked chop unit: whole vocal bars + the natural end of its last word.
    `bars` are (start, end) seconds in Song 2's OWN timeline (the renderer warps each to a beat bar)."""
    bars: tuple[tuple[float, float], ...]
    word_end: float          # natural end of the last word (secs, Song-2 time); the renderer fades from here


# A chop "unit" is a list of phrases (ChopBlocks). Each phrase gets its own word-safe fade, so a
# multi-phrase full sentence fades cleanly at every internal join, not only at the very end.
ChopUnit = list[ChopBlock]


@dataclass(frozen=True)
class ChopHit:
    """One scheduled fire: play `block` ('A' or 'C') starting on beat downbeat index `beat_db_index`."""
    block: str               # "A" | "C"
    beat_db_index: int


@dataclass(frozen=True)
class Rule3Plan:
    """The full chop-and-repeat schedule for one mix — consumed by the Rule-3 renderer."""
    a_unit: ChopUnit         # the short tease (usually one phrase)
    c_unit: ChopUnit         # the full sentence (one or more phrases, each word-safe)
    hits: list[ChopHit] = field(default_factory=list)
    keep_beat_vocal: bool = True


def unit_bars(unit: ChopUnit) -> int:
    """Total whole bars a unit occupies on the beat grid."""
    return sum(len(b.bars) for b in unit)


# --- phrase / word detection on the vocal envelope (analysis-time RMS, not raw audio) --------
def voiced_phrases(env: np.ndarray, sr_env: float, t0: float, t1: float,
                   floor: float = VOICED_FLOOR, merge_gap: float = PHRASE_GAP_SECS) -> list[tuple[float, float]]:
    """Sung phrases within [t0, t1): contiguous voiced stretches, word-gaps < merge_gap bridged.
    `env` is a per-sample vocal RMS envelope; `sr_env` its samples-per-second."""
    lo, hi = int(t0 * sr_env), min(len(env), int(t1 * sr_env))
    if hi <= lo:
        return []
    thr = floor * float(np.max(env[lo:hi]) or 1.0)
    voiced = env > thr
    gap = int(merge_gap * sr_env)
    out, i = [], lo
    while i < hi:
        if voiced[i]:
            j = i + 1
            while j < hi and (voiced[j] or np.any(voiced[j:min(hi, j + gap)])):
                j += 1
            if (j - i) / sr_env > 0.6:
                out.append((i / sr_env, j / sr_env))
            i = j
        else:
            i += 1
    return out


def word_end_after(env: np.ndarray, sr_env: float, t0: float, thr: float,
                   max_extra: float = WORD_TAIL_MAX_SECS, dip: float = 0.08) -> float:
    """The natural end of the word being sung at t0: extend until the first short silence (a word
    boundary), capped at max_extra. This is what the renderer fades out — never a hard cut."""
    i, end, d = int(t0 * sr_env), min(len(env), int((t0 + max_extra) * sr_env)), int(dip * sr_env)
    while i < end:
        if np.all(env[i:i + d] < thr):
            return i / sr_env
        i += 1
    return end / sr_env


def _snap(p0: float, p1: float, vocal_downbeats: list[float], vocal_bar: float,
          env: np.ndarray, sr_env: float, thr: float, max_bars: int) -> ChopBlock:
    """Snap a sung phrase [p0, p1] to whole vocal bars (downbeat-aligned) and find its word-safe end."""
    k = max(0, bisect.bisect_right(vocal_downbeats, p0) - 1)
    n = max(1, min(max_bars, max(1, round((p1 - vocal_downbeats[k]) / vocal_bar))))
    bars = tuple((vocal_downbeats[k + i], vocal_downbeats[k + i + 1])
                 for i in range(n) if k + i + 1 < len(vocal_downbeats))
    we = word_end_after(env, sr_env, bars[-1][1], thr)
    return ChopBlock(bars=bars, word_end=we)


def pick_blocks(hook: tuple[float, float], vocal_downbeats: list[float], vocal_bpm: float,
                env: np.ndarray, sr_env: float,
                a_range: tuple[float, float] | None = None,
                c_range: tuple[float, float] | None = None) -> tuple[ChopUnit, ChopUnit]:
    """Decide the A (short tease) and C (full sentence) UNITS from the hook.

    A founder-given (a_range, c_range) wins (C is one continuous phrase); otherwise A = the hook's
    first sung phrase and C = that phrase + the next as two phrases (each word-safe). B never alone.
    """
    vbar = 60.0 / vocal_bpm * 4
    if a_range and c_range:
        thr = VOICED_FLOOR * float(np.max(env[int(a_range[0] * sr_env):int(c_range[1] * sr_env)]) or 1.0)
        a = _snap(a_range[0], a_range[1], vocal_downbeats, vbar, env, sr_env, thr, max_bars=3)
        c = _snap(c_range[0], c_range[1], vocal_downbeats, vbar, env, sr_env, thr, max_bars=C_MAX_BARS)
        return [a], [c]
    win = (hook[0], min(hook[0] + 25.0, len(env) / sr_env))
    thr = VOICED_FLOOR * float(np.max(env[int(win[0] * sr_env):int(win[1] * sr_env)]) or 1.0)
    ph = voiced_phrases(env, sr_env, hook[0], min(hook[0] + 22.0, hook[1] if hook[1] > hook[0] + 6 else hook[0] + 22))
    if len(ph) < 2:
        ph = voiced_phrases(env, sr_env, hook[0], hook[0] + 30.0)
    if not ph:
        raise ValueError("Rule 3: no sung phrase found in the hook window")
    a = _snap(ph[0][0], ph[0][1], vocal_downbeats, vbar, env, sr_env, thr, max_bars=A_MAX_BARS)
    if len(ph) >= 2:                                  # C = tease phrase + the next -> the full line
        b = _snap(ph[1][0], ph[1][1], vocal_downbeats, vbar, env, sr_env, thr, max_bars=A_MAX_BARS)
        return [a], [a, b]
    return [a], [a]


def instrumental_gaps(beat_vocal_env: np.ndarray | None, sr_env: float, track_end: float,
                      keep_beat_vocal: bool) -> list[tuple[float, float]]:
    """Where the BEAT song is NOT singing (chops trade into these). If keep_beat_vocal is False
    (a vocal-heavy or short beat, or no beat vocal at all), the whole track is one gap and the env
    is ignored (may be None)."""
    if not keep_beat_vocal or beat_vocal_env is None:
        return [(0.0, track_end)]
    thr = 0.06 * float(np.max(beat_vocal_env) or 1.0)
    voiced = beat_vocal_env > thr
    bridge = int(1.0 * sr_env)
    sing, i = [], 0
    while i < len(voiced):
        if voiced[i]:
            j = i + 1
            while j < len(voiced) and (voiced[j] or np.any(voiced[j:min(len(voiced), j + bridge)])):
                j += 1
            if (j - i) / sr_env > 1.5:
                sing.append((i / sr_env, j / sr_env))
            i = j
        else:
            i += 1
    gaps, prev = [], 0.0
    for a, b in sing:
        if a - prev > MIN_GAP_SECS:
            gaps.append((prev, a))
        prev = b
    if track_end - prev > MIN_GAP_SECS:
        gaps.append((prev, track_end))
    return gaps


def schedule(beat_downbeats: list[float], gaps: list[tuple[float, float]],
             a_unit: ChopUnit, c_unit: ChopUnit, track_end: float,
             stride_secs: float = 6.0) -> list[ChopHit]:
    """Weave A (tease) and C (full) into the beat's gaps, on the grid, with a rest between fires.
    Not too tight: fires start on downbeats and leave `stride_secs` of pause after each chop."""
    skip_first = min(40.0, track_end * CLEAN_OPEN_FRAC)
    n_a, n_c = unit_bars(a_unit), unit_bars(c_unit)
    hits, idx = [], 0
    for g0, g1 in gaps:
        t = max(g0 + 2.0, skip_first if g0 < skip_first else g0 + 2.0)
        while t < g1 - 4.0:
            didx = bisect.bisect_left(beat_downbeats, t)
            if didx >= len(beat_downbeats):
                break
            want_c = (idx % 2 == 1)
            nb = n_c if want_c else n_a
            if didx + nb + 1 >= len(beat_downbeats) or beat_downbeats[didx + nb] > g1 - 0.3:
                want_c, nb = False, n_a          # C didn't fit -> try the short A
                if didx + nb + 1 >= len(beat_downbeats) or beat_downbeats[didx + nb] > g1 - 0.3:
                    break
            hits.append(ChopHit(block="C" if want_c else "A", beat_db_index=didx))
            idx += 1
            t = beat_downbeats[didx + nb] + stride_secs
    return hits
