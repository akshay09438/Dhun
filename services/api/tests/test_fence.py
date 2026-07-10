"""Tests for the fence — the deterministic 'legal, safe options' layer.

Pure arithmetic over a TrackAnalysis, so no audio, no network: fast and exact.
"""

from app.models import KeyInfo, Placement, Section, TrackAnalysis
from app.planner import fence


def make_analysis(bpm=120.0, n_bars=32, key="8A", vocal_regions=None,
                  energy=None, sections=None):
    beat = 60.0 / bpm
    n_beats = n_bars * 4
    beats = [round(i * beat, 3) for i in range(n_beats)]
    downbeats = beats[::4]
    phrase_starts = downbeats[::8]
    energy_curve = energy if energy is not None else [0.5] * len(downbeats)
    return TrackAnalysis(
        song_id="x" * 64, status="ready", bpm=bpm, beats=beats,
        downbeats=downbeats, phrase_starts=phrase_starts,
        key=KeyInfo(camelot=key, tonic="A", mode="minor", confidence=0.7),
        sections=sections or [], energy_curve=energy_curve,
        vocal_regions=vocal_regions or [],
    )


def test_best_stretch_safe_band():
    ratio, safe = fence.best_stretch(120.0, 122.0)
    assert 0.97 < ratio < 1.0 and safe


def test_best_stretch_too_far_is_unsafe():
    ratio, safe = fence.best_stretch(120.0, 150.0)
    assert not safe and ratio < fence.SAFE_STRETCH_LO


def test_best_stretch_folds_half_time():
    # a source the analyzer read at half tempo (61) still matches 122-ish cleanly
    ratio, safe = fence.best_stretch(120.0, 61.0)
    assert safe and 0.95 < ratio < 1.0


def test_best_stretch_guards_zero():
    assert fence.best_stretch(120.0, 0.0) == (1.0, False)


def test_tempo_plan_in_band_keeps_house_native():
    m, bed, voc, safe = fence.tempo_plan(122.0, 111.0)  # +9.9% one-sided, in band
    assert safe and bed == 1.0 and m == 122.0 and 1.08 < voc < 1.11


def test_tempo_plan_protects_house_for_a_fast_guest():
    # 122 house x 144 guest (Tere Bina): house moves the MINIMUM and only UP; vocal to band edge.
    m, bed, voc, safe = fence.tempo_plan(122.0, 144.0)
    assert safe
    assert 1.0 < bed <= 1.0 + fence.HOUSE_SPEED_MAX + 1e-9   # house sped up, within its cap
    assert abs(voc - fence.SAFE_STRETCH_LO) < 1e-3            # vocal parked at its slow edge
    assert abs(m - bed * 122.0) < 0.05                        # master == house_bpm * bed_stretch


def test_tempo_plan_octave_folds_a_half_counted_ballad():
    # a 72-BPM ballad read as 72 folds to 144 (nearest 122) -> same result as 144
    assert fence.tempo_plan(122.0, 72.0) == fence.tempo_plan(122.0, 144.0)


def test_tempo_plan_declines_when_house_would_move_too_far():
    # 120 x 150: house would need > +8% to reach the vocal's band -> declined (house protected)
    assert fence.tempo_plan(120.0, 150.0)[3] is False


def test_tempo_plan_guards_zero():
    assert fence.tempo_plan(122.0, 0.0)[3] is False


def test_retimed_analysis_scales_grid_to_target_tempo():
    a1 = make_analysis(bpm=122.0, n_bars=16, vocal_regions=[(10.0, 20.0)],
                       sections=[Section(start=0.0, end=8.0, label="intro")])
    r = fence.retimed_analysis(a1, 128.16)          # house sped up (bed_stretch ~1.05)
    f = 122.0 / 128.16
    assert r.bpm == 128.16
    assert abs(r.downbeats[1] - a1.downbeats[1] * f) < 1e-3   # every downbeat pulled in
    assert abs(r.vocal_regions[0][0] - 10.0 * f) < 1e-3
    assert abs(r.sections[0].end - 8.0 * f) < 1e-3
    assert r.energy_curve == a1.energy_curve         # per-bar values unchanged
    assert a1.downbeats[1] != r.downbeats[1]          # original left untouched (a copy)


def test_arrangement_options_engages_movable_master_for_tere_bina_shape():
    a1 = make_analysis(bpm=122.0, n_bars=64, vocal_regions=[(20.0, 40.0)])
    a2 = make_analysis(bpm=144.0, n_bars=64, vocal_regions=[(16.0, 40.0)])
    opts = fence.arrangement_options(a1, a2)
    assert opts["mixable"]
    assert opts["bed_stretch"] > 1.0                      # house nudged up (never slowed)
    assert opts["master_bpm"] > 122.0                     # shared tempo above the house's own
    assert opts["a1_grid"].bpm == opts["master_bpm"]      # planning grid is the retimed one


def test_arrangement_options_in_band_pair_stays_native():
    a1 = make_analysis(bpm=122.0, n_bars=64, vocal_regions=[(20.0, 40.0)])
    a2 = make_analysis(bpm=118.0, n_bars=64, vocal_regions=[(16.0, 40.0)])
    opts = fence.arrangement_options(a1, a2)
    assert opts["bed_stretch"] == 1.0 and opts["master_bpm"] == 122.0
    assert opts["a1_grid"] is a1                          # untouched grid, today's path


def test_candidate_drops_ranks_by_energy():
    energy = [0.3] * 32
    for i in range(8, 16):  # the second phrase (bars 8..15) is the loudest
        energy[i] = 0.9
    a1 = make_analysis(bpm=120.0, n_bars=32, energy=energy)
    drops = fence.candidate_drops(a1, need_secs=4.0)
    assert drops[0] == 16.0  # phrase 2 starts at bar 8 -> 16.0s, highest energy


