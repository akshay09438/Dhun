# Zuko handoff — Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-08-10 (**overnight `/zuko:goodnight` — two tasks: HARD ±2 pitch rule + Grinder Rythm-style UI**) — **Branch `zuko/goodnight-2026-08-10`, NOT merged. Almost everything is done & tested; ONE 30-second morning tap remains (approve the referee-hardening).**

---

## ☀️ Read this first — your morning (2 minutes)

Two tasks ran overnight. **All the safe work is done and tested. One safety-critical file is staged for your approval** — that's the only thing that needs you.

### The one tap: approve the referee hardening

Open a normal (non-overnight) session and run **`/zuko:goodnight --review`** (or apply the queued card). There is **one** card:

- **`task1-referee-pitch-cap`** — hardens the quality-referee (`validate.py`) so it independently rejects any vocal pitched beyond ±2 semitones. Plain-language card + the exact diff are in `.zuko/goodnight/queue/`. Verdict: **safe** (it's a belt-and-suspenders backstop; the engine already can't produce >±2, so this just makes it impossible). The apply step re-runs the full test suite before folding it in.

**Even if you never tap it, the app is already protected** — the over-pitch was fixed in the non-dangerous files (already applied + tested). The tap just hardens the final backstop.

---

## What got done

### Task 1 — Make the pitch rule unbreakable (your "no song goes beyond the rules")

**The bug you caught:** on Silence × With You the vocal was pushed **+3 semitones up** (chipmunky) — the audio-measured key fallback used a looser ±3 ceiling than the ±2 rule.

**The fix (defense-in-depth — one rule, enforced at every layer so no single loosened line can reopen it):**

- **Single source of truth:** `keys.CAP_SEMITONES = 2`. `mix.KEY_SHIFT_CAP` now equals it (was 3). The audio matcher (`chroma.py`) defaults dropped ±3→±2.
- **Executor floor:** `pitch.shifted_vocal` refuses to render any shift >±2, whatever a caller passes.
- **Referee backstop (STAGED for your tap):** `validate.py` P1 ±3→±2 + a new K1 size-check.
- **Force-checks (your "multiple checks"):** `tests/test_pitch_cap_hardrule.py` proves each layer; `scripts/sanity_check.py` now sweeps the whole catalog (216 pairs) and confirms **0** exceed ±2.
- **Docs:** `RULEBOOK.md` gained a "Hard Rules (enforced — can never be broken)" section.

**Tempo/BPM: intentionally UNCHANGED** — you said "the BPM stretching is being done currently," so I kept it exactly as-is; the app still never refuses a pair. ⚠️ **Flag for your correction:** your tempo note was terse; I interpreted it as "keep tempo, fix pitch." If you actually wanted the tempo stretch also clamped, tell me and I'll do it (low-risk — it wasn't touched).

**Verified:** full API suite **651 passed**. `ENGINE_VERSION +m18cap2` (any old >2-shifted mix re-renders).

### Task 2 — Grinder Discord bot, Rythm-style + purple

- New `services/discord-bot/ui.py`: the app's **exact purple `#6d3bf5`**, a Rythm-style **"Now playing" card** (title + slider progress bar + Style/Take/Length + "Requested by"), plus cooking/set/help/error cards — all in one place.
- New **`/help`** command (a Rythm-style guide). Mix cards now show **length**.
- **Kept** the pick-a-beat + pick-a-vocal flow — **no** search-any-song (your call). Commands work in any text channel; audio plays in voice.
- Engine untouched (pure front-end). **22 bot tests pass** (15 + 7 new).
- **To see it live:** it needs your token — run `services/discord-bot/Start-Grinder.bat`, then `/mix` or `/help` in your server. (I can't live-test Discord; the mock tests are green.)

---

## In flight / honest state

- **Branch `zuko/goodnight-2026-08-10` is NOT merged.** It also carries the earlier same-session work (the 6 new songs ingested + their marks wired + `+m17marks6`). Merge after you approve the one staged card.
- **Nothing half-built.** The only deferred item is the staged `validate.py` card (by design — dangerous surfaces are never self-applied overnight).
- **The catalog is now 30 songs** (24 + Hey Brother, Silence, Bad Guy, Panda, Woh Lamhe Woh Baatein, Hum Pyaar Karne Wale). Their hand-marks are wired.
- **Still open (your ears, not code):** ear-check the 5 "untrusted-key" songs (With You, Anchor Point, Dooriyan, Rapture, Wari Jawa) so their pairs use a real ±2 shift instead of the audio guess. Same for the new songs' keys.
- **The localhost app** was left running from earlier (backend `:8000`, web `:5173`) on the OLD code — **restart the backend** to pick up the pitch-cap change (`preview_start` / `.claude/launch.json` "backend").

## Verification evidence (this session)

- Task 1: `test_pitch_cap_hardrule.py` 4/4; `test_keys`/`test_pitch`/`test_chroma_match` 18/18; `test_mix_route` 19/19; **full API suite 651/651**; catalog sweep 216 pairs **0 rule failures**.
- Task 2: `py_compile bot.py ui.py` OK; discord-bot suite **22/22**.
- Staged card content compiles (`py_compile`) and no test assumes the old ±3.
