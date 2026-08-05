"""Follow-up to sensor_audit.py — READ-ONLY. Tests the AMBER remedy BEFORE proposing it.

Full-mix RMS includes Song 1's vocal, which is excluded from the bed by construction.
On vocal-blob beats that masks the drop. This compares the shipped FULL-MIX energy
curve against a BED curve (drums+bass+other, the parts that actually play) to see
whether the bed recovers a drop START / release / plateau the full-mix hides.

No cloud, no cache writes, no product-code changes. Decodes cached stems with ffmpeg.
Run: services/api/.venv/Scripts/python.exe scripts/sensor_audit_bed.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))  # import the sibling audit helpers
from sensor_audit import (  # noqa: E402
    decode_stem_mono, energy_drops, load_analysis, load_beats, max_rise,
    nearest_bar, rms_per_bar, sparkline, wav_duration,
)
from app.planner.main_drops import main_drops_for  # noqa: E402

# The revealing cases + one known-good control (Father Ocean) to prove bed doesn't break it.
TARGETS = [
    ("Father Ocean (control, clean drop)", "ac59f8c4af7e89e916dc825690ade5dbc2b9c6f221c5a7ef863eb9863f3826e1"),
    ("I Adore You (97% vocal blob)", "b8696c4dec8a4d50c2ee493360a868d46ffcc915a43b0fdfdbe30241d9962bef"),
    ("Rapture (99.5% vocal blob)", "7f0b66c94d2be61f18a64485dba0a33b5f4387ccce2ff1b5d23aa7da469076eb"),
    ("Merrygo (flat-loud, 0 onsets)", "4fc82b59807fcbd3071bca7f612e2311f044f0e203f8e82895d7682d67629480"),
]


def bed_curve(sid, downbeats):
    """RMS/bar of drums+bass+other summed — the parts that actually reach the listener."""
    acc, sr = None, 0
    for stem in ("drums", "bass", "other"):
        mono, s = decode_stem_mono(sid, stem)
        if mono is None:
            continue
        sr = s
        acc = mono if acc is None else acc[:min(len(acc), len(mono))] + mono[:min(len(acc), len(mono))]
    if acc is None:
        return None
    return rms_per_bar(acc, sr, downbeats)


INNERBLOOM = "2471e18e1eb820114c0782501babac43b6e5b52c06254da4c1fe0d9e8369c406"
ANCHOR = "2c17fc64b6928f0499a306402b676bc62e3118588e42494c8ec7063a7a948267"


def _compare(name, sid, notes=True):
    a = load_analysis(sid)
    if not a:
        print(f"### {name}: no analysis\n")
        return None
    db = a.get("downbeats", []) or []
    full = a.get("energy_curve", []) or []
    bed = bed_curve(sid, db)
    print("=" * 78)
    print(f"### {name}")
    if bed is None:
        print("  stems missing — skipped\n")
        return None
    fo, bo = energy_drops(full, db), energy_drops(bed, db)
    print(f"  FULL-MIX  std={np.std(full):.3f} maxrise={max_rise(full):.3f} onsets={len(fo)} "
          f"@ {[round(t,0) for t in fo][:12]}")
    print("      " + sparkline(full))
    print(f"  BED       std={np.std(bed):.3f} maxrise={max_rise(bed):.3f} onsets={len(bo)} "
          f"@ {[round(t,0) for t in bo][:12]}")
    print("      " + sparkline(bed))
    return dict(db=db, full=full, bed=bed, fo=fo, bo=bo)


def part1_finish_bed():
    print("PART 1 — BED vs FULL-MIX on the two skipped beats\n")
    _compare("Anchor Point", ANCHOR)
    print()
    r = _compare("Innerbloom", INNERBLOOM)
    if not r:
        return
    print("\n  -- Innerbloom ground-truth checks (hand mark = 377s in main_drops.py) --")
    # near-377 in the bed curve? (±8s ≈ ±4 bars at ~2.04s/bar)
    near = [t for t in r["bo"] if abs(t - 377.0) <= 8.0]
    print(f"  bed onset near 377s (±8s)? {'YES @ ' + str([round(t,1) for t in near]) if near else 'NO'}")
    # false-fire window 6:00-8:40 = 360-520s
    win_full = [t for t in r["fo"] if 360 <= t <= 520]
    win_bed = [t for t in r["bo"] if 360 <= t <= 520]
    print(f"  onsets in the busy 360-520s window:  full-mix={len(win_full)} @ {[round(t,0) for t in win_full]}")
    print(f"                                        bed={len(win_bed)} @ {[round(t,0) for t in win_bed]}")
    verdict_mark = bool(near)
    verdict_calm = len(win_bed) < len(win_full)
    print(f"  >> Reproduces 377s mark: {verdict_mark}.  Reduces false fires: {verdict_calm} "
          f"({len(win_full)}->{len(win_bed)}).")
    print(f"  >> TWO-FOR-TWO vs human ground truth (Merrygo 40s + Innerbloom 377s): "
          f"{'YES' if verdict_mark else 'NO — bed did not independently hit 377s'}.")


def part2_offsets():
    print("\n\nPART 2 — VOCAL-RETURN OFFSET (bars from drop onset to next S1 vocal_region start)\n")
    beats = load_beats()
    cluster_pool = []  # (name, offset_bars) from non-blob tracks only
    for e in beats:
        sid, name = e["song_id"], e["name"]
        a = load_analysis(sid)
        if not a:
            continue
        db = a.get("downbeats", []) or []
        full = a.get("energy_curve", []) or []
        vr = a.get("vocal_regions", []) or []
        dur = wav_duration(sid) or (db[-1] if db else 0.0)
        cover = (sum(y - x for x, y in vr) / dur * 100.0) if dur else 0.0
        hand = main_drops_for(sid)
        drops = hand if hand else energy_drops(full, db)  # the shipped drop set (hand overrides)
        blob = cover > 80.0
        tag = "  [BLOB >80% — offset unreliable, EXCLUDED from clustering]" if blob else ""
        print(f"### {name}  (cover {cover:.0f}%, drops from {'HAND' if hand else 'energy_drops'}){tag}")
        for t in drops:
            d_bar = nearest_bar(db, t)
            starts = sorted(s for s, e2 in vr if s > t + 1e-6)
            if not starts:
                print(f"    drop @ {t:6.1f}s (bar {d_bar:3d}) -> NO S1 vocal returns after it")
                continue
            s = starts[0]
            s_bar = nearest_bar(db, s)
            off = s_bar - d_bar
            on_phrase = (s_bar % 8 == 0)
            print(f"    drop @ {t:6.1f}s (bar {d_bar:3d}) -> S1 vocal returns @ {s:6.1f}s (bar {s_bar:3d})  "
                  f"= +{off} bars  {'[on phrase start]' if on_phrase else '[off phrase]'}")
            if not blob:
                cluster_pool.append((name, off, on_phrase))
        print()

    print("-- Innerbloom hand-marked drop @ 377s specifically --")
    a = load_analysis(INNERBLOOM)
    db, vr = a["downbeats"], a.get("vocal_regions", [])
    d_bar = nearest_bar(db, 377.0)
    starts = sorted(s for s, e2 in vr if s > 377.0 + 1e-6)
    if starts:
        s = starts[0]; s_bar = nearest_bar(db, s)
        print(f"    377s = bar {d_bar}; next S1 vocal @ {s:.1f}s = bar {s_bar}; offset = +{s_bar - d_bar} bars; "
              f"lands on phrase start (downbeats[::8])? {'YES' if s_bar % 8 == 0 else 'NO'}")
    else:
        print("    no S1 vocal returns after 377s")

    print("\n-- Clustering (non-blob tracks only) --")
    offs = [o for _, o, _ in cluster_pool]
    print(f"    offsets (bars): {sorted(offs)}")
    print(f"    on-phrase-start count: {sum(1 for _, _, p in cluster_pool if p)}/{len(cluster_pool)}")
    for _, o, p in cluster_pool:
        pass
    print("    (read: do these cluster on 4/8/16, or scatter per-song? -> decides global vs per-track)")


def main():
    part1_finish_bed()
    part2_offsets()


if __name__ == "__main__":
    main()
