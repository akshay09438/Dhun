"""Vocal-chain tuning harness (Phase 0). Renders a pair BOTH ways — enabled=False (the m6.0 baseline)
and enabled=True with the dials you pass — writes both to a folder with the dial values stamped into
the filename, and prints crest factor before/after, peak, and the dials in effect.

You never have to remember what a render was made with: the dials are in the filename AND a sidecar
.txt next to it.

Cloud is guarded to raise — this only ever uses already-cached songs (no Replicate cost).

USAGE (run in the sandbox, from the repo root):
  python scripts/tune_chain.py "<beat-substr>" "<vocal-substr>" [dial=value ...]

EXAMPLES:
  python scripts/tune_chain.py "father ocean" "der lagi"
  python scripts/tune_chain.py "father ocean" "der lagi" saturate_wet=0.30 presence_gain_db=3.0
  python scripts/tune_chain.py "anchor point" "dil ye bekarar" reverb_wet=0.18 deess_enabled=false

TUNE ONE DIAL AT A TIME, in this order (most perceptible -> least):
  saturate_wet -> presence_gain_db -> reverb_wet -> duck_depth_db -> compress_ratio
  -> highpass_hz -> deess_intensity
When something sounds wrong, BISECT: set a stage's *_enabled=false to find the culprit. Never guess.

⚠️ Do NOT tune on these three pairs — they are harmonically CLASHING (Slice-1 key-fit logging), and
tuning against a clash produces compensating dials that are wrong for every clean pair:
  Father Ocean x Suniyan (10B/4B) | Anchor Point x Maula Mere (8A/5A) | Innerbloom x Dooriyan (6B/7A)
Keep those three as the Slice 2d before/after evidence set instead.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "api"))
sys.path.insert(0, str(REPO))

import replicate  # noqa: E402
replicate.run = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("REPLICATE CALLED — pair not cached"))

os.environ.pop("ANTHROPIC_API_KEY", None)  # deterministic rules path (as shipped)
import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
from app.audio.analysis import analysis_path  # noqa: E402
from app.audio.normalize import normalize_audio  # noqa: E402
from app.audio.stems import stem_path  # noqa: E402
from app.models import TrackAnalysis, VocalChainConfig  # noqa: E402
from app.planner import validate  # noqa: E402
from app.planner.plan import build_mix_plan  # noqa: E402
from app.storage import store_wav  # noqa: E402
from workers import chain_guards, render  # noqa: E402

DROPBOX = REPO / "song-dropbox"
OUT = Path.home() / "OneDrive" / "Desktop" / "DJAI TUNING"


def _coerce(v: str):
    low = v.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        return v


def _find(sub: str) -> Path:
    hits = [p for p in DROPBOX.glob("*.mp3") if sub.lower() in p.name.lower()]
    if len(hits) != 1:
        sys.exit(f"'{sub}' matched {[h.name for h in hits]} — need exactly one")
    return hits[0]


def _ingest(sub: str) -> str:
    with tempfile.TemporaryDirectory() as td:
        w = Path(td) / "n.wav"
        normalize_audio(_find(sub), w)
        return store_wav(w)


def _analysis(sid: str) -> TrackAnalysis:
    return TrackAnalysis(status="ready", **json.loads(analysis_path(sid).read_text()))


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    beat_sub, voc_sub = sys.argv[1], sys.argv[2]
    overrides = dict(kv.split("=", 1) for kv in sys.argv[3:])
    cfg = VocalChainConfig(enabled=True, **{k: _coerce(v) for k, v in overrides.items()})

    b, v = _ingest(beat_sub), _ingest(voc_sub)
    for sid, label in ((b, beat_sub), (v, voc_sub)):
        if not analysis_path(sid).exists():
            sys.exit(f"'{label}' is not analyzed/cached — process it through the app first")
    a1, a2 = _analysis(b), _analysis(v)
    stems = {s: stem_path(b, s) for s in ("drums", "bass", "other")}
    if stem_path(b, "vocals").exists():
        stems["vocals"] = stem_path(b, "vocals")
    s2voc = stem_path(v, "vocals")

    OUT.mkdir(parents=True, exist_ok=True)
    pair = f"{beat_sub} x {voc_sub}"
    dials = "_".join(f"{k}{v}" for k, v in overrides.items()) or "defaults"

    def render_one(chain, name):
        plan = build_mix_plan("tune", a1, a2, "", take=1, chain=chain)
        validate.assert_plan(plan, a1, a2)
        out = OUT / name
        render.render_mix(plan, stems, s2voc, out)
        validate.assert_render(out)
        y, _ = sf.read(out, dtype="float32", always_2d=True)
        return plan, out, float(np.max(np.abs(y)))

    _, off_path, off_peak = render_one(VocalChainConfig(), f"{pair} - OFF.wav")
    plan_on, on_path, on_peak = render_one(cfg, f"{pair} - ON [{dials}].wav")

    # crest before/after the chain, on the first placement's vocal (the mush indicator)
    p0 = plan_on.placements[0]
    warp = getattr(p0, "warp", None)
    voc0 = render._edge_fade(render._vocal_take_warped(s2voc, warp) if warp
                             else render._vocal_take(s2voc, p0.vocal_src[0],
                                                     p0.vocal_src[1] - p0.vocal_src[0], plan_on.vocal_stretch))
    cf_before = chain_guards.crest_factor(voc0)
    cf_after = chain_guards.crest_factor(render._apply_vocal_chain(voc0.copy(), plan_on.vocal_moves[0], render.SR))

    report = (
        f"PAIR: {pair}\n"
        f"dials: {json.dumps(overrides) if overrides else 'defaults'}\n"
        f"config: {cfg.model_dump_json()}\n"
        f"OFF (m6.0 baseline): {off_path.name}   peak {off_peak:.3f}\n"
        f"ON:                  {on_path.name}   peak {on_peak:.3f}\n"
        f"vocal-chain crest factor: {cf_before:.2f} -> {cf_after:.2f}  "
        f"(ratio {cf_after / cf_before:.2f}; mush guard fires below {chain_guards.CREST_MIN_RATIO})\n"
        f"key-fit: {plan_on.camelot_fit.song1_camelot}/{plan_on.camelot_fit.song2_camelot} "
        f"compatible={plan_on.camelot_fit.compatible}\n"
    )
    (OUT / f"{pair} - ON [{dials}].txt").write_text(report, encoding="utf-8")
    print("\n" + report + f"\nwritten to: {OUT}")


if __name__ == "__main__":
    main()
