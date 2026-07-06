"""The fence: the deterministic 'legal, safe options' the brain chooses among.

Given both songs' TrackAnalysis, compute the moves that won't embarrass the mix —
phrase-aligned high-energy drop points, a safe tempo stretch, a clean vocal slice,
key compatibility. The AI driver (planner.plan) only ever picks from what this
returns; the referee (planner.validate) re-checks the result against the hard
rules. Everything here is straight from the DJ Judgment Handbook (Parts 2, 4, 9)
and needs no AI — it is pure, testable arithmetic over the analysis.
"""

from __future__ import annotations

from app.models import TrackAnalysis

# Small stretches sound clean; big ones warble. Keep Song 2's vocal within ±8% of
# Song 1's tempo (atempo is transparent in this band). Outside it, we decline the
# pair rather than ship a warbly voice (Handbook B3).
SAFE_STRETCH_LO = 0.92
SAFE_STRETCH_HI = 1.08

# Cap the vocal slice so one long region can't dominate the whole mix — M3 is a
# single placement; a section-length drop stays punchy.
MAX_VOCAL_SECS = 40.0
MIN_VOCAL_SECS = 4.0

_BARS_PER_PHRASE = 8  # 4/4 assumed in V1 (matches analysis.phrase_starts = downbeats[::8])


def best_stretch(master_bpm: float, source_bpm: float) -> tuple[float, bool]:
    """Ratio to stretch Song 2's vocal onto Song 1's tempo, and whether it's safe.

    Folds octaves (half/double-time) so a source the analyzer read at 2x or 0.5x
    still matches — we take the candidate closest to 1.0 (the least stretch). Safe
    when within ±8%.
    """
    if source_bpm <= 0 or master_bpm <= 0:
        return 1.0, False
    candidates = (
        master_bpm / source_bpm,
        master_bpm / (source_bpm * 2),
        master_bpm / (source_bpm / 2),
    )
    ratio = min(candidates, key=lambda r: abs(r - 1.0))
    return round(ratio, 4), SAFE_STRETCH_LO <= ratio <= SAFE_STRETCH_HI


def _phrase_energy(energy_curve: list[float], phrase_idx: int) -> float:
    """Average energy of the 8 bars that make up a phrase (0 if out of range)."""
    start = phrase_idx * _BARS_PER_PHRASE
    window = energy_curve[start : start + _BARS_PER_PHRASE]
    return sum(window) / len(window) if window else 0.0


