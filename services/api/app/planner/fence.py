"""The fence: the deterministic 'legal, safe options' the brain chooses among.

Given both songs' TrackAnalysis, compute the moves that won't embarrass the mix —
phrase-aligned high-energy drop points, a safe tempo stretch, a clean vocal slice,
key compatibility. The AI driver (planner.plan) only ever picks from what this
returns; the referee (planner.validate) re-checks the result against the hard
rules. Everything here is straight from the DJ Judgment Handbook (Parts 2, 4, 9)
and needs no AI — it is pure, testable arithmetic over the analysis.
"""

from __future__ import annotations

from app.models import StemMove, TrackAnalysis

# Small stretches sound clean; big ones warble. Song 2's vocal is kept within this band
# of Song 1's tempo (atempo stays acceptable here); outside it we decline rather than ship
# a warbly voice (Handbook B3; also enforced per-bar by validate R7). Widened from ±8% to
# ±11% (2026-07-07) so the curated catalog's key-perfect but slightly-off-tempo vocals fit
# (Der Lagi Lekin 111 BPM ≈ +9.9%, Tujhe Bhula Diya 133 ≈ −8.3% against Father Ocean's 122).
# Trade-off: a bit more audible stretch on wide pairs — acceptable at validation scale.
SAFE_STRETCH_LO = 0.89
SAFE_STRETCH_HI = 1.11

# The house/EDM track is the anchor — slowing it kills its drive, so when a far-apart pair
# needs the movable master, the house moves the MINIMUM and is bounded here (never dragged
# down; a small nudge only). The guest vocal absorbs the rest of the stretch and sits near
# the edge of the safe band (recipe §1.5; founder call 2026-07-08). Tunable by ear.
HOUSE_SLOW_MAX = 0.04   # the house may slow at most 4%
HOUSE_SPEED_MAX = 0.08  # ...and speed at most 8%

# The per-bar beat-lock (warp_map / validate R7) grip band — DELIBERATELY WIDER than the global
# SAFE_STRETCH band. A per-bar stretch is a TRANSIENT single-bar correction (~1.7s) that snaps the
# vocal back onto Song 1's downbeat; the global band above governs the SUSTAINED overall stretch
# (which pairs mix / warble). When a pair's global stretch sits near a SAFE_STRETCH edge, its bars
# straddle that edge (measured: Tere Bina bars 0.874–0.894 at global 0.89; Der Lagi 1.086–1.112 at
# 1.099), so a grip band == the global band lets go and the vocal DRIFTS off the beat over a long
# placement. This wider grip holds every bar down; the extra per-bar excursion is brief and far
# preferable to sustained drift (founder call 2026-07-08). Tunable by ear.
WARP_LO = 0.85
WARP_HI = 1.15

# Cap the vocal slice so one long region can't dominate the whole mix — M3 is a
# single placement; a section-length drop stays punchy.
MAX_VOCAL_SECS = 40.0
MIN_VOCAL_SECS = 4.0

# A hand-off between the two vocals may overlap by up to this long — enough for the OUTGOING
# vocal's OWN natural phrase-end decay (e.g. "…alone…" ringing out) to keep sounding as the
# incoming lead enters underneath it (a real DJ blend, using the recording's own tail, not an
# imposed fade). It's the last sung word decaying, not a new lead, so a longer ring is still one
# lead — but bounded so the outgoing vocal can't run its NEXT words over the incoming lead. Beyond
# this the referee (R1) rejects it as two full lead voices (mud). Tunable by ear.
LEAD_XFADE_SECS = 1.2

_BARS_PER_PHRASE = 8  # 4/4 assumed in V1 (matches analysis.phrase_starts = downbeats[::8])


