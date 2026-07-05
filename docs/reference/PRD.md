# Prompt-DJ — V1 Technical Architecture & PRD

**Build target:** Claude Code (implementation by Opus)
**Author:** Product (acting PM) · **Status:** V1 spec, build-ready · **Scope:** frozen to exactly two features
**Format note:** written to be pasted directly into Claude Code as the source-of-truth spec.

---

## 0. Scope freeze (read first)

V1 contains **exactly two features and nothing else.** Anything not on this list is explicitly out of scope for V1 and must not be built.

**Feature 1 — "The Mix" (offline generation).**
Input: two user-uploaded audio files, Song 1 (the *beat/instrumental source*) and Song 2 (the *vocal source*). Output: one finished, continuous mixed track that uses Song 1's instrumental as the musical bed and places Song 2's vocals on top **arranged like a DJ** — i.e. the system decides *where* Song 2's vocals enter, *sometimes* keeps Song 1's own vocals, *sometimes* drops the beat out to let a vocal breathe, and lands everything on the beat. Not a blind full-length paste of one vocal over one instrumental.

**Feature 2 — "Instant Changes" (live control).**
While the generated mix plays back, the user issues short natural-language commands ("beat up", "fade away", "remove song two's vocals", "take the bass out", "bring the vocals back", "drop everything but the beat") and the mix responds **on the next beat**.

**Explicitly OUT of V1:** third songs / multi-track sets; any audio generation or synthesis; outside instrument/loop libraries; streaming-catalog sources (Spotify/Apple); track recommendation or library management; lyric editing, autotune, or style transfer; live club/controller/MIDI; mobile; accounts/billing beyond a stub. Reject or decline these (see §11 command routing).

---

## 1. The one architectural principle (do not violate)

**The language model plans. The audio engine executes. They never mix.**

