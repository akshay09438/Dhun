"""Render an OFFLINE beat-matched-seam demo: join two finished mixes into one WAV so
the seam engine (set transitions 3.1-3.4) can be HEARD before any /set UI exists.

Why this script exists: the set engine is built and unit-tested, but tests prove maths,
not sound. The founder asked to hear the biggest new thing — a real beat-matched seam —
before we wire a screen around it. This produces exactly that: two catalog mixes,
crossfaded on a phrase boundary with their downbeats aligned, written to a WAV you play.

What it does, reusing the SHIPPED pipeline (no duplicated mix logic, ZERO cloud — catalog
stems + analyses are already cached, so nothing hits Replicate):
  1. For each of two (beat, vocal) pairs: reuse routes.mix._run_mix to render the mix and
     stamp its own output-time grid onto the plan (MixPlan.out_phrase_starts — the 3.1 work).
     If that exact mix is already cached WITH a grid, it's reused as-is.
  2. Read each plan's out_phrase_starts and feed {wav, phrase_starts} to the SHIPPED
     workers.set_render.assemble_beatmatched_set (the 3.3/3.4 engine).
  3. Write the joined set to a WAV and print WHERE the seam sits, so you know when to listen.

Both defaults are Father-Ocean-beat mixes, so they share one master tempo and the seam is
beat-matched by construction (3.2's global-tempo step is a no-op when the bed is identical);
the script prints each mix's master_bpm and WARNS if they differ, since a true multi-tempo
set must re-render every mix at one global tempo (that's the /set-wiring work, not this demo).

Usage (from the repo root, with the api venv):
  services/api/.venv/Scripts/python.exe scripts/set_seam_demo.py
  ... scripts/set_seam_demo.py --out "C:/Users/Akshay/OneDrive/Desktop/set-seam demo.wav"
  ... scripts/set_seam_demo.py --vocals "Der Lagi Lekin (ZNMD)" "Don't Start Now (Dua Lipa)"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
# Reuse the SHIPPED code — never a copy. routes.mix owns the render+grid pipeline;
# set_render owns the seam engine. Importing the module does NOT start a server.
sys.path.insert(0, str(_REPO / "services" / "api"))
sys.path.insert(0, str(_REPO))

from app.config import settings  # noqa: E402
from app.models import MixPlan  # noqa: E402
from app.routes import mix as mixroute  # noqa: E402
from workers.set_render import assemble_beatmatched_set  # noqa: E402

_DEFAULT_BEAT = "Father Ocean (Ben Böhmer Remix)"
_DEFAULT_VOCALS = ["Don't Start Now (Dua Lipa)", "Der Lagi Lekin (ZNMD)"]
_DEFAULT_OUT = Path.home() / "OneDrive" / "Desktop" / "Prompt-DJ set-seam demo.wav"


def _catalog() -> dict[str, str]:
    """Display name -> song_id, from the same manifest the /library route reads."""
    p = settings.data_dir / "library" / "manifest.json"
    entries = json.loads(p.read_text(encoding="utf-8"))
    return {str(e["name"]): str(e["song_id"]) for e in entries}


def _ensure_mix(beat_id: str, vocal_id: str) -> MixPlan:
    """Render (beat x vocal) if it isn't already cached with a grid, and return its plan.
    Renders synchronously through the SHIPPED _run_mix (plan -> validate -> render -> grid)."""
    mix_id = mixroute.mix_id_for(beat_id, vocal_id, "", take=1)
    wav, plan_file = mixroute._mix_wav(mix_id), mixroute._plan_path(mix_id)

    cached = wav.exists() and plan_file.exists()
    if cached:
        plan = MixPlan(**json.loads(plan_file.read_text()))
        if plan.out_phrase_starts:  # already carries the 3.1 grid -> reuse, no re-render
            print(f"  reuse cached mix {mix_id[:12]} ({len(plan.out_phrase_starts)} phrases)")
            return plan

    print(f"  rendering mix {mix_id[:12]} (beat x vocal)... this is local DSP, no cloud")
    mixroute._run_mix(mix_id, beat_id, vocal_id, "", 1)
    if not (wav.exists() and plan_file.exists()):
        status, message = mixroute._jobs.get(mix_id, ("error", "unknown failure"))
        raise SystemExit(f"mix render failed ({status}): {message}")
    return MixPlan(**json.loads(plan_file.read_text()))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--beat", default=_DEFAULT_BEAT, help="catalog display name of the beat song")
    ap.add_argument("--vocals", nargs=2, default=_DEFAULT_VOCALS,
                    help="two catalog vocal display names, in play order")
    ap.add_argument("--out", type=Path, default=_DEFAULT_OUT, help="output WAV path")
    args = ap.parse_args()

    cat = _catalog()
    missing = [n for n in (args.beat, *args.vocals) if n not in cat]
    if missing:
        raise SystemExit(f"not in the catalog: {missing}\nknown: {sorted(cat)}")

    print(f"Beat: {args.beat}")
    plans: list[MixPlan] = []
    for v in args.vocals:
        print(f"Mix with vocal: {v}")
        plans.append(_ensure_mix(cat[args.beat], cat[v]))

    tempos = {round(p.master_bpm, 1) for p in plans}
    print(f"\nmaster_bpm per mix: {[round(p.master_bpm, 2) for p in plans]}")
    if len(tempos) > 1:
        print("  [!] the two mixes are NOT at the same bed tempo -- the seam still crossfades on a\n"
              "      phrase boundary, but bars won't perfectly coincide. A true set re-renders every\n"
              "      mix at ONE global tempo (set_tempo_plan); that's the /set wiring, not this demo.")
    else:
        print("  [ok] same bed tempo -- the seam is beat-matched by construction (equal-length bars).")

    mixes = [{"wav": mixroute._mix_wav(mixroute.mix_id_for(cat[args.beat], cat[v], "", 1)),
              "phrase_starts": p.out_phrase_starts}
             for v, p in zip(args.vocals, plans)]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    assemble_beatmatched_set(mixes, args.out)

    # Report where to listen: the seam is at the FIRST mix's last phrase boundary (where it
    # mixes out) — mirrors set_render._phrase_seam's a_end pick.
    a_dur = plans[0].mix_duration or 0.0
    a_ps = [x for x in plans[0].out_phrase_starts if 0.0 <= x <= a_dur + 1e-6]
    seam = a_ps[-1] if a_ps else None
    print(f"\n[done] wrote {args.out}")
    if seam is not None:
        m, s = divmod(int(seam), 60)
        print(f"   Listen around {m}:{s:02d} (~{seam:.1f}s) -- that's where mix 1 hands off to mix 2.")
    print("   The whole file is the set; the seam is the one join in the middle.")


if __name__ == "__main__":
    main()
