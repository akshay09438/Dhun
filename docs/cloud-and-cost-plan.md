# Prompt-DJ — Cloud & Cost Management Plan

_How the paid/cloud pieces work, what they cost, and how we keep it cheap and safe. Plain-language reference. Written 2026-07-05._

## Why cloud at all

The developer's Windows-on-ARM machine cannot run the audio-AI engine (PyTorch crashes on it — proven). So the 2–3 "heavy AI" steps run in the cloud; everything else stays local and free.

## 1. What runs where

| On the local machine (free) | In the cloud (paid, tiny)                               |
| --------------------------- | ------------------------------------------------------- |
| The web page                | **Stem splitting** (vocals/drums/bass)                  |
| The backend orchestrator    | **Song analysis** (beat, key, structure) — M2b, later   |
| Cleaning songs (FFmpeg)     | **The AI planner** (arranges the mix) — Claude, pennies |
| Storing songs & mixes       |                                                         |
| Playback & live controls    |                                                         |

## 2. Services we rent (buy-not-built)

| Service                | Job                                       | Rough cost          | Free start    |
| ---------------------- | ----------------------------------------- | ------------------- | ------------- |
| **Replicate**          | Split stems (Demucs); likely analysis too | ~2–6¢ / song        | Yes (credits) |
| **Anthropic (Claude)** | Plan the arrangement + live commands      | ~1–2¢ / mix         | Pay-as-you-go |
| Cloud storage (later)  | Hold files when hosting for real users    | ~free at this scale | Yes           |

Only stem-splitting and analysis are real per-song costs — and both get cached.

## 3. The #1 cost control: cache once, pay once

- Every song is processed **exactly once, ever** (tagged by content hash), and the result is stored.
- Reusing that song later (by anyone) is **free**.
- Cost scales with _new unique songs_, not with mixes — so it grows slowly, then flattens.

## 4. Cost by stage (estimates)

| Stage               | What                                                | Est. total            |
| ------------------- | --------------------------------------------------- | --------------------- |
| Building M2         | A handful of test songs                             | **$0** (free credits) |
| ~50-user validation | A few hundred unique songs, cached                  | **~$10–25**           |
| If it scales        | Switch to bulk/self-hosted GPU to cut per-song cost | Per-song cost drops   |

## 5. Key (secret) management

- Each service gives one secret key. Stored as an **environment variable** on the machine that runs the app — never in a file, never in chat, never in git.
- Keys are **revocable / rotatable** in seconds.
- When hosting for real users, keys live in the host's secrets vault.
- The founder owns all accounts & keys; the code only _uses_ them.

## 6. One mix, step by step (where money is spent)

```
Upload 2 songs → clean            (local, free)
              → split stems       (Replicate ~5¢, then cached free)
              → analyze           (cloud ~cents, then cached free)
              → plan arrangement  (Claude ~1¢)
              → render mix         (local, free)
              → play + live control (local, free)
```

Spend happens only at the cloud-AI steps, and only the first time a song is seen.

## 7. Scaling path

- **Today:** laptop = backend; cloud = AI; pay per new song.
- **Validation (~50 users):** backend moves to a cheap always-on host + cloud storage; same AI services.
- **Growth:** move stem-splitting to a rented GPU (cheaper in bulk); app code barely changes (vendors kept swappable).

## 8. Who does what

- **Founder (one-time per service):** sign up, add a card if required, create a key, hand it over safely.
- **Claude Code:** all code + wiring, cheapest reliable vendor, caching, surfacing real costs.

## 9. Staying in control

- Set a low **hard spending cap** on each service (e.g. $10–20/mo).
- **Caching** keeps the meter mostly still.
- **Swappable vendors** — move if one gets pricey/flaky.
- Real per-song and monthly costs surfaced from dashboards, not just estimates.

## Current status (2026-07-05)

Setting up **Replicate** for stem separation (M2a). **Anthropic** key to be added for the planner (M3+). Analysis vendor for M2b to be confirmed (aim: Replicate; Music.ai as fallback).
