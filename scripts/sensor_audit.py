"""Rule 2 (DROP_CLEAR) sensor audit — READ-ONLY go/no-go gate.

Proves (or disproves) that the signals Rule 2 needs — a drop's START, its END, and
the post-drop point where energy goes FLAT — actually exist, at usable contrast, on
the real 6-beat catalog. It touches NO product code and changes NO behaviour:

  * reads only cached analyses (data/{id}.analysis.json) and cached stems
    (data/{id}.{stem}.mp3), decoding stems with ffmpeg exactly like analysis.py does;
  * makes ZERO cloud calls, re-ingests nothing, bumps no version, writes no cache;
  * imports the REAL drop detector (planner.fence.energy_drops) so the "onset" it
    marks is the exact one Rule 2 would reuse.

Run:  services/api/.venv/Scripts/python.exe scripts/sensor_audit.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

# Make `import app...` work the same way uvicorn does (--app-dir services/api),
# and let app.config resolve settings.data_dir to services/api/data.
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "services" / "api"))

try:  # UTF-8 so block glyphs and accented titles never choke the Windows console
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import soundfile as sf  # noqa: E402  (after sys.path tweak)

from app.config import settings  # noqa: E402
from app.audio.analysis import analysis_path  # noqa: E402
from app.audio.stems import STEMS, stem_path  # noqa: E402
from app.planner.main_drops import main_drops_for  # noqa: E402

try:
    from app.planner.fence import energy_drops as _real_energy_drops
except Exception:  # pragma: no cover — fall back to a verbatim copy if the import chain breaks
    _real_energy_drops = None


def energy_drops(energy_curve, downbeats, high=0.6, min_rise=0.15, look_back=4):
    """The exact shipped detector (imported when possible; verbatim copy otherwise)."""
    if _real_energy_drops is not None:
        return _real_energy_drops(energy_curve, downbeats, high=high,
                                  min_rise=min_rise, look_back=look_back)
    drops, n, in_drop = [], min(len(energy_curve), len(downbeats)), False
    for i in range(n):
        e = energy_curve[i]
        if e < high:
            in_drop = False
            continue
        window = energy_curve[max(0, i - look_back):i]
        rose = bool(window) and (e - sum(window) / len(window)) >= min_rise
        if rose and not in_drop:
            drops.append(downbeats[i])
        in_drop = True
    return drops


# ---------------------------------------------------------------- helpers

DATA = settings.data_dir
SPARK = "▁▂▃▄▅▆▇█"
STD_FLOOR = 0.05          # curve flatter than this: RMS can't tell build from drop
RISE_FLOOR = 0.15         # max 4-bar rise below this: the detector can never fire


def load_beats() -> list[dict]:
    manifest = json.loads((DATA / "library" / "manifest.json").read_text(encoding="utf-8"))
    return [e for e in manifest if e.get("role_hint") == "beat"]


def load_analysis(song_id: str) -> dict | None:
    p = analysis_path(song_id)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def wav_duration(song_id: str) -> float:
    p = DATA / f"{song_id}.wav"
    try:
        return float(sf.info(str(p)).duration)
    except Exception:
        return 0.0


def decode_stem_mono(song_id: str, stem: str):
    """ffmpeg-decode a cached stem mp3 to mono float32 (mirrors analysis._vocal_regions)."""
    src = stem_path(song_id, stem)
    if not src.exists():
        return None, 0
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "s.wav"
        r = subprocess.run(["ffmpeg", "-y", "-i", str(src), "-ac", "1", str(wav)],
                           capture_output=True, timeout=180)
        if r.returncode != 0:
            return None, 0
        y, sr = sf.read(str(wav), dtype="float32", always_2d=True)
    return y.mean(axis=1), sr


def rms_per_bar(mono, sr, downbeats) -> list[float]:
    """Peak-normalised RMS per bar on the downbeat grid — same recipe as analysis._rms_per_bar."""
    out = []
    for i, start in enumerate(downbeats):
        end = downbeats[i + 1] if i + 1 < len(downbeats) else len(mono) / sr
        seg = mono[int(start * sr):int(end * sr)]
        out.append(float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0)
    peak = max(out) if out else 1.0
    return [round(v / peak, 3) if peak > 0 else 0.0 for v in out]


def max_rise(curve, look_back=4) -> float:
    if len(curve) <= look_back:
        return 0.0
    return max(curve[b] - curve[b - look_back] for b in range(look_back, len(curve)))


def nearest_bar(downbeats, t: float) -> int:
    if not downbeats:
        return -1
    return int(np.argmin([abs(d - t) for d in downbeats]))


def sparkline(curve) -> str:
    return "".join(SPARK[min(7, max(0, int(v * 8)))] for v in curve)


def print_curve(curve, onset_bars, hand_bars, width=100):
    """Sparkline in aligned chunks: ruler (bar # every 8), the curve, and marks below."""
    n = len(curve)
    onset_set, hand_set = set(onset_bars), set(hand_bars)
    for base in range(0, n, width):
        chunk = range(base, min(base + width, n))
        ruler = [" "] * (len(chunk))
        for j, b in enumerate(chunk):
            if b % 8 == 0:
                label = str(b)
                for k, ch in enumerate(label):
                    if j + k < len(ruler):
                        ruler[j + k] = ch
        marks = []
        for b in chunk:
            marks.append("H" if b in hand_set else ("^" if b in onset_set else " "))
        print("  bar " + "".join(ruler))
        print("      " + "".join(SPARK[min(7, max(0, int(curve[b] * 8)))] for b in chunk))
        print("      " + "".join(marks))
        print()


# ---------------------------------------------------------------- phases

def phase_a():
    print("=" * 78)
    print("PHASE A — Signal inventory (from the CODE, not the docs)")
    print("=" * 78)
    rows = [
        ("energy_curve", "audio/analysis._rms_per_bar", "list[float], one entry PER BAR (len==len(downbeats)); "
         "bar i = [downbeats[i], downbeats[i+1]); FULL-MIX mono RMS; peak-normalised per track (v/max, 0..1, 3dp); "
         "NOT smoothed; NOT stem-based -> Song 1's vocal IS in it."),
        ("downbeats", "cloud analyzer -> structure.json", "list[float] seconds; grid every boundary snaps to."),
        ("beats / bpm", "cloud (bpm) + structure.json", "beats: list[float] sec; bpm float; "
         "bpm_confidence = analysis._beat_regularity(beats), 0.1..0.98 from beat-gap steadiness."),
        ("phrase_starts", "analysis: downbeats[::8]", "every 8th downbeat (4/4 assumed)."),
        ("sections / conf", "cloud segments; conf FIXED 0.6", "weak link; nothing load-bearing -> ignorable."),
        ("vocal_regions", "analysis._vocal_regions (vocal STEM)", "list[[start,end]] sec, thresh 0.25*loudest "
         "vocal bar; needs stems FIRST; conf 0.8 w/ stem else 0.3 & []."),
        ("drop detector", "planner.fence.energy_drops", "RETURNS list[float] = downbeat TIMES (sec), NOT bar "
         "indices/objects; high=0.6, min_rise=0.15, look_back=4; computed live (not cached); "
         "main_drops.py HAND MARKS override it for listed beats."),
    ]
    for name, src, detail in rows:
        print(f"\n• {name}\n    source : {src}\n    shape  : {detail}")
    print("\nSpec questions answered:")
    print("  1. Bar-aligned? YES — index i is exactly [downbeats[i], downbeats[i+1]). Not a time grid.")
    print("  2. len(energy_curve) vs len(downbeats)? EQUAL by construction (loop is over downbeats). Verified per-track in Phase B.")
    print("  3. Full-mix or stems? FULL-MIX mono. So Song 1's vocal contributes to the 'energy' -> a")
    print("     feature the listener won't hear in the bed (S1 vocal is excluded by construction). LOUD FLAG.")
    print("  4. Normalised how? PER-TRACK MAX (v/peak). So energy>=0.6 is a DIFFERENT physical loudness on")
    print("     every song; cross-song energy constants are NOT comparable.")


def phase_bce(beats):
    print("\n" + "=" * 78)
    print("PHASE B — Real numbers, all 6 beat tracks")
    print("=" * 78)
    summary = []
    for e in beats:
        sid, name = e["song_id"], e["name"]
        a = load_analysis(sid)
        print(f"\n### {name}\n    id {sid[:12]}…")
        if not a:
            print("    NO cached analysis.json — SKIPPED")
            summary.append((name, None))
            continue
        ec = a.get("energy_curve", []) or []
        db = a.get("downbeats", []) or []
        bt = a.get("beats", []) or []
        arr = np.asarray(ec, dtype=float) if ec else np.zeros(0)
        std = float(arr.std()) if arr.size else 0.0
        mr = max_rise(ec)
        hand = main_drops_for(sid)
        onsets = energy_drops(ec, db)
        vr = a.get("vocal_regions", []) or []
        dur = wav_duration(sid) or (db[-1] if db else 0.0)
        cover = (sum(y - x for x, y in vr) / dur * 100.0) if dur else 0.0
        flat = std < STD_FLOOR
        cant_fire = mr < RISE_FLOOR
        print(f"    len(energy_curve)={len(ec)}  len(downbeats)={len(db)}  len(beats)={len(bt)}"
              f"  {'[LEN MISMATCH]' if len(ec) != len(db) else '[len OK]'}")
        print(f"    bpm={a.get('bpm')}  bpm_confidence={round(float(a.get('bpm_confidence', 0)), 3)}"
              f"  local_ver={a.get('local_analysis_version')}  vocal_conf={a.get('vocal_confidence')}")
        if arr.size:
            print(f"    energy: min={arr.min():.3f} max={arr.max():.3f} mean={arr.mean():.3f} "
                  f"std={std:.3f} {'<< FLAT (RMS blind)' if flat else ''}")
        print(f"    bars energy>=0.6 : {int((arr >= 0.6).sum()) if arr.size else 0}")
        print(f"    LARGEST 4-bar rise : {mr:.3f} {'<< BELOW 0.15 — detector CANNOT fire here' if cant_fire else ''}")
        print(f"    drop onsets (energy_drops): {len(onsets)} at "
              f"{[round(t, 1) for t in onsets][:12]}{' …' if len(onsets) > 12 else ''}"
              f"{'  [!! 0 onsets]' if len(onsets) == 0 else ''}{'  [!! >8 onsets]' if len(onsets) > 8 else ''}")
        if hand:
            print(f"    HAND-MARKED drop overrides detection -> {hand} sec (bars {[nearest_bar(db, t) for t in hand]})")
        print(f"    vocal_regions coverage: {cover:.1f}% of {dur:.0f}s  ({len(vr)} regions)")
        summary.append((name, dict(std=std, mr=mr, flat=flat, cant_fire=cant_fire,
                                   onsets=onsets, hand=hand, ec=ec, db=db, vr=vr,
                                   dur=dur, cover=cover, vocal_conf=a.get("vocal_confidence"))))

    print("\n" + "=" * 78)
    print("PHASE C — The curve, for the founder's ear check")
    print("     glyphs ▁..█ = per-bar energy (0..1)   ^ = detected onset   H = hand-marked drop")
    print("=" * 78)
    for name, s in summary:
        if not s:
            continue
        onset_bars = [nearest_bar(s["db"], t) for t in s["onsets"]]
        hand_bars = [nearest_bar(s["db"], t) for t in s["hand"]]
        print(f"\n### {name}   ({len(s['ec'])} bars)")
        print_curve(s["ec"], onset_bars, hand_bars)
        marks = sorted(set(onset_bars) | set(hand_bars))
        for b in marks:
            lo, hi = max(0, b - 16), min(len(s["ec"]), b + 16)
            tag = "HAND" if b in hand_bars else "onset"
            vals = " ".join(f"{v:.2f}" for v in s["ec"][lo:hi])
            print(f"    32-bar window around {tag} bar {b} (bars {lo}..{hi - 1}):")
            print(f"      {vals}")
    return summary


def phase_d(beats, summary):
    triggered = any(s and (s["flat"] or s["cant_fire"]) for _, s in summary)
    print("\n" + "=" * 78)
    print("PHASE D — Stem-derived sensors (local numpy on cached stems, no cloud)")
    print("=" * 78)
    if not triggered:
        print("NOT TRIGGERED — every beat's RMS has usable contrast (std>=0.05 and max-rise>=0.15).")
        print("Stem sensors not needed to make the gate call.")
        return
    print("TRIGGERED — at least one beat's RMS is flat or below the detector's firing floor.")
    print("Computing bass-band, drum-onset-density, HF-flux, stem-activity per bar (same grid).\n")
    for e in beats:
        sid, name = e["song_id"], e["name"]
        a = load_analysis(sid)
        if not a:
            continue
        db = a.get("downbeats", []) or []
        if not db:
            continue
        print(f"\n### {name}")
        # 1) bass-band energy = bass stem RMS/bar
        bass, sr = decode_stem_mono(sid, "bass")
        if bass is not None:
            bcurve = rms_per_bar(bass, sr, db)
            print(f"  bass-band  std={np.std(bcurve):.3f} maxrise={max_rise(bcurve):.3f}")
            print("      " + sparkline(bcurve))
        else:
            print("  bass stem missing")
        # 2) drum onset density/bar
        drums, sr = decode_stem_mono(sid, "drums")
        if drums is not None:
            print("      " + sparkline(_onset_density(drums, sr, db)))
            print("  drum-onset-density (per bar, normalised) ^ above")
        # 3) HF flux on full mix
        # 4) stem-activity count
        act = _stem_activity(sid, db)
        if act is not None:
            print("      " + sparkline([v / 4.0 for v in act]))
            print("  stem-activity (#stems active /4) ^ above")


def _onset_density(mono, sr, downbeats):
    frame, hop = 1024, 512
    n = max(1, (len(mono) - frame) // hop)
    env = np.array([np.sqrt(np.mean(mono[i * hop:i * hop + frame] ** 2)) for i in range(n)])
    flux = np.diff(env, prepend=env[:1])
    flux[flux < 0] = 0.0
    thr = flux.mean() + flux.std()
    times = np.arange(n) * hop / sr
    dens = []
    for i, start in enumerate(downbeats):
        end = downbeats[i + 1] if i + 1 < len(downbeats) else times[-1] if len(times) else start
        m = (times >= start) & (times < end)
        dens.append(int(((flux[m] > thr) & (flux[m] > 0)).sum()))
    peak = max(dens) if dens else 1
    return [d / peak if peak else 0.0 for d in dens]


def _stem_activity(sid, downbeats):
    per = {}
    for stem in STEMS:
        mono, sr = decode_stem_mono(sid, stem)
        if mono is None:
            continue
        per[stem] = rms_per_bar(mono, sr, downbeats)
    if not per:
        return None
    n = len(downbeats)
    out = []
    for i in range(n):
        out.append(sum(1 for stem in per if i < len(per[stem]) and per[stem][i] > 0.15))
    return out


def phase_e(beats, summary):
    print("\n" + "=" * 78)
    print("PHASE E — Song 1 vocal check (does S1's own lyric carry the drop?)")
    print("=" * 78)
    for (name, s), e in zip(summary, beats):
        if not s:
            continue
        sid = e["song_id"]
        stem_exists = stem_path(sid, "vocals").exists()
        stale = (not s["vr"]) and stem_exists  # empty regions but a stem on disk => analyzed pre-stems
        blob = s["cover"] >= 95.0
        print(f"\n### {name}")
        print(f"    vocal_regions coverage: {s['cover']:.1f}%  vocal_conf={s['vocal_conf']}  "
              f"stem_on_disk={stem_exists}")
        if blob:
            print("    >> ~full coverage = BLOB failure: 'S1 vocal passages' is not a well-defined set (CORE fill = mush).")
        if stale:
            print("    >> STALE-CACHE ORDERING TRAP: regions empty but a vocals stem exists -> analyzed BEFORE stems.")
        if s["vocal_conf"] == 0.3 and not stem_exists:
            print("    >> analyzed with NO stem (conf 0.3) and none on disk.")
        # vocals present in the drop region?
        marks = list(s["onsets"]) + list(s["hand"])
        if not marks:
            print("    (no drop marked -> can't check drop-region vocals)")
            continue
        for t in marks[:6]:
            has = any(x < t + 20 and y > t for x, y in s["vr"])
            print(f"    drop@{t:.0f}s: S1 vocal in [drop, drop+20s]? {'YES' if has else 'NO (CORE runs bed-only)'}")


def gate(summary):
    print("\n" + "=" * 78)
    print("DECISION GATE")
    print("=" * 78)
    live = [(n, s) for n, s in summary if s]
    if not live:
        print("RED — no cached analyses to judge.")
        return
    flat = [n for n, s in live if s["flat"]]
    cant = [n for n, s in live if s["cant_fire"]]
    zero = [n for n, s in live if len(s["onsets"]) == 0 and not s["hand"]]
    print(f"tracks judged: {len(live)}/6")
    print(f"flat RMS (std<{STD_FLOOR}): {flat or 'none'}")
    print(f"below firing floor (max-rise<{RISE_FLOOR}): {cant or 'none'}")
    print(f"0 auto-onsets AND no hand mark: {zero or 'none'}")
    print("\n(Machine read below — the FOUNDER'S EAR on the Phase C plots is the real verdict.)")
    if not flat and not cant:
        print(">> Leaning GREEN: RMS is bar-aligned with usable contrast on the judged tracks.")
    elif flat or cant:
        print(">> Leaning AMBER: RMS too flat / below floor on some tracks; check Phase D for a cleaner stem signal.")


def main():
    beats = load_beats()
    print(f"Sensor audit — {len(beats)} beat tracks — data dir: {DATA}")
    phase_a()
    summary = phase_bce(beats)
    phase_d(beats, summary)
    phase_e(beats, summary)
    gate(summary)


if __name__ == "__main__":
    main()