def best_stretch(master_bpm: float, source_bpm: float) -> tuple[float, bool]:
    """Ratio to stretch Song 2's vocal onto Song 1's tempo, and whether it's safe.

    Folds octaves (half/double-time) so a source the analyzer read at 2x or 0.5x
    still matches — we take the candidate closest to 1.0 (the least stretch). Safe
    when within the SAFE_STRETCH band (±11%; see the constant for the history).
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


def _fold_source(master_bpm: float, source_bpm: float) -> float:
    """Octave-fold the source BPM to the multiple (x0.5 / x1 / x2) nearest the master."""
    return min((source_bpm, source_bpm * 2, source_bpm / 2), key=lambda b: abs(b - master_bpm))


def tempo_plan(master_bpm: float, source_bpm: float,
               lo: float = SAFE_STRETCH_LO, hi: float = SAFE_STRETCH_HI,
               slow_max: float = HOUSE_SLOW_MAX, speed_max: float = HOUSE_SPEED_MAX
               ) -> tuple[float, float, float, bool]:
    """Choose the shared tempo for the pair, PROTECTING the house track (the movable master).

    Returns (master_bpm_out, bed_stretch, vocal_stretch, safe):
      - if the one-sided lock (house fixed) already fits the safe band -> native master
        (bed_stretch == 1.0), exactly today's behaviour; else
      - move the house the MINIMUM to bring the vocal back into band, bounded to
        [1-slow_max, 1+speed_max] (never dragged down; a small nudge only). The guest
        vocal absorbs the rest and sits at its band edge.
    `safe` is False (decline) when the house would have to move beyond its bounds.
    """
    if master_bpm <= 0 or source_bpm <= 0:
        return master_bpm, 1.0, 1.0, False
    src = _fold_source(master_bpm, source_bpm)
    one_sided = master_bpm / src
    if lo <= one_sided <= hi:
        return master_bpm, 1.0, round(one_sided, 4), True         # native master (today)
    t = min(max(master_bpm, lo * src), hi * src)                  # vocal-legal tempo nearest the house
    bed, voc = t / master_bpm, t / src
    safe = (1.0 - slow_max) - 1e-9 <= bed <= (1.0 + speed_max) + 1e-9
    return round(t, 3), round(bed, 4), round(voc, 4), safe


def retimed_analysis(a1: TrackAnalysis, target_bpm: float) -> TrackAnalysis:
    """Return a copy of a1 whose timeline is scaled to target_bpm (for the movable master:
    the house bed is stretched to target_bpm, so its grid must move with it). Pure arithmetic;
    the per-bar energy_curve is unchanged (only re-timestamped via the scaled downbeats). Both
    the planner and the referee call this, so they can never drift onto different grids. No-op
    if either bpm is missing/zero."""
    if not a1.bpm or a1.bpm <= 0 or target_bpm <= 0:
        return a1
    f = a1.bpm / target_bpm
    return a1.model_copy(update={
        "bpm": target_bpm,
        "beats": [round(t * f, 4) for t in a1.beats],
        "downbeats": [round(t * f, 4) for t in a1.downbeats],
        "phrase_starts": [round(t * f, 4) for t in a1.phrase_starts],
        "sections": [s.model_copy(update={"start": round(s.start * f, 4), "end": round(s.end * f, 4)})
                     for s in a1.sections],
        "vocal_regions": [(round(s * f, 4), round(e * f, 4)) for s, e in a1.vocal_regions],
    })


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


def _snap_and_cap(a2: TrackAnalysis, s: float, e: float) -> tuple[float, float]:
    """Snap a slice start to the nearest Song-2 downbeat, then cap its length to
    MAX_VOCAL_SECS (and floor it to MIN). Snap-then-cap is the single ordering used
    everywhere a slice is finalized, so no two paths produce different lengths."""
    start = min(a2.downbeats, key=lambda d: abs(d - s)) if a2.downbeats else s
    end = min(e, start + MAX_VOCAL_SECS)
    return round(start, 3), round(max(end, start + MIN_VOCAL_SECS), 3)


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
    return _snap_and_cap(a2, start, end)  # single source of truth for snap-to-downbeat + cap


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

    # Movable master (house-protective): pick the shared tempo, nudging the house the minimum
    # only when a pair would otherwise be declined. bed_stretch == 1.0 is today's native path.
    master_bpm, bed_stretch, vocal_stretch, safe = tempo_plan(a1.bpm, a2.bpm)
    if not safe:
        pct = round(abs(a1.bpm / _fold_source(a1.bpm, a2.bpm) - 1) * 100)
        return {
            "mixable": False,
            "reason": f"These two songs are too far apart in tempo (~{pct}% stretch) to blend cleanly.",
        }

    # Plan against the retimed grid when the house is stretched, so anchors/drops/warp land on
    # the beats the audio will actually play at. Identity (a1g is a1) on the native path.
    a1g = retimed_analysis(a1, master_bpm) if abs(bed_stretch - 1.0) >= 1e-6 else a1
    vocal_src = best_vocal_slice(a2)
    need = (vocal_src[1] - vocal_src[0]) * vocal_stretch
    drops = candidate_drops(a1g, need)
    if not drops:
        return {"mixable": False, "reason": "Couldn't find a spot in Song 1 with room for the vocal."}

    key_fit = (
        camelot_fit(a1.key.camelot, a2.key.camelot) if (a1.key and a2.key) else None
    )
    return {
        "mixable": True,
        "master_bpm": master_bpm,
        "bed_stretch": bed_stretch,
        "vocal_stretch": vocal_stretch,
        "vocal_src": vocal_src,
        "drops": drops,  # ranked best-first
        "key_fit": key_fit,
        "a1_grid": a1g,  # the (possibly retimed) grid to plan + warp + validate against
    }


_SUNG_LABELS = {"verse", "chorus", "prechorus", "pre-chorus", "bridge", "solo", "hook"}


def vocal_slices(a2: TrackAnalysis, limit: int = 4) -> list[tuple[float, float]]:
    """Song 2's strongest sung stretches — longest first, snapped to a downbeat, each
    capped to MAX_VOCAL_SECS.

    Falls back to the song's own labelled sections (verse/chorus/bridge/solo — never
    an intro/outro/instrumental) when vocal-region detection came up empty, which real
    analyses do surprisingly often (confirmed on 3 of the 4 real catalog vocal tracks).
    Without this, every placement — and every regenerate take — reused the exact same
    single fallback slice, since there was nothing else to choose from. Only when BOTH
    are unavailable does this fall back to one best-guess slice."""
    regions = sorted(
        ((s, e) for s, e in a2.vocal_regions if e - s >= MIN_VOCAL_SECS),
        key=lambda r: r[1] - r[0], reverse=True,
    )[:limit]
    if not regions:
        regions = sorted(
            ((s.start, s.end) for s in a2.sections
             if s.label.lower() in _SUNG_LABELS and s.end - s.start >= MIN_VOCAL_SECS),
            key=lambda r: r[1] - r[0], reverse=True,
        )[:limit]
    if not regions:
        return [best_vocal_slice(a2)]
    return [_snap_and_cap(a2, s, e) for s, e in regions]


# ---------------------------------------------------------------- energy detection (Step 2)
# The house × Bollywood recipe hinges on ENERGY SYNC: land the vocal's most powerful moment on
# the house track's DROP. These derive builds/drops/peaks straight from the already-cached
# per-bar energy curve — no re-analysis, no analysis.py change, works on the existing catalog.


def energy_drops(energy_curve: list[float], downbeats: list[float],
                 high: float = 0.6, min_rise: float = 0.15, look_back: int = 4) -> list[float]:
    """The house track's DROP moments: downbeat times where energy jumps up (a rise of at least
    `min_rise` over the preceding `look_back` bars) into a sustained-high stretch, after a quieter
    run. Consecutive high bars collapse to the single onset. A track that merely opens loud and
    stays loud has no drop (no low→high transition). Empty energy/grid → no drops."""
    drops: list[float] = []
    n = min(len(energy_curve), len(downbeats))
    in_drop = False
    for i in range(n):
        e = energy_curve[i]
        if e < high:
            in_drop = False
            continue
        window = energy_curve[max(0, i - look_back):i]
        rose = bool(window) and (e - sum(window) / len(window)) >= min_rise
        if rose and not in_drop:
            drops.append(downbeats[i])
        in_drop = True
    return drops


def synced_anchors(anchors_ranked: list[float], drops: list[float], track_end: float,
                   count: int = 3, take: int = 1) -> list[float]:
    """Energy-synced arc: one vocal entry per third, PREFERRING a real drop in that third (so the
    vocal lands on the house drop — recipe R1), and falling back to the loudest phrase-anchor in
    that third when the third has no detected drop. Same whole-song span guarantee as `arc_anchors`
    (every band gets an entry, backfilled if sparse), just drop-aware. `take` rotates the pick
    within a band for Regenerate variety. Returns anchors in time order."""
    if not anchors_ranked or track_end <= 0:
        return sorted(anchors_ranked)
    if len(anchors_ranked) <= count and not drops:
        return sorted(anchors_ranked)
    picks: list[float] = []
    for i in range(count):
        lo, hi = track_end * i / count, track_end * (i + 1) / count
        band_drops = [d for d in drops if lo <= d < hi]  # a real drop in this third wins
        if band_drops:
            picks.append(band_drops[(take - 1) % len(band_drops)])
            continue
        band_anchors = [a for a in anchors_ranked if lo <= a < hi]  # energy-desc within the band
        if band_anchors:
            picks.append(band_anchors[(take - 1) % len(band_anchors)])
    if len(picks) < count:  # sparse -> backfill the loudest unused anchor (like arc_anchors)
        for a in anchors_ranked:
            if a not in picks:
                picks.append(a)
            if len(picks) >= count:
                break
    return sorted(set(picks))


def _region_energy(a2: TrackAnalysis, s: float, e: float) -> float:
    """Mean per-bar energy of the bars inside [s, e) — how POWERFUL a sung stretch is."""
    if not (a2.downbeats and a2.energy_curve):
        return 0.0
    vals = [a2.energy_curve[i] for i, d in enumerate(a2.downbeats)
            if i < len(a2.energy_curve) and s - 1e-6 <= d < e - 1e-6]
    return sum(vals) / len(vals) if vals else 0.0


def vocal_peaks(a2: TrackAnalysis, limit: int = 4) -> list[tuple[float, float]]:
    """Song 2's most POWERFUL sung stretches — loudest first, snapped to a downbeat and capped.
    This is what lands on the house drop (recipe R1). Same fallback ladder as `vocal_slices`
    (labelled sung sections, then a single best-guess slice) when vocal regions are missing —
    but ranked by loudness (power), not length."""
    regions = [(s, e) for s, e in a2.vocal_regions if e - s >= MIN_VOCAL_SECS]
    if not regions:
        regions = [(sec.start, sec.end) for sec in a2.sections
                   if sec.label.lower() in _SUNG_LABELS and sec.end - sec.start >= MIN_VOCAL_SECS]
    if not regions:
        return [best_vocal_slice(a2)]
    ranked = sorted(regions, key=lambda r: _region_energy(a2, r[0], r[1]), reverse=True)[:limit]
    return [_snap_and_cap(a2, s, e) for s, e in ranked]


def predrop_licks(a1: TrackAnalysis, placements, stretch: float,
                  max_lick: float = 4.0, min_lick: float = 1.5) -> list[tuple[float, float]]:
    """Keep Song 1's short vocal 'lick' in the seconds right BEFORE each Song-2 entry — the
    vocal-that-leads-into-the-drop a real DJ never cuts. Each is clipped to END at the entry so it
    hands off the instant Song 2 drops in (no overlap — one lead at a time, R1). Only where Song 1
    actually sings within `max_lick` of the entry, and only if at least `min_lick` long (so it's a
    real lick, not a sliver). This is the judgment upgrade: a short bit against a drop is NOT a
    throwaway scrap — it's the most important vocal to keep."""
    out: list[tuple[float, float]] = []
    for p in placements:
        a = p.anchor
        for vs, ve in a1.vocal_regions:
            # Song 1's vocal in the run-up, running a crossfade PAST the entry so it fades out as
            # Song 2 comes in (the vocal-into-the-drop blend) — bounded to LEAD_XFADE_SECS.
            s, e = max(vs, a - max_lick), min(ve, a + LEAD_XFADE_SECS)
            if min(e, a) - s >= min_lick:  # a real lick BEFORE the entry (not just a crossfade tail)
                # Clamp the end so rounding to 3 dp can't push it PAST the crossfade boundary
                # (a + LEAD_XFADE_SECS). A retimed (movable-master) anchor is a non-round number
                # whose a+XFADE rounds up ~5e-4, beyond the referee's 1e-6 crossfade tolerance —
                # which would wrongly flag the lick and decline the pair.
                out.append((round(s, 3), min(round(e, 3), a + LEAD_XFADE_SECS)))
    return out