def test_candidate_drops_respects_runway():
    a1 = make_analysis(bpm=120.0, n_bars=32)  # track ends ~62s
    drops = fence.candidate_drops(a1, need_secs=40.0)
    assert 32.0 not in drops and 48.0 not in drops  # no room for a 40s vocal there
    assert all(t + 40.0 <= a1.beats[-1] + 1e-6 for t in drops)


def test_candidate_drops_falls_back_to_downbeats():
    a1 = make_analysis()
    a1.phrase_starts = []  # phrases untrusted -> anchor on any downbeat
    drops = fence.candidate_drops(a1, need_secs=4.0)
    assert drops and set(drops) <= set(a1.downbeats)


def test_best_vocal_slice_picks_longest_and_snaps():
    a2 = make_analysis(vocal_regions=[(3.1, 9.0), (20.0, 40.0)])
    start, end = fence.best_vocal_slice(a2)
    assert start == 20.0 and end == 40.0  # longest region, already on a downbeat


def test_best_vocal_slice_caps_length():
    a2 = make_analysis(vocal_regions=[(10.0, 100.0)])
    start, end = fence.best_vocal_slice(a2)
    assert end - start <= fence.MAX_VOCAL_SECS + 1e-6


def test_best_vocal_slice_falls_back_to_chorus():
    a2 = make_analysis(vocal_regions=[], sections=[Section(start=8.0, end=24.0, label="chorus")])
    start, end = fence.best_vocal_slice(a2)
    assert start == 8.0 and end == 24.0


def test_camelot_fit():
    assert fence.camelot_fit("8A", "8A")
    assert fence.camelot_fit("8A", "9A")   # +1
    assert fence.camelot_fit("8A", "10A")  # +2
    assert fence.camelot_fit("8A", "8B")   # relative major/minor
    assert fence.camelot_fit("1A", "12A")  # wraps the clock
    assert not fence.camelot_fit("8A", "11A")  # +3 is a clash
    assert not fence.camelot_fit("8A", "3B")


def test_legal_options_happy_path():
    a1 = make_analysis(bpm=120.0)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(16.0, 40.0)])
    opts = fence.legal_options(a1, a2)
    assert opts["mixable"]
    assert opts["master_bpm"] == 120.0
    assert 0.97 < opts["vocal_stretch"] < 1.05
    assert opts["drops"] and opts["vocal_src"][1] > opts["vocal_src"][0]


def test_legal_options_declines_far_tempo():
    a1 = make_analysis(bpm=120.0)
    a2 = make_analysis(bpm=150.0, vocal_regions=[(16.0, 40.0)])
    opts = fence.legal_options(a1, a2)
    assert not opts["mixable"] and "tempo" in opts["reason"].lower()


def test_legal_options_declines_no_beat():
    a1 = make_analysis()
    a1.bpm, a1.beats, a1.downbeats, a1.phrase_starts = 0.0, [], [], []
    a2 = make_analysis(vocal_regions=[(16.0, 40.0)])
    opts = fence.legal_options(a1, a2)
    assert not opts["mixable"] and "beat" in opts["reason"].lower()


def test_vocal_slices_ranked_and_capped():
    a2 = make_analysis(vocal_regions=[(8.0, 14.0), (20.0, 60.0), (70.0, 76.0)])
    slices = fence.vocal_slices(a2)
    assert slices[0][1] - slices[0][0] <= fence.MAX_VOCAL_SECS + 1e-6  # capped
    assert len(slices) >= 2 and slices[0][0] == 20.0  # longest first, snapped to a downbeat


def test_vocal_slices_falls_back_to_sections_when_regions_missing():
    """Real analyses sometimes detect ZERO vocal_regions even on a song that clearly has
    sung sections (confirmed on 3 of the 4 real catalog vocal tracks). Without this
    fallback, `vocal_slices` returned a single slice (`best_vocal_slice`'s one chorus),
    so every placement AND every regenerate reused the exact same short vocal excerpt —
    the real "vocals are always short and never unique" complaint."""
    a2 = make_analysis(bpm=120.0, n_bars=64, vocal_regions=[], sections=[
        Section(start=4.0, end=20.0, label="intro"),   # not sung — must be excluded
        Section(start=20.0, end=36.0, label="verse"),
        Section(start=36.0, end=52.0, label="chorus"),
        Section(start=52.0, end=68.0, label="chorus"),
        Section(start=68.0, end=84.0, label="bridge"),
        Section(start=84.0, end=90.0, label="outro"),  # not sung — must be excluded
    ])
    slices = fence.vocal_slices(a2)
    assert len(slices) >= 3  # multiple real candidates, not a single fallback slice
    starts = {s for s, _ in slices}
    assert not any(4.0 <= s < 20.0 for s in starts)  # the intro is never offered as vocal


def test_arrangement_options_happy():
    energy = [0.3] * 32
    for i in range(8, 16):
        energy[i] = 0.9
    a1 = make_analysis(bpm=120.0, n_bars=32, energy=energy)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(16.0, 40.0), (60.0, 80.0)])
    opts = fence.arrangement_options(a1, a2)
    assert opts["mixable"]
    assert opts["anchors_ranked"] and opts["anchors_ranked"][0] == 16.0
    assert len(opts["vocal_slices"]) >= 1


def test_arrangement_options_declines_far_tempo():
    a1 = make_analysis(bpm=120.0)
    a2 = make_analysis(bpm=150.0, vocal_regions=[(16.0, 40.0)])
    assert not fence.arrangement_options(a1, a2)["mixable"]