The LLM never touches audio samples. For Feature 1 it converts (song analysis + the user's request) into a structured **`MixPlan`** — a deterministic "score" describing which stems play where. For Feature 2 it converts a spoken command + live state into a structured **`LiveOp`**. A separate deterministic **render/playback engine** executes those objects with DSP.

Consequences we are deliberately buying: editability (regenerate = re-plan; instant tweak = patch state), near-zero LLM cost (planning is a few KB of JSON, not audio), no hallucinated audio (engine only performs a fixed operation set), and full debuggability (the plan is inspectable JSON).

---

## 2. Goals, non-goals, success criteria

**Goals.**
- G1: From two compatible uploads, produce a DJ-style vocal-over-beat mix that a non-DJ perceives as "a real DJ made this."
- G2: Let the user reshape the playing mix in real time with plain-language commands that land cleanly on the beat.
- G3: Keep the arrangement *inspectable and re-runnable* (a `MixPlan` the user can regenerate or nudge).

**Non-goals (V1).** Perfect separation; flawless results on arbitrarily mismatched songs; understanding lyric meaning; live crowd sensing; anything in the OUT list (§0).

**Success criteria (measurable, evaluated on the curated demo set).**
- S1: On a *compatible* pair (BPM within easy stretch range, Camelot-adjacent keys, clear structure), the generated mix has **no beat drift**, **no two-vocal overlaps**, **no two-bassline overlaps**, and vocal entries land on phrase downbeats.
- S2: Song 2's vocal is placed in **at least 2 distinct, musically sensible locations** (e.g. a chorus/drop and a post-breakdown), not pasted across the whole track.
- S3: Every Feature-2 command executes on the next musically correct beat with **no click, no stall, no silence**.
- S4: A "regenerate" produces a *different, still-valid* arrangement.

---

## 3. The two features specified precisely

### 3.1 Feature 1 — user stories & acceptance

- *As a user, I upload two songs and ask for "Song 1's beat with Song 2's vocals, mixed like a DJ," and get back one finished track.*
  **Accept:** output is a single continuous audio file; Song 1's instrumental is the bed throughout; Song 2's vocal appears in selected sections; the arrangement varies (not a flat overlay); all hard rules (§7.3) hold.
- *As a user, I can steer placement ("only bring the vocal in on the drops", "keep Song 1's vocals in the verses").*
  **Accept:** the planner honors the placement constraint where structure detection supports it; if it can't locate the referenced section confidently, it falls back to a safe placement and reports what it did.
- *As a user, I can press "regenerate" for a different take.*
  **Accept:** a new valid `MixPlan` with different segment choices.

### 3.2 Feature 2 — user stories & acceptance

- *As a user, while the mix plays, I type "beat up" / "fade away" / "remove song two's vocals" and hear it happen on the beat.*
  **Accept:** each command maps to a deterministic `LiveOp`, scheduled to the next bar/phrase downbeat, executed without artifacts; the UI confirms in DJ language ("dropping song two's vocal on the next bar").

---

## 4. System architecture

```
apps/web (React)                 services/api (FastAPI)              workers
────────────────                 ─────────────────────               ───────────────────────
Upload (2 files)          ─▶     POST /songs               ─▶ job    analyze_worker  (MIR)
Prompt box                       POST /mix/plan            ─▶        stems_worker    (separation)
Arrangement view  ◀─MixPlan──    POST /mix/render          ─▶ job    render_worker   (DSP mixdown)
Player + live prompt bar         POST /mix/{id}/regenerate
   │  (live commands)            WS  /mix/{id}/live         ◀────────  live_engine    (on-beat ops)
   ▼
Live playback (stems kept separate under the hood)

           Postgres (metadata + plans)   ·   Redis (job queue + live pub/sub)   ·   Object store (audio)
           Anthropic Claude API (planning: MixPlan + LiveOp)   ·   GPU (Modal/Replicate) for stems
```

**Two execution modes:**
- **Offline (Feature 1):** async jobs. Analysis + stems are cached per file content-hash (run once). Planning is a fast LLM call. Render is a DSP job producing a file **and** a stems-preserved bundle for live playback.
- **Live (Feature 2):** a persistent session over WebSocket. The rendered mix is held as separately-addressable stem buses; commands become on-beat `LiveOp`s applied to those buses.

---

## 5. Core data models

These Pydantic schemas are the single source of truth. Everything else is glue.

### 5.1 `TrackAnalysis` (one per uploaded song; cached by content hash)

```jsonc
{
  "song_id": "s1",
  "duration_sec": 214.7,
  "bpm": 124.0,
  "bpm_confidence": 0.93,
  "beat_times_sec": [0.48, 0.96, ...],        // every beat
  "downbeat_times_sec": [0.48, 2.42, ...],    // bar starts (the "one")
  "downbeat_confidence": 0.88,
  "phrase_starts_sec": [0.48, 15.9, 31.3, ...],// 8/16-bar block starts
  "phrase_confidence": 0.71,
  "key": { "camelot": "8A", "tonic": "A", "mode": "minor", "confidence": 0.82 },
  "sections": [                                // WEAK LINK — carry confidence
    { "label": "intro",     "start_bar": 0,  "end_bar": 8,  "conf": 0.7 },
    { "label": "verse",     "start_bar": 8,  "end_bar": 24, "conf": 0.6 },
    { "label": "drop",      "start_bar": 40, "end_bar": 56, "conf": 0.65 },
    { "label": "breakdown", "start_bar": 72, "end_bar": 80, "conf": 0.5 }
  ],
  "sections_confidence": 0.6,
  "vocal_regions_bar": [ [8,24], [40,56] ],    // where THIS song sings
  "vocal_confidence": 0.8,
  "energy_curve": [ {"bar":0,"e":0.2}, ... ]   // 0..1 per bar
}
```

### 5.2 `StemSet` (one per song; cached)

```jsonc
{
  "song_id": "s1",
  "stems": {
    "vocals": "s3://.../s1/vocals.wav",
    "drums":  "s3://.../s1/drums.wav",
    "bass":   "s3://.../s1/bass.wav",
    "other":  "s3://.../s1/other.wav"
  },
  "separation_model": "htdemucs",
  "quality_score": 0.78,          // used to warn when a stem is too bleed-y to expose solo
  "vocal_isolation_ok": true
}
```

### 5.3 `MixPlan` (the spine of Feature 1 — LLM+rules output, engine input, UI state)

The mix is **Song 1's instrumental as the continuous bed**, with an **arrangement timeline** deciding, bar by bar (in Song 1's grid), what vocal sits on top and what the instrumental does.

