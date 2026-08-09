# Prompt-DJ — Web launch cost estimate (200-song catalog)

_What it costs to run Prompt-DJ on the web with a 200-song catalog, at several sizes. Prepared
2026-08-09. Unit prices verified against live vendor pages (August 2026); sources in the
appendix. Figures are rounded engineering estimates — good for a go/no-go decision, not a
finance-grade forecast. USD first, ₹ at ~83/USD._

---

## The bottom line

| Size             | Active users | **Monthly cost (USD)**             | **Monthly cost (₹)** | One-time setup |
| ---------------- | ------------ | ---------------------------------- | -------------------- | -------------- |
| **Validation**   | ~100         | **~$40 / mo** (~$30 optimized)     | **~₹3,300 / mo**     | ~$26 (₹2,150)  |
| **Small launch** | ~1,000       | **~$260 / mo** (~$160 optimized)   | **~₹21,500 / mo**    | ~$26           |
| **Growth**       | ~10,000      | **~$1,800 / mo** (~$800 optimized) | **~₹1,50,000 / mo**  | ~$26           |

**The one figure that matters:** almost the entire bill is the **AI "mix planning" call** — one
small Claude request per mix (~$0.008). Everything else — storing 200 songs + stems, the
servers, and the bandwidth to stream audio — is **tiny** (a few dollars a month) if you use
zero-egress storage (Cloudflare R2). So: **cost scales with how many mixes people make**, not
with catalog size or plays. "Optimized" above uses prompt-caching + batching on that one call,
which roughly halves-to-thirds it, plus the app's existing cache (a repeated pair is free).

---

## Assumptions (change these and the numbers move)

- **Catalog:** 200 songs, each pre-processed **once** into 4 stems + analysis, then cached.
- **Per active user / month:** ~20 mixes generated (each = one AI planning call) and ~20 plays
  (~3.5 MB each as MP3).
- **Storage:** source songs + stems kept as WAV (quality-first) ≈ **44 GB**; on Cloudflare R2.
- **Serving audio:** via R2 / Cloudflare (**$0 egress**) — the single biggest money-saver for
  an audio app.
- **AI planner:** Claude Haiku (the cheap tier) — the app makes one structured-JSON call per
  mix. The deterministic audio engine does the actual mixing on CPU (no GPU per mix).

---

## 1. One-time setup — loading the 200-song catalog

Each song needs TWO paid Replicate (cloud GPU) passes — split into stems, and analyze its
structure (beat / downbeats / sections). The analysis runs on a pricier A100 GPU, so **it, not
the stems, dominates this cost** (corrected 2026-08-09 — an earlier version wrongly treated
analysis as free/local).

| Item                                                          | Unit            | 200 songs          |
| ------------------------------------------------------------- | --------------- | ------------------ |
| Stem separation (Replicate Demucs, T4, ~$0.018/song)          | per song        | ~$3.60             |
| **Structure analysis (All-In-One, A100, ~94 s, ~$0.11/song)** | per song        | **~$22**           |
| **Total one-time**                                            | **~$0.13/song** | **~$26 (₹~2,150)** |

Longer tracks cost more (analysis time varies with song length), so budget **~$26–37
(₹2,150–3,050)** for ~200–215 songs. Re-run only when the catalog changes — stems + analysis are
cached forever per song, so this is a genuine one-time cost.

## 2. Per-mix marginal cost (what one new mix costs)

| Item                                                       | Cost per mix             |
| ---------------------------------------------------------- | ------------------------ |
| Claude Haiku planning call (~3k in + 1k out tokens)        | **~$0.008**              |
| CPU render (deterministic DSP)                             | negligible (server time) |
| Store the rendered mix (~3.5 MB MP3)                       | negligible               |
| **Per mix (list price)**                                   | **~$0.008 (₹0.66)**      |
| Per mix, optimized (prompt caching −90% input, batch −50%) | **~$0.003 (₹0.25)**      |

Because the app is **content-addressed cached**, the _same_ pair/take is planned **once** and
served free forever after — so real-world cost is often below list.

## 3. Monthly cost by size

All using **R2 (zero egress)** + **Haiku planner**. "Claude" = users × 20 mixes × per-mix.