def test_lead_sections_merges_a_passage_and_drops_scraps():
    """Both-vocals trade (Step 1): Song 1 LEADS its own substantial sung passages in the gaps
    between Song 2's placements. Adjacent Song-1 regions split by a breath merge into one passage;
    a real lead (>= min_secs) is kept, a tiny scrap is dropped."""
    # Song 1 sings a passage 40-77 (3 regions, breaths bridged) + a 4s scrap at 100.
    a1 = make_analysis(bpm=120.0, n_bars=64,
                       vocal_regions=[(40.0, 54.0), (56.0, 67.0), (70.0, 77.0), (100.0, 104.0)])
    placements = [Placement(anchor=10.0, vocal_src=(0.0, 8.0)),   # ends 18
                  Placement(anchor=110.0, vocal_src=(0.0, 8.0))]  # gap 18-110
    leads = fence.lead_sections(a1, placements, stretch=1.0)
    assert leads, "Song 1 should lead its real passage"
    assert leads[0][0] <= 41.0 and leads[0][1] >= 76.0     # the merged 40-77 passage, not a fragment
    assert all(e - s >= 10.0 for s, e in leads)            # only substantial leads (the 4s scrap dropped)


def test_lead_sections_never_overlap_a_placement():
    """One lead at a time (R1): every Song-1 lead sits strictly in a beat-only gap, never over a
    Song-2 vocal."""
    a1 = make_analysis(bpm=120.0, n_bars=64, vocal_regions=[(0.0, 200.0)])  # S1 sings throughout
    placements = [Placement(anchor=20.0, vocal_src=(0.0, 10.0)),   # ends 30
                  Placement(anchor=60.0, vocal_src=(0.0, 10.0))]   # ends 70
    leads = fence.lead_sections(a1, placements, stretch=1.0)
    assert leads
    for ls, le in leads:
        for p in placements:
            pe = fence.placement_end(p.anchor, p.vocal_src, 1.0, None)
            assert le <= p.anchor + 1e-6 or ls >= pe - 1e-6  # strictly in a gap


def test_predrop_licks_keeps_song1_vocal_into_the_drop():
    """A real DJ never cuts the vocal just before the drop. Keep Song 1's vocal 'lick' in the
    seconds before a Song-2 entry, and let it run a crossfade-length PAST the entry so it fades
    out AS Song 2 comes in (the vocal-into-the-drop blend)."""
    a1 = make_analysis(bpm=120.0, n_bars=64, vocal_regions=[(100.0, 106.0)])  # FO sings 100-106
    placements = [Placement(anchor=104.0, vocal_src=(0.0, 8.0))]              # Song 2 drops at 104
    licks = fence.predrop_licks(a1, placements, stretch=1.0)
    assert licks[0][0] == 100.0                                       # from where FO starts
    assert 104.0 < licks[0][1] <= 104.0 + fence.LEAD_XFADE_SECS + 1e-6  # runs a crossfade past the drop


def test_predrop_licks_extend_only_a_crossfade_past_the_entry():
    """The overlap is bounded to a crossfade — Song 1's vocal can't run a long way into Song 2's
    lead (that would be two full voices, not a fade blend)."""
    a1 = make_analysis(bpm=120.0, n_bars=64, vocal_regions=[(100.0, 130.0)])  # FO sings well past the drop
    placements = [Placement(anchor=104.0, vocal_src=(0.0, 8.0))]
    licks = fence.predrop_licks(a1, placements, stretch=1.0)
    assert licks and all(e <= 104.0 + fence.LEAD_XFADE_SECS + 1e-6 for _s, e in licks)  # bounded


def test_predrop_licks_end_stays_within_the_crossfade_after_rounding():
    """Movable-master regression: with a non-round (retimed) anchor, a + LEAD_XFADE_SECS can round
    UP past the crossfade boundary, and the referee (1e-6 tolerance) then flags the lick as beyond a
    crossfade — wrongly declining the pair. The lick end must never exceed a + LEAD_XFADE_SECS."""
    a = 359.7238  # a retimed downbeat; a + 1.2 = 360.9238 -> round(_, 3) = 360.924 (rounds UP)
    a1 = make_analysis(vocal_regions=[(a - 3.0, a + 10.0)])  # Song 1 sings through the entry
    placements = [Placement(anchor=a, vocal_src=(0.0, 8.0))]
    licks = fence.predrop_licks(a1, placements, stretch=1.0)
    assert licks
    assert all(e <= a + fence.LEAD_XFADE_SECS + 1e-6 for _s, e in licks)  # within the referee's tolerance


def test_predrop_licks_ignores_when_song1_silent_before_the_drop():
    a1 = make_analysis(bpm=120.0, n_bars=64, vocal_regions=[(10.0, 20.0)])  # FO sings only early
    placements = [Placement(anchor=104.0, vocal_src=(0.0, 8.0))]
    assert fence.predrop_licks(a1, placements, stretch=1.0) == []


def test_lead_sections_empty_when_song1_has_no_real_passage():
    a1 = make_analysis(bpm=120.0, n_bars=64, vocal_regions=[(0.0, 6.0)])  # only a short scrap early
    placements = [Placement(anchor=16.0, vocal_src=(0.0, 12.0)),
                  Placement(anchor=90.0, vocal_src=(0.0, 12.0))]
    assert fence.lead_sections(a1, placements, stretch=1.0) == []


def test_arc_anchors_spreads_across_thirds():
    # anchors evenly across a 240s track -> the arc must take one per third, so the
    # vocal reaches the whole song (a strong entry near the end), never clustered.
    anchors = [float(t) for t in range(0, 240, 16)]  # 0,16,...,224
    picks = fence.arc_anchors(anchors, track_end=240.0, count=3)
    assert len(picks) == 3
    assert picks[0] < 80.0             # first third
    assert 80.0 <= picks[1] < 160.0    # middle third
    assert picks[2] >= 160.0           # final third — the strong finish


