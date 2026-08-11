"""Concurrency diagnosis for the Prompt-DJ engine. MEASURES ONLY - changes no engine code.

    python loadtest.py <scenario> [n]

Scenarios
  baseline        one cold render, alone. The unit everything else is measured against.
  cached          the same pair again. Proves (or disproves) the "instant repeat" claim.
  concurrent N    N DIFFERENT pairs fired at the same instant. THE question: does N at once
                  cost N x baseline (serial) or about baseline (parallel)?
  samepair N      N people asking for the SAME pair at the same instant. Should render once.

Every run samples CPU (per core) and memory for the whole duration, and prints per-request
submit -> ready timings, not just a total.

CACHE MISSES are forced with a unique prompt per run: mix_id is a hash over
(song1, song2, prompt, take, rule), so a fresh prompt guarantees real work rather than a
disk read. The prompt also seeds the effect-combo shuffle, so each render is a genuine,
representative render - just not byte-identical to another run's.

DISK: every mix written by a run is deleted at the end (the ids are recorded as they are
created). The machine has limited headroom and a render is ~98 MB.
"""
from __future__ import annotations

import json
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import psutil

API = "http://127.0.0.1:8000"
DATA = Path(r"C:\Users\Akshay\OneDrive\Desktop\DJ AI Official Folder for claude\services\api\data")
POLL_SECS = 0.5
TIMEOUT_SECS = 900


