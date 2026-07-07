# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. `/handoff` rewrites this at the end of a session; `/start` and the SessionStart hook replay it at the beginning. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-07-08 (**discovery + planning session — NO code written**). Two triggers: the founder **showed V0.1 to 3–4 real people who said it "sucks / too simple,"** and asked hard whether an AI/transformer model should power the mashup. This session did deep cited research, reframed the product with the founder, mapped the current code, and **wrote a build plan** (`docs/richer-mashup-proof-plan.md`) that is **awaiting founder approval**. The working tree change is docs-only; the code and the test suite are **untouched** (last known green: 181 backend + 39 web).

## Where things stand (one breath)

Both V1 features (offline DJ mix + live steering) remain built and founder-confirmed; the app is the curated "Father Ocean shelf." **The real news this session is a validated problem and a chosen direction, not a code change.** Real testers found V0.1 **too simple — "the mix sounds basic"** (their words), which matches the code: the engine is hard-wired to **Song 1's beat + Song 2's vocal only** — Song 2 never plays as itself, so only one song is ever truly present. Research (many cited scouts) settled the big questions **with the founder aligned:** (1) **no model, open or closed, mashes up two REAL songs** — they all _regenerate_ new audio (real recordings lost) and a generated track _kills live steering_, so the app's **stem + DSP + LLM-plan architecture is confirmed correct**; (2) **fine-tuning on 50–100 songs cannot buy DJ judgment** (needs thousands of _labelled_ examples) — the practical "judgment transformer" is **Claude planning over good analysis features, tuned by human ears**; (3) genuinely useful **open judgment-layer models exist for later** (Beat This! for beat/downbeat, Demucs-stem+VAD for vocal detection, AutoMashUpper mashability, Automix cue-points — all _perception_, not generators; MERT is non-commercial); (4) the **"both beats + both vocals" goal was reframed** (founder agreed): not simultaneous (mud/clash) but a **DJ journey that trades/weaves both songs**. The plan turns this into a scoped **proof on ONE pair**.

## In flight

- **NO half-done code. No code was touched this session.** The only working-tree changes are documents: `docs/richer-mashup-proof-plan.md` (new), plus this handoff and an implementation-plan drift entry — all committed here.
- **THE BUILD IS PLANNED, NOT STARTED — awaiting founder approval of the plan doc.** Founder explicitly asked to "collect + plan first, write a doc I read, then execute — no code until I approve." The doc is `docs/richer-mashup-proof-plan.md`.
- **3 open decisions the founder has not yet answered** (they'll answer next session): (a) proof shows **one** Song-2-as-itself switch vs **several**; (b) add a **"describe your mix" prompt** in this proof or as the next step (the AI driver `plan.py` _already accepts_ a `prompt`, fed `""` today — cheap to wire); (c) confirm the proof pair = **Father Ocean × Don't Start Now**.
- **Suite state:** NOT re-run this session because no executable code changed. Last known green from the prior handoff stands: **181 backend + 39 web, typecheck clean.**

## Do first next session

1. **Founder reads `docs/richer-mashup-proof-plan.md`** and answers the 3 open decisions above (or edits the plan). This is the approval gate — nothing gets built until then.
2. **On approval, execute the heavy build** (the plan's process): an **independent test-author writes the failing tests first**, then build in small pieces, then a **fresh adversarial-safety quorum** before touching the two protected files, then **confirm-and-apply** on `workers/render.py` + `services/api/app/planner/validate.py` (founder's explicit yes recorded via `.zuko/approve.js`), then **founder listens** and ideally **re-shows the same 3–4 people**.
3. **Still-open from before (carried):** the **founder ear-test of the shelf** (Father Ocean × each vocal) remains the standing catalog acceptance gate.

## Verification evidence (which checks ran, what they returned)

- **No code changed this session → no checks were re-run.** Honest baseline (from the 2026-07-07 handoff, re-verified there): backend `pytest -q` in `services/api` → **181 passed**; web `npm test` → **39 passed**; `npm run typecheck` → **clean**. Adding markdown docs cannot affect these.
- **This session's only artifacts are documents:** `docs/richer-mashup-proof-plan.md`, this handoff, and one implementation-plan drift-log entry.

## Open escalations

- **PLANNED dangerous-surface work (not yet done — a claim about the FUTURE build, not a settled state):** the approved richer-mashup build will edit `workers/render.py` (new "Song 2 as itself" DSP + bass-swap crossfades) and `services/api/app/planner/validate.py` (new one-bassline / one-vocal / on-beat rules for the segment). These are the quality guardrails — they MUST go through the test-author + adversarial quorum + confirm-and-apply flow, and the founder's ears, before merge. Nothing here is verified yet because nothing is built yet.
- **CLAIM to re-verify — the ±8%→±11% band widening** (`fence.SAFE_STRETCH_LO/HI` = 0.89/1.11): relaxes the anti-warble guard for ALL mixes; founder-accepted. Tighten back if any mix sounds warbly.
- **The private ngrok link is DOWN** (session-bound; dies with the process). To bring it back: founder double-clicks **`Start-PromptDJ.bat`** (repo root), keeps the window open. Do **not** make it public (copyrighted audio + spends the founder's Anthropic/Replicate credits).
- **Catalog audio + `data/library/manifest.json` are LOCAL-ONLY** (gitignored `data/`, not in GitHub). Any new machine / cloud deploy must re-source the song files (`song-dropbox/` on the Desktop) and re-ingest. Not reproducible from git alone.
- **Upload route** (`services/api/app/routes/songs.py`, dangerous) still exists (operator-only). Streaming size-cap + FFmpeg timeout in place; rate-limit + duration cap still open — re-verify hardening before any public deploy.
- **`main` is behind** (M4 tip); all work is on `feat/m5-live-control` (pushed). Merge deferred by the founder.
- **Environment truths (unchanged):** Windows-ARM can't run PyTorch/heavy-audio locally — split/analyze go via Replicate; local DSP is FFmpeg + numpy/scipy. Work lean/sequential (memory-constrained).

## How to run the app

**Local dev:** backend `.venv/Scripts/python -m uvicorn app.main:app --port 8000` (from `services/api`), web `npm run dev` (from root), open http://localhost:5173.
**Shareable link (self-hosted tunnel):** double-click **`Start-PromptDJ.bat`** (repo root) — builds the web app, starts the engine on :8000 (also serves the built UI), opens the ngrok tunnel; the public URL prints on the "Forwarding" line. Keep the window open + PC on = link live. (ngrok free = one tunnel at a time; claim the free static domain for a stable URL.)
**Flow:** pick a beat + a vocal from the dropdowns → Make my mix → Play (tap parts / Beat up / chips / type commands / drag the transport) → Export.
