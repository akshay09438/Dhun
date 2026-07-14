"""build_set.py — render a continuous DJ SET from catalog two-song mixes, to a WAV you play.

A dev tool (like measure_drops.py) for the founder to hear real sets by ear — NO /set UI. Each
--set is one two-song mix (beat, vocal) rendered through the REAL product pipeline at the current
ENGINE_VERSION (your hooks, the movable master, the full arrangement — not a special path), then
the mixes are joined by the SHIPPED beat-matched seam engine. Before rendering, the set reconciles
to ONE tempo and DECLINES outliers (a vocal too far from the beat to hold the safe stretch band),
telling you which and why. Zero cloud: catalog stems + analyses are already cached, and the /mix
pipeline only ever reads local files — proven per song before each render.

Reuses, never duplicates: mixroute._run_mix (arrangement+render), set_render.set_tempo_plan (the
one-tempo/decline logic, 3.2), set_render.assemble_beatmatched_set (the phrase-boundary seams,
3.3/3.4). Touches none of render.py / validate.py / vocal_regions / lead_sections / enabled / Slice 2d.

Usage:
  python scripts/build_set.py \
    --set "father_ocean, der_lagi" \
    --set "father_ocean, dont_start_now" \
    --set "father_ocean, tere_bina" \
    --order 2,1,3 \
    --out "my_set.wav"

  * each --set is "beat_slug, vocal_slug" (slugs are loose prefixes of the catalog names);
  * --order is 1-indexed into the --set list (default: the order given);
  * --out lands on your Desktop unless you give an absolute path.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO / "services" / "api"))
sys.path.insert(0, str(_REPO))

try:  # let non-ASCII song names (Böhmer) print on a Windows cp1252 console instead of mangling
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from app.models import MixPlan  # noqa: E402
from app.routes import mix as mixroute  # noqa: E402
from workers.set_render import (  # noqa: E402  (shipped engine — reuse, never copy)
    SR, assemble_beatmatched_set, set_tempo_plan, _phrase_seam,
)
import soundfile as sf  # noqa: E402


def _slugify(name: str) -> str:
    """A loose slug: drop apostrophes, lowercase, non-alphanumeric -> underscore."""
    s = name.lower().replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def _load_catalog() -> list[dict]:
    import json
    p = mixroute.settings.data_dir / "library" / "manifest.json"
    out = []
    for e in json.loads(p.read_text(encoding="utf-8")):
        out.append({"id": str(e["song_id"]), "name": str(e["name"]),
                    "role": str(e.get("role_hint", "")), "slug": _slugify(str(e["name"]))})
    return out


def _resolve(user_slug: str, catalog: list[dict]) -> dict:
    u = _slugify(user_slug)
    exact = [c for c in catalog if c["slug"] == u]
    pref = [c for c in catalog if c["slug"].startswith(u)]
    sub = [c for c in catalog if u in c["slug"]]
    for hits in (exact, pref, sub):
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            names = ", ".join(f"{c['name']!r} (try '{c['slug']}')" for c in hits)
            raise SystemExit(f"'{user_slug}' is ambiguous: {names}")
    avail = "\n".join(f"    {c['slug']:<28} {c['name']}  [{c['role'] or '?'}]" for c in catalog)
    raise SystemExit(f"'{user_slug}' matches no catalog song. Available:\n{avail}")


def _mmss(t: float) -> str:
    m, s = divmod(int(round(t)), 60)
    return f"{m}:{s:02d}"


def _seam_positions(seq: list[dict]) -> tuple[list[float], float]:
    """Seam times + total length, mirroring assemble_beatmatched_set's sample accounting (reusing
    the shipped _phrase_seam) so the founder can jump straight to each join."""
    y_len = seq[0]["frames"]
    y_ps = list(seq[0]["phrase_starts"])
    seams: list[float] = []
    for i in range(1, len(seq)):
        nxt_len, nxt_ps = seq[i]["frames"], seq[i]["phrase_starts"]
        seam = _phrase_seam(y_ps, y_len / SR, nxt_ps, 1)
        if seam is None:
            a_len, xf, b_skip, b_len = y_len, int(SR * 4.0), 0, nxt_len
        else:
            a_end, b_start, xf_t = seam
            a_len, b_skip, xf = int(round(a_end * SR)), int(round(b_start * SR)), int(round(xf_t * SR))
            b_len = nxt_len - b_skip
        xf = max(0, min(xf, a_len // 2, b_len // 2))
        b_out_start = a_len - xf
        seams.append(b_out_start / SR)
        y_len = a_len + b_len - xf
        y_ps = [(b_out_start + (p * SR - b_skip)) / SR for p in nxt_ps if p * SR >= b_skip - 1e-6]
    return seams, y_len / SR


def _coerce(v: str):
    lo = v.lower()
    if lo in ("true", "false"):
        return lo == "true"
    for cast in (int, float):
        try:
            return cast(v)
        except ValueError:
            pass
    return v


def _chain_config(dials_str: str):
    """VocalChainConfig(enabled=True, **overrides) + the raw overrides. Per-render only -- this never
    touches the shipped default (enabled=False) and is never committed. Referee P1-P5 bound every dial."""
    from app.models import VocalChainConfig
    overrides = dict(kv.split("=", 1) for kv in dials_str.split()) if dials_str.strip() else {}
    return VocalChainConfig(enabled=True, **{k: _coerce(v) for k, v in overrides.items()}), overrides


def _render_with_chain(beat_id: str, vocal_id: str, chain, out_wav: Path):
    """Render one mix with the vocal chain ON to a SANDBOX path (never the app cache). Reuses the SHIPPED
    build_mix_plan(chain=...) + render_mix -- enabling the chain needs NO render.py change (the chain is
    already built and gated on the plan's vocal_moves, which the config emits). Returns the plan (with its
    out_phrase_starts, so the beat-matched seam works on chain-on mixes too)."""
    from app.planner.plan import build_mix_plan
    from app.planner import validate as _validate
    from app.audio.stems import stem_path
    from workers.render import render_mix
    a1 = mixroute._load_analysis(beat_id)
    a2 = mixroute._load_analysis(vocal_id)
    plan = build_mix_plan("tune", a1, a2, "", take=1, chain=chain)
    _validate.assert_plan(plan, a1, a2)          # referee P1-P5 bound the dials
    stems = {s: stem_path(beat_id, s) for s in mixroute._S1_STEMS}
    if stem_path(beat_id, "vocals").exists():
        stems["vocals"] = stem_path(beat_id, "vocals")
    render_mix(plan, stems, stem_path(vocal_id, "vocals"), out_wav)
    _validate.assert_render(out_wav)             # P2 + crest mush guard (render-side)
    mixroute._attach_set_grid(plan, a1, out_wav)  # out_phrase_starts for the seam
    return plan


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", action="append", dest="sets", metavar='"beat, vocal"', required=True,
                    help="one two-song mix; repeat for more. e.g. --set \"father_ocean, der_lagi\"")
    ap.add_argument("--order", default="", help="1-indexed play order into the --set list, e.g. 2,1,3")
    ap.add_argument("--out", default="prompt-dj set.wav", help="output WAV (bare name -> Desktop)")
    ap.add_argument("--chain", action="store_true",
                    help="SANDBOX tuning A/B: render with the vocal chain ON (default OFF = the shipped, "
                         "byte-identical baseline). Not the shipped config, never committed -- per-render only. "
                         "Chain renders go to data/tuning_renders/, never the app cache.")
    ap.add_argument("--dials", default="",
                    help='chain dial overrides, space-separated, e.g. '
                         '--dials "saturate_wet=0.3 presence_gain_db=3.0"')
    args = ap.parse_args()

    catalog = _load_catalog()
    pairs = []  # (orig_index, beat_dict, vocal_dict)
    for i, spec in enumerate(args.sets, start=1):
        parts = [p.strip() for p in spec.split(",") if p.strip()]
        if len(parts) != 2:
            raise SystemExit(f'--set #{i} must be "beat, vocal"; got {spec!r}')
        pairs.append((i, _resolve(parts[0], catalog), _resolve(parts[1], catalog)))

    print(f"{len(pairs)} set(s) requested:")
    for i, b, v in pairs:
        print(f"  #{i}  {b['name']}  x  {v['name']}")

    # ---- ONE tempo across the set + decline outliers (shipped set_tempo_plan, 3.2) ----
    songs, seen = [], set()
    for _i, b, v in pairs:
        for s in (b, v):
            if s["id"] not in seen:
                seen.add(s["id"])
                a = mixroute._load_analysis(s["id"])
                songs.append({"id": s["id"], "name": s["name"], "bpm": (a.bpm if a else 0.0) or 0.0})
    plan = set_tempo_plan(songs)
    print(f"\nOne-tempo feasibility gate (set_tempo_plan, 3.2) — which songs can share a tempo:")
    print(f"  a single shared tempo of ~{plan['tempo']:.1f} BPM keeps the remaining songs inside the safe\n"
          f"  stretch band{'; all songs fit.' if plan['all_fit'] else '; the outlier(s) below are declined:'}")
    declined_ids = {d["id"] for d in plan["declined"]}
    for d in plan["declined"]:
        print(f"  DECLINED  {d['name']}  ({d['bpm']:.0f} BPM): needs stretch {d['ratio']} to reach a shared "
              f"tempo — outside the safe 0.89-1.11 band (would warble), so it sits out.")
    # NOTE: the mixes don't render at that abstract feasibility tempo — each renders at its BEAT song's
    # own master tempo (the movable master; the beat is the master clock), reported after rendering. For a
    # single-beat catalog the two always agree in practice: the only real outlier (Tere Bina) is dropped
    # either way, and every kept mix locks to the shared beat.

    # a set is kept only if BOTH its songs survived the tempo reconciliation
    kept, dropped = [], []
    for i, b, v in pairs:
        bad = [s["name"] for s in (b, v) if s["id"] in declined_ids]
        (dropped if bad else kept).append((i, b, v, bad))
    for i, b, v, bad in dropped:
        print(f"  set #{i} dropped ({b['name']} x {v['name']}): {', '.join(bad)} declined.")
    if not kept:
        raise SystemExit("No sets survived the tempo reconciliation.")

    # ---- zero-cloud proof: the /mix pipeline reads only cached local files ----
    print("\nZero-cloud check (the /mix pipeline never calls Replicate — it reads cached files):")
    for i, b, v, _ in kept:
        miss = mixroute._missing_prerequisite(b["id"], v["id"])
        if miss:
            raise SystemExit(f"set #{i} can't render locally: {miss} (would need the cloud — refusing).")
        print(f"  set #{i}: stems + analyses present for both songs -> local render, no cloud.")

    # ---- render each kept mix (chain OFF = shipped cache, byte-identical baseline; chain ON = sandbox) ----
    chain_cfg, dial_overrides = (_chain_config(args.dials) if args.chain else (None, {}))
    dials_tag = ("_".join(f"{k}{val}" for k, val in dial_overrides.items()) or "defaults") if args.chain else ""
    sandbox = mixroute.settings.data_dir / "tuning_renders"
    if args.chain:
        sandbox.mkdir(exist_ok=True)
        print(f"\nRendering {len(kept)} mix(es) -- CHAIN ON [{dials_tag}] to the SANDBOX (data/tuning_renders/, "
              f"never the app cache) -- ENGINE {mixroute.ENGINE_VERSION}...")
    else:
        print(f"\nRendering {len(kept)} mix(es) -- chain OFF (byte-identical baseline) -- "
              f"ENGINE {mixroute.ENGINE_VERSION}...")
    rendered: dict[int, dict] = {}
    for i, b, v, _ in kept:
        if args.chain:
            wav = sandbox / f"{b['id'][:8]}x{v['id'][:8]}_chain_{dials_tag}.mix.wav"
            print(f"  set #{i}: rendering {b['name']} x {v['name']} CHAIN-ON (local DSP, sandbox)...")
            try:
                p = _render_with_chain(b["id"], v["id"], chain_cfg, wav)
            except Exception as e:  # noqa: BLE001 — a declined pair or a referee reject (P1-P5)
                print(f"  set #{i} DROPPED — {type(e).__name__}: {e}")
                continue
        else:
            mid = mixroute.mix_id_for(b["id"], v["id"], "", 1)
            wav = mixroute._mix_wav(mid)
            if not (wav.exists() and mixroute._plan_path(mid).exists()):
                print(f"  set #{i}: rendering {b['name']} x {v['name']} (local DSP)...")
                mixroute._run_mix(mid, b["id"], v["id"], "", 1)
            else:
                print(f"  set #{i}: reusing cached render.")
            pf = mixroute._plan_path(mid)
            if not pf.exists():
                _status, reason = mixroute._jobs.get(mid, ("error", "unknown failure"))
                print(f"  set #{i} DROPPED — the pipeline declined this pair: {reason}")
                continue
            import json
            p = MixPlan(**json.loads(pf.read_text()))
        info = sf.info(str(wav))
        rendered[i] = {"name": f"{b['name']} x {v['name']}", "wav": wav,
                       "phrase_starts": p.out_phrase_starts, "master_bpm": p.master_bpm,
                       "frames": info.frames}
    if not rendered:
        raise SystemExit("No mixes rendered successfully.")

    # ---- play order (1-indexed into the ORIGINAL --set list) ----
    if args.order.strip():
        try:
            order = [int(x) for x in args.order.split(",")]
        except ValueError:
            raise SystemExit(f"--order must be comma-separated numbers, got {args.order!r}")
    else:
        order = [i for i, *_ in pairs]
    seq_idx = [i for i in order if i in rendered]
    skipped = [i for i in order if i not in rendered]
    if skipped:
        print(f"\nNote: order positions {skipped} were declined/dropped and are skipped.")
    seq = [rendered[i] for i in seq_idx]
    if not seq:
        raise SystemExit("Nothing left to play after ordering.")

    # ---- one-tempo sanity: every kept mix should share a master (seam is beat-matched only then) ----
    masters = sorted({round(m["master_bpm"], 2) for m in seq})
    if len(masters) > 1:
        print(f"\n[!] kept mixes are at DIFFERENT tempos {masters} — the seams still crossfade on a phrase\n"
              "    boundary but bars won't perfectly coincide. (Happens only with mixed beat songs; a\n"
              "    single-beat set is one tempo by construction.)")
    else:
        print(f"\n[ok] all kept mixes locked to {masters[0]} BPM (the shared beat) — seams beat-matched.")

    # ---- join with the shipped beat-matched seam engine ----
    out = Path(args.out)
    if args.chain:  # stamp the dials into the set filename so a chain render is self-documenting
        out = out.with_name(f"{out.stem} [chain {dials_tag}]{out.suffix}")
    if not out.is_absolute():
        out = Path.home() / "OneDrive" / "Desktop" / out.name
    out.parent.mkdir(parents=True, exist_ok=True)
    assemble_beatmatched_set([{"wav": m["wav"], "phrase_starts": m["phrase_starts"]} for m in seq], out)

    seams, total = _seam_positions(seq)
    print("\n" + "=" * 64)
    print(f"SET written: {out}")
    print(f"length {_mmss(total)}   |   {len(seq)} mixes   |   order {seq_idx}")
    print("-" * 64)
    at = 0.0
    for k, m in enumerate(seq):
        tag = "(start)" if k == 0 else f"seam at {_mmss(seams[k-1])}"
        print(f"  {k+1}. {m['name']:<40} {tag}")
    print("-" * 64)
    if seams:
        print("Jump to the joins:  " + "   ".join(_mmss(s) for s in seams))
    print("zero cloud (local cached stems/analyses only).")

    # Silent set-order scoring (feature 5) — LOG the order the app WOULD recommend vs the one the user
    # chose (harmonic + energy arc). DATA COLLECTION ONLY: the set above is already written in the
    # user's order, this changes nothing they hear, and it's fully guarded so it can never break a set.
    # Zero cloud (cached analyses + arithmetic; runs AFTER the render, on a handful of mixes).
    try:
        import numpy as _np
        from datetime import datetime as _dt
        from workers import set_score
        canon = sorted(rendered)                          # the rendered mixes, in --set order (canonical)
        pair_by_i = {i: (b, v) for i, b, v in pairs}
        keys, energies, names = [], [], []
        for i in canon:
            b, v = pair_by_i[i]
            a1, a2 = mixroute._load_analysis(b["id"]), mixroute._load_analysis(v["id"])
            keys.append(a1.key.camelot if a1 and a1.key else "")

            def _mean_energy(a):
                ec = (a.energy_curve if a else None) or []
                return float(_np.mean(ec)) if ec else 0.5

            energies.append(0.5 * (_mean_energy(a1) + _mean_energy(a2)))
            names.append(f"{b['name']} x {v['name']}")
        user_order = [canon.index(i) for i in seq_idx]    # the user's play order as positions in canon
        rec = set_score.log_set_pick(
            mixroute.settings.data_dir / "set_order_log.csv", names, keys, energies, user_order,
            when=_dt.now().isoformat(timespec="seconds"))
        print(f"[set-score] logged (data only, no change to the set): your order {rec['user_order']} vs "
              f"app pick {rec['app_order']}  (match={rec['match']}; app {rec['app_score']} / you "
              f"{rec['user_score']})  -> data/set_order_log.csv")
    except Exception:  # noqa: BLE001 — scoring is background data collection; never break the set
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