def arrangement_options(a1: TrackAnalysis, a2: TrackAnalysis) -> dict:
    """The legal menu for a full arrangement: the M3 legal set plus ranked phrase
    anchors and the available vocal slices. Declines pass through unchanged."""
    base = legal_options(a1, a2)
    if not base["mixable"]:
        return base
    a1g = base["a1_grid"]  # the retimed grid (== a1 on the native path); everything grid-derived uses it
    slices = vocal_slices(a2)
    need = min(e - s for s, e in slices) * base["vocal_stretch"]
    anchors_ranked = candidate_drops(a1g, need)  # best energy first, with runway
    track_end = (
        a1g.beats[-1] if a1g.beats
        else (max(anchors_ranked) + need if anchors_ranked else need)
    )
    return {
        **base,
        "anchors_ranked": anchors_ranked,
        "vocal_slices": slices,
        "vocal_peaks": vocal_peaks(a2),  # Song 2's strongest slices, loudest first (recipe R1)
        "drops": energy_drops(a1g.energy_curve, a1g.downbeats),  # the house track's real drops
        "track_end": track_end,  # the whole song's length, so the arrangement can span it
        "sections": [(s.start, s.label) for s in a1g.sections],  # Song 1's shape, for the AI
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
             lo: float = WARP_LO, hi: float = WARP_HI
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


def _merge_regions(regions: list[tuple[float, float]], max_gap: float = 4.0) -> list[tuple[float, float]]:
    """Merge vocal regions separated by <= max_gap seconds (a breath between sung phrases) into
    one continuous passage, so a real sung passage isn't seen as a string of short scraps."""
    if not regions:
        return []
    rs = sorted((float(s), float(e)) for s, e in regions)
    merged = [list(rs[0])]
    for s, e in rs[1:]:
        if s - merged[-1][1] <= max_gap:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged]