def test_arc_anchors_rotates_with_take_for_variety():
    anchors = [0.0, 20.0, 100.0, 200.0]  # first band [0,80) has two options to rotate
    a = fence.arc_anchors(anchors, track_end=240.0, count=3, take=1)
    b = fence.arc_anchors(anchors, track_end=240.0, count=3, take=2)
    assert a != b  # Regenerate gets a genuinely different pick within a band


def test_arc_anchors_falls_back_when_too_few():
    # fewer anchors than placements -> just use what's there (short songs are limited)
    assert fence.arc_anchors([10.0, 20.0], track_end=240.0, count=3) == [10.0, 20.0]


def _jittered_downbeats(bpm, n, jitter):
    """A realistic beatgrid whose bars are NOT a perfect metronome (each bar length
    wobbles by +/- jitter), so a single global stretch ratio can't stay aligned."""
    bar = 60.0 / bpm * 4
    t, out = 0.0, []
    for k in range(n):
        out.append(round(t, 4))
        t += bar * (1.0 + (jitter if k % 2 else -jitter))  # alternate long/short bars
    return out


def test_warp_map_locks_each_bar_to_song1_downbeats():
    d1 = _jittered_downbeats(122.0, 24, 0.02)   # Song 1 bars, slightly irregular
    d2 = _jittered_downbeats(125.0, 24, 0.03)   # Song 2 bars, differently irregular
    anchor = d1[0]
    s0, s1 = d2[0], d2[10]                        # a 10-bar vocal slice
    ratio, _ = fence.best_stretch(122.0, 125.0)

    segs = fence.warp_map(anchor, (s0, s1), d1, d2, ratio)

    # every bar boundary (cumulative out_secs from the anchor) lands on a Song-1 downbeat
    cum = anchor
    for i, (_a, _b, out_secs) in enumerate(segs):
        cum += out_secs
        nearest = min(d1, key=lambda t: abs(t - cum))
        assert abs(cum - nearest) <= 0.03, f"bar {i} boundary off the grid by {cum - nearest:.3f}s"


def test_warp_map_beats_the_single_ratio_drift():
    # The real failure mode: Song 2's DETECTED bpm (125) is a bit off from its true tempo
    # (~123.5 here), so the single global ratio computed from the detection is systematically
    # wrong and the vocal walks off the beat — exactly what was measured (315 ms over 40 s).
    d1 = _jittered_downbeats(122.0, 24, 0.02)
    d2 = _jittered_downbeats(123.5, 24, 0.03)          # Song 2's TRUE grid
    anchor, ratio = d1[0], fence.best_stretch(122.0, 125.0)[0]  # ratio from the (wrong) detection
    s0, s1 = d2[0], d2[10]

    old_end = anchor + (d2[10] - s0) / ratio           # single global ratio
    old_drift = abs(old_end - d1[10])

    segs = fence.warp_map(anchor, (s0, s1), d1, d2, ratio)  # per-bar re-lock, uses the true grid
    new_end = anchor + sum(o for _, _, o in segs)
    new_drift = abs(new_end - d1[10])

    assert old_drift > 0.1        # the single ratio drifts badly (detection ≠ true tempo)
    assert new_drift <= 0.03      # the per-bar re-lock stays glued to Song 1's grid


def test_warp_map_grips_bars_near_the_stretch_edge():
    """Regression (drift fix): at a global stretch near the SAFE_STRETCH edge (e.g. Tere Bina at
    0.89), the per-bar ratios sit in [WARP_LO, SAFE_STRETCH_LO) (~0.87). The WIDER grip band must
    still LOCK them (a populated warp) instead of bailing to [] — an empty warp means a single
    global stretch that drifts off the beat over a long placement (what the founder heard at 4:18)."""
    bar1 = 60.0 / 122.0 * 4       # a Song 1 bar
    bar2 = 0.87 * bar1            # Song 2 bar -> per-bar ratio 0.87, BELOW the old 0.89 floor
    d1 = [round(i * bar1, 4) for i in range(12)]
    d2 = [round(i * bar2, 4) for i in range(12)]
    segs = fence.warp_map(d1[0], (d2[0], d2[10]), d1, d2, 0.87)
    assert segs, "beat-lock must engage near the edge (was [] with the tight band -> drift)"
    for s0, s1, out_secs in segs:
        assert fence.WARP_LO - 1e-6 <= (s1 - s0) / out_secs <= fence.WARP_HI + 1e-6


def test_warp_map_thin_grid_falls_back_to_one_global_segment():
    segs = fence.warp_map(10.0, (0.0, 20.0), [10.0], [0.0], 0.98)  # <2 downbeats each side
    assert segs == [(0.0, 20.0, round(20.0 / 0.98, 4))] or segs == [(0.0, 20.0, 20.0 / 0.98)]


def test_warp_map_keeps_every_ratio_in_the_safe_band():
    d1 = _jittered_downbeats(122.0, 24, 0.02)
    d2 = _jittered_downbeats(125.0, 24, 0.03)
    del d2[5]  # a missing downbeat -> one double-length bar (a grid glitch)
    segs = fence.warp_map(d1[0], (d2[0], d2[10]), d1, d2, fence.best_stretch(122.0, 125.0)[0])
    for a, b, out_secs in segs:
        local_ratio = (b - a) / out_secs
        assert fence.SAFE_STRETCH_LO - 1e-6 <= local_ratio <= fence.SAFE_STRETCH_HI + 1e-6


def test_placement_end_uses_warp_when_present():
    warp = [(0.0, 2.0, 1.9), (2.0, 4.0, 2.1)]  # total out = 4.0
    assert abs(fence.placement_end(10.0, (0.0, 4.0), 0.98, warp) - 14.0) < 1e-9
    # no warp -> unchanged (source / stretch)
    assert fence.placement_end(10.0, (0.0, 4.0), 1.0) == 14.0


