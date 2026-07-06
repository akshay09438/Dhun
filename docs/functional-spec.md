# Prompt-DJ — Functional Spec (V1)

_What the app does, for the user, screen by screen. Approved during discovery on 2026-07-05. This is a living document — kept true to the code. The "how it's built" lives in [technical-spec.md](technical-spec.md); progress lives in [implementation-plan.md](implementation-plan.md)._

## What the app does TODAY (as of 2026-07-06, M1–M3 built; M4 complete)

Upload two songs → each is cleaned to a standard format/volume and playable back. Per song, two on-demand actions: **"Split into parts"** (hear the vocals / drums / bass / other separately — cloud AI, ~30–120s first time, instant after) and **"Analyze track"** (see BPM, the Camelot key, and a colored section-structure timeline — the DJ's read of the song). Once both songs are split and analyzed, **"Make my mix"** produces a **full DJ arrangement** — Song 1's beat running throughout, with Song 2's vocal **weaving in and out across the WHOLE song as an energy arc** (an instrumental intro, then a vocal moment in each third — early, middle, and a strong entry saved for near the end — with beat-only stretches between), tempo-locked, on the beat and click-free, with a real one-bar **beat-breath** and one subtle **filter sweep** before a big entry, and — for contrast — **Song 1's own vocal answering in a gap** so the two songs trade (never two voices at once). The vocal no longer clusters in the middle of a long song; it spans the track and finishes strong. On a song with shaky analysis it automatically plays safer (fewer moves). The mix screen **shows the arrangement** (a two-lane timeline: where each song's vocal is, in distinct colors), and **"Give me another take"** (Regenerate) produces a different valid arrangement; **Download** saves the WAV. (Live steering now plays the **whole mix** — the mix screen's **live player** plays Song 1's beat/bass/melody **and** Song 2's arranged vocal together, and you reshape it live: tap any of the four parts — **Beat · Bass · Melody · Vocals** — or type a command ("take the bass out", "remove the vocals", **"drop everything but the beat"**, "bring it all back"), and it lands **on the next beat** with a smooth fade, replying in DJ language (M5 Slices 1–2). The live player is a steerable _approximation_; the **Download stays the polished master** (it also carries the filter sweep and beat-breath). Still to come: the AI's context-aware suggestion buttons and the remaining energy moves ("beat up", "fade away"), final mastering, and short-clip export. Today you still press Split and Analyze on each song before mixing; the one-click "studying" screen is queued next.) The sections below describe the full V1 target.

## The core value, in one sentence

A person who can't DJ uploads two songs, and gets back a mix that sounds like a real DJ made it — then reshapes it with plain words.

## Who it's for

Casual music fans and creators who can't DJ but want to make good-sounding mashups to share or enjoy. First target slice: people making short mashup clips for TikTok / Reels / for fun.

## The V1 decisions (frozen)

| Decision                | V1 choice                                                                  |
| ----------------------- | -------------------------------------------------------------------------- |
| Who it's for            | Casual creators / fans                                                     |
| Song source             | **Uploads only** ("search any song" is the V2 north star)                  |
| Core loop               | Upload 2 songs → DJ-style mix → steer / regenerate → export                |
| Feature 2               | Lean live commands **+ regenerate**; energy moves only                     |
| Live tempo (BPM) change | **V2 stretch goal** (energy-up is V1; changing song speed live is later)   |
| Music                   | Western + Indian (Indian pairs need extra hand-checking — weaker analysis) |
| Success bar             | ~50 real casual creators clearly feel "I made a real mix by describing it" |

## The two features (frozen scope)

1. **The Mix (offline):** two uploads — Song 1 (beat) + Song 2 (vocals) — become one finished, continuous track with Song 2's vocals arranged _like a DJ_ over Song 1's instrumental (vocals enter on drops/choruses, the beat sometimes drops out for a breath, Song 1's own vocal sometimes kept for contrast, everything on the beat). Not a flat paste.
2. **Instant Changes (live) + Regenerate:** while the mix plays, short typed commands land on the next beat; a Regenerate button produces a different valid take.

---

## Screen 1 — Bring your two songs

- **Purpose:** get the raw material in.
- **On it:** two drop zones — "Song 1: the beat" and "Song 2: the vocals" — plus a prompt box pre-filled with "Mix Song 1's beat with Song 2's vocals, like a DJ" so a blank-brain user can just press go. One-line explainer.
- **Main action:** drop two files → **Make my mix**.
- **Empty / first-run:** a clear example pairing and a "not sure? try these two" demo pair so a first-timer succeeds immediately.
- **Error:** unsupported/corrupt file, or a mismatch too extreme to sound good → plain-language message + suggestion, never a crash.

## Screen 2 — Studying your songs (the wait)

- **Purpose:** honest progress while we analyze + split stems (~1 min first time, then cached).
- **On it:** friendly step list — "finding the beat… splitting the vocals… planning the arrangement".
- **Edge:** low-confidence song (loose beat, unclear structure, non-Western key) → note it gently here; the planner then picks safer moves (see DJ Handbook Part 9 fallback ladder).

## Screen 3 — Your mix (the heart)

- **Purpose:** play the mix, show what the "DJ" decided, let the user reshape it.
- **On it:** play/pause; a simple timeline showing where Song 2's vocal enters and where the beat drops out (arrangement is visible, not a black box); the prompt/command bar; a **Regenerate ("give me another take")** button; an **Export** button.
- **Main actions:** play/pause; type a live command; regenerate; export.
- **Live command set (V1, lean):** "beat up" (drums/energy up), "take the bass out", "remove / bring back song two's vocals", "drop everything but the beat", "fade away". Each lands on the next beat/bar and answers back in DJ language ("dropping song two's vocal on the next bar").
- **Error / edge:** out-of-scope request ("add a third song", "make it sound like Drake", "change the lyrics", live BPM change) → polite decline that points to what V1 can do; a command with no clean runway → it waits for the next beat or does the closest clean move, and says so.

## Screen 4 — Export / share

- **Purpose:** get the mix out.
- **On it:** download the full mix, and a **short 15–30s clip** (the creator's native unit).

## Global

- No real accounts in V1 (a stub at most).
- Nothing is fetched from outside — only the two uploaded songs' own parts, rearranged on the beat.

---

## Open assumptions (to confirm as we build)

1. Short-clip export as a hero output — keep or cut.
2. "Search any song" is explicitly V2, not V1.
3. ~~Full-length mix is the primary output, clip export secondary.~~ **Resolved 2026-07-06 (discovery):** the **full-length mix is the hero output** (the founder's call). Short-clip export stays a secondary M6 output. This is why full-song arrangement quality (the energy arc) is worth investing in.
4. The ~50-user test uses real casual creators, not friends being nice.
