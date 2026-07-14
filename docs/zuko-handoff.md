# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. `/handoff` rewrites this at the end of a session; `/start` and the SessionStart hook replay it at the beginning. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-07-15 (**BEST-PARTS RESEARCH SESSION — done entirely in the experiment clone `C:\Dhun-Experiment`, NOT the official app. No official product code changed this session (the only diffs in this repo are pre-existing Windows LF↔CRLF line-ending noise, not edited by this session).** Three experiments ran toward a future "best parts" feature: find the best part, cut to it, combine two songs' best parts. Findings below. **The multi-set PR from 2026-07-14 is STILL OPEN and unchanged — not merged.**)

## Where things stand (one breath)

Two separate threads:

- **(A) Multi-set UI — still pending merge (unchanged since 2026-07-14).** Built + verified last session on branch `feat/multiset-ui` (`319d507`, pushed to `origin`); a PR is one click from being opened. NOT merged. Nothing about it changed this session.
- **(B) Best-parts research (this session) — in the sandbox only.** Explored whether the app can find a song's best part, cut to it cleanly, and combine two songs' best parts. All work lives in `C:\Dhun-Experiment\experiments\climb-finder\` (that repo has no GitHub remote; committed there as `4b07e81`). It is research/measurement, not shipped code — nothing here is ready to promote into the official app yet.

## In flight - done vs left

### (A) Multi-set (carried over — re-verify, do not trust the sentence)

- On `feat/multiset-ui` (`319d507`), pushed. Suite was **415 backend + 49 web green, typecheck clean** _as of 2026-07-14_ — this is a CLAIM to re-run before merge, not re-verified this session.
- **Left:** founder ear-listen to a real two-set join, then open + merge the PR. Then fold the set WAV into the owed `storage.py` cache-eviction sweep.

### (B) Best-parts research (this session)

- **Exp 1 — the climb-finder.** Measures each stem's per-bar energy "climb" (build→peak→release), SOLO (math alone) vs ANCHORED (hand-mark as the peak), scored against the founder's ear-marks on 5 songs. **Finding:** for BEAT songs the best drop = "the marked drop nearest the whole-_mix_ energy peak" (2/2 vs ear; drums-only energy is a flat plateau and can't pick). For VOCAL songs, auto-picking _which_ hook instance is still unsolved (loudest-repeat overshoots to the final chorus; first-strong grabs too-early lines). Confirmed the hook phrase genuinely repeats (chroma sequence match).
- **Exp 2 — cut a song to its best part.** Validated on Father Ocean (beat-led) AND Tere Bina (vocal-led). **Rule that emerged:** crop edges must be **vocal-aware** — land every edge in a _measured-silent_ gap between sung lines (low instrumental energy is NOT enough), never mid-word. Founder confirmed both crops "cut fine."
- **Exp 3 — combine best-parts (Father Ocean beat + Der Lagi vocals).** Built V1 (full), V2 (hook-only), V3 (hook + touches) **through the real engine** (`build_mix_plan` + `render_mix`), keeping Song 1's own vocals in the gaps. Founder: **V1 sounds right; V3 is the preferred arrangement.**
  - ⚠️ **OPEN ISSUE (all versions):** the vocal at the drop sounds "a little early / off tune." Diagnosed with measured numbers (no blind nudge): keys are compatible (both 10B / D major — ruled out), the real drum slam is 236.10s (marked drop 235.1 was ~1s off), the hook is beat-locked tight (0.02s). The measured anomaly: **Der Lagi's hook slice starts mid-phrase** — its sung pickup begins ~18.4s but the beat-lock starts on the downbeat 19.86s, chopping the lead-in — AND Father Ocean's own pre-drop lick (234.1–237.3s) sits stacked right before it. **Waiting on the founder to pinpoint by ear which of the two stacked vocals is the wrong one** before fixing (asked, not yet answered — they said hold).

## Do first next session

Ask the founder which thread to advance — they are independent:

1. **(B) Finish Exp 3 (most recent):** get the founder's answer to "at the V3 drop (~76–82s), which vocal is early/off — Father Ocean's pre-drop lick, or Der Lagi's mid-phrase hook entry?" Then apply the _matching_ fix (trim the lick / include the hook's pickup / land the main word on the slam). Do NOT nudge blindly — the diagnosis is done, the fix is one measured change once they pinpoint. All in `C:\Dhun-Experiment`.
2. **(A) Or ship multi-set:** re-run the suite (below), founder ear-listens a two-set join, open the pre-filled PR (`https://github.com/akshay09438/Dhun/compare/main...feat/multiset-ui?expand=1`; `gh` is NOT installed on this machine), merge.

## Verification evidence (which checks ran, what they returned)

- **Official app tests this session: NOT RUN — nothing in the official repo changed, so there was nothing to verify.** The 2026-07-14 result (415 backend + 49 web green, typecheck clean) stands as the last-known state and must be **re-run before the multi-set merge**, not trusted as a sentence.
- **Best-parts research (sandbox `C:\Dhun-Experiment`) — verified by render + measurement + the founder's ear, not a test suite (throwaway research):**
  - Exp 2 crops: rendered Father Ocean (196.7s) + Tere Bina (41.7s); confirmed both edges land in measured-silent vocal gaps (Tere Bina start 50.3s: voc 0.01/0.00). Founder: "cuts fine."
  - Exp 3 mixes: V1 via real `/mix` endpoint (476.3s; plan = 3 Der Lagi placements + 3 Father Ocean vocal regions — Song 1's vocals present, verified rms 0.077 in its gap). V2/V3 via windowed real plan (127.9s each; hook on the drop, Father Ocean vocals kept). Founder: V1 right, V3 preferred, drop timing off (open issue above).
  - Measured diagnosis of the drop issue: Father Ocean drums slam at 236.10s; both songs key 10B; Der Lagi warp starts at DL downbeat 19.86s while the sung pickup starts ~18.4s.
- **Git:** sandbox `C:\Dhun-Experiment` committed `4b07e81` (scripts + plots + CSVs; audio renders gitignored). Official repo: only LF↔CRLF noise, nothing committed here except this handoff (on a docs branch).

## Open escalations / re-verify next session (claims, not settled facts)

- **Multi-set suite "green" is a 2026-07-14 CLAIM** — re-run `cd services/api && ./.venv/Scripts/python.exe -m pytest -q` and `npm run typecheck && npm test` before merging.
- **No dangerous-surface code was touched this session** (render.py / validate.py / routes/songs.py / storage.py all untouched; the sandbox used `render_mix`/`build_mix_plan` import-and-call only). Nothing to re-verify there.
- **Exp 3 "best parts" combining is NOT a shipped feature** — it is sandbox research. Do not treat any of it as in the official app.
- The founder's Exp-3 pinpoint question is **open and awaiting their answer** — do not guess a fix direction.