| Line                                                       | 100 users      | 1,000 users    | 10,000 users     |
| ---------------------------------------------------------- | -------------- | -------------- | ---------------- |
| Compute (API + render worker)                              | ~$25           | ~$75           | ~$150            |
| Object storage (44 GB + growing mix cache, R2 @ $0.015/GB) | ~$1            | ~$2            | ~$5              |
| Database (Postgres)                                        | $0 (free tier) | ~$25           | ~$50             |
| Bandwidth (R2 egress)                                      | **$0**         | **$0**         | **$0**           |
| AI planning (Claude Haiku, list)                           | ~$16           | ~$160          | ~$1,600          |
| **Total (list)**                                           | **~$42 / mo**  | **~$262 / mo** | **~$1,805 / mo** |
| **Total (optimized Claude)**                               | **~$32 / mo**  | **~$162 / mo** | **~$805 / mo**   |
| **In ₹ (list)**                                            | **~₹3,500**    | **~₹21,700**   | **~₹1,49,800**   |

> **If you ever use S3/CloudFront instead of R2**, add bandwidth: ~$0.6 / $6 / $60 per month at
> the three sizes (700 GB/mo at 10k users ≈ $60). R2's zero egress avoids this entirely — it's
> the recommended choice for an audio app.

## 4. Where the money goes — and how to keep it low

1. **The AI planning call is ~90% of the bill at scale.** Levers, all supported today or cheap
   to add: **prompt caching** (the system prompt/schema repeats every call → −90% on input),
   the **batch API** (−50%), the **content cache** (popular pairs planned once), and staying on
   **Haiku** (Sonnet is ~2–3× the price for this job).
2. **Bandwidth is free on R2** (zero egress). This is the difference between ~$0 and ~$60/mo at
   10k users. Choose R2 (or Cloudflare/Bunny) over S3+CloudFront.
3. **Storage is trivially cheap** (~$1–5/mo). Storing stems as FLAC instead of WAV would roughly
   halve the ~44 GB, but it barely matters at these prices — not worth the effort pre-launch.
4. **Compute is modest** until render concurrency is high; a separate render worker that scales
   on queue depth is the right shape when you get there.

## 5. Not included (flag before a real launch)

- **User uploads** (V1 is catalog-only). If you allow uploads later, **each uploaded song adds a
  ~$0.13 processing cost (stems + structure analysis)** and storage — a real per-upload variable cost.
- **Domain, email, error monitoring, backups** — small but real (~$5–20/mo combined).
- **The Discord bot** (Grinder) is separate and runs locally for the demo — ~$0. Hosting it 24/7
  later would be ~$5–15/mo on the same small compute.
- Support, moderation, and music-licensing/legal — **not** infra costs, but real for a public
  launch of a mashup product.

---

## Appendix — unit prices (verified Aug 2026)

| Item                                           | Price                             | Source                                |
| ---------------------------------------------- | --------------------------------- | ------------------------------------- |
| Replicate Demucs (T4, ~81 s/song)              | ~$0.018 / song                    | replicate.com/cjwbw/demucs + /pricing |
| Claude Haiku 4.5                               | $1.00 / M input, $5.00 / M output | Anthropic pricing (Aug 2026)          |
| Claude Sonnet (intro→Aug 31)                   | $2 / $10 per M                    | Anthropic pricing                     |
| Cloudflare R2                                  | $0.015 / GB-mo, **$0 egress**     | R2 pricing                            |
| AWS S3 Standard                                | $0.023 / GB-mo, ~$0.09/GB egress  | S3 pricing                            |
| S3 + CloudFront egress                         | ~$0.085 / GB                      | CloudFront pricing                    |
| Bunny CDN                                      | $0.005–0.01 / GB                  | Bunny pricing                         |
| Compute (Fly / Render / Railway, ~1 vCPU/2 GB) | ~$11 / $25 / ~$30 / mo            | vendor pages                          |
| Managed Postgres (Supabase Pro / Neon)         | $0 free → ~$19–25 / mo            | vendor pages                          |
| Audio size (3.5 min)                           | WAV ~37 MB · MP3 128k ~3.4 MB     | deterministic                         |
| 4 stems / song (WAV)                           | ~148 MB (FLAC ~75 MB)             | deterministic                         |

**Confidence:** high on Replicate/Claude/storage/CDN unit prices and audio-size math; medium on
the compute band and the 81 s Demucs runtime (varies by input). The scenario totals inherit the
per-user activity assumptions above — adjust "20 mixes/user/month" to your real number and the
Claude line (and thus the total) scales linearly.
