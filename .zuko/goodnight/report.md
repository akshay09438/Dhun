# Morning report — the second voice

_Overnight run of 2026-08-12 night 3. Branch `feat/second-grinder-voice`. Nothing was merged to `main`._

---

## The short version

**Everything I said I would build is built, tested and on a branch.** Nothing was staged for your
approval, because this whole job touched **none** of the handle-with-care files — the mixing engine,
the quality referee and the file-deleter were never opened.

**But the second room will still be silent when you wake up**, and that is expected, not a failure.
The one step I cannot do is create the second bot's token — that lives behind your Discord login.
It takes about two minutes and it is step 2 of the test sheet below.

**One thing genuinely unproven:** that sound actually comes out of a second identity. I can prove
every _decision_ it makes — 58 new tests do — but a fake voice client is always more forgiving than
Discord, which is exactly how seven bugs shipped past a green suite on 2026-08-11. **The status of
that one line is "built, reviewed, unheard."** Your ears settle it.

---

## What is done

|                                                      |                                                                                                                                           |
| ---------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| **Two rooms can hold sound at once**                 | Each room has its own everything now — what is playing, its own waiting list, its own position, its own station.                          |
| **`/skip`, `/stop`, `/play` are per-room**           | Skipping in Hollywood_Blends cannot touch Bollywood_House. It has no way to name it.                                                      |
| **The extra Grinder is an identical twin**           | Same name, same "# GRINDER" disc, applied from code. It never speaks, never posts, never takes a command.                                 |
| **Waiting people are told where they are**           | "waiting for a free voice · 2nd in line" instead of a silent "grinding…".                                                                 |
| **An empty room keeps its voice ~60s**               | Step out for twenty seconds and the music is still playing when you come back.                                                            |
| **Nothing changes until you paste a token**          | With none configured there is exactly one voice and the app behaves precisely as it did before. Its own regression tests hold it to that. |
| **Saving a token no longer wipes your settings**     | See below — this was the nastiest thing I found.                                                                                          |
| **A bad second token cannot hurt the first Grinder** | If it will not log in, one honest line in the log and the community carries on with the rooms that work.                                  |

### The nasty one, fixed before it could bite you

`Set-Grinder-Token.bat` wrote your settings file with a single `>`, which **overwrites the whole
file**. Running it a second time — the obvious thing to do after resetting a token — would have
silently thrown away your server id and all four channel ids. The bot would have come back up with
no rooms, no status message and no showcase, **and nothing in the log saying why**, because from its
point of view those settings simply were not configured any more.

This was recorded as a known, unfixed hazard in the last handoff. It is fixed now, with tests, and
I re-injected the old behaviour to confirm the tests actually catch it (they do — four of them fail).

Both scripts also now genuinely **hide the token as you type it**. The old one promised that while
using a command that echoes every character.

And pasting the _main_ Grinder's own token as an extra is now refused outright. It would have looked
completely fine — valid token, successful login — but it is the same identity, so the moment the
"second" room started, **the first room would have gone silent mid-song**. That would have read as a
far worse bug than the one being fixed.

---

## Your test sheet

Do these in order. Steps 1 and 2 are the only ones that need anything from you.

**1. Check nothing broke, before adding anything.**
Run `Start-Grinder.bat` as normal. Everything should work exactly as it does today. In the Grinder
window you should see:

> `voices: one Grinder - ONE room can have sound at a time.`

**Expected:** `/grind`, `/play`, `/skip`, `/stop` all behave exactly as they did yesterday.

**2. Create the second identity.** (~2 minutes, in your browser.)
Discord Developer Portal → you already have a spare application, `1535993733269684334`, that is not
in the server — use it, or make a new one. Then: **Bot → Reset Token → Copy.** Invite it to your
server with the same permissions as Grinder, and make sure it can **See** and **Connect to** your
listening-rooms category. _(You do not need to set its picture — Grinder does that itself.)_

**3. Paste it in.**
Double-click **`Add-Grinder-Rooms.bat`**. Paste the token, press Enter, then press Enter again on the
empty line to finish.

**Expected:** nothing appears on screen as you paste, and it ends with

> `Saved. Grinder can now have sound in 2 rooms at the same time.`

**4. Check your other settings survived.**
Run `Start-Grinder.bat` again.

