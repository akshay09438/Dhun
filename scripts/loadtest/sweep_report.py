"""What the catalog sweep found — read from the engine's own event log, not from the CSV.

WHY THIS EXISTS. `failure_sweep.py` writes its CSV only when it finishes. A sweep that is stopped
early — by the disk guard, by a reboot, by somebody closing the window — leaves no CSV at all, and
on 2026-08-11 exactly that happened and the numbers had to be reconstructed by hand.

They did not need to be. `events.db` records every render outcome as it happens, including WHY a
failure failed, so the answer survives the sweep being interrupted. This reads it back.

Read-only. Touches nothing.

    python scripts/loadtest/sweep_report.py            # everything since the last sweep started
    python scripts/loadtest/sweep_report.py 2026-08-12 # everything on one day
"""
from __future__ import annotations

import sqlite3
import sys
from collections import Counter
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / "services" / "api" / "data" / "events.db"


def kind_of(reason: str) -> str:
    """Group a failure by what the engine itself said, so these can be COUNTED rather than read.

    The distinction that matters: a pair the quality referee refused (a real property of those two
    songs) versus a render that fell over because the machine was full (nothing to do with the
    songs at all). Confusing the two is what sent the 2026-08-11 investigation down the wrong path
    for hours and produced a catalog failure rate that was never true."""
    low = (reason or "").lower()
    if not low:
        return "unrecorded"
    if "room" in low and "songs" in low:
        return "machine was full (not the songs)"
    if "clean" in low or "quality" in low or "referee" in low:
        return "quality referee refused it"
    if "beat" in low and "grid" in low:
        return "no beat grid"
    return "other"


def main() -> None:
    if not DB.exists():
        sys.exit(f"no event log at {DB}")
    day = sys.argv[1] if len(sys.argv) > 1 else None
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row

    where = "WHERE kind='mix'"
    args: tuple = ()
    if day:
        where += " AND created_at LIKE ?"
        args = (day + "%",)
    rows = c.execute(
        f"SELECT song1_name, song2_name, status, fail_reason, created_at FROM events {where} "
        "ORDER BY id", args).fetchall()

    if not rows:
        sys.exit("no mixes recorded for that window")

    bad = [r for r in rows if r["status"] != "ok"]
    print(f"PAIRS RECORDED: {len(rows)}   worked: {len(rows) - len(bad)}   "
          f"failed: {len(bad)}  ({100 * len(bad) / len(rows):.1f}%)")
    print(f"window: {rows[0]['created_at']}  ->  {rows[-1]['created_at']}")

    if not bad:
        print("\nnothing failed.")
        return

    print("\nWHY they failed — the engine's own words:")
    kinds = Counter(kind_of(r["fail_reason"]) for r in bad)
    for kind, n in kinds.most_common():
        print(f"  {n:3d}  {kind}")
        for r in [x for x in bad if kind_of(x["fail_reason"]) == kind][:2]:
            print(f"         e.g. {r['song1_name']} x {r['song2_name']}")

    # A pair that fails because the machine was full says nothing about the pair. Separating these
    # is the whole point - the headline rate above is an UPPER BOUND until they are taken out.
    real = [r for r in bad if kind_of(r["fail_reason"]) != "machine was full (not the songs)"]
    print(f"\nTAKING OUT the machine-was-full failures, {len(real)} of {len(rows)} pairs "
          f"({100 * len(real) / len(rows):.1f}%) are genuine pair failures.")

    print("\nVOCALS that genuinely fail (failed / tried):")
    tried = Counter(r["song2_name"] for r in rows)
    for name, n in Counter(r["song2_name"] for r in real).most_common(10):
        print(f"  {n:2d}/{tried[name]:2d}  {name}")

    print("\nBEATS that genuinely fail (failed / tried):")
    triedb = Counter(r["song1_name"] for r in rows)
    for name, n in Counter(r["song1_name"] for r in real).most_common(10):
        print(f"  {n:2d}/{triedb[name]:2d}  {name}")

    print("\nA pair that fails EVERY time it is tried is a catalog problem; one that fails once is\n"
          "usually the machine. Check the tried-count before withdrawing any song — three beats\n"
          "were wrongly blamed on 2026-08-11 for exactly that reason.")


if __name__ == "__main__":
    main()