def test_warp_map_midbar_start_does_not_shift_the_grid():
    # A slice that begins MID-BAR (the AI path doesn't snap the start) must NOT emit a
    # leading partial that pushes every later bar boundary off Song 1's grid — that was
    # the F1 defect: the referee then (correctly) flagged the drift and rejected good mixes.
    d1 = _jittered_downbeats(122.0, 24, 0.02)
    d2 = _jittered_downbeats(125.0, 24, 0.03)
    s0 = d2[2] + 0.9   # 0.9 s AFTER a Song-2 downbeat -> mid-bar
    segs = fence.warp_map(d1[0], (s0, d2[12]), d1, d2, fence.best_stretch(122.0, 125.0)[0])

    assert segs, "should still produce a locked warp, not bail entirely"
    assert min(abs(segs[0][0] - d) for d in d2) < 0.01  # first bar starts ON a Song-2 downbeat (not 0.9s mid-bar)
    cum = d1[0]  # every interior boundary must land on Song 1's grid (what the referee checks)
    for _a, _b, out_secs in segs[:-1]:
        cum += out_secs
        assert min(abs(cum - d) for d in d1) <= 0.03


def test_warp_map_glitch_bar_falls_back_to_legacy():
    # A real grid glitch (a missing downbeat -> one double-length bar whose ratio is way out
    # of band) can't lock cleanly. Rather than emit a half-locked, grid-shifting map, warp_map
    # bails to [] so the placement uses the legacy global stretch (no worse than before).
    d1 = _jittered_downbeats(122.0, 24, 0.02)
    d2 = _jittered_downbeats(125.0, 24, 0.03)
    del d2[5]  # missing downbeat -> a double-length bar in the middle of the slice
    segs = fence.warp_map(d1[0], (d2[0], d2[12]), d1, d2, fence.best_stretch(122.0, 125.0)[0])
    assert segs == []  # legacy fallback, not a broken lock


# ---------------------------------------------------------------- energy detection (Step 2)
# Builds/drops/peaks are DERIVED from the already-cached per-bar energy curve — no re-analysis,
# no analysis.py change. Pure arithmetic, so fast and exact.


def test_energy_drops_finds_the_low_to_high_jump():
    # low for 8 bars, then the beat DROPS in (high + sustained) at bar 8, back to low at 16.
    energy = [0.25] * 8 + [0.9] * 8 + [0.25] * 8
    downbeats = [round(i * 2.0, 3) for i in range(len(energy))]
    drops = fence.energy_drops(energy, downbeats)
    assert drops == [downbeats[8]]  # the onset of the drop, not every high bar


def test_energy_drops_finds_two_drops_across_a_breakdown():
    # drop, breakdown (low), drop again — two separate onsets.
    energy = [0.25] * 4 + [0.9] * 6 + [0.2] * 6 + [0.95] * 6
    downbeats = [round(i * 2.0, 3) for i in range(len(energy))]
    drops = fence.energy_drops(energy, downbeats)
    assert drops == [downbeats[4], downbeats[16]]


def test_energy_drops_ignores_an_energetic_intro_with_no_rise():
    # a track that just opens loud and stays loud has no DROP (no low->high transition).
    energy = [0.9] * 24
    downbeats = [round(i * 2.0, 3) for i in range(len(energy))]
    assert fence.energy_drops(energy, downbeats) == []


def test_energy_drops_empty_on_no_data():
    assert fence.energy_drops([], []) == []


def test_vocal_peaks_ranks_regions_by_loudness():
    # Song 2's LOUDEST sung stretch should come first — that's what lands on the house drop.
    # bars: region A (8..12) is quiet, region B (16..24) is loud.
    energy = [0.2] * 8 + [0.3, 0.3, 0.3, 0.3] + [0.2] * 4 + [0.9] * 8 + [0.2] * 8
    a2 = make_analysis(bpm=120.0, n_bars=32, energy=energy,
                       vocal_regions=[(16.0, 24.0), (32.0, 48.0)])
    peaks = fence.vocal_peaks(a2)
    assert peaks[0][0] == 32.0  # the louder region (bars 16..23 -> 32..48s) ranks first


def test_vocal_peaks_falls_back_to_sections_when_no_regions():
    a2 = make_analysis(bpm=120.0, n_bars=64, vocal_regions=[], sections=[
        Section(start=20.0, end=36.0, label="chorus"),
        Section(start=4.0, end=20.0, label="intro"),  # never a vocal peak
    ])
    peaks = fence.vocal_peaks(a2)
    assert peaks and all(s >= 20.0 for s, _ in peaks)  # the sung section, not the intro


def test_synced_anchors_prefers_a_drop_over_a_louder_plateau_in_the_same_band():
    # The middle third holds a real DROP (120s) AND a louder non-drop plateau anchor (100s).
    # Energy-sync lands the vocal on the DROP, not the loud plateau (recipe R1).
    anchors_ranked = [100.0, 40.0, 200.0]  # energy-desc; 100 is the loudest anchor
    picks = fence.synced_anchors(anchors_ranked, drops=[120.0], track_end=240.0, count=3)
    assert 120.0 in picks and 100.0 not in picks
    assert len(picks) == 3 and picks[0] < 80.0 and picks[2] >= 160.0  # still spans the thirds


def test_synced_anchors_falls_back_to_loud_anchor_when_a_band_has_no_drop():
    # No drops at all -> behave exactly like the energy arc (one loud anchor per third).
    picks = fence.synced_anchors([10.0, 90.0, 200.0], drops=[], track_end=240.0, count=3)
    assert picks == [10.0, 90.0, 200.0]


def test_synced_anchors_spans_even_when_the_only_drop_is_in_the_middle():
    # A song whose only drop is dead-center must STILL span (fall back to loud anchors in the
    # empty thirds), never collapse to one middle entry.
    anchors_ranked = [16.0, 120.0, 224.0]
    picks = fence.synced_anchors(anchors_ranked, drops=[120.0], track_end=240.0, count=3)
    assert min(picks) < 80.0 and max(picks) >= 160.0 and 120.0 in picks