def _post(path: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(API + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {"detail": e.read().decode(errors="ignore")[:200]}


def _get(path: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(API + path, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {"detail": e.read().decode(errors="ignore")[:200]}


def library() -> tuple[list, list]:
    _s, d = _get("/library")
    songs = d if isinstance(d, list) else d.get("songs", d)
    beats = [s for s in songs if s.get("role_hint") == "beat" and s.get("status") == "ready"]
    vocals = [s for s in songs if s.get("role_hint") == "vocals" and s.get("status") == "ready"]
    return beats, vocals


class Sampler(threading.Thread):
    """CPU per core + memory, sampled for the whole run. This is what shows whether the work is
    spread across the cores or pinned to one by Python's global lock."""

    def __init__(self):
        super().__init__(daemon=True)
        self.stop = threading.Event()
        self.total_cpu: list[float] = []
        self.max_per_core = 0.0
        self.busy_cores: list[float] = []      # how many cores were >50% busy at each sample
        self.rss_gb: list[float] = []
        self.threads: list[int] = []
        self.proc = self._engine_proc()

    @staticmethod
    def _engine_proc():
        """Whoever is LISTENING on 8000. Matching on the command line found the launcher process
        instead (1 thread, no memory), which silently reported zeroes for everything."""
        for c in psutil.net_connections(kind="inet"):
            if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port == 8000 and c.pid:
                try:
                    return psutil.Process(c.pid)
                except psutil.Error:
                    return None
        return None

    def run(self) -> None:
        while not self.stop.is_set():
            per = psutil.cpu_percent(interval=0.5, percpu=True)
            self.total_cpu.append(sum(per) / len(per))
            self.busy_cores.append(sum(1 for c in per if c > 50))
            if self.proc is not None:
                try:
                    self.rss_gb.append(self.proc.memory_info().rss / 1e9)
                    self.threads.append(self.proc.num_threads())
                except Exception:  # noqa: BLE001
                    pass

    def report(self) -> str:
        def m(xs, f="{:.1f}"):
            return f.format(max(xs)) if xs else "?"

        avg = f"{statistics.mean(self.total_cpu):.1f}" if self.total_cpu else "?"
        return (f"CPU avg {avg}% peak {m(self.total_cpu)}%  |  "
                f"cores >50% busy: peak {m(self.busy_cores, '{:.0f}')} of {psutil.cpu_count()}  |  "
                f"engine RAM peak {m(self.rss_gb, '{:.2f}')} GB  |  "
                f"engine threads peak {m(self.threads, '{:.0f}')}")


def one_mix(beat: str, vocal: str, prompt: str, uid: str, out: list, idx: int) -> None:
    """Submit and poll one mix. Records the full submit -> ready timeline."""
    t0 = time.perf_counter()
    code, r = _post("/mix", {"song1_id": beat, "song2_id": vocal, "prompt": prompt,
                             "user_id": uid, "source": "web"})
    submit_ms = (time.perf_counter() - t0) * 1000
    if code not in (200, 202):
        out[idx] = {"ok": False, "err": f"HTTP {code}: {str(r)[:120]}", "submit_ms": submit_ms}
        return
    mix_id = r.get("mix_id")
    cached = (r.get("status") == "ready")
    while True:
        if time.perf_counter() - t0 > TIMEOUT_SECS:
            out[idx] = {"ok": False, "err": "timed out", "mix_id": mix_id,
                        "secs": time.perf_counter() - t0}
            return
        _c, s = _get(f"/mix/{mix_id}")
        st = s.get("status")
        if st == "ready":
            out[idx] = {"ok": True, "mix_id": mix_id, "secs": time.perf_counter() - t0,
                        "submit_ms": submit_ms, "cached": cached}
            return
        if st == "error":
            out[idx] = {"ok": False, "err": s.get("message", "error"), "mix_id": mix_id,
                        "secs": time.perf_counter() - t0}
            return
        time.sleep(POLL_SECS)


def cleanup(mix_ids: set[str]) -> float:
    """Delete everything this run wrote. Returns GB reclaimed."""
    freed = 0
    for mid in mix_ids:
        if not mid:
            continue
        for p in DATA.glob(f"{mid}*"):
            try:
                freed += p.stat().st_size
                p.unlink()
            except OSError:
                pass
    return freed / 1e9


def run(scenario: str, n: int) -> None:
    beats, vocals = library()
    print(f"catalog: {len(beats)} beats x {len(vocals)} vocals")
    stamp = f"lt{int(time.time())}"

    pairs: list[tuple[str, str, str, str]] = []      # beat, vocal, prompt, user
    if scenario == "baseline":
        pairs = [(beats[0]["id"], vocals[0]["id"], f"{stamp}-base", "u0")]
    elif scenario == "cached":
        # deliberately the SAME prompt twice: second must hit the cache
        pairs = [(beats[0]["id"], vocals[0]["id"], f"{stamp}-cache", "u0")]
    elif scenario == "samepair":
        pairs = [(beats[0]["id"], vocals[0]["id"], f"{stamp}-same", f"u{i}") for i in range(n)]
    elif scenario == "concurrent":
        # OFFSET exists because Father Ocean x Khuda Jaane (combo 9) fails on its own, every time -
        # a broken pair, nothing to do with load. Leaving it in the set would make a concurrency
        # number look like a concurrency failure.
        off = int(sys.argv[3]) if len(sys.argv) > 3 else 0
        combos = [(b["id"], v["id"]) for b in beats for v in vocals]
        pairs = [(combos[off + i][0], combos[off + i][1], f"{stamp}-c{off + i}", f"u{i}")
                 for i in range(n)]
    else:
        print(f"unknown scenario {scenario}")
        return

    free_before = psutil.disk_usage("C:\\").free / 1e9
    print(f"disk free before: {free_before:.2f} GB")
    if free_before < 2.5:
        print("REFUSING: under the 2.5 GB safety line. Free space first.")
        return

    sampler = Sampler()
    if sampler.proc is None:
        print("note: could not identify the engine process; RAM/thread numbers unavailable")
    sampler.start()

    out: list = [None] * len(pairs)
    wall0 = time.perf_counter()
    threads = [threading.Thread(target=one_mix, args=(b, v, p, u, out, i))
               for i, (b, v, p, u) in enumerate(pairs)]
    for t in threads:
        t.start()                      # all fired as close to the same instant as possible
    for t in threads:
        t.join()
    wall = time.perf_counter() - wall0
    sampler.stop.set()
    sampler.join(timeout=3)

    if scenario == "cached":
        again: list = [None]
        t0 = time.perf_counter()
        one_mix(pairs[0][0], pairs[0][1], pairs[0][2], "u0", again, 0)
        print(f"\n  first (cold): {out[0]['secs']:.1f}s")
        print(f"  second (same pair, same prompt): {again[0]['secs']:.2f}s  "
              f"served-from-cache={again[0].get('cached')}")
        out = out + again

    print(f"\n--- {scenario} n={len(pairs)} ---")
    ok = [r for r in out if r and r.get("ok")]
    bad = [r for r in out if r and not r.get("ok")]
    for i, r in enumerate(out):
        if r and r.get("ok"):
            print(f"  #{i:<3} ready in {r['secs']:7.1f}s   (submit ack {r['submit_ms']:.0f} ms)")
        elif r:
            print(f"  #{i:<3} FAILED  {r.get('err')}  after {r.get('secs', 0):.1f}s")
    if ok:
        secs = sorted(r["secs"] for r in ok)
        print(f"\n  finished    : {len(ok)}/{len(pairs)}   failed: {len(bad)}")
        print(f"  wall clock  : {wall:.1f}s   (first done {secs[0]:.1f}s, last done {secs[-1]:.1f}s)")
        print(f"  per-request : median {statistics.median(secs):.1f}s")
        print(f"  throughput  : {len(ok) / wall * 60:.1f} mixes/minute")
    print(f"  {sampler.report()}")

    ids = {r.get("mix_id") for r in out if r}
    freed = cleanup(ids)
    free_after = psutil.disk_usage("C:\\").free / 1e9
    print(f"\n  cleaned up {freed:.2f} GB; disk free now {free_after:.2f} GB")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "baseline",
        int(sys.argv[2]) if len(sys.argv) > 2 else 1)