def lead_sections(a1: TrackAnalysis, placements, stretch: float,
                  min_secs: float = 10.0, margin: float = 2.0, max_leads: int = 3) -> list[tuple[float, float]]:
    """Where Song 1 (the house track) LEADS with its OWN vocal — its substantial sung passages
    that fall in the beat-only gaps between Song 2's placements, so the two songs TRADE the lead
    (one voice at a time). This is the both-vocals move: Song 1's vocal is a real, central part,
    not stripped.

    A gap runs from one Song-2 placement's real end to the next entry (plus the tail after the
    last), shrunk by `margin` so it never touches a Song-2 vocal (the R1 guarantee, by
    construction). Song 1's own vocal regions are merged across breaths into passages; a passage
    clipped to a gap is kept only if it is still >= min_secs (a real lead, not a throwaway scrap —
    the founder's keep-or-drop judgment). Returned longest-first, capped at `max_leads`.
    """
    passages = _merge_regions(list(a1.vocal_regions))
    if not passages:
        return []
    track_end = a1.beats[-1] if a1.beats else 0.0
    if placements:
        ordered = sorted(placements, key=lambda p: p.anchor)
        _end = lambda p: placement_end(p.anchor, p.vocal_src, stretch, getattr(p, "warp", None))
        last_end = _end(ordered[-1])
        if not track_end:
            track_end = last_end + min_secs
        gaps = [(_end(prev), nxt.anchor) for prev, nxt in zip(ordered, ordered[1:])]
        gaps.append((last_end, track_end))
    else:  # no Song-2 vocal at all -> Song 1 can lead across the whole track
        if not track_end:
            track_end = max(e for _s, e in passages)
        gaps = [(0.0, track_end)]

    out: list[tuple[float, float]] = []
    for gap_start, gap_end in gaps:
        gs, ge = gap_start + margin, gap_end - margin
        if ge - gs < min_secs:
            continue
        for ps, pe in passages:  # where Song 1 itself sings a real passage
            s, e = max(gs, ps), min(ge, pe)
            if e - s >= min_secs:
                out.append((round(s, 3), round(e, 3)))
    out.sort(key=lambda r: r[1] - r[0], reverse=True)  # the biggest lead moments first
    return out[:max_leads]


