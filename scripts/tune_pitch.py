"""Slice 2d pitch-repair A/B — render a dropbox pair BEFORE (shipped chain on, pitch repair OFF) and
AFTER (shipped chain on, pitch repair ON) so the founder can hear the key correction in isolation.

The seven approved SHIPPED_CHAIN dials are held CONSTANT; the ONLY variable is `pitch_repair_enabled`.
A pair that clashes beyond the ±cap band DECLINES on the AFTER render (the app refuses it rather than
warp it past the safe band) — that decline IS the demonstration for such a pair.

Zero cloud: reuses `tune_chain`'s dropbox ingest, which guards `replicate.run` to RAISE — so a pair
whose stems/analysis aren't already cached errors loudly instead of calling the cloud. formant is set
`preserved` render-side (render.py:_pitch_shift), so a shift never chipmunks the voice.

USAGE (from the repo root):
  python scripts/tune_pitch.py "father ocean" "suniyan"
"""
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "services" / "api"))
sys.path.insert(0, str(_REPO))

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

import scripts.tune_chain as tc  # noqa: E402  (dropbox ingest + the zero-cloud guard)
from app.audio.stems import stem_path  # noqa: E402
from app.models import VocalChainConfig  # noqa: E402
from app.planner import validate  # noqa: E402
from app.planner.plan import MixDeclined, build_mix_plan  # noqa: E402
from workers import render  # noqa: E402

OUT = Path.home() / "OneDrive" / "Desktop" / "DJAI PITCH TEST"

# The approved shipped chain (SHIPPED_CHAIN); pitch repair is toggled per render, nothing else.
_DIALS = dict(saturate_wet=0.3, presence_gain_db=4.0, reverb_wet=0.08, duck_depth_db=1.0,
              compress_ratio=2.0, highpass_hz=120, deess_intensity=0.4)


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    beat_sub, voc_sub = sys.argv[1], sys.argv[2]
    b, v = tc._ingest(beat_sub), tc._ingest(voc_sub)
    a1, a2 = tc._analysis(b), tc._analysis(v)
    stems = {s: stem_path(b, s) for s in ("drums", "bass", "other")}
    if stem_path(b, "vocals").exists():
        stems["vocals"] = stem_path(b, "vocals")
    s2voc = stem_path(v, "vocals")

    OUT.mkdir(parents=True, exist_ok=True)
    pair = f"{beat_sub} x {voc_sub}"
    print(f"PAIR: {pair}   keys {a1.key.camelot}/{a2.key.camelot}")
    for label, pitch_on in (("BEFORE (pitch OFF)", False), ("AFTER (pitch ON)", True)):
        cfg = VocalChainConfig(enabled=True, pitch_repair_enabled=pitch_on, **_DIALS)
        try:
            plan = build_mix_plan("tune", a1, a2, "", take=1, chain=cfg)
        except MixDeclined as e:
            print(f"  {label}: DECLINED -> {e}")
            continue
        validate.assert_plan(plan, a1, a2)          # referee incl. P1 (±3) on the emitted shift
        shift = plan.vocal_moves[0].pitch_semitones if plan.vocal_moves else 0.0
        out = OUT / f"{pair} - {label} [shift {shift:+.0f}st].wav"
        render.render_mix(plan, stems, s2voc, out)  # _pitch_shift uses formant=preserved
        validate.assert_render(out)
        y, _ = sf.read(out, dtype="float32", always_2d=True)
        print(f"  {label}: shift={shift:+.0f}st  peak={float(np.max(np.abs(y))):.3f}  -> {out.name}")
    print(f"\nwritten to: {OUT}   (formant=preserved, zero cloud)")


if __name__ == "__main__":
    main()
