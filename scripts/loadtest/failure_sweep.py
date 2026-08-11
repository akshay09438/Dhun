"""How many of the catalog's pairs actually FAIL for a user? MEASURES ONLY.

Every pair in the catalog is rendered for real, ten at a time, and each batch's files are deleted
before the next starts (a success is ~120 MB; the whole catalog at once would not fit).

This is a RENDER-level sweep, not a plan-level one. The existing scripts/sanity_check.py checks
that a PLAN can be built and passes the referee, and reports 0 declines - but the failures users
actually hit happen later, inside render_mix, when the quality guard measures the finished audio.
A plan-level sweep cannot see them, which is why this exists.

Writes a CSV so the failures can be grouped by song afterwards.
"""
from __future__ import annotations

import csv
import sys
import threading
import time
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).parent))
import loadtest as lt                                        # noqa: E402

BATCH = 10
OUT = Path(__file__).parent / "failure_sweep.csv"
MIN_FREE_GB = 2.5


def main() -> None:
    beats, vocals = lt.library()
    combos = [(b, v) for b in beats for v in vocals]
    print(f"{len(beats)} beats x {len(vocals)} vocals = {len(combos)} pairs, {BATCH} at a time")

    stamp = int(time.time())
    rows = []
    t_start = time.perf_counter()

    for start in range(0, len(combos), BATCH):
        free = psutil.disk_usage("C:/").free / 1e9
        if free < MIN_FREE_GB:
            print(f"\nSTOPPING at pair {start}: disk down to {free:.2f} GB "
                  f"(safety line {MIN_FREE_GB} GB). Partial result below.")
            break
        chunk = combos[start:start + BATCH]
        out: list = [None] * len(chunk)
        ths = [threading.Thread(target=lt.one_mix,
                                args=(b["id"], v["id"], f"sweep{stamp}-{start + i}",
                                      f"u{i}", out, i))
               for i, (b, v) in enumerate(chunk)]
        t0 = time.perf_counter()
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        secs = time.perf_counter() - t0

        ids = set()
        nfail = 0
        for (b, v), r in zip(chunk, out):
            ok = bool(r and r.get("ok"))
            nfail += 0 if ok else 1
            rows.append({"beat": b["original_name"], "vocal": v["original_name"],
                         "ok": ok, "secs": round((r or {}).get("secs", 0), 1),
                         "error": "" if ok else (r or {}).get("err", "?")})
            ids.add((r or {}).get("mix_id"))
        lt.cleanup(ids)

        done = start + len(chunk)
        bad = sum(1 for x in rows if not x["ok"])
        rate = bad / len(rows) * 100
        eta = (time.perf_counter() - t_start) / done * (len(combos) - done) / 60
        print(f"  {done:3d}/{len(combos)}  batch {secs:5.1f}s  {nfail} failed here  |  "
              f"running failure rate {rate:5.1f}%  |  ~{eta:.0f} min left")

    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["beat", "vocal", "ok", "secs", "error"])
        w.writeheader()
        w.writerows(rows)

    bad = [r for r in rows if not r["ok"]]
    print(f"\n{'=' * 74}\nRESULT: {len(bad)} of {len(rows)} pairs FAIL "
          f"({len(bad) / max(len(rows), 1) * 100:.1f}%)\n{'=' * 74}")

    from collections import Counter
    print("\nWorst VOCALS (fails / times tried):")
    tried = Counter(r["vocal"] for r in rows)
    fails = Counter(r["vocal"] for r in bad)
    for name, n in fails.most_common(12):
        print(f"  {n:2d}/{tried[name]:2d}  {name}")
    print("\nWorst BEATS (fails / times tried):")
    triedb = Counter(r["beat"] for r in rows)
    failsb = Counter(r["beat"] for r in bad)
    for name, n in failsb.most_common(12):
        print(f"  {n:2d}/{triedb[name]:2d}  {name}")
    print(f"\ncsv: {OUT}")


if __name__ == "__main__":
    main()
