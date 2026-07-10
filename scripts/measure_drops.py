"""Measure `fence.energy_drops` against the founder's hand-marked drops (Task 2).

Reads the marks CSV exported by scripts/mark_drops.html plus the cached per-song
analyses, runs the SHIPPED `energy_drops` (the founder's rule: energy >= 0.6 AND a
rise >= 0.15 over 4 bars) on each song's energy curve, and reports how well the
detector matches a human ear:

  * Precision - of the drops we FIND, how many are real (near a marked drop)?
  * Recall    - of the REAL drops, how many do we find?
  * Offset    - when we're right, how far off (in bars) are we?

A predicted drop matches a marked drop when they are within `--tol-bars` of each
other (default 1 bar); matching is greedy nearest, one-to-one. Zero cloud: reads
only local cached analyses.

Usage (from repo root or anywhere):
  python scripts/measure_drops.py --csv scripts/ground_truth/drops_hooks.csv
  python scripts/measure_drops.py --csv <path> --data services/api/data --tol-bars 1
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
# energy_drops is a pure function in the API package - reuse the SHIPPED code, never a copy.
sys.path.insert(0, str(_REPO / "services" / "api"))
from app.planner.fence import energy_drops  # noqa: E402


def _bar_secs(bpm: float, downbeats: list[float]) -> float:
    """Seconds per bar - from BPM when sane, else the median downbeat spacing."""
    if bpm and bpm > 0:
        return 4.0 * 60.0 / bpm
    if len(downbeats) >= 2:
        gaps = sorted(b - a for a, b in zip(downbeats, downbeats[1:]) if b > a)
        return gaps[len(gaps) // 2] if gaps else 2.0
    return 2.0


def _match(predicted: list[float], marked: list[float], tol: float) -> list[tuple[float, float]]:
    """Greedy nearest one-to-one pairing of predicted<->marked within `tol` seconds.
    Returns the matched (predicted, marked) pairs."""
    pairs: list[tuple[float, float]] = []
    used = [False] * len(predicted)
    for m in sorted(marked):
        best, bestd = -1, tol + 1e-9
        for i, p in enumerate(predicted):
            if used[i]:
                continue
            d = abs(p - m)
            if d < bestd:
                best, bestd = i, d
        if best >= 0:
            used[best] = True
            pairs.append((predicted[best], m))
    return pairs


def _load_marks(csv_path: Path) -> dict[str, dict]:
    """song_id -> {'name':..., 'drops':[...], 'hook':(s,e)|None}."""
    out: dict[str, dict] = {}
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            sid = (row.get("song_id") or "").strip()
            if not sid:
                continue
            e = out.setdefault(sid, {"name": row.get("song_name", ""), "drops": [], "hook": None})
            kind = (row.get("kind") or "").strip()
            if kind == "drop" and row.get("t_start"):
                e["drops"].append(float(row["t_start"]))
            elif kind == "hook" and row.get("t_start") and row.get("t_end"):
                e["hook"] = (float(row["t_start"]), float(row["t_end"]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(_HERE / "ground_truth" / "drops_hooks.csv"))
    ap.add_argument("--data", default=str(_REPO / "services" / "api" / "data"))
    ap.add_argument("--tol-bars", type=float, default=1.0, help="match window, in bars (default 1)")
    ap.add_argument("--high", type=float, default=0.6)
    ap.add_argument("--min-rise", type=float, default=0.15)
    ap.add_argument("--look-back", type=int, default=4)
    args = ap.parse_args()

    csv_path, data = Path(args.csv), Path(args.data)
    if not csv_path.exists():
        print(f"No marks CSV at {csv_path}.\nMark some songs with scripts/mark_drops.html, export the "
              f"CSV, and point --csv at it.")
        return 2

    marks = _load_marks(csv_path)
    songs_with_drops = {s: m for s, m in marks.items() if m["drops"]}
    if not songs_with_drops:
        print(f"Loaded {len(marks)} song(s) from {csv_path.name}, but none have marked drops yet.")
        return 2

    tot_pred = tot_marked = tot_matched = 0
    offsets_bars: list[float] = []
    rows: list[tuple] = []
    skipped: list[str] = []

    for sid, m in songs_with_drops.items():
        ap_ = data / f"{sid}.analysis.json"
        if not ap_.exists():
            skipped.append(m["name"] or sid[:8])
            continue
        a = json.loads(ap_.read_text(encoding="utf-8"))
        energy, downs, bpm = a.get("energy_curve", []), a.get("downbeats", []), a.get("bpm", 0.0)
        bar = _bar_secs(bpm, downs)
        tol = args.tol_bars * bar
        predicted = energy_drops(energy, downs, high=args.high, min_rise=args.min_rise, look_back=args.look_back)
        marked = m["drops"]
        pairs = _match(predicted, marked, tol)
        tot_pred += len(predicted)
        tot_marked += len(marked)
        tot_matched += len(pairs)
        offsets_bars.extend(abs(p - mk) / bar for p, mk in pairs)
        prec = len(pairs) / len(predicted) if predicted else float("nan")
        rec = len(pairs) / len(marked) if marked else float("nan")
        rows.append((m["name"] or sid[:10], len(marked), len(predicted), len(pairs), prec, rec))

    def pct(x): return "  n/a" if x != x else f"{100 * x:5.0f}%"

    print(f"\nENERGY_DROPS vs the human ear  (rule: energy>={args.high}, rise>={args.min_rise} over "
          f"{args.look_back} bars; match window {args.tol_bars:g} bar)\n")
    print(f"{'song':<34}{'marked':>7}{'found':>7}{'hit':>5}{'prec':>7}{'recall':>8}")
    print("-" * 68)
    for name, nm, npd, nh, pr, rc in sorted(rows, key=lambda r: r[0].lower()):
        print(f"{name[:33]:<34}{nm:>7}{npd:>7}{nh:>5}{pct(pr):>7}{pct(rc):>8}")
    print("-" * 68)

    micro_p = tot_matched / tot_pred if tot_pred else float("nan")
    micro_r = tot_matched / tot_marked if tot_marked else float("nan")
    print(f"{'OVERALL (pooled)':<34}{tot_marked:>7}{tot_pred:>7}{tot_matched:>5}{pct(micro_p):>7}{pct(micro_r):>8}")
    if offsets_bars:
        so = sorted(offsets_bars)
        med = so[len(so) // 2]
        print(f"\nWhen right: mean offset {sum(offsets_bars) / len(offsets_bars):.2f} bars, "
              f"median {med:.2f} bars (n={len(offsets_bars)}).")
    print(f"\nPRECISION {pct(micro_p).strip()} -- of the drops we find, how many are real.")
    print(f"RECALL    {pct(micro_r).strip()} -- of the real drops, how many we find.")
    if skipped:
        print(f"\nSkipped (no cached analysis on disk): {', '.join(skipped)}")
    print(f"\nSongs scored: {len(rows)}   ·   zero cloud (local analyses only).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
