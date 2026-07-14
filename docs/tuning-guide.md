# Vocal-chain tuning guide (Phase 0)

_How to tune the nine-stage vocal chain by ear, in the sandbox, and turn the winning dial positions
into the first `bollywood_vocal_over_house` recipe. The chain ships **off**; tuning happens in the
`C:\DJ-AI-Experiment` sandbox — nothing here flips it on in the shipped config._

## The harness

`scripts/tune_chain.py` renders a pair **both ways** and stamps everything so you never have to
remember what a render was:

```
python scripts/tune_chain.py "<beat-substr>" "<vocal-substr>" [dial=value ...]
```

- Writes `<pair> - OFF.wav` (the m6.0 baseline) and `<pair> - ON [dials].wav` to
  `Desktop/DJAI TUNING/`, plus a `.txt` with the full config, peak, and crest factor before/after.
- Uses only cached songs (no cloud cost). Rules arrangement path (as shipped).

Examples:

```
python scripts/tune_chain.py "father ocean" "der lagi"
python scripts/tune_chain.py "father ocean" "der lagi" saturate_wet=0.30 presence_gain_db=3.0
python scripts/tune_chain.py "anchor point" "dil ye bekarar" reverb_wet=0.18 deess_enabled=false
```

## The tuning set — use these (key-compatible)

Tune only on pairs whose keys actually fit. The Slice-1 key-fit logging confirmed these are
compatible:

| Beat         | Vocal            | Keys      |
| ------------ | ---------------- | --------- |
| Father Ocean | Der Lagi Lekin   | 10B / 10B |
| Father Ocean | Tujhe Bhula Diya | 10B / 10B |
| Father Ocean | Don't Start Now  | 10B / 10B |
| Father Ocean | Tere Bina        | 10B / 11B |
| Anchor Point | Dil Ye Bekarar   | 8A / 8A   |
| I Adore You  | Tujhe Bhula Diya | 10A / 10B |
| Anchor Point | Jee Karda        | 8A / 9A   |

## Exclude these three — they clash (reserve for Slice 2d evidence)

| Beat         | Vocal      | Keys     |
| ------------ | ---------- | -------- |
| Father Ocean | Suniyan    | 10B / 4B |
| Anchor Point | Maula Mere | 8A / 5A  |
| Innerbloom   | Dooriyan   | 6B / 7A  |

**Why this is not optional.** Tuning dials against a vocal that is fighting the bed harmonically
produces **compensating** settings — extra brightness and grit forced in to push a vocal through a
clash that shouldn't exist. Those numbers would then be wrong for every clean pair we own; the tuning
week would produce a recipe calibrated on a defect.

**Keep these three as the Slice 2d before/after evidence set.** When pitch repair goes live, render
them before and after — that A/B is the proof of what the repair layer is worth, and the most
convincing demo in the product.

## Tuning order — one dial at a time (most perceptible → least)

```
saturate_wet  →  presence_gain_db  →  reverb_wet  →  duck_depth_db
              →  compress_ratio    →  highpass_hz →  deess_intensity
```

## When something sounds wrong — bisect, don't guess

Every stage has an independent kill switch. Disable them one at a time to find the culprit:

```
python scripts/tune_chain.py "..." "..." saturate_enabled=false      # is it the saturation?
python scripts/tune_chain.py "..." "..." reverb_enabled=false        # the reverb?
```

That's what the nine kill switches are for. Never guess which stage did it.

## Guardrails already in place (so you can push safely)

- **P3 caps** the dials (`saturate_wet ≤ 0.5`, `presence_gain_db ≤ ±6 dB`, …) — the referee rejects a
  plan that exceeds them.
- **P2** rejects a chain that inflates the vocal's peak > +3 dB.
- **The crest-factor backstop** catches distortion that escapes P3 (it can't fire inside the caps).
- **The master** peak-normalizes to −1 dB and hard-clips, so the output can never clip.

## The output

The winning dial positions become the first **`bollywood_vocal_over_house`** recipe (Phase 3, T19).
Record them; they are our taste written down as numbers — the thing nobody can copy once it's done.
Then, and only then, Slice 2d (pitch repair).
