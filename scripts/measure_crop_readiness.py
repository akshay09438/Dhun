"""Is the drop detector good enough to build the CROP (Task 4) on? A read-only, zero-cloud
report that goes deeper than raw precision/recall, because a crop doesn't consume the whole
candidate list -- it anchors a ~90s window on ONE drop (the strongest), and it can decline
to fire on low confidence. Two questions, answered against the founder's ear-marks:

PART A -- the strongest-drop go/no-go (what the crop actually does)
  The crop's main drop is the highest-INTENSITY detected drop (window._drop_intensity: mean
  energy of the 8 bars from the onset forward -- NOT a phrase average, which buries a big drop
  under its quiet run-up). For each song we take THAT drop and ask:
    * HIT      -- within tol of one of your marks (the crop would anchor correctly);
    * MISS-NEAR-- off by a little (<= near_bars): recoverable, the window still lands in ~the
                  right section;
    * MISS-FAR -- off by a lot: the crop would build on the WRONG part of the song (the old
                  loudest-slice failure mode -- the dangerous case);
    * NO-FIRE  -- no drop detected at all -> choose_window returns None -> the crop STAYS OFF
                  and the song plays full-length (this is SAFE, not a failure).
  Reports per song + the pooled distribution + the offset on every miss (bars AND seconds), so
  a near-miss and a section-miss are never averaged into one misleading number.

PART B -- confidence gating (is there a threshold that makes precision acceptable?)
  A crop can refuse weak candidates. Sweep energy_drops' thresholds (high, min_rise) and report
  pooled precision/recall at each, to find whether a stricter rule reaches ~70%+ precision on a
  smaller, more-trustworthy set -- the "ambitious only on good data" behaviour we want.

Reuses the SHIPPED detector + ranking (never a copy): fence.energy_drops, window._drop_intensity,
and scripts/measure_drops.py's own match/bar/marks helpers. Reads only local cached analyses.

Usage:
  services/api/.venv/Scripts/python.exe scripts/measure_crop_readiness.py
  ... --tol-bars 1 --near-bars 4          (HIT within 1 bar; MISS-NEAR within 4)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_HERE))                          # reuse measure_drops.py helpers
sys.path.insert(0, str(_REPO / "services" / "api"))     # the app package (shipped detector + ranking)

import measure_drops as md  # noqa: E402  (_match, _bar_secs, _load_marks)
from app.models import TrackAnalysis  # noqa: E402
from app.planner import fence, window  # noqa: E402


def _load_a1(data: Path, sid: str) -> TrackAnalysis | None:
    """Build a TrackAnalysis from the cached analysis json (only the grid/energy fields are needed)."""
    p = data / f"{sid}.analysis.json"
    if not p.exists():
        return None
    a = json.loads(p.read_text(encoding="utf-8"))
    fields = {k: v for k, v in a.items() if k in TrackAnalysis.model_fields}
    fields.setdefault("status", "ready")
    return TrackAnalysis(**fields)


def _mmss(t: float) -> str:
    m, s = divmod(int(round(t)), 60)
    return f"{m}:{s:02d}"


def part_a(songs: dict, data: Path, tol_bars: float, near_bars: float) -> None:
    print("=" * 78)
    print("PART A -- the STRONGEST drop the crop would anchor on, vs your marks")
    print("         (crop ranks by window._drop_intensity = post-onset hit energy)")
    print("=" * 78)
    print(f"{'song':<30}{'strongest':>10}{'nearest mark':>14}{'off(bars)':>11}{'off':>7}  verdict")
    print("-" * 78)

    cats = {"HIT": 0, "MISS-NEAR": 0, "MISS-FAR": 0, "NO-FIRE": 0}
    far_list, near_list = [], []
    for sid, m in sorted(songs.items(), key=lambda kv: (kv[1]["name"] or kv[0]).lower()):
        a1 = _load_a1(data, sid)
        name = (m["name"] or sid[:10])[:29]
        if a1 is None:
            print(f"{name:<30}{'(no cached analysis)':>42}")
            continue
        bar = md._bar_secs(a1.bpm or 0.0, a1.downbeats)
        detected = fence.energy_drops(a1.energy_curve, a1.downbeats)
        marked = m["drops"]
        if not detected:
            cats["NO-FIRE"] += 1
            print(f"{name:<30}{'--none--':>10}{'':>14}{'':>11}{'':>7}  NO-FIRE (crop stays off -> full song, SAFE)")
            continue
        strongest = max(detected, key=lambda d: window._drop_intensity(a1, d))
        nearest = min(marked, key=lambda mk: abs(mk - strongest))
        off_s = abs(strongest - nearest)
        off_b = off_s / bar if bar else 0.0
        if off_b <= tol_bars:
            verdict, cat = "HIT (anchors correctly)", "HIT"
        elif off_b <= near_bars:
            verdict, cat = "MISS-NEAR (roughly right section)", "MISS-NEAR"
            near_list.append((name, off_b, off_s))
        else:
            verdict, cat = "MISS-FAR (WRONG section)", "MISS-FAR"
            far_list.append((name, off_b, off_s))
        cats[cat] += 1
        print(f"{name:<30}{_mmss(strongest):>10}{_mmss(nearest):>14}{off_b:>11.1f}{off_s:>6.0f}s  {verdict}")

    n = sum(cats.values())
    print("-" * 78)
    print(f"Pooled over {n} songs:")
    for k in ("HIT", "MISS-NEAR", "MISS-FAR", "NO-FIRE"):
        frac = f"{100 * cats[k] / n:.0f}%" if n else "n/a"
        print(f"   {k:<10} {cats[k]:>3}   {frac:>4}")
    fires = cats["HIT"] + cats["MISS-NEAR"] + cats["MISS-FAR"]
    if fires:
        good = cats["HIT"] + cats["MISS-NEAR"]
        print(f"\n   When the crop WOULD fire ({fires} songs): "
              f"{100 * cats['HIT'] / fires:.0f}% dead-on, "
              f"{100 * good / fires:.0f}% at-least-right-section, "
              f"{100 * cats['MISS-FAR'] / fires:.0f}% wrong-section.")
    if far_list:
        print("\n   MISS-FAR detail (the dangerous ones -- crop would build on the wrong part):")
        for nm, ob, os_ in far_list:
            print(f"      {nm:<28} off {ob:.1f} bars / {os_:.0f}s")
    if near_list:
        print("\n   MISS-NEAR detail (recoverable):")
        for nm, ob, os_ in near_list:
            print(f"      {nm:<28} off {ob:.1f} bars / {os_:.0f}s")


def part_b(songs: dict, data: Path, tol_bars: float) -> None:
    print("\n" + "=" * 78)
    print("PART B -- confidence gating: does a stricter rule buy acceptable precision?")
    print("=" * 78)
    print(f"{'high':>5}{'min_rise':>10}{'found':>8}{'hit':>6}{'prec':>8}{'recall':>8}")
    print("-" * 78)
    grid_high = [0.6, 0.7, 0.8]
    grid_rise = [0.15, 0.20, 0.25, 0.30, 0.40]
    loaded = {sid: _load_a1(data, sid) for sid in songs}
    for high in grid_high:
        for rise in grid_rise:
            tp = tm = th = 0
            for sid, m in songs.items():
                a1 = loaded[sid]
                if a1 is None:
                    continue
                bar = md._bar_secs(a1.bpm or 0.0, a1.downbeats)
                pred = fence.energy_drops(a1.energy_curve, a1.downbeats, high=high, min_rise=rise)
                pairs = md._match(pred, m["drops"], tol_bars * bar)
                tp += len(pred)
                tm += len(m["drops"])
                th += len(pairs)
            prec = th / tp if tp else float("nan")
            rec = th / tm if tm else float("nan")
            flag = "  <-- precision >= 70%" if (prec == prec and prec >= 0.70) else ""
            pp = "n/a" if prec != prec else f"{100 * prec:.0f}%"
            rr = "n/a" if rec != rec else f"{100 * rec:.0f}%"
            print(f"{high:>5}{rise:>10}{tp:>8}{th:>6}{pp:>8}{rr:>8}{flag}")
    print("\n(default shipped rule is high=0.6, min_rise=0.15 -- the top row.)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", default=str(_HERE / "ground_truth" / "drops_hooks.csv"))
    ap.add_argument("--data", default=str(_REPO / "services" / "api" / "data"))
    ap.add_argument("--tol-bars", type=float, default=1.0, help="HIT window, in bars (default 1)")
    ap.add_argument("--near-bars", type=float, default=4.0, help="MISS-NEAR ceiling, in bars (default 4)")
    args = ap.parse_args()

    csv_path, data = Path(args.csv), Path(args.data)
    if not csv_path.exists():
        print(f"No marks CSV at {csv_path}.")
        return 2
    marks = md._load_marks(csv_path)
    songs = {s: m for s, m in marks.items() if m["drops"]}
    if not songs:
        print("No songs with marked drops in the CSV.")
        return 2

    part_a(songs, data, args.tol_bars, args.near_bars)
    part_b(songs, data, args.tol_bars)
    print("\nzero cloud (local cached analyses only).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