# ---------------------------------------------------------------- stem dynamics (Step 3)
# fence.stem_moves_for_drops emits the auto-performed tension arc for every produced drop: an
# `other` ramp-down (melody LOWERS, drums alone by the end) for _CUT_BARS bars, then `bass` ramps
# down (1.0->0.0, a genuine decline, not a flat hold) across the WHOLE cut+build span so it SLAMS
# back only at the anchor. Both ends land on Song 1's real downbeat grid (make_analysis: downbeats
# every 2.0s). Founder correction (2026-07-08): a continuous element must be LOWERED, never CUT — an
# earlier draft held gain flat at 0 (reached via the engine's ~8ms declick), which read as a stem
# cutting out mid-song; both moves now ramp from gain_from=1.0 so the decline is audible.


def test_stem_moves_cut_then_bass_ramps_down_on_a_produced_drop():
    a1 = make_analysis(bpm=120.0, n_bars=32)  # downbeats 0,2,4,...; anchor 16.0 = downbeats[8]
    p = Placement(anchor=16.0, vocal_src=(0.0, 8.0), build_bars=3)
    moves = fence.stem_moves_for_drops([p], a1.downbeats)
    assert len(moves) == 2  # one bass (cut+build), one other (cut only)
    bass = next(m for m in moves if m.stem == "bass")
    other = next(m for m in moves if m.stem == "other")
    assert bass.gain_from == 1.0 and bass.gain_to == 0.0  # a real decline, not a flat hold
    assert other.gain_from == 1.0 and other.gain_to == 0.0
    build_start_i = 8 - 3                                    # 3 bars before the anchor — build starts here (10.0)
    other_end_i = build_start_i - fence._CUT_RECOVERY_BARS   # 1 bar EARLIER — melody is back to full by here (8.0)
    cut_start_i = other_end_i - fence._CUT_BARS              # 2 MORE bars back — the cut starts here (4.0)
    assert bass.start == a1.downbeats[cut_start_i] and bass.end == 16.0  # bass ramps down the WHOLE cut+build
    assert other.start == a1.downbeats[cut_start_i] and other.end == a1.downbeats[other_end_i]  # ends 1 bar early
    # every edge lands exactly on a real downbeat (on-beat by construction -> referee R3)
    for m in moves:
        assert m.start in a1.downbeats and m.end in a1.downbeats


def test_no_stem_move_for_a_plain_entry():
    a1 = make_analysis(bpm=120.0, n_bars=32)
    p = Placement(anchor=16.0, vocal_src=(0.0, 8.0))  # build_bars defaults 0 -> not a produced drop
    assert fence.stem_moves_for_drops([p], a1.downbeats) == []


def test_stem_moves_one_pair_per_produced_drop():
    a1 = make_analysis(bpm=120.0, n_bars=64)
    ps = [Placement(anchor=16.0, vocal_src=(0.0, 8.0), build_bars=3),
          Placement(anchor=64.0, vocal_src=(0.0, 8.0), build_bars=3),
          Placement(anchor=100.0, vocal_src=(0.0, 8.0))]  # plain -> no move
    moves = fence.stem_moves_for_drops(ps, a1.downbeats)
    assert sum(1 for m in moves if m.stem == "bass") == 2
    assert sum(1 for m in moves if m.stem == "other") == 2


def test_stem_moves_empty_without_a_grid():
    p = Placement(anchor=16.0, vocal_src=(0.0, 8.0), build_bars=3)
    assert fence.stem_moves_for_drops([p], []) == []


def test_stem_move_clamps_to_the_grid_start():
    # A produced drop near the very start has no room for a full build-bars step-back (build starts
    # at the very first downbeat), so there's no room for the cut either — the bass move alone still
    # clamps to the first downbeat and never goes negative (matches Wave 1's original guarantee).
    a1 = make_analysis(bpm=120.0, n_bars=32)
    p = Placement(anchor=4.0, vocal_src=(0.0, 8.0), build_bars=3)  # only 2 bars of runway
    moves = fence.stem_moves_for_drops([p], a1.downbeats)
    assert len(moves) == 1 and moves[0].stem == "bass"  # no room left for a separate cut
    assert moves[0].start == a1.downbeats[0] and moves[0].end == 4.0
    assert moves[0].start < moves[0].end


def test_stem_moves_cut_clamped_by_a_close_previous_vocal():
    # A previous placement's vocal tail sits close enough that the naive step-back (to 4.0, 2 bars
    # before the melody's recovery point at 8.0) would reach back over it (real end 6.0) — the cut is
    # pulled forward to the next downbeat at/after the vocal's end, rather than talking over the prior
    # vocal, mirroring the engine's own build-window clamp. There's still room before the melody's
    # recovery point (8.0), so the cut still fires, just shorter.
    a1 = make_analysis(bpm=120.0, n_bars=32)  # downbeats every 2.0s
    prev = Placement(anchor=2.0, vocal_src=(0.0, 4.0))  # ends at 2.0+4.0=6.0 (stretch=1.0)
    drop = Placement(anchor=16.0, vocal_src=(0.0, 8.0), build_bars=3)  # naive cut wants 4.0, build starts 10.0
    moves = fence.stem_moves_for_drops([prev, drop], a1.downbeats)
    bass = next(m for m in moves if m.stem == "bass")
    other = next(m for m in moves if m.stem == "other")
    assert bass.start == 6.0  # pulled forward off the naive 4.0, right to the previous vocal's end
    assert other.start == 6.0 and other.end == 8.0  # the shortened cut still fires, ending 1 bar before the build


