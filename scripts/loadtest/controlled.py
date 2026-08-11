"""The controlled concurrency experiment. MEASURES ONLY.

The first three attempts each gave a different answer (41s, 139s, 289s worst-case for ten at once)
because each used a different set of songs, and render cost is dominated by the BEAT's length -
Innerbloom is 9:38 and costs roughly 7x what Father Ocean does. Comparing those runs measured the
songs, not the concurrency.

So: the SAME ten pairs, twice.
  Phase A - one at a time, back to back. Gives the true solo cost of each, and their sum: what a
            strictly serial engine would take.
  Phase B - all ten fired at the same instant.

speedup = sum(Phase A) / wall(Phase B). 1.0 means fully serial. 10.0 means perfectly parallel.
Anything in between is the real answer, and nobody has measured it before now.

Cleans up every file it writes.
"""
from __future__ import annotations

import statistics
import sys
import threading
import time
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).parent))
import loadtest as lt                                        # noqa: E402

# Ten pairs across four beats of comparable length, deliberately excluding Innerbloom (7x the cost,
# it would swamp the average) and Khuda Jaane (fails every time on its own - see the report).
BEATS = [0, 1, 3, 4]          # Father Ocean, I Adore You, Rapture, Anchor Point
VOCALS = [0, 1, 2, 3, 5, 8, 12, 13, 16, 17]


def main() -> None:
    beats, vocals = lt.library()
    pairs = []
    for i, vi in enumerate(VOCALS):
        bi = BEATS[i % len(BEATS)]
        pairs.append((beats[bi]["id"], vocals[vi]["id"],
                      f"{beats[bi]['original_name'][:18]} x {vocals[vi]['original_name'][:18]}"))

    free = psutil.disk_usage("C:\\").free / 1e9
    print(f"disk free: {free:.2f} GB")
    if free < 2.5:
        print("REFUSING: under the 2.5 GB safety line.")
        return

    stamp = int(time.time())
    ids: set[str] = set()

    # ---------- Phase A: one at a time ----------
    print(f"\n{'=' * 74}\nPHASE A - one at a time (the true solo cost of each)\n{'=' * 74}")
    solo: list[float] = []
    solo_ok = []
    for i, (b, v, label) in enumerate(pairs):
        out: list = [None]
        lt.one_mix(b, v, f"ctl{stamp}-a{i}", "u0", out, 0)
        r = out[0]
        ids.add(r.get("mix_id"))
        if r.get("ok"):
            solo.append(r["secs"])
            solo_ok.append(label)
            print(f"  {label:42s} {r['secs']:6.1f}s")
        else:
            print(f"  {label:42s} FAILED after {r.get('secs', 0):.1f}s")
        lt.cleanup({r.get("mix_id")})            # free the disk as we go

    if not solo:
        print("no pair succeeded; nothing to compare")
        return
    serial_total = sum(solo)
    print(f"\n  solo cost: min {min(solo):.1f}s  median {statistics.median(solo):.1f}s  "
          f"max {max(solo):.1f}s")
    print(f"  SUM of all {len(solo)} = {serial_total:.1f}s  "
          f"<- what a strictly one-at-a-time engine would take")

    # ---------- Phase B: all at once ----------
    print(f"\n{'=' * 74}\nPHASE B - the same {len(solo)} pairs, fired together\n{'=' * 74}")
    live = [p for p, lab in zip(pairs, [x[2] for x in pairs]) if lab in solo_ok]
    sampler = lt.Sampler()
    sampler.start()
    out2: list = [None] * len(live)
    t0 = time.perf_counter()
    ths = [threading.Thread(target=lt.one_mix,
                            args=(b, v, f"ctl{stamp}-b{i}", f"u{i}", out2, i))
           for i, (b, v, _l) in enumerate(live)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    wall = time.perf_counter() - t0
    sampler.stop.set()
    sampler.join(timeout=3)

    got = [r for r in out2 if r and r.get("ok")]
    for r, (_b, _v, label) in zip(out2, live):
        if r and r.get("ok"):
            print(f"  {label:42s} {r['secs']:6.1f}s")
        else:
            print(f"  {label:42s} FAILED  {(r or {}).get('err', '')}")
    ids |= {r.get("mix_id") for r in out2 if r}

    print(f"\n  finished {len(got)}/{len(live)}   wall clock {wall:.1f}s")
    print(f"  {sampler.report()}")

    print(f"\n{'=' * 74}\nTHE ANSWER\n{'=' * 74}")
    print(f"  one at a time : {serial_total:6.1f}s for {len(solo)} mixes")
    print(f"  all at once   : {wall:6.1f}s for {len(got)} mixes")
    print(f"  SPEEDUP       : {serial_total / wall:5.2f}x   "
          f"(1.0 = fully serial, {len(live)}.0 = perfectly parallel)")
    if got:
        secs = sorted(r["secs"] for r in got)
        print(f"  slowest person waited {secs[-1]:.1f}s; fastest {secs[0]:.1f}s "
              f"({secs[-1] / secs[0]:.1f}x unfairness)")
        print(f"  throughput    : {len(got) / wall * 60:.1f} mixes/minute "
              f"(vs {len(solo) / serial_total * 60:.1f} one at a time)")

    freed = lt.cleanup(ids)
    print(f"\n  cleaned up {freed:.2f} GB; free now "
          f"{psutil.disk_usage('C:/').free / 1e9:.2f} GB")


if __name__ == "__main__":
    main()
