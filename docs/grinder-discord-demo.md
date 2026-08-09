# Grinder — the Prompt-DJ Discord bot (demo UX + rationale)

_A throwaway beta to get the feel of Prompt-DJ **inside Discord**, for a validation meeting
with store-sector people. This document is the "acting-as-a-consumer" judgment call: what is
the most convenient way for a person to mix and play music through a Discord bot, and why we
built it the way we did. It is a demo, deliberately not the "proper" production build._

## The goal (who + why)

- **Who:** the founder (to test), then store-sector validators in a live meeting who will
  judge whether "make a DJ mix by just describing/picking songs" feels real inside Discord.
- **Job:** in under ~15 seconds, a total non-DJ types one command, picks two songs, and hears
  a mix they'd actually keep — and can instantly ask for another take or play it out loud.
- **Success for the demo:** a validator says "wait, _that's_ it? I just typed that and got a
  real mix?" — the same "I made a real mix by describing it" reaction the web app chases.

## Acting as a consumer: what makes a bot easy?

I looked at the two proven mental models people already have for "a bot that makes/plays media":

| Model | Example | What users love | What's fiddly |
| --- | --- | --- | --- |
| **Prompt → artifact in the channel** | **Midjourney** | Type one command, get the result back _in the chat_ with buttons (variations/again). Nothing to install, everyone sees it, it's shareable, you can re-roll. | The result is a file, not "live". |
| **Play in a voice channel** | **Rhythm / Groovy / Jockie** | It feels like a real DJ playing to the room; social, live. | Everyone must be in the voice call; more moving parts; no artifact to keep/share. |

**Consumer verdict:** for a _mashup_ tool the **Midjourney model is the more convenient core** —
because the value is the *creation* (a mix you can replay, re-roll, and share), not just live
playback. So Grinder leads with a clip in the channel, and _adds_ voice playback as a one-tap
bonus for the "play it to the room" moment. That's the **Both** choice, with the reliable
Midjourney-style path as the spine.

## The chosen design

### One command, autocomplete, no manual anything
`/mix` with two options — **beat** (Song 1) and **vocals** (Song 2) — each an **autocomplete**
box. Start typing "fa…" and Discord shows *Father Ocean, Faded* to click. This is the key
convenience decision:

- **Why autocomplete, not a dropdown menu?** Discord select-menus cap at 25 options and get
  unwieldy; autocomplete searches as you type and **scales to the full 200-song catalog**
  effortlessly. It's the native, familiar pattern for picking from many items.
- **Why two clearly-labelled roles?** The whole product is "Song 1's beat + Song 2's vocals".
  Naming the two boxes *beat* and *vocals* teaches the mental model in the command itself.

### The result comes back like Midjourney
Send `/mix` → a **"🎧 Cooking your mix…"** card appears (honest progress), then becomes the
finished mix:
- a **playable MP3 clip** attached (plays inline on desktop & mobile, and is shareable/downloadable),
- the mix's **playful AI name**, the two songs, and the **mix style** used (Simple / Echo /
  Chop & repeat — visible, like the web app),
- three buttons: **🔄 Another take · 🔊 Play in voice · ⏹️ Leave voice**.

### Buttons = the whole live-steering story, made tap-simple
- **🔄 Another take** re-rolls the arrangement (up to 5), reusing the app's exact
  deterministic "regenerate" — different every tap, cached so repeats are instant.
- **🔊 Play in voice** makes Grinder join the presser's voice channel and stream the mix,
  giving the rhythm-bot "play it to the room" feel on demand.

## The two flows a validator will see

1. **Make + re-roll (the hero):** `/mix beat: Father Ocean  vocals: Dooriyan` → clip in ~a few
   seconds (cached) → tap **🔄 Another take** twice to show instant variety → download/share.
2. **Play it to the room:** join a voice channel → tap **🔊 Play in voice** → the mix plays
   live for everyone in the call.

_Suggested 60-second demo script:_ run one `/mix`, let the clip land, hit **Another take** once
("same two songs, different DJ take"), then **Play in voice** ("…and it plays out loud like a
real bot"). Then let a validator type their own `/mix`.

## Why this is convenient (the summary)

- **Zero learning curve** — it's the Midjourney flow people already know.
- **No manual steps** — no uploads, no settings; pick two, done. (Songs are picked, matching
  V1's curated-catalog model.)
- **Shareable by default** — the clip lives in the channel; re-rolls and voice are one tap.
- **Scales to 200 songs** via autocomplete without a cluttered menu.

## Honest limits (because it's a demo, not the "proper" build)

- **Local & single-user-ish:** runs on the founder's PC against the local engine; no cloud, no
  rate limits, no real accounts, in-memory state. Fine for a personal server + a meeting.
- **Catalog only:** the ~24 local songs; no uploads (same as V1). The 200-song catalog is the
  cost-estimate scenario, not loaded for this demo.
- **Voice needs PyNaCl:** if it won't install on this Windows/ARM machine, voice is disabled
  and the clip path (the reliable core) still works — the button says so plainly.
- **First render of a new pair** is slower (up to ~a minute); cached after that.

## What the "proper way" would add later (not now)

Hosted 24/7 (so the link works without the founder's PC on), a real queue + rate limits,
per-user history, uploads, a persistent DB, sharing/permalinks, and observability. All
deliberately out of scope for a feel-first validation beta.
