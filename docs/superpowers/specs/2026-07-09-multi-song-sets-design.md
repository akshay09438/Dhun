# Design — Multi-song auto-transition sets

_Date: 2026-07-09 · Status: design approved (founder decisions below) · Branch: `feat/house-bollywood-energy-sync`_

## What this is

Instead of one two-song mix, the user lines up a **sequence of mixes** (each a beat + vocal pair, exactly like today), and the app plays them as **one continuous set** — each mix flowing into the next with a DJ-style transition. This reverses the frozen V1 non-goal "strictly two songs" — a deliberate founder decision (2026-07-09) to make sets a V1 feature.

## Founder decisions (this design)

- **Transition style:** **wind-down → cue-in.** Mix 1 winds down (the good-parts outro we already build), then Mix 2 enters on its low-density cue-in point, joined by a short **crossfade**. No beatmatched overlap — because both mixes carry a loud lead vocal, overlapping them clashes worse than instrumentals (DJ research), and a fade/echo-out handoff is the most forgiving, works across any tempo/key.
- **Set-building:** the user **picks each mix (beat+vocal pair) and their order** — full control, reuses today's per-mix flow. (Auto-pairing/ordering is a later upgrade.)
- **Ordering:** the user's chosen order. Because there's no beatmatch/overlap, consecutive mixes need NOT share tempo or key — the transition is robust to mismatch.
- **Output:** one continuous set, playable and exportable.

## Why this shape is safe and cheap

Every mix in a set is just a **good-parts windowed mix** — the entire existing engine (plan → render, all founder-ear-confirmed) is reused per mix, unchanged. The only genuinely new thing is **stitching finished mixes together**. That isolates the new risk to one small, testable, deterministic-DSP module.

## Architecture

### New: `workers/set_render.py` (the "set stitcher" — deterministic DSP, safe surface)

- `assemble_set(mix_wavs: list[Path], out_path: Path, xfade_secs: float = 4.0) -> Path`
- Decodes each finished mix WAV (stereo, SR). Joins them **in order** with an **equal-power crossfade** of `xfade_secs` at each seam: the tail of mix N (its wind-down) fades out while the head of mix N+1 (its cue-in) fades in, overlapped. Both ends are low-energy by construction (wind-down / cue-in), so the overlap is smooth and tempo-agnostic.
- Peak-normalizes the whole set to the same headroom as a single mix, with the same clip ceiling — so a set can never clip.
- Set length = Σ(mix lengths) − (n−1)·xfade_secs. A single mix passes through unchanged (no seam).
- New file, **not** on the dangerous-path list; does not touch `render.py`/`validate.py`. Produces audio (quality-critical) → thoroughly tested.

### Later (after the stitcher is ear-confirmed)

- **API:** a `/set` endpoint taking an ordered list of `(song1_id, song2_id)` pairs → render each mix (reusing `_run_mix`'s plan→render) → `assemble_set` → serve the set WAV. Cache per pair (mixes already cache) so re-renders are cheap.
- **UI:** a set builder — add several mixes in order, "Make my set", play the continuous set, export. Reuses the Setup/Generating/Play/Export screens.
- **Export:** the full set, plus (existing goal) a short clip.

## Non-goals (this feature, for now)

- Beatmatched/bass-swap blends (a later upgrade; higher clash risk with two lead vocals).
- Auto-pairing / auto-ordering of songs (user picks and orders for now).
- Unbounded sets — start bounded (~2–4 mixes) at validation scale.
- Live BPM matching across mixes (energy/handoff only, per the V1 tempo non-goal).

## Testing (the stitcher)

- Two mixes → set length ≈ len1 + len2 − xfade; the seam is continuous (no silent gap, no click).
- Equal-power crossfade → no volume dip at the seam (mid-crossfade RMS ≈ the surrounding level).
- Never clips (peak ≤ ceiling) even if both mixes are hot.
- Single mix → byte-for-behaviour passthrough.
- N mixes (3+) → all seams present, order preserved.
- Robust to different-length / different-tempo mixes (no beatmatch assumption).

## Validation

Render a real 2-mix set (e.g. Anchor Point × Maula Mere → Father Ocean × a vocal) and the founder confirms the **handoff sounds like a DJ set** (one mix winds down, the next eases in) — the same ear-test loop that validated good-parts.
