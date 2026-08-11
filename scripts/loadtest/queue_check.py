"""The acceptance check for the render queue, against the REAL engine. MEASURES ONLY.

From the handoff, verbatim: "20 simultaneous requests: all 20 eventually succeed, at most 8
render at once, none fail."

Unit tests prove the queue's logic with fake jobs. This proves the real thing: twenty real
renders of real catalog songs, fired at the same instant at a real FastAPI process, and it
watches /queue while they run to see the cap actually hold.

Before the queue existed this same shape of test is what produced a 20.7% failure rate on a
starved host (docs/concurrency-diagnosis.md), because nothing anywhere said "not yet".

Cleans up every file it writes.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import httpx
import psutil

sys.path.insert(0, str(Path(__file__).parent))
import loadtest as lt                                        # noqa: E402

DATA = Path(__file__).resolve().parents[2] / "services" / "api" / "data"
API = lt.API
N = 20

BEATS = [0, 1, 3, 4]
VOCALS = [0, 1, 2, 3, 5, 8, 12, 13, 16, 17]


def _watch(stop: threading.Event, seen: list[dict]) -> None:
    """Poll the queue while the storm runs. This is the only way to observe the cap holding -
    after the fact, everything just looks finished."""
    while not stop.is_set():
        try:
            seen.append(httpx.get(f"{API}/queue", timeout=5).json())
        except Exception:  # noqa: BLE001 - a missed sample must not end the watch
            pass
        time.sleep(0.5)


def main() -> None:
    free = psutil.disk_usage("C:\\").free / 1e9
    print(f"disk free: {free:.2f} GB")
    if free < 4.0:
        print("REFUSING: 20 real renders need room. Under the 4 GB line.")
        return

    beats, vocals = lt.library()
    stamp = int(time.time())
    pairs = [(beats[BEATS[i % len(BEATS)]]["id"], vocals[VOCALS[i % len(VOCALS)]]["id"])
             for i in range(N)]

    results: list = [None] * N
    threads = []
    seen: list[dict] = []
    stop = threading.Event()
    watcher = threading.Thread(target=_watch, args=(stop, seen), daemon=True)
    watcher.start()

    print(f"\nfiring {N} at the same instant...")
    t0 = time.monotonic()
    for i, (b, v) in enumerate(pairs):
        # A DIFFERENT user id every four requests, so the per-person cap does not turn this
        # into a test of one person's fair share instead of a test of the cap.
        t = threading.Thread(target=lt.one_mix,
                             args=(b, v, f"q{stamp}-{i}", f"user{i % 5}", results, i))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    wall = time.monotonic() - t0
    stop.set()
    time.sleep(0.6)

    ok = [r for r in results if r and r.get("ok")]
    bad = [r for r in results if not r or not r.get("ok")]
    peak_running = max((s.get("running", 0) for s in seen), default=0)
    peak_waiting = max((s.get("waiting", 0) for s in seen), default=0)
    capacity = next((s.get("capacity") for s in seen if s.get("capacity")), None)

    print(f"\n{'=' * 74}\nRESULT\n{'=' * 74}")
    print(f"  succeeded            {len(ok)} of {N}")
    print(f"  failed               {len(bad)}")
    print(f"  wall clock           {wall:.1f}s  ({N / (wall / 60):.1f} mixes/min)")
    print(f"  cap                  {capacity}")
    print(f"  peak rendering       {peak_running}")
    print(f"  peak waiting in line {peak_waiting}")
    for r in bad:
        print(f"    FAILED: {(r or {}).get('err', 'no result')}")

    verdict = (len(ok) == N and capacity is not None and peak_running <= capacity
               and peak_waiting > 0)
    print(f"\n  {'PASS' if verdict else 'FAIL'} - all {N} succeeded, "
          f"never more than {capacity} at once, and a real line formed")

    removed = 0
    for r in results:
        mid = (r or {}).get("mix_id")
        if not mid:
            continue
        for suffix in (".mix.wav", ".bestparts.wav", ".mixplan.json"):
            p = DATA / f"{mid}{suffix}"
            if p.exists():
                p.unlink()
                removed += 1
    print(f"  cleaned up {removed} files this run created")


if __name__ == "__main__":
    main()
