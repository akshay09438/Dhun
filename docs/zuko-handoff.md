# Zuko handoff — Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-08-10 (**key-referee fix shipped + everything merged to `main` and pushed**) — **Nothing is in flight. `main` == GitHub `main` (PRs #20, #21 merged). Working tree clean. App + Discord bot running locally.**

---

## Where things stand

**Everything from the last two days is merged, pushed, and green.** No staged approvals remain, no branch is unmerged, nothing is half-built.

- **Catalog: 30 songs** (24 + Hey Brother, Silence, Bad Guy, Panda, Woh Lamhe Woh Baatein, Hum Pyaar Karne Wale) with their hand-marked drops/hooks wired into the planner.
- **Song marks: 176 songs** captured in `scripts/song_marks.csv` (beat + English + Hindi). Not yet ingested — only the 6 above are in the app.
- **Running locally:** backend `:8000`, web `:5173`, Grinder Discord bot (discord.py pinned <2.6 so voice works via PyNaCl).

## What shipped (2026-08-10)

1. **±2 pitch hard-cap, defence in depth.** One constant (`keys.CAP_SEMITONES`) enforced at the decision layer, the audio-measured fallback (`mix.KEY_SHIFT_CAP`, was ±3 — the leak that made Silence × With You chipmunk at +3), the executor (`pitch.shifted_vocal`), and the referee. Force-checks: `tests/test_pitch_cap_hardrule.py` + a catalog-wide pitch sweep in `scripts/sanity_check.py`.
2. **K1 referee re-ruled (the big one).** Three sets came back "skipped" on a key error. Diagnosis proved the **pitch engine correct** (measured +1.91 / −0.99 / −1.00 st for asked +2/−1/−1) and the **checker wrong**: whole-stem chroma misreads rap/whisper vocals. `validate.py` now measures the singer's actual pitch (`app/audio/f0.py`) first, falling back to chroma only when a vocal is unmeasurable. Founder-approved via confirm-and-apply, ear-trialled on Father Ocean × Bad Guy before applying.
3. **Never-refuse now covers key.** If a shift can't be produced or verified, the mix ships the vocal in its **native key** with an ops warning (`key_shift_fallback`) instead of declining. Mirrored in `routes/live.py` so Play matches Download.
4. **Half-time pairs flagged.** `anomaly.half_time_pair` reports a ~2× pair (Silence 143 × Panda 72 — octave-folded, exactly on-beat, but one pulse is twice the other). Report-only; the mix is still made.
5. **f0 measurement cached.** Verification cost a measured 14–25 s per key-matched render; now ~20 ms on repeats (`MEASURE_VERSION` invalidates on any algorithm change).
6. **Grinder Discord UI** — Rythm-style purple (`#6d3bf5`) now-playing cards, `/help`, voice enabled.
7. **Style + take hidden from users** everywhere (web + Discord); still visible on the internal ops dashboard.

## Verification evidence

- **Full API suite: 670 passed, 0 failed.** Web: 66 passed, typecheck clean. Discord bot: 23 passed.
- Catalog sweep: 216 pairs, 0 rule failures (includes the pitch-cap check).
- Cache speed-up measured on real stems: 14.1→0.032 s, 21.4→0.020 s, 25.0→0.021 s, identical answers.
- Previously-skipped pairs (Father Ocean × Bad Guy, Silence × Panda) now render on the real backend.
- **Fixed a pre-existing flaky test** (`test_cache_sweep`): a just-written file's mtime can read ahead of `time.time()` on Windows (~13% of writes), so the grace-0 check skipped it. `_touch` now pins mtime 1 s in the past; 20/20 clean runs. Not a weakening — the age-grace test still passes explicit mtimes.

## DO FIRST NEXT SESSION

1. **Ear-check (founder only):** one rap/whisper pair and one high female vocal — the two cases verified mathematically but not by ear. Also the 5 "untrusted-key" songs (With You, Anchor Point, Dooriyan, Rapture, Wari Jawa) so their pairs use a real ±2 shift rather than the audio guess.
2. **Ingest the remaining ~146 marked songs** when ready — one-time ~$26–37 (Demucs + All-In-One via Replicate). **Resolve disk/storage first** (~8–10 GB free on C:; ~215 songs' stems need 30–40 GB → point storage at R2 before ingesting).
3. Optional: install the GitHub CLI (`gh`) so PRs can be opened/merged from the session instead of a manual click.

## Open / parked (honest)

- **Half-time pairs are flagged, not de-prioritised** in set building — deliberate; revisit if odd pairings keep surfacing first.
- **Tempo behaviour deliberately unchanged** (founder: keep the current BPM matching; never refuse a pair).
- The `.zuko/goodnight/queue/` is empty — the referee card was applied and its provenance recorded in `.zuko/goodnight/applied.json`.
