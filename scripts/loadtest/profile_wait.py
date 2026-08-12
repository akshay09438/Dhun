"""How long does a person ACTUALLY wait? MEASURES ONLY - changes nothing.

WHY THIS EXISTS, and why it is not `profile_stages.py`.

`profile_stages.py` answered "where do the 25-30 seconds of a cold render go" and produced a
clean breakdown: mixing 15.23s, best-parts crop 7.98s, key 1.84s, referee 0.40s, total 25.68s.
That number then got quoted as "a grind takes 26 seconds".

It is not what anybody waits. On 2026-08-12 the render queue's own rolling average of real
grinds read 67.4s - two and a half times the profile. The profile measures the RENDER STAGES
inside the worker. A person waits for everything around them too: getting through the queue,
whatever the request does before and after the stages, writing the file out, and - for a Discord
user - the mp3 transcode and upload that happen after the engine says "done".

You cannot speed up what you have measured wrong. Before anyone optimises the 8-second crop
because it is "31% of the wait", it is worth knowing what share of the REAL wait it is.

So this measures the wall clock a caller experiences, end to end, and lines it up against the
stage timings the engine recorded for the same mix. The gap between them is the part nobody has
been looking at.

COLD BY CONSTRUCTION: the prompt is part of the mix id, so a unique prompt per run guarantees a
fresh render rather than a 0.03s cache hit, which would measure nothing.

Run:  services/api/.venv/Scripts/python.exe scripts/loadtest/profile_wait.py
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
EVENTS = DATA / "events.db"
RUNS = 3


def _stages_for(ref_id: str) -> dict:
    """The engine's own per-stage timings for this mix, if it recorded any."""
    if not EVENTS.exists():
        return {}
    c = sqlite3.connect(EVENTS)
    c.row_factory = sqlite3.Row
    try:
        row = c.execute("SELECT extra FROM events WHERE ref_id=? AND extra IS NOT NULL "
                        "ORDER BY id DESC LIMIT 1", (ref_id,)).fetchone()
    finally:
        c.close()
    if row is None or not row["extra"]:
        return {}
    try:
        extra = json.loads(row["extra"])
    except (TypeError, ValueError):
        return {}
    stages = extra.get("stages") or extra.get("timings") or {}
    if not isinstance(stages, dict):
        return {}
    # The engine records a "total" alongside the individual stages. Summing the dict as-is counts
    # every second twice and produces a nonsensical negative "unaccounted" figure - which is
    # exactly what the first run of this script reported before the key was dropped.
    return {k: v for k, v in stages.items() if k != "total"}


def main() -> int:
    beats, vocals = lt.library()
    if not beats or not vocals:
        print("no ready songs in the catalog - is the engine running on port 8000?")
        return 1
    pairs = [(beats[i % len(beats)]["id"], vocals[i % len(vocals)]["id"]) for i in range(RUNS)]

    print("measuring the FULL wait on %d cold grinds" % len(pairs))
    print()
    rows, made = [], set()
    for i, (beat, vocal) in enumerate(pairs, start=1):
        prompt = "wait-profile-%d-%d" % (time.time_ns(), i)   # unique -> guaranteed cold
        out = [None]
        t0 = time.perf_counter()
        lt.one_mix(beat, vocal, prompt, "wait-profile-%d" % i, out, 0)
        felt = time.perf_counter() - t0
        res = out[0] or {}
        if not res.get("ok"):
            print("  run %d: FAILED (%s)" % (i, res.get("err")))
            continue
        made.add(res["mix_id"])
        stages = _stages_for(res["mix_id"])
        stage_sum = sum(v for v in stages.values() if isinstance(v, (int, float)))
        rows.append({"total": felt, "stages": stages, "stage_sum": stage_sum})
        print("  run %d: felt %6.2fs   stages summed %6.2fs   unaccounted %6.2fs"
              % (i, felt, stage_sum, felt - stage_sum))

    if not rows:
        print()
        print("no successful runs - nothing measured")
        return 1

    totals = [r["total"] for r in rows]
    sums = [r["stage_sum"] for r in rows]
    mean_total = statistics.mean(totals)
    gap = mean_total - statistics.mean(sums)
    share = 100 * gap / mean_total if mean_total else 0

    print()
    print("=" * 70)
    print("THE WAIT A PERSON FEELS   : %6.2fs (min %.2f, max %.2f)"
          % (mean_total, min(totals), max(totals)))
    print("THE STAGES THE PROFILE SAW: %6.2fs" % statistics.mean(sums))
    print("NOT IN THE OLD BREAKDOWN  : %6.2fs  (%.0f%% of the real wait)" % (gap, share))
    print("=" * 70)

    agg: dict[str, list[float]] = {}
    for r in rows:
        for k, v in r["stages"].items():
            if isinstance(v, (int, float)):
                agg.setdefault(k, []).append(v)
    if agg:
        print()
        print("stages, as a share of the REAL wait (not of each other):")
        for k, vs in sorted(agg.items(), key=lambda kv: -statistics.mean(kv[1])):
            m = statistics.mean(vs)
            print("  %-22s %6.2fs   %5.1f%%" % (k, m, 100 * m / mean_total))
    print()
    print("  %-22s %6.2fs   %5.1f%%   <-- never measured before"
          % ("everything else", gap, share))

    # Leave no litter: these were unique-prompt renders made only to be timed.
    try:
        freed = lt.cleanup(made)
        print()
        print("cleaned up %d profile renders (%.2f GB)" % (len(made), freed))
    except Exception as e:  # noqa: BLE001
        print()
        print("cleanup skipped: %s" % e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
