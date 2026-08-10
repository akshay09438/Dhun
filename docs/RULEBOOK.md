# Prompt-DJ — The Rule Book

_Finalized 2026-08-06 (founder-approved design). The canonical description of the mixing rules — the shared foundation and the arrangement rules that sit on it. When the Rule-3 code lands, the functional & technical specs get their Rule-3 sections updated in that same change; this book stays the single source of the rule design._

## The one idea

Every mix = two songs → the engine **matches** them → a chosen **rule** arranges them → a mix. The matching is identical for every rule; the rule only decides the arrangement _style_. Mixes are then sequenced into a **set**, one rule per track.

```
  A SET  =  Rule 1 → Rule 2 → Rule 1 → Rule 3 → Rule 4 …   (pick a rule per mix)
                       ▲ built from
  THE RULES           R1 simple · R2 reserved · R3 chop&repeat · R4 echo&reverb
                       ▲ every rule stands on
  THE FOUNDATION      track BPM · stretch BPM to the beat · track key · change key · decline if too far
```

---

## 1. The Foundation — the same in every rule

_Updated 2026-08-07 (founder rule): **no pair is ever declined.** The vocal's BPM is ALWAYS matched to the beat, however far apart; key is chosen by **measuring the audio** (labels are only a hint); the vocal stays beat-locked so it never goes off-beat._

Before **any** rule runs, the engine reads both songs with its analyzer ("the sensor") and fixes the match. Nothing about the rule matters until the songs are locked in tempo and key.

- **Track BPM.** Detect each song's tempo and every beat & downbeat, and check the grid is healthy (regular spacing that agrees with the tempo — a mis-read grid is flagged, `planner/beatgrid.py`). The beat song is the master clock.
- **Stretch BPM (always match).** Time-stretch the vocal song onto the beat's grid, **bar by bar**, so the vocal locks to the beat and can never drift. When the pair is far apart, the vocal is stretched **fully** onto the beat (the beat keeps its native tempo and drive) and each bar is re-locked to a downbeat with a wider grip — so even a big stretch still lands on-beat. _Never declined for tempo._
- **Track key.** Detect each song's musical key (Camelot) **with a confidence**.
- **Change key (measured, not guessed).** Shift the vocal into a compatible key. When the key labels are trustworthy, use fuzzy keymixing (match the Camelot number, ignore the letter, smallest shift). When a label is **untrusted** (flagged / low-confidence — common on real uploads), **measure** the shift from the audio: chromagram of the beat's harmony vs the vocal, rotate the vocal across candidate shifts, pick the best harmonic fit (AutoMashUpper, `audio/chroma.py`). **Hard cap ±2 semitones** (the industry / CDJ-3000 ceiling — enforced at every layer, see **Hard Rules** below; this replaced the earlier ±3 fallback that let a flagged song chipmunk, 2026-08-10), **formant-preserved** so the voice never chipmunks. Zero shift when they already agree.
- **The only decline left.** A track with **no usable beat grid at all** (no clock to lock to) is the sole un-mixable case — a detection problem, not a tempo/key one. Everything else always produces a mix.

_Research basis: AutoMashUpper (Davies et al., ISMIR 2013, `archives.ismir.net/ismir2013/paper/000077.pdf`) for the chroma match; fuzzy keymixing / CDJ-3000 Key Sync for the ±2–3 cap; Lee et al. (ISMIR 2015, `.../ismir2015/paper/000302.pdf`) vocal-over-instrumental asymmetry as a future refinement._

> **Founder's rule:** BPM tracking + stretching and key tracking + changing are the **base of all rules**. Any pair going through any rule is matched first; only then does the rule build the mix.

### Hard Rules (enforced — can never be broken)

_Added 2026-08-10 (founder: "make it so no song can go beyond the rules… multiple checks, force checks"). These are limits the app may NEVER exceed, held by several independent layers so no single loosened line can reopen the gap._

**Pitch — a vocal is NEVER shifted more than ±2 semitones.** One constant, `keys.CAP_SEMITONES = 2`, is the single source of truth, enforced independently at every layer a shift could slip through:

1. **Decision (labels):** `keys.fuzzy_key_shift` only ever proposes a shift within ±2.
2. **Decision (audio fallback):** `mix.KEY_SHIFT_CAP = keys.CAP_SEMITONES`, and the chroma matcher defaults to ±2 — so the audio-measured fallback can never exceed the label rule. _(This was the ±3 leak that made Silence × With You chipmunk at +3 st; closed 2026-08-10.)_
3. **Executor:** `pitch.shifted_vocal` refuses to render any shift beyond ±2 — its own hard floor, whatever a caller passes.
4. **Referee:** `validate.assert_key_shift` (K1) and P1 independently reject any finished render pitched beyond ±2.
5. **Force-checks:** `tests/test_pitch_cap_hardrule.py` proves each layer; `scripts/sanity_check.py` proves every catalog pair stays within ±2 — a future edit that loosens any layer fails CI loudly.