def candidate_drops(a1: TrackAnalysis, need_secs: float) -> list[float]:
    """Song 1's phrase-start downbeats ranked by energy (the 'drops'), keeping only
    those that leave enough runway for the vocal.

    Fallback ladder (Handbook 9.4): if phrase starts are missing, anchor on any
    downbeat; if even downbeats are missing, any beat. Ranking needs the energy
    curve + downbeats; without them the analysis order is kept.
    """
    anchors = a1.phrase_starts or a1.downbeats or a1.beats
    if not anchors:
        return []
    track_end = a1.beats[-1] if a1.beats else anchors[-1] + need_secs

    def energy_of(t: float) -> float:
        if a1.downbeats and a1.energy_curve:
            idx = min(range(len(a1.downbeats)), key=lambda i: abs(a1.downbeats[i] - t))
            return _phrase_energy(a1.energy_curve, idx // _BARS_PER_PHRASE)
        return 0.0

    usable = [t for t in anchors if t + need_secs <= track_end + 1e-6]
    if not usable:
        usable = anchors[:1]  # nothing has full runway — still offer the earliest
    usable.sort(key=energy_of, reverse=True)
    return usable


def arc_anchors(anchors_ranked: list[float], track_end: float,
                count: int = 3, take: int = 1) -> list[float]:
    """Distribute `count` vocal entries across the track to shape an energy ARC, instead
    of letting them cluster where the song is merely loudest.

    Straight from the DJ Handbook (H1 shape-an-arc, H2 think-in-thirds, H5 don't-peak-
    early): split the timeline into `count` equal bands and take the best-energy anchor
    in each, so one vocal moment lands in every third of the song and — because the last
    band is the final third — a strong entry is saved for the end. `anchors_ranked` must
    be energy-best-first (as `candidate_drops` returns), so band[0] is the loudest anchor
    in that band and quiet intros stay instrumental. `take` rotates the pick within a band
    for Regenerate variety. Returns anchors in time order.
    """
    if not anchors_ranked or track_end <= 0 or len(anchors_ranked) <= count:
        return sorted(anchors_ranked)
    picks: list[float] = []
    for i in range(count):
        lo, hi = track_end * i / count, track_end * (i + 1) / count
        band = [a for a in anchors_ranked if lo <= a < hi]  # energy-desc within the band
        if band:
            picks.append(band[(take - 1) % len(band)])
    if len(picks) < count:  # sparse anchors left a band empty — backfill the loudest unused
        for a in anchors_ranked:
            if a not in picks:
                picks.append(a)
            if len(picks) >= count:
                break
    return sorted(set(picks))


def best_vocal_slice(a2: TrackAnalysis) -> tuple[float, float]:
    """The slice of Song 2's vocal to lay on the drop: its strongest (longest) sung
    stretch, snapped to start on a downbeat ('the one'), capped to a punchy length.
    Falls back to a chorus section, then the track's middle, if vocal regions are
    unknown (Handbook 9.4)."""
    regions = [(s, e) for s, e in a2.vocal_regions if e - s >= MIN_VOCAL_SECS]
    if regions:
        start, end = max(regions, key=lambda r: r[1] - r[0])
    else:
        chorus = [s for s in a2.sections if s.label.lower() in ("chorus", "drop")]
        if chorus:
            start, end = chorus[0].start, chorus[0].end
        elif a2.beats:
            span = a2.beats[-1]
            start, end = span / 3, span / 3 + MAX_VOCAL_SECS
        else:
            start, end = 0.0, MAX_VOCAL_SECS
    end = min(end, start + MAX_VOCAL_SECS)
    if a2.downbeats:
        start = min(a2.downbeats, key=lambda d: abs(d - start))
    end = max(end, start + MIN_VOCAL_SECS)
    return round(start, 3), round(end, 3)


def _parse_camelot(code: str) -> tuple[int, str]:
    return int(code[:-1]), code[-1].upper()


def camelot_fit(c1: str, c2: str) -> bool:
    """The Handbook's safe harmonic moves (C1): same key, ±1/±2 on the clock (same
    letter), or relative major/minor (same number). Informational in M3."""
    try:
        n1, l1 = _parse_camelot(c1)
        n2, l2 = _parse_camelot(c2)
    except (ValueError, IndexError):
        return False
    if (n1, l1) == (n2, l2):
        return True
    if n1 == n2 and l1 != l2:  # relative major/minor
        return True
    dist = min(abs(n1 - n2), 12 - abs(n1 - n2))  # circular distance on the 12-clock
    return l1 == l2 and dist in (1, 2)


def legal_options(a1: TrackAnalysis, a2: TrackAnalysis) -> dict:
    """Assemble the fence: every legal, safe choice for mixing S2's vocal over S1's
    bed — or a plain-language decline if the pair can't be blended cleanly."""
    if not a1.bpm or not a2.bpm or not (a1.phrase_starts or a1.downbeats or a1.beats):
        return {"mixable": False, "reason": "One track has no reliable beat to lock to."}

    ratio, safe = best_stretch(a1.bpm, a2.bpm)
    if not safe:
        pct = round(abs(ratio - 1) * 100)
        return {
            "mixable": False,
            "reason": f"These two songs are too far apart in tempo (~{pct}% stretch) to blend cleanly.",
        }

    vocal_src = best_vocal_slice(a2)
    need = (vocal_src[1] - vocal_src[0]) * ratio
    drops = candidate_drops(a1, need)
    if not drops:
        return {"mixable": False, "reason": "Couldn't find a spot in Song 1 with room for the vocal."}

    key_fit = (
        camelot_fit(a1.key.camelot, a2.key.camelot) if (a1.key and a2.key) else None
    )
    return {
        "mixable": True,
        "master_bpm": a1.bpm,
        "vocal_stretch": ratio,
        "vocal_src": vocal_src,
        "drops": drops,  # ranked best-first
        "key_fit": key_fit,
    }


def vocal_slices(a2: TrackAnalysis, limit: int = 4) -> list[tuple[float, float]]:
    """Song 2's strongest sung stretches — longest first, snapped to a downbeat, each
    capped to MAX_VOCAL_SECS. Falls back to a single best slice if regions are unknown."""
    regions = sorted(
        ((s, e) for s, e in a2.vocal_regions if e - s >= MIN_VOCAL_SECS),
        key=lambda r: r[1] - r[0], reverse=True,
    )[:limit]
    if not regions:
        return [best_vocal_slice(a2)]
    out: list[tuple[float, float]] = []
    for s, e in regions:
        start = min(a2.downbeats, key=lambda d: abs(d - s)) if a2.downbeats else s
        end = min(e, start + MAX_VOCAL_SECS)
        out.append((round(start, 3), round(max(end, start + MIN_VOCAL_SECS), 3)))
    return out


def section_at(a1: TrackAnalysis, t: float) -> str:
    """The Song-1 section label containing time t (or '' if unknown)."""
    for s in a1.sections:
        if s.start <= t < s.end:
            return s.label
    return ""


def arrangement_options(a1: TrackAnalysis, a2: TrackAnalysis) -> dict:
    """The legal menu for a full arrangement: the M3 legal set plus ranked phrase
    anchors and the available vocal slices. Declines pass through unchanged."""
    base = legal_options(a1, a2)
    if not base["mixable"]:
        return base
    slices = vocal_slices(a2)
    need = min(e - s for s, e in slices) * base["vocal_stretch"]
    anchors_ranked = candidate_drops(a1, need)  # best energy first, with runway
    track_end = (
        a1.beats[-1] if a1.beats
        else (max(anchors_ranked) + need if anchors_ranked else need)
    )
    return {
        **base,
        "anchors_ranked": anchors_ranked,
        "vocal_slices": slices,
        "track_end": track_end,  # the whole song's length, so the arrangement can span it
        "sections": [(s.start, s.label) for s in a1.sections],  # Song 1's shape, for the AI
    }


def rendered_vocal_secs(vocal_src: tuple[float, float], stretch: float) -> float:
    """How long a vocal slice actually plays after FFmpeg `atempo=stretch`.

    atempo changes tempo by `stretch`, so the OUTPUT duration is source_duration /
    stretch — NOT * stretch. The two only agree at stretch == 1.0; for stretch < 1
    (Song 2 faster than Song 1, so we slow it) the vocal plays *longer*. The single
    source of truth for a placed vocal's real length — the driver and the referee
    both call this so they can never drift onto different math (which shipped
    overlapping vocals in an earlier cut of M4).
    """
    return (vocal_src[1] - vocal_src[0]) / stretch if stretch > 0 else 0.0


def placement_end(anchor: float, vocal_src: tuple[float, float], stretch: float,
                  warp: list[tuple[float, float, float]] | None = None) -> float:
    """The real time (secs into the mix) a placed vocal finishes playing.

    With a per-bar `warp` map the vocal plays for exactly the sum of the bars' output
    lengths (each bar re-locked to Song 1's grid); without one it is the single-ratio
    rendered length. Both the driver and the referee call this, so they can never drift
    onto different math about where a placed vocal ends (the R1 no-overlap guarantee).
    """
    if warp:
        return anchor + sum(out_secs for _s, _e, out_secs in warp)
    return anchor + rendered_vocal_secs(vocal_src, stretch)


def warp_map(anchor: float, vocal_src: tuple[float, float],
             a1_downbeats: list[float], a2_downbeats: list[float], global_ratio: float,
             lo: float = SAFE_STRETCH_LO, hi: float = SAFE_STRETCH_HI
             ) -> list[tuple[float, float, float]]:
    """Per-bar phase-lock: map each Song-2 bar in the vocal slice onto the matching Song-1
    bar from the anchor, so every bar re-locks to the beat and drift can't accumulate
    (Handbook 9.6). Returns `(src_start, src_end, out_secs)` segments — take the vocal
    seconds `[src_start, src_end]` and stretch them to play for `out_secs`, which is the
    matching Song-1 bar's length, so each bar boundary lands on a Song-1 downbeat.

    A single global ratio can't stay aligned because real tempos wobble and BPM detection
    is imperfect; this maps bar-to-bar instead. A glitchy bar (a missing beat → an out-of-
    band local ratio) falls back to the global ratio for that bar (no warble). With too few
    downbeats to define bars, returns one global segment (the legacy behaviour).
    """
    s0, s1 = vocal_src
    d2 = [t for t in a2_downbeats if s0 - 1e-6 <= t <= s1 + 1e-6]
    d1 = [t for t in a1_downbeats if t >= anchor - 1e-6]
    if len(d2) < 2 or len(d1) < 2:
        return [(round(s0, 3), round(s1, 3), (s1 - s0) / global_ratio)]

    # Start the warp on Song 2's first downbeat inside the slice: any audio before it (a
    # mid-bar start — the AI path doesn't snap the slice) is dropped rather than emitted as a
    # leading partial, because a partial's length isn't a Song-1 bar and would shift EVERY
    # later boundary off the grid (the F1 defect: the referee then rejected good mixes).
    segs: list[tuple[float, float, float]] = []
    m = min(len(d2), len(d1))  # only map bars both grids can cover
    for k in range(m - 1):
        src_len = d2[k + 1] - d2[k]
        out_secs = d1[k + 1] - d1[k]  # the matching Song-1 bar length -> boundary locks to its downbeat
        if out_secs <= 0 or not (lo <= src_len / out_secs <= hi):
            return []  # a glitch bar can't lock without warbling or drifting -> fall back to legacy stretch
        segs.append((round(d2[k], 3), round(d2[k + 1], 3), round(out_secs, 4)))

    if s1 - d2[m - 1] > 1e-3:  # a trailing partial (the vocal's own tail) — the last boundary may be off-grid
        segs.append((round(d2[m - 1], 3), round(s1, 3), round((s1 - d2[m - 1]) / global_ratio, 4)))
    return segs


def contrast_windows(a1: TrackAnalysis, placements, stretch: float,
                     min_secs: float = 6.0, margin: float = 2.0) -> list[tuple[float, float]]:
    """The beat-only gaps between Song-2 placements where Song 1 *actually sings* — the
    only spots Song 1's own vocal can answer without ever overlapping Song 2's vocal.

    A gap runs from one placement's real end to the next placement's entry (plus the tail
    after the last one); each gap is shrunk by `margin` so it never touches a Song-2 vocal,
    then intersected with Song 1's own `vocal_regions`. Windows shorter than `min_secs` are
    dropped. This keeps the R1 "one voice at a time" guarantee true by construction.
    """
    if not placements:
        return []
    ordered = sorted(placements, key=lambda p: p.anchor)
    _end = lambda p: placement_end(p.anchor, p.vocal_src, stretch, getattr(p, "warp", None))
    last_end = _end(ordered[-1])
    track_end = a1.beats[-1] if a1.beats else last_end + min_secs

    gaps = [(_end(prev), nxt.anchor) for prev, nxt in zip(ordered, ordered[1:])]
    gaps.append((last_end, track_end))

    out: list[tuple[float, float]] = []
    for gap_start, gap_end in gaps:
        gs, ge = gap_start + margin, gap_end - margin
        if ge - gs < min_secs:
            continue
        for vs, ve in a1.vocal_regions:  # where Song 1 itself sings
            s, e = max(gs, vs), min(ge, ve)
            if e - s >= min_secs:
                out.append((round(s, 3), round(e, 3)))
                break  # one contrast window per gap is plenty
    return out