def test_stem_moves_skip_a_drop_where_song1s_own_vocal_leads_in():
    # BUG REPRODUCTION (founder ear-test): Father Ocean's OWN vocal (a lead or a predrop lick) often
    # runs right up to a drop's anchor — the "vocal-into-the-drop a DJ never cuts". A cut+bass-hold
    # move under it hollows out the backing (no bass, no melody) while he's singing, which read as
    # broken, not stripped-back. The whole move must be SKIPPED for that drop when an s1_region
    # overlaps its cut+build span — not trimmed, not shortened, skipped entirely.
    a1 = make_analysis(bpm=120.0, n_bars=64)  # downbeats every 2.0s
    drop = Placement(anchor=16.0, vocal_src=(0.0, 8.0), build_bars=3)  # cut wants [6.0,10.0], build [10.0,16.0]
    s1_lick = [(14.0, 16.0)]  # Father Ocean sings right into the anchor — overlaps the build window
    moves = fence.stem_moves_for_drops([drop], a1.downbeats, s1_regions=s1_lick)
    assert moves == []  # no bass, no melody move at all for this drop


def test_stem_moves_fire_normally_without_an_s1_overlap():
    # The mirror of the above: an s1 region that does NOT overlap this drop's cut+build span must
    # not suppress it (regression guard — the new check shouldn't over-trigger).
    a1 = make_analysis(bpm=120.0, n_bars=64)
    drop = Placement(anchor=16.0, vocal_src=(0.0, 8.0), build_bars=3)  # cut+build spans [6.0, 16.0]
    s1_far = [(40.0, 44.0)]  # Father Ocean sings much later, nowhere near this drop
    moves = fence.stem_moves_for_drops([drop], a1.downbeats, s1_regions=s1_far)
    assert len(moves) == 2  # bass + other both fire as normal


# ---------------------------------------------------------------- beat-up (Step 3 Wave 2, 2nd move)
# fence.beat_up_moves slides a _BEAT_UP_BARS-wide window across every beat-only gap and picks the
# single highest-energy window across the whole song (make_analysis: downbeats every 2.0s).


def test_beat_up_ducks_the_melody_somewhere_in_the_gap():
    a1 = make_analysis(bpm=120.0, n_bars=32)  # downbeats 0,2,...,62.0; track_end (last beat) = 63.5
    placements = [Placement(anchor=10.0, vocal_src=(0.0, 4.0))]  # ends at 14.0 -> one gap [14.0, 63.5]
    moves = fence.beat_up_moves(a1, placements, [], [])
    assert len(moves) == 1
    m = moves[0]
    assert m.stem == "other" and m.gain_from == 1.0 and m.gain_to == fence._BEAT_UP_TARGET
    assert m.end - m.start == fence._BEAT_UP_BARS * 2.0  # exactly _BEAT_UP_BARS bars wide
    assert 14.0 <= m.start and m.end <= 63.5  # entirely inside the gap
    assert m.start in a1.downbeats and m.end in a1.downbeats  # on-beat by construction (referee R3)


def test_beat_up_returns_nothing_below_the_energy_floor():
    a1 = make_analysis(bpm=120.0, n_bars=32, energy=[0.1] * 32)  # every bar too quiet to beat-up
    placements = [Placement(anchor=10.0, vocal_src=(0.0, 4.0))]
    assert fence.beat_up_moves(a1, placements, [], []) == []


def test_beat_up_finds_the_loudest_window_anywhere_in_a_gap():
    # The loud stretch sits in the MIDDLE of a long gap, not at either edge — the search must slide
    # across the whole gap to find it, not just check the ends.
    a1 = make_analysis(bpm=120.0, n_bars=64)  # downbeats every 2.0s, 0..126
    energy = [0.3] * 64
    for i in range(6, 10):  # bars 12-18s — well inside the gap [6.0, 40.0], nowhere near either edge
        energy[i] = 0.9
    a1.energy_curve = energy
    placements = [Placement(anchor=2.0, vocal_src=(0.0, 4.0)),    # ends 6.0 -> gap A: [6.0, 40.0]
                  Placement(anchor=40.0, vocal_src=(0.0, 4.0))]   # ends 44.0 -> gap B: [44.0, track_end]
    moves = fence.beat_up_moves(a1, placements, [], [])
    assert len(moves) == 1
    assert moves[0].start == 12.0 and moves[0].end == 20.0  # exactly the loud stretch, mid-gap


def test_beat_up_clamped_away_from_song1s_own_vocal():
    a1 = make_analysis(bpm=120.0, n_bars=32)  # downbeats 0,2,...,62.0
    placements = [Placement(anchor=10.0, vocal_src=(0.0, 4.0))]  # gap [14.0, 63.5]
    s1_regions = [(14.0, 63.5)]  # covers the WHOLE gap -> no window can avoid it
    assert fence.beat_up_moves(a1, placements, s1_regions, []) == []


def test_beat_up_shifts_away_from_a_partial_song1_vocal_block():
    # A block that covers only PART of the gap must not suppress beat-up entirely — the search finds
    # a valid window elsewhere in the same gap instead.
    a1 = make_analysis(bpm=120.0, n_bars=32)  # downbeats 0,2,...,62.0
    placements = [Placement(anchor=10.0, vocal_src=(0.0, 4.0))]  # gap [14.0, 63.5]
    s1_regions = [(14.0, 50.0)]  # blocks the first part of the gap, leaves the tail clear
    moves = fence.beat_up_moves(a1, placements, s1_regions, [])
    assert len(moves) == 1
    assert moves[0].start >= 50.0  # landed clear of the blocked span


def test_beat_up_clamped_away_from_an_existing_stem_move():
    from app.models import StemMove
    a1 = make_analysis(bpm=120.0, n_bars=32)
    placements = [Placement(anchor=10.0, vocal_src=(0.0, 4.0))]  # gap [14.0, 63.5]
    existing = [StemMove(stem="bass", start=14.0, end=63.5, gain_from=1.0, gain_to=0.0)]  # the WHOLE gap
    assert fence.beat_up_moves(a1, placements, [], existing) == []


