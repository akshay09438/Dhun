# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-08-05 — **A very long Rule 4 (Regenerate variety) session. Built a full echo/reverb "phrase-throw" engine on a branch, ceremony-passed it, then the founder CUT IT BACK HARD: most of what was built is the wrong feature and will be deleted next session in favour of a much simpler Rule 4. Nothing merged to `main`. All work sits on branch `design/mix-reverse-engineering`, committed as a checkpoint by this handoff.**

## Where things stand (one breath)

- **`main` is untouched.** Everything this session is on `design/mix-reverse-engineering` and ships **OFF** behind flags (`plan._PHRASE_THROW_ENABLED = False`, `plan._EFFECT_POOL_ENABLED = False`). With the flags off the render is **byte-identical to `main`** (golden gate verified this session).
- **Rule 4 was built the WRONG way and is being simplified.** The engine built (the "phrase-throw" model: sing/carry cut ratios + a re-fired vocal bar) works and passed its ceremony — but the founder identified the re-fire as **chop-and-repeat = Rule 3 leaking in**, and cut the whole cut-ratio model. See the drift log (2026-08-05 late) for the full decision.
- **THE SIMPLIFIED RULE 4 (the target):** take Rule 1's vocal EXACTLY as-is (do NOT cut / shorten / chop / re-fire). Add echo + reverb ON TOP — **ONE variation, always both together**. Echo fires **at the END of each vocal line, sized to fit the GAP before the next vocal** (longer gap → longer tail; no gap → no echo). Reverb runs continuously underneath (already built, kept).
- **Other work this session that is real and keeps:** the **cache-eviction sweep** (`storage.py`, dangerous — built, ceremony-passed, 1 test committed as `401062f`; dogfooded, reclaimed 1.15 GB, catalog verified intact); the **audibility fix** + **joint wet-trim** + **chain_guards**; the **recalibrated isolated-vocal differs-check** (`scripts/audio_diff.py`); the **length-preserving tail containment**; the **reverb bed**. These are on the KEEP list.

## In flight — honest state

- **Rule 4 simplification is PLANNED, not built.** The founder said "plan first, no code until I sign off." Next session must REPORT gap-detection first, then propose the simplified implementation, then get sign-off, then build.
- **The old phrase-throw code is still in the tree** (shipping OFF). To be DELETED next session (after sign-off): the 5 cut ratios, sing/carry gating, `_punchy_bar` + the re-fire, throw-moment selection by energy, the energy→ratio mapping, the three variations, and `app/planner/throws.py`'s selection model. **PRESERVE `_punchy_bar` + the breath fix** — it's genuinely useful for Rule 3 later; it lives in `workers/render.py` and is preserved in git history by this checkpoint commit.
- **Suite is GREEN** in the current (pre-simplification) state — see evidence below. The simplification will necessarily change/delete many of the phrase-throw tests.

## Do first next session

1. **Gap-detection report (read-only, no code).** Can Song 2's **vocal-stem energy troughs** give reliable **line-END points AND gap lengths**? This session measured: the vocal stem has **9 clear troughs across 59 bars (std 0.278)** while `vocal_regions` (segmentation) is an **86% blob** — so use vocal-stem RMS (reliable loudness), NOT `vocal_regions`. Report the smallest reliable way to measure "the gap before the next vocal."
2. **Propose the simplified Rule 4 implementation** — small. Echo placed at each line-end, tail sized to the gap; continuous reverb kept; one variation; delete the cut-ratio/re-fire model; keep the KEEP list.
3. **Get founder sign-off, THEN build** (render.py + validate.py are dangerous → full ceremony again).

## Verification evidence

- **Backend, current branch state (post length-weighting change), 2026-08-05:**
  `pytest test_render.py test_phrase_throw.py test_phrase_throw_e2e.py test_validate.py test_cache_sweep.py -q`
  → **141 passed** (~60 s). Includes the m6.0 **golden byte-identical-OFF gate**, so flags-off renders exactly as `main`.
- **Ceremony (phrase-throw, step 3):** independent test-author wrote 17 acceptance tests (all pass, mutation-verified); adversarial reviewer verdict **`safe` for the OFF ship** — both tail-containment attacks and the byte-identical-OFF-with-`Placement.echo` attack held (byte-identity proven vs `HEAD:render.py`). Two flip-on residuals found and FIXED (reverb bed joint-trimmed to ≤ +2.0 dB; a flaky Windows test deflaked).
- **Re-fire verification (Item 3):** 9/9 throws re-fire a voiced bar; +10.3 dB over the decayed tail in the 2nd carry bar — the re-fire works (but is the wrong feature, being cut).
- **NOT run this session:** the full backend suite in one pass (disk pressure; ran affected subsets instead) and the web suite (no web code touched).

## Open escalations / re-verify next session (claims, not facts)

- **DANGEROUS surfaces touched (`workers/render.py`, `services/api/app/planner/validate.py`, `services/api/app/storage.py`) — all ceremony-passed and shipping OFF this session. RE-VERIFY next session** that (a) both flags are still `False`, (b) the golden byte-identical-OFF gate still passes, before trusting "OFF == main".
- **Disk is tight.** Hit zero ~5× this session; the eviction sweep now exists (`scripts/evict_cache.py`, dry-run by default) and auto-runs before renders. `data/` is under OneDrive (dehydrates), so free space fluctuates.
- **Founder decision pending:** which gap-detection approach to build for the simplified Rule 4 (report it first).
- **Older open item (carried, re-verify):** the Export screen "Download full mix" defect from the 2026-07-21 handoff — not touched this session; status unknown, re-verify if it comes up.
- **Listening artefacts on the founder's Desktop** (throwaway, for his ear): `Prompt-DJ three variations (2026-08-05)`, `Prompt-DJ throw+reverb listening (2026-08-05)`, `Prompt-DJ cut-ratio prototype`, `Prompt-DJ reverb listening (trimmed 2026-08-05)`.