# ---------------------------------------------------------------- stem dynamics (Step 3)
# The "mixing board": auto-perform Song 1's bed stems so the beat MOVES like a DJ set instead of
# sitting flat under the vocal (recipe §2.6 "PRODUCE, don't assemble"). Every produced drop is a
# 3-stage tension arc, all via the one StemMove primitive:
#   1. CUT (Wave 2) — bass + melody ("other") held fully muted for _CUT_BARS bars: just the drums
#      driving alone, a stripped-back breather before the build (the "drop to just the beat" move).
#   2. BUILD (unchanged, render.py) — drums + melody filter/volume-climb across the drop's BUILD
#      window; bass stays held muted through this too (one continuous mute, not a fading ramp — a
#      guaranteed silence regardless of how loud the source bass happens to be beforehand).
#   3. SLAM — right at the anchor, the ~8ms declick snaps bass back to full with the vocal, and the
#      melody is already back up from the build — so everything lands together on the beat.
# Everything is on-beat by construction (windows are real Song-1 downbeats) and additive: no
# produced drops => no moves => today's flat bed.

_CUT_BARS = 2  # bars of "just the beat" (bass+melody muted, drums alone) right before the build


def stem_moves_for_drops(placements, a1_downbeats: list[float], stretch: float = 1.0) -> list[StemMove]:
    """Auto-perform every produced drop's beat: a `bass` StemMove held silent (gain 0->0, not a
    fading ramp) across [the cut start, the anchor] so it SLAMS to full only at the anchor, and — when
    there's real runway — an `other` StemMove muted across [the cut start, the build start] so the
    melody drops out too, leaving just the drums for `_CUT_BARS` bars (the "drop to just the beat"
    breather) before the build climbs. Both windows are taken from Song 1's REAL downbeat grid (not
    bpm arithmetic), so every edge is on-beat by construction (referee R3), and the cut is clamped to
    never reach back over the PREVIOUS placement's real vocal end (`fence.placement_end`) — the same
    guard the engine's own build window uses, so a close prior vocal simply shortens or skips the cut
    rather than talking over it.

    One `bass` move per drop, held silent for its whole cut+build span (rather than one move per
    stage), so there is no seam where the two would otherwise touch: two independent moves on the
    same stem, each computing its own ramp, would leave bass jump to 1.0 for an instant at the join —
    an audible pop right in the middle of the build. Holding it as one continuous mute keeps the
    envelope's decline-into-silence exact and click-free (the engine's existing declick logic).

    Returns [] when there are no produced drops or no grid — the bed then stays flat (today's mix).
    The caller gates this on a confident grid; a produced drop only exists on one anyway.
    """
    if not a1_downbeats:
        return []
    moves: list[StemMove] = []
    ordered = sorted(placements, key=lambda pl: pl.anchor)
    for i, p in enumerate(ordered):
        build_bars = getattr(p, "build_bars", 0)
        if build_bars <= 0:  # only produced drops get the tension arc; a plain entry stays untouched
            continue
        anchor_i = min(range(len(a1_downbeats)), key=lambda k: abs(a1_downbeats[k] - p.anchor))
        build_start_i = max(0, anchor_i - build_bars)  # step back build_bars WHOLE bars, on the real grid
        anchor = a1_downbeats[anchor_i]
        build_start = a1_downbeats[build_start_i]
        if build_start >= anchor:  # anchor at/near the very start — no runway for a build; skip
            continue
        cut_start_i = max(0, build_start_i - _CUT_BARS)  # step back _CUT_BARS MORE bars for the cut
        if i > 0:  # never reach back over the PREVIOUS placement's real vocal tail
            prev = ordered[i - 1]
            prev_end = placement_end(prev.anchor, prev.vocal_src, stretch, getattr(prev, "warp", None))
            while cut_start_i < build_start_i and a1_downbeats[cut_start_i] < prev_end - 1e-6:
                cut_start_i += 1
        cut_start = a1_downbeats[cut_start_i]
        # the bass stays silent across the WHOLE cut+build span (one move, no seam) — it slams to
        # full only at the anchor. If there's no cut room (a close prior vocal), the bass move still
        # covers the build window alone, exactly as Wave 1 did.
        moves.append(StemMove(stem="bass", start=round(cut_start, 3), end=round(anchor, 3),
                              gain_from=0.0, gain_to=0.0))
        if cut_start_i < build_start_i:  # real cut room -> mute the melody too, just for the cut stretch
            moves.append(StemMove(stem="other", start=round(cut_start, 3), end=round(build_start, 3),
                                  gain_from=0.0, gain_to=0.0))
    return moves