**A pair is NEVER refused, on key either.** If the shift cannot be produced or verified, the mix ships the vocal in its **native key** (with a visible ops warning) instead of declining — a mix always comes out. The referee measures the singer's actual pitch (`audio/f0.py`) and only falls back to chroma when a vocal is unmeasurable; the old chroma-only check wrongly declined correct shifts on rap/whisper vocals (2026-08-10).

**Half-time pairings are flagged, not refused.** `best_stretch` folds octaves, so a ~2× pair (e.g. Silence 143 × Panda 72) locks perfectly on the beat with almost no stretch — technically right, but one song's pulse is twice the other's, which can feel frantic. The mix is still made; `anomaly.half_time_pair` records it (ops-visible) so a human can prefer a closer-tempo partner.

**Tempo — the vocal is matched to the beat and stays beat-locked; a pair is never refused.** The beat is the master clock; the vocal is stretched (bar-by-bar re-locked) onto it. This behavior is intentionally unchanged (founder keeps the current BPM matching); the only un-mixable case remains a track with no usable beat grid.

---

## 2. The Rules

### Rule 1 — Simple Mix — _LIVE_

The base. Song 1's beat + Song 2's vocal, matched and arranged, clean.

- The beat plays; the vocal is placed at the song's **drops**, beat-locked and in key.
- **No echo, no reverb.** The dry, straight mix. Everything else builds on this.

### Rule 3 — Chop & Repeat — _EXPERIMENTAL (ear-approving)_

Sits on Rule 1's base. Instead of the full vocal, a hand-picked hook line is chopped and repeated as the hook.

- **The hook** comes from the song's best part — the curated marker, or a timestamp the founder gives (e.g. How Deep 61–71s). No blind guessing.
- **Two blocks.** `A` = the short chop (2–3 words) — the **tease**. `C` = the full sentence — the **payoff**, looped. `B` (the second half) only ever lives inside C — **never played alone**.
- **Weave A and C** at different moments — tease with the short line, land the full line later.
- **Beat-locked.** The chop is cut on the vocal's own bars and each bar is snapped to a beat bar — it can't drift, and every repeat starts on the beat.
- **Not too tight.** Spaced and gated, with room to breathe — it can wait a beat for the grid.
- **Echo + reverb tail** (borrowed from Rule 4) rings each chop out into the gap.
- **Trade, don't bury.** The beat song's own vocal is **kept**; the chops answer in the gaps where the beat isn't singing (call & response). If the beat is vocal-heavy or short, drop its vocal instead.

> **HARD RULE — the one I let slip:** **Never cut the last word.** Each chop's final word must **finish and fade out** — never a hard chop. The fade means it's never abrupt, doesn't overstay off-beat, and blends cleanly if the next part comes in. (Told to me early; it regressed when the code was generalized — now it's a written law.)

### Rule 4 — Echo & Reverb Mix — _LIVE_

Everything in Rule 1, plus space.

- **Echo** — a tempo-synced throw off the end of each vocal line (a dotted-eighth delay that decays).
- **Reverb bed** under the vocal. Echo and reverb always ride together.
- Rule 1 and Rule 4 stay **distinct and toggleable** — a dry base and an echoed version — so a set can mix and match.

### Rule 2 — Reserved — _NOT INTEGRATED_

Referenced in a set sequence but deliberately **not integrated right now** (founder's call, 2026-08-06). Held open — to be defined later.

---

## 3. The Set Builder (where this is heading)

Preparing a set = a **sequence of mixes, each with a chosen rule** (e.g. `Rule 1 → Rule 2 → Rule 1 → Rule 3 → Rule 4`). Pick the rule per track; the engine makes each mix with that rule. The foundation (BPM + key) applies to every one, so the whole set stays matched and beat-locked.

---

## 4. Execution plan (after approval)

1. Promote the experimental Rule-3 harness into the real engine path, inheriting Rule 1's plan + the shared foundation.
2. Make the rule a **choice per mix** (and later per set track).
3. Touch the guarded files (render / validator) on the careful safety path.
4. Update the living specs (functional, technical, implementation) to match.
5. Re-test on our pairs by ear before it ships.

## Decisions locked (2026-08-06)

- **Build Rule 3 into the app** — promote it from the throwaway harness to the real engine (this is now in progress).
- **Rule 2** — not integrated now; reserved.

## Still open (small, non-blocking)

1. **How Deep hook** — A starts at 59.8s (beat before your 61) to stay on-beat; keep or snap to 61?
2. **Density default** for Rule 3 — medium or sparse?
