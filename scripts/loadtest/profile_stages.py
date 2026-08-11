"""Where does a cold render's 25-30 seconds actually GO? MEASURES ONLY.

The concurrency diagnosis established the TOTAL (a cold mix is ~25-30s, a repeat 0.03s) but
never the breakdown, so "make it faster" had nowhere to aim. Every mix now records its own
per-stage timings into events.db (routes/mix.py::_Stages); this fires a few cold renders and
reads them back.

COLD BY CONSTRUCTION: the prompt is part of the mix id, so a unique prompt per run guarantees
a fresh render rather than a 0.03s cache hit that would measure nothing.

Cleans up every file it writes.
"""
from __future__ import annotations

import json
import sqlite3
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import loadtest as lt                                        # noqa: E402

DATA = Path(__file__).resolve().parents[2] / "services" / "api" / "data"

# Four beats of comparable length. Deliberately NOT Innerbloom (9:38, roughly 7x the cost -
# it would swamp an average) and NOT Khuda Jaane (fails on its own; see the diagnosis).
BEATS = [0, 1, 3, 4]
VOCALS = [0, 1, 2, 5]


def _timings_for(mix_ids: set[str]) -> list[dict]:
    conn = sqlite3.connect(DATA / "events.db")
    conn.row_factory = sqlite3.Row
    out = []
    for r in conn.execute("SELECT ref_id, status, extra FROM events ORDER BY id DESC LIMIT 200"):
        if r["ref_id"] not in mix_ids or r["status"] != "ok":
            continue
        extra = json.loads(r["extra"] or "{}")
        if extra.get("timings"):
            out.append(extra["timings"])
    conn.close()
    return out


def main() -> None:
    free = lt.psutil.disk_usage("C:\\").free / 1e9 if hasattr(lt, "psutil") else 99.0
    print(f"disk free: {free:.2f} GB")
    if free < 2.5:
        print("REFUSING: under the 2.5 GB safety line.")
        return

    beats, vocals = lt.library()
    stamp = int(time.time())
    pairs = [(beats[BEATS[i % len(BEATS)]]["id"], vocals[v]["id"],
              f"{beats[BEATS[i % len(BEATS)]]['original_name'][:20]} x {vocals[v]['original_name'][:20]}")
             for i, v in enumerate(VOCALS)]

    print(f"\n{'=' * 74}\nCOLD RENDERS, one at a time\n{'=' * 74}")
    ids: set[str] = set()
    for i, (b, v, label) in enumerate(pairs):
        out: list = [None]
        t0 = time.monotonic()
        lt.one_mix(b, v, f"prof{stamp}-{i}", "profiler", out, 0)
        res = out[0] or {}
        if res.get("mix_id"):
            ids.add(res["mix_id"])
        print(f"  {label:<46} {time.monotonic() - t0:6.1f}s  "
              f"{'ok' if res.get('ok') else res.get('err', '?')}")

    rows = _timings_for(ids)
    if not rows:
        print("\nNo timings recorded - is this engine running the build with _Stages?")
        return

    print(f"\n{'=' * 74}\nWHERE THE TIME GOES  (n={len(rows)} cold renders)\n{'=' * 74}")
    keys = [k for k in rows[0] if k != "total"]
    totals = [r.get("total", 0.0) for r in rows]
    for k in sorted(keys, key=lambda k: -statistics.median(r.get(k, 0.0) for r in rows)):
        vals = [r.get(k, 0.0) for r in rows]
        med = statistics.median(vals)
        share = 100 * med / statistics.median(totals) if statistics.median(totals) else 0
        bar = "#" * int(round(share / 2))
        print(f"  {k:<28} {med:6.2f}s  {share:5.1f}%  {bar}")
    print(f"  {'TOTAL':<28} {statistics.median(totals):6.2f}s "
          f"(min {min(totals):.1f}, max {max(totals):.1f})")

    removed = 0
    for mid in ids:
        for suffix in (".mix.wav", ".bestparts.wav", ".mixplan.json"):
            p = DATA / f"{mid}{suffix}"
            if p.exists():
                p.unlink()
                removed += 1
    print(f"\ncleaned up {removed} files this run created")


if __name__ == "__main__":
    main()