```jsonc
{
  "mix_id": "m1",
  "bed": { "song": "s1", "use_stems": ["drums","bass","other"] },   // Song 1 instrumental
  "topline": { "song": "s2", "stem": "vocals" },                    // Song 2 vocal
  "target": { "bpm": 124, "key_camelot": "8A", "loudness_lufs": -9.0 },
  "sync": {
    "song2_timestretch_ratio": 0.9688,     // stretch S2 vocal 128→124
    "song2_pitch_shift_semitones": -1,     // key-fit S2 vocal into 8A (0 if compatible)
    "song2_anchor_bar_in_song1": 40        // where S2 vocal phrase 1 is pinned
  },
  "arrangement": [                          // segments over SONG 1's bars, phrase-aligned
    { "from_bar": 0,  "to_bar": 8,  "vocal": "none",  "instrumental": "full",       "note": "intro builds, instrumental" },
    { "from_bar": 8,  "to_bar": 24, "vocal": "song1", "instrumental": "full",       "note": "keep S1's own vocal in verse" },
    { "from_bar": 24, "to_bar": 26, "vocal": "song2", "instrumental": "drop",       "note": "beat drops out, S2 vocal breathes before drop" },
    { "from_bar": 26, "to_bar": 40, "vocal": "song2", "instrumental": "full",       "note": "S2 vocal lands on the drop" },
    { "from_bar": 40, "to_bar": 48, "vocal": "none",  "instrumental": "drums_only", "note": "instrumental breather" },
    { "from_bar": 48, "to_bar": 64, "vocal": "song2", "instrumental": "full",       "note": "second S2 vocal section" }
  ],
  "fx": [
    { "type": "filter_sweep", "at_bar": 24, "length_bars": 2, "curve": "lpf_open" },
    { "type": "reverb_tail",  "at_bar": 26, "length_bars": 1, "amount": 0.3 }
  ],
  "warnings": [ "sections_confidence low (0.6); vocal placements verified against downbeats only" ]
}
```

`instrumental` values: `full` (drums+bass+other), `drums_only` (drop bass+other), `drop` (kill the bed for a breath), `no_bass` (drop just bass under an incoming vocal).
`vocal` values: `none`, `song1` (use Song 1's own vocal stem here), `song2` (use Song 2's vocal), never both in the same segment.

### 5.4 `LiveState` + `LiveOp` (Feature 2)

```jsonc
// LiveState — held by the live engine per session
{
  "mix_id": "m1",
  "playhead_bar": 37,
  "buses": {                       // current fader levels 0..1 per addressable stem
    "s1.drums": 1.0, "s1.bass": 1.0, "s1.other": 1.0, "s1.vocals": 0.0,
    "s2.vocals": 1.0
  },
  "active_fx": [],
  "pending_ops": [ { "op_id":"o12", "fires_at_bar": 38 } ]
}

// LiveOp — produced by the LLM+rules from one command, scheduled to a beat
{
  "op_id": "o12",
  "targets": [ { "bus": "s1.drums", "to_level": 1.0, "ramp_beats": 2 } ],
  "fx": [],
  "anchor": "next_bar",            // next_bar | next_phrase | next_beat | now
  "reason": "user said 'beat up'"
}
```

---

## 6. Feature 1 pipeline (stage by stage)

Each stage lists **input → output → tool → acceptance**. All stages after analysis read cached artifacts.

**Stage A — Ingest.** Two uploads → normalized WAV (decode, resample 44.1k, peak-normalize) in object storage; content-hash for caching. *Tool:* FFmpeg. *Accept:* both files decoded and stored.

**Stage B — Analysis** (per song, cached). WAV → `TrackAnalysis`. *Tools:* librosa + Essentia + madmom (beat/downbeat), Essentia HPCP + key-profile (key→Camelot), librosa self-similarity + heuristics (sections), stem-based vocal detection (run after Stage C, or a quick vocal-activity pass). *Accept:* BPM within ±1 of reference on the demo set; downbeats land on the one; key matches a reference key-finder. **Attach confidence to every field** (§9 depends on it).

**Stage C — Stem separation** (per song, cached). WAV → `StemSet` (vocals/drums/bass/other). *Tool:* Demucs (htdemucs) on GPU, or a stems API (Music.ai/AudioShake) to start. *Accept:* isolated vocal intelligible; `quality_score` computed; flag if vocal isolation is too bleed-y to expose solo.

