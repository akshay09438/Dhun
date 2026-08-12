# Can Grinder run when the laptop is shut? — free-tier research, 2026-08-12

_Research only. Nothing was signed up for, nothing was migrated, no money was spent or committed.
Brief: **hard zero budget — genuinely free options only, and a straight answer on whether free is
possible at all.**_

## The straight answer

**Yes. Free always-on hosting exists and would run Grinder — including voice.** The strongest
option is Oracle Cloud's Always Free tier, and the single thing that could have killed it turns
out not to apply.

But it got meaningfully worse two months ago, and there are three real catches. Read to the end
before deciding.

---

## The headline finding: voice is NOT a problem there

This was the thing worth checking first, because it could have ended the conversation.

Oracle's free machines are **ARM** — the same word that made voice impossible on the founder's
laptop. The obvious fear was that moving to a free ARM server would re-break the one thing that
started working today.

**It does not.** The blocker was narrower than "ARM":

| Platform                              | `davey` wheel published?                 |
| ------------------------------------- | ---------------------------------------- |
| Windows ARM64                         | ❌ **no** — this is the laptop's problem |
| **Linux ARM64 (`manylinux aarch64`)** | ✅ **yes**                               |
| Linux x86-64                          | ✅ yes                                   |
| Windows x86-64                        | ✅ yes                                   |
| macOS (both)                          | ✅ yes                                   |

So the true statement is narrower again than the one recorded this morning. It was
"`davey` publishes no ARM build" → then "no **Windows**-ARM build" → and now, precisely:

> **`davey` has no Windows-ARM wheel. Linux ARM is fully supported.**

Voice on a free Oracle ARM box would work with no emulation trick and no second Python. That is
a better position than the laptop is in today.

---

## What Oracle Always Free actually gives you now

**It was halved on 15 June 2026, with no public announcement.**

|                      | Before   | **Now**    |
| -------------------- | -------- | ---------- |
| ARM CPUs (Ampere A1) | 4        | **2**      |
| RAM                  | 24 GB    | **12 GB**  |
| Block storage        | 200 GB   | **200 GB** |
| Outbound traffic     | 10 TB/mo | 10 TB/mo   |

Existing free instances were **shut down** until owners resized them to the new limits. Anything
above the limits now bills on a pay-as-you-go account. Worth knowing before relying on it.

Even halved, **12 GB RAM and 200 GB of disk is far more headroom than the laptop has** — the
machine that hit 5.86 GB free today. Most of tonight's disk anxiety simply goes away at 200 GB.

## The three real catches

1. **Capacity.** ARM instances are in heavy demand and frequently return "out of capacity" in
   popular regions. Frankfurt and Singapore reportedly provision within minutes; others can take
   repeated attempts.
2. **Idle reclamation.** Oracle reclaims instances that look idle. A bot holding a Discord
   gateway connection is genuinely active, so this is unlikely to bite — but it is a stated policy,
   not a guarantee.
3. **Account creation is refused fairly often**, sometimes with no reason given. This is the most
   commonly reported frustration.

## What was rejected, and why

| Option                    | Verdict                                                                                                                                                                    |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Fly.io** free allowance | 3 shared VMs at **256 MB RAM**. Fine for a bot that only chats. Nowhere near enough to render audio — mixing alone is the heaviest thing this app does. Also wants a card. |
| **Railway**               | ~$5 of credit ≈ one month. **Not free forever**, so it fails the brief. Genuinely the easiest deploy experience if that ever changes.                                      |
| **Replit / Glitch free**  | **Disqualifying.** They sleep the process after inactivity, which drops the Discord gateway connection. A sleeping Discord bot is an offline Discord bot.                  |

---

## What this does NOT answer

Being honest about the edges, because the next step depends on them:

- **Can 2 ARM cores actually render a mix in a reasonable time?** Unknown, and it is the real
  question. Mixing is 16.2s and the crop 8.5s on the founder's laptop, both CPU-bound ffmpeg work.
  Two shared ARM cores will be slower — plausibly 2–3× — and the current 8-at-once cap would
  certainly need lowering. **This needs measuring on the actual hardware, not guessing.**
- **Stem separation and analysis already run on Replicate**, so they do not care where the app
  lives. But Replicate is metered, and "zero budget" and "metered API" are in tension regardless
  of hosting. That is a separate conversation and it is coming.
- **Nothing here was tested.** No account was made, no instance was created, no code was moved.
  This is desk research against public documentation and reports.

## Recommendation

**Free hosting is real and voice is not the obstacle — but do not migrate on the strength of this
document.**

The cheap next step, if the founder wants it, is a **measurement**, not a migration: create one
free instance, install the audio toolchain, and time a single render. That answers the only
question that matters — _is 2 ARM cores enough to mix a song?_ — and costs nothing but an evening.
If the answer is yes, everything else about the move is routine. If it is no, no time was spent
migrating something that was never going to work.

The one part only the founder can do is **create the Oracle account**, which is also the step
most likely to be refused.

## Sources

- [Oracle quietly halves free-tier Ampere A1 limits (InfoQ)](https://www.infoq.com/news/2026/07/oracle-cloud-free-tier-limits/)
- [Oracle Cloud free tier 2026: 4 OCPU/24GB cut to 2 OCPU/12GB (TerminalBytes)](https://terminalbytes.com/oracle-cloud-free-tier-changes-2026/)
- [Breaking down the free tier of Oracle Cloud Infrastructure (Fullmetalbrackets)](https://fullmetalbrackets.com/blog/oci-free-tier-breakdown)
- [Best free 24/7 Discord bot hosting, tested (ClawdHost)](https://clawdhost.net/blog/best-discord-bot-hosting-2026/)
- [Free Discord bot hosting 24/7 — working methods (space-node)](https://space-node.net/blog/host-discord-bot-free-247-2026)
- [`davey` on PyPI — published wheels](https://pypi.org/project/davey/)
- [`dave.py` — Python bindings for Discord's DAVE protocol](https://github.com/DisnakeDev/dave.py)