**Expected:** the log does **not** complain that any channel id is missing, and it now says:

> `voices: 1 extra identities - up to 2 rooms can have sound at the same time`

**5. Look at the server.**
**Expected:** a second Grinder in the member list, wearing the same "# GRINDER" disc.

**6. The real test — two rooms at once.**
Easiest with two people (or your phone as the second). One person sits in `#Bollywood_House`, the
other in `#Hollywood_Blends`. Both `/grind`.

**Expected:** both rooms play **at the same time**. The first room's music does **not** stop when the
second one starts.

**On your own instead:** `/grind` in `#Bollywood_House` and let it start playing. Then move yourself
to `#Hollywood_Blends` and type `/play`. **Expected:** music starts in Hollywood_Blends, and if you
look at the channel list, **both** Grinders are sitting in **both** rooms at once with the speaker
icon lit. You can only hear one, but you can see both.

**7. Skip in one room only.**
While both rooms are playing, `/skip` in one.
**Expected:** that room moves on; the other one carries on undisturbed.

**8. Stop in one room only.**
`/stop` in one room.
**Expected:** that room stops; the other one keeps playing.

**9. The minute of grace.**
Leave a playing room and come back within a minute.
**Expected:** the music is still going — it never paused.

**10. Leaving properly.**
Leave a room and stay out for more than a minute.
**Expected:** that Grinder leaves the channel.

**If anything is wrong**, the useful thing to send me is the lines in the Grinder window that start
with `voices:` or `booth:` — they say which identity took which room and why.

---

## What I did NOT do, and why

- **No extra mix-making capacity.** You and I settled this at kickoff: a second identity is a second
  seat, not a second kitchen. The engine still tops out around 8–10 at once, and past that it still
  **fails** rather than queueing. That is the next job and I think it is the more urgent one now,
  because two working rooms means more people grinding at the same time.
- **I did not touch your Discord server.** No `/setup`, no channels, no categories, no roles, no
  server icon.
- **Nothing was merged to `main`.** One branch, one PR, your call.
- **The leftover decision from an earlier night is still waiting**: "Clean up disk earlier, and clear
  out stale mixes on a timer" — it would start tidying at 4 GB free instead of 2 GB, and it touches
  the file that deletes finished mixes, so it was correctly never applied. Still on your desk.

## Where I was wrong at kickoff

I told you all 245 existing bot tests would pass untouched. **17 of them did not** — they reached
directly into the old single-room internals, so I re-pointed them at the new per-room structure with
their assertions unchanged. Nothing was weakened, but "untouched" was a promise I should not have
made about a change that reshapes exactly what those tests poke at.

## Verification, real output

| Check                                                   | Result                                                    |
| ------------------------------------------------------- | --------------------------------------------------------- |
| Discord bot suite                                       | **303 passed** (245 at session start; +58 new, 0 removed) |
| Backend, full                                           | **768 passed** in 229s                                    |
| Web                                                     | **78 passed**, 9 files                                    |
| Typecheck / lint                                        | clean                                                     |
| `render.py` / `validate.py` / `storage.py`              | **untouched** — confirmed by diff                         |
| Mutation check: re-inject the shared-connection bug     | **6 tests fail**, as they should                          |
| Mutation check: re-inject the settings-wiping behaviour | **4 tests fail**, as they should                          |
| Sound out of a second identity                          | **unproven — needs your ears**                            |

---

## How this was reviewed, honestly

The overnight process normally puts a dangerous change in front of a panel of fresh reviewers before
anything is applied. **That panel was not run here, and it was not meant to be**: it exists for
changes that touch the handle-with-care files, and this bundle touched none of them.

What was done instead is arguably harder evidence: **mutation testing.** I deliberately re-broke the
two things most likely to be wrong and confirmed the tests catch them.

- Made every identity reuse the main bot's channel object — the bug where both rooms quietly share
  one connection and the log still looks healthy. **6 tests failed.** Reverted.
- Restored the old "overwrite the whole settings file" behaviour. **4 tests failed.** Reverted.

A test that has never been seen to fail is a guess. Those two have now been seen to fail for the
right reason.

**What that still does not cover:** any of it coming out of a real speaker. That is the one thing
only you can check.