**Stage D — Arrangement planning** (the judgment layer, §7). (analysis of both songs + user request) → `MixPlan`. *Tool:* Claude (structured output) + deterministic rule helpers. *Accept:* plan validates against schema; all hard rules hold; ≥2 distinct Song-2 vocal placements; warnings populated where confidence is low.

**Stage E — Tempo lock.** Compute `song2_timestretch_ratio = target_bpm / song2_bpm`; time-stretch Song 2's vocal to Song 1's tempo, pitch preserved. *Tool:* Rubber Band (commercial license) or SoundTouch (LGPL). *Accept:* stretched vocal stays in time against Song 1's grid across the whole track (no drift); if the ratio is extreme (see §9.4) the planner should have chosen shorter vocal segments instead.

**Stage F — Key lock.** If `key_shift_semitones != 0`, pitch-shift Song 2's vocal by that amount (small only). *Tool:* same library. *Accept:* shifted vocal doesn't sound "underwater"; if required shift > ±2, planner must instead place the vocal only where key clash is masked (percussive/short segments) or warn.

**Stage G — Beat alignment.** Pin Song 2 vocal phrases to Song 1 phrase-start downbeats per `arrangement`/`sync`. *Accept:* every vocal segment begins on a Song 1 downbeat; lyric phrases sit in musically correct spots.

**Stage H — Render/mixdown.** Execute the `MixPlan`: for each segment, sum the specified stems at the specified levels, apply fades at segment edges (equal-power), enforce single-bassline and single-vocal, apply `fx`. Produce (1) a flat rendered file, and (2) a **stems-preserved live bundle** (each addressable bus kept separate) for Feature 2. *Tools:* FFmpeg + pydub/numpy. *Accept:* click-free segment joins; hard rules hold in the actual audio.

**Stage I — Post.** Loudness-normalize to target LUFS + brickwall limiter + dither. *Accept:* integrated loudness within ±1 LUFS of target; no clipping.

---

## 7. The judgment / arrangement engine (Feature 1's brain)

This is where "like a DJ" is earned. It converts one line of intent into a full arrangement.

### 7.1 What the planner receives
- Both songs' `TrackAnalysis` (with confidences) and `StemSet.quality_score`.
- The user's request text (default: "Song 1 beat + Song 2 vocals, like a DJ") plus any placement constraints.
- A compact "menu" of Song 1's phrase-start downbeats and labeled sections, and Song 2's vocal regions (so it knows *what vocal material exists to place*).