def test_beat_up_empty_without_a_grid():
    a1 = make_analysis(bpm=120.0, n_bars=32)
    a1.downbeats = []
    placements = [Placement(anchor=10.0, vocal_src=(0.0, 4.0))]
    assert fence.beat_up_moves(a1, placements, [], []) == []


# ---------------------------------------------------------------- breakdown (Step 3 Wave 2, 3rd move)
# fence.breakdown_moves fades drums+bass to a low simmer for _BREAKDOWN_BARS bars in the strongest
# clear stretch, leaving 'other' full, then they return at the window end (make_analysis: 2.0s bars).


def test_breakdown_fades_drums_and_bass_keeps_the_melody():
    a1 = make_analysis(bpm=120.0, n_bars=64, energy=[0.6] * 64)  # energetic throughout
    placements = [Placement(anchor=10.0, vocal_src=(0.0, 4.0))]  # gap [14.0, track_end]
    moves = fence.breakdown_moves(a1, placements, [], [])
    assert {m.stem for m in moves} == {"drums", "bass"}  # never touches 'other' (the exposed simmer)
    for m in moves:
        assert m.gain_from == 1.0 and m.gain_to == fence._BREAKDOWN_FLOOR  # a gradual fade to a simmer
        assert m.end - m.start == fence._BREAKDOWN_BARS * 2.0  # a real section, longer than beat-up
        assert m.start in a1.downbeats and m.end in a1.downbeats  # on-beat (referee R3)
    assert moves[0].start == moves[1].start and moves[0].end == moves[1].end  # drums+bass together


def test_breakdown_returns_nothing_below_the_energy_floor():
    a1 = make_analysis(bpm=120.0, n_bars=64, energy=[0.1] * 64)  # nothing energetic enough to break down
    placements = [Placement(anchor=10.0, vocal_src=(0.0, 4.0))]
    assert fence.breakdown_moves(a1, placements, [], []) == []


def test_breakdown_avoids_an_existing_move_and_song1_vocal():
    from app.models import StemMove
    a1 = make_analysis(bpm=120.0, n_bars=64, energy=[0.6] * 64)
    placements = [Placement(anchor=10.0, vocal_src=(0.0, 4.0))]  # gap [14.0, track_end]
    # a beat-up already placed AND a Song-1 vocal together cover the whole gap -> no clear room
    existing = [StemMove(stem="other", start=14.0, end=70.0, gain_from=1.0, gain_to=0.4)]
    s1 = [(70.0, 130.0)]
    assert fence.breakdown_moves(a1, placements, s1, existing) == []


def test_breakdown_never_all_muted_by_construction():
    # drums+bass go to _BREAKDOWN_FLOOR (> the referee's mute floor) and 'other' is untouched, so the
    # never-all-muted guard passes by construction — verified through the real referee.
    from app.models import MixPlan
    from app.planner import validate
    a1 = make_analysis(bpm=120.0, n_bars=64, energy=[0.6] * 64)
    placements = [Placement(anchor=10.0, vocal_src=(0.0, 4.0))]
    moves = fence.breakdown_moves(a1, placements, [], [])
    assert moves
    plan = MixPlan(mix_id="m" * 64, song1_id="a" * 64, song2_id="b" * 64, master_bpm=120.0,
                   vocal_stretch=1.0, vocal_src=(0.0, 4.0), anchor=10.0,
                   placements=[Placement(anchor=10.0, vocal_src=(0.0, 4.0))], stem_moves=moves)
    assert not any("mute" in v.lower() for v in validate._stem_move_violations(moves, a1.downbeats))


# ---------------------------------------------------------------- Phase 0 pitch repair (Slice 2a)


def test_compute_pitch_repair_no_shift_when_already_compatible():
    from app.models import VocalChainConfig
    r = fence.compute_pitch_repair(make_analysis(key="8A"), make_analysis(key="8A"), VocalChainConfig())
    assert isinstance(r, fence.PitchRepair) and r.semitones == 0.0


def test_compute_pitch_repair_finds_a_small_fixing_shift():
    """A same-letter clash is repairable within a couple of semitones; the returned shift genuinely
    lands the vocal in a key that IS compatible with the bed."""
    from app.models import VocalChainConfig
    r = fence.compute_pitch_repair(make_analysis(key="8A"), make_analysis(key="1A"), VocalChainConfig())
    assert isinstance(r, fence.PitchRepair)
    assert 0 < abs(r.semitones) <= 2
    pc, letter = fence._camelot_pc("1A")
    shifted = fence._pc_to_camelot(int(pc + r.semitones) % 12, letter)
    assert fence.camelot_fit("8A", shifted)          # the shift really fixes it
    assert "key_correction" in r.reason


def test_compute_pitch_repair_declines_a_cross_letter_clash():
    """Pitch-shifting can't change major<->minor, so a bed-minor/vocal-major clash whose only
    compatible landing (the relative) is 6 semitones away is DECLINED (> the ±3 cap)."""
    from app.models import VocalChainConfig
    r = fence.compute_pitch_repair(make_analysis(key="8A"), make_analysis(key="2B"), VocalChainConfig())
    assert isinstance(r, fence.Decline)


def test_compute_pitch_repair_is_a_noop_without_a_key():
    from app.models import VocalChainConfig
    voc = make_analysis(key="8A")
    voc.key = None
    r = fence.compute_pitch_repair(make_analysis(key="8A"), voc, VocalChainConfig())
    assert isinstance(r, fence.PitchRepair) and r.semitones == 0.0


def test_camelot_pitch_class_roundtrips():
    for code in ("8A", "8B", "9A", "3B", "1A", "12B"):
        pc, letter = fence._camelot_pc(code)
        assert fence._pc_to_camelot(pc, letter) == code