### 7.2 What the planner decides (the hidden questions in one line)
- Roles: which song is bed (S1), which is topline (S2).
- Target BPM (S1's) and whether S2's vocal needs a key shift, and whether that shift is small enough to sound OK (else restrict placement).
- **Where** S2's vocal enters — prefer S1's drops/choruses and post-breakdown openings; avoid S1's own vocal regions and its quiet intro.
- **Whether/where** to keep S1's own vocal (for variety / "conversation between songs").
- **Where** to drop the beat for a breath before a big vocal entry.
- Segment lengths (phrase-aligned, 8/16 bars).
- FX placements (a filter sweep into a drop, a short reverb tail on a breath).

### 7.3 Hard rules the planner must never break (validated post-generation)
- **R1** One lead vocal at a time — never `song1` and `song2` vocal in overlapping bars.
- **R2** One bassline at a time — the bed provides bass; if a segment brings S1 vocal, it's still S1's own track, fine; never sum two basslines. (In V1 the bed is always S1 only, so this is automatic; keep the check for safety.)
- **R3** Every vocal/segment boundary lands on a Song 1 downbeat (phrase-start preferred).
- **R4** No vocal in a clashing key without either a small key-shift (≤±2) or masking (short/percussive placement).
- **R5** S2 vocal appears in ≥2 distinct sections and is NOT pasted across the whole track (variety requirement).
- **R6** Final loudness never clips.

### 7.4 Soft rules (defaults the LLM may vary for musicality)
- Prefer entering S2's vocal on the drop/chorus; prefer a 1–2 bar beat-drop breath right before it; keep S1's vocal in a verse for contrast; end on a resolved section. These are *guidelines*, deliberately varied on regenerate.

### 7.5 LLM vs deterministic split
- **Deterministic helpers (functions the LLM calls, never guesses):** `snap_to_phrase(song1, bar)`, `camelot_fit(keyA, keyB) → {compatible, shift}`, `stretch_ratio(bpmA, bpmB) → {ratio, safe}`, `vocal_regions(song)`, `section_windows(song)`.
- **LLM (taste among legal options):** choosing *which* legal phrase-start to enter on, *how many* S2 vocal sections and where, *when* to keep S1's vocal, *where* to breathe. The LLM outputs the `arrangement` array; a validator enforces §7.3 and repairs/rejects violations.

### 7.6 Confidence gating (ties to §9)
If `sections_confidence` is low, the planner does **not** trust section labels; it falls back to placing S2 vocals on **downbeat-aligned phrase boundaries** in higher-energy regions of the `energy_curve` instead of on named "drops," and records a warning. If `vocal_confidence` on Song 1 is low, it conservatively avoids overlapping S1 vocal regions by widening the guard.

---

## 8. Feature 2 — live control engine

### 8.1 The model
The rendered mix is played back as **separately-addressable stem buses** (from Stage H's live bundle): `s1.drums, s1.bass, s1.other, s1.vocals, s2.vocals`. Live control = moving those bus faders and applying bounded FX, always **scheduled to a beat** using Song 1's grid (which is the mix's master grid).

### 8.2 Command lifecycle
`received → interpreted (LLM→LiveOp) → scheduled (bound to anchor beat) → armed → executing (ramped) → done`. The scheduler uses the master beat clock (a musical timeline, e.g. Tone.js Transport on web or a server-side scheduler) so ramps start exactly on the anchor beat.

### 8.3 Command catalog (exact mappings)

| User says | LiveOp | Anchor | Ramp |
|---|---|---|---|
| "beat up" / "more drums" | `s1.drums → up (or +)` | next bar | 2 beats |
| "fade away" / "fade out" | all buses → 0 | next bar | 4–8 beats |
| "remove song two's vocals" | `s2.vocals → 0` | next bar | 1 beat |
| "bring the vocals back" | `s2.vocals → 1` | next phrase | 1 beat |
| "take the bass out" | `s1.bass → 0` | next bar | 2 beats |
| "drop everything but the beat" | `s1.bass, s1.other, s2.vocals → 0`; drums stay | next bar | 2 beats |
| "add reverb / echo" | bounded FX on active vocal bus | next bar | on-grid, time-boxed |
| "filter sweep" | LPF/HPF sweep on bus/master | next bar | 4–16 beats |
| "lower song two's vocal" | `s2.vocals → ~0.5` | now/next beat | 1 beat |

### 8.4 Orchestration (condensed from the full spec)
- **Invariants:** music never stops; nothing fires off-grid.
- **Concurrency:** independent ops (different buses) merge onto the same beat; conflicting ops (same bus) — later overrides earlier; duplicates/no-ops are ignored with a confirmation.
- **State-aware:** "take bass out" when bass already muted = no-op + confirm.
- **Confirm:** every accepted op returns a one-line DJ-language confirmation to the UI.

---

## 9. Analysis confidence & fallback (why V1 doesn't break on real files)

Every rule leans on analysis, and analysis is imperfect — **section detection is the weakest link in the entire stack** (no reliable off-the-shelf tool gives "the drop is at 1:04"). The engine must distrust its own data.

- **9.1 Per-field confidence.** Store confidence for BPM, beatgrid, downbeats, phrases, key, sections, vocal regions (see §5.1).
- **9.2 What lowers it:** live drums, tempo drift, swing, sparse intros, atonal/percussive material, irregular phrasing, low-bitrate sources, dense mixes, non-Western tonality (relevant if targeting Indian/Bollywood/Punjabi catalogs — key + structure models are weaker there).
- **9.3 Cross-checks:** two BPM estimators must agree; verify the grid still aligns to onsets at the *end* of the track (drift check); check stem-drum onsets fall on predicted beats.
- **9.4 Fallback ladder:** can't trust phrases → anchor to downbeats; can't trust downbeats → any beat + avoid drop-alignment; can't trust the grid → don't beatmatch, keep S2 vocal segments short and cut-in; can't trust key → only place vocal where clash is masked; can't trust sections → use `energy_curve` peaks instead of named drops. Extreme stretch ratio → planner chooses shorter vocal segments (long stretches artifact).
- **9.5 Runtime verify:** before Stage H commits a vocal segment, phase-check that S2 vocal downbeats coincide with S1 downbeats within tolerance; nudge or shorten if off.
- **9.6 Honesty:** surface a short note ("that song's structure was unclear, so I placed the vocal on the strongest sections") rather than failing silently.
- **9.7 Demo shortcut:** for the demo, pre-verify the curated pairs offline (hand-check grid/key/sections) so confidence is effectively 100% and fallbacks never trigger on stage — but build the fallback layer anyway for real uploads.

---

## 10. Tech stack (pinned)

| Layer | Choice | Notes |
|---|---|---|
| Frontend | React + Vite + TypeScript | upload, arrangement view, player, live prompt bar |
| Waveform/UI | wavesurfer.js | show S1 grid + section + placement overlays |
| Live clock/playback | Web Audio API + Tone.js Transport | musical scheduler for on-beat live ops; **no browser storage APIs** |
| Backend | Python 3.11 + FastAPI + Pydantic v2 | schemas = source of truth |
| Queue / live bus | Redis (RQ for jobs, pub/sub for live) | |
| DB | Postgres | analyses, stems refs, plans |
| Object storage | Cloudflare R2 / S3 | presigned upload/download |
| MIR | librosa + Essentia + madmom + aubio | BPM/beatgrid/key/sections/energy |
| Stems | Demucs (htdemucs) self-host **or** Music.ai/AudioShake API | API first for speed; self-host to cut cost |
| Time-stretch / pitch | Rubber Band (commercial license) **or** SoundTouch (LGPL) | licensing gate in CI (§14) |
| Mux/encode | FFmpeg (LGPL build) + pydub/numpy | |
| LLM | Anthropic Claude API (structured output) | `MixPlan` + `LiveOp` only |
| GPU compute | Modal or Replicate | run Demucs / heavy MIR |

---

## 11. Internal API surface (V1)

```
POST /songs                      upload → {song_id}; enqueues analyze + stems
GET  /songs/{id}                 → analysis + stem status
POST /mix/plan                   {song1_id, song2_id, request_text} → MixPlan (+warnings)
POST /mix/render                 {mix_plan} → {job_id}
GET  /mix/{id}                   → {MixPlan, render_status, mix_url, live_bundle_url}
POST /mix/{id}/regenerate        {request_text?} → new MixPlan
WS   /mix/{id}/live              live session: client sends {command_text}; server returns {LiveOp, confirmation, state}
POST /mix/{id}/export            {format: wav|mp3} → {download_url}
```

**Command routing (guardrail):** a thin classifier on `/mix/plan` and the live WS rejects out-of-scope requests (third song, "generate a beat," "mix this Spotify track," lyric edit, style transfer) with a plain-language decline and a pointer to what V1 *can* do. See §0 OUT list and Document 2's scenario table.

---

## 12. Repository layout

```
prompt-dj/
├─ apps/web/
│  ├─ src/components/Uploader/         # two-file upload
│  ├─ src/components/Arrangement/      # MixPlan viewer (segments over S1 grid)
│  ├─ src/components/Player/           # stem-bus player + live prompt bar
│  └─ src/lib/liveClock.ts             # Tone.js Transport scheduling of LiveOps
├─ services/api/
│  ├─ routes/{songs,mix,live}.py
│  ├─ models/                          # TrackAnalysis, StemSet, MixPlan, LiveState, LiveOp
│  ├─ planner/
│  │  ├─ system_prompt.md              # arrangement planner contract (§7)
│  │  ├─ tools.py                      # snap_to_phrase, camelot_fit, stretch_ratio, ...
│  │  ├─ plan.py                       # request+analysis -> MixPlan
│  │  └─ validate.py                   # enforce/repair hard rules R1..R6
│  ├─ live/
│  │  ├─ interpret.py                  # command_text -> LiveOp (LLM)
│  │  └─ orchestrate.py                # concurrency, anchors, state-awareness
│  └─ decisions/                       # camelot.py, phrase.py, energy.py, confidence.py
├─ workers/
│  ├─ analyze.py                       # -> TrackAnalysis (+confidence)
│  ├─ stems.py                         # -> StemSet
│  └─ render.py                        # MixPlan -> flat mix + live stem bundle
├─ schemas/*.schema.json               # exported from Pydantic
└─ infra/                              # Modal/Docker, migrations, CI licensing gate
```

---

## 13. Build phases (milestones + acceptance)

**M0 — Skeleton (wk1).** Repo, FastAPI, Postgres, Redis, R2, two-file upload + FFmpeg normalize. *Accept:* upload two songs, get them back re-encoded.

**M1 — Analysis + stems (wk1–2).** `analyze.py` + `stems.py` producing `TrackAnalysis` (with confidence) and `StemSet`, cached; overlays render in UI. *Accept:* BPM ±1 and downbeats on the one for the demo set; isolated vocal intelligible.

**M2 — Plan + basic render (wk2–4).** Planner emits a valid `MixPlan`; render does S1 instrumental bed + S2 vocal placed in the drop, tempo-locked, phrase-aligned; export WAV. *Accept:* S1 beat + S2 vocal on the drop, drift-free, on-phrase, click-free, single vocal.

**M3 — Full DJ arrangement (wk4–6).** Planner adds S1-vocal segments, beat-drop breaths, ≥2 S2 placements, FX; key-fit; confidence fallbacks; regenerate. *Accept:* S1–S3 success criteria (§2) on the demo set; regenerate yields a different valid plan.

**M4 — Live control (wk6–8).** Stem-bus player + Tone.js scheduling; command catalog (§8.3); orchestration; WS session; confirmations. *Accept:* S3 — every command lands on the beat, no artifact/stall; conflicting commands resolve correctly.

**M5 — Polish + guardrails (wk8–9).** Out-of-scope command routing; loudness/limiter; edge cases (huge BPM/key gaps → graceful degrade or honest decline); export. *Accept:* out-of-scope prompts declined cleanly; loudness within ±1 LUFS.

---

## 14. Non-functional requirements

- **Latency:** analysis ≤ ~15s/song (cached after first run); stems ~30–60s/song (cached); plan ≤ a few seconds; render of a 3–4 min mix ≤ ~30–60s. Live ops schedule to the next beat (sub-second perceived).
- **Determinism:** identical `MixPlan` + inputs → byte-comparable render (seed dithering).
- **Cost discipline:** MIR on CPU; **stems are the main cost** — cache aggressively, run once per song; LLM cost negligible.
- **No browser storage APIs** in the web app.
- **Licensing gate in CI:** fail the build if a GPL time-stretch lib is linked without the commercial-license flag; ship FFmpeg LGPL build.

---

## 15. Risks & mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Section detection unreliable (the weak link) | Vocals placed at wrong moments | Confidence gating + energy-curve fallback (§9); "regenerate"; curated demo pairs pre-verified |
| Stem bleed on isolated vocal | S2 vocal sounds ghostly/artifacty | `quality_score` gate; choose cleaner sources; keep reverb-heavy vocals in busier segments |
| Large BPM gap | Time-stretch warble | Planner shortens/limits S2 segments; or decline "make these work" honestly |
| Large key gap | Vocal sounds off | Small shift only (≤±2); else mask placement or warn |
| Two-vocal / two-bass slips through | Amateur "mud" | Hard-rule validator (§7.3) on the actual render, not just the plan |
| Rubber Band GPL in a commercial build | Legal exposure | CI gate; SoundTouch fallback |
| User uploads copyrighted songs | Distribution exposure | V1 = personal, in-session use of user-owned files; no stem redistribution/export as separate stems |

---

## 16. Test plan & curated demo assets

- Curate ~10 pairs: (a) *compatible* pairs (close BPM, Camelot-adjacent, clear structure) to showcase quality; (b) 2–3 *hard* pairs (big BPM/key gap, messy structure) to exercise fallbacks and honest declines.
- Golden tests: for a fixed `MixPlan`, render is byte-stable; validator catches injected two-vocal/two-bass violations; confidence fallback triggers when section confidence is forced low.
- Live tests: scripted command sequences (including rapid-fire and conflicting) verify on-beat scheduling and correct override/no-op behavior.

---

## 17. Open questions

- Stems: Music.ai API (fast to integrate) vs self-hosted Demucs on Modal (cheaper at scale) — decide at M3 by per-mix cost.
- Time-stretch: license Rubber Band vs ship SoundTouch — decide before any public/commercial release.
- How much of the live engine runs client-side (Tone.js) vs server-authoritative — start server-authoritative for correctness, add client preview if needed.
- Regenerate variety: enforce a minimum "difference" between successive plans (e.g. different entry sections) so "try again" feels meaningfully different.
