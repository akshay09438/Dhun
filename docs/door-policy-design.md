# The door — who gets into the Grinder community

_Design, 2026-08-13. Awaiting founder sign-off. Nothing built yet._

## What the founder asked for

> "I want to decide on how to allow users to enter... there are too many users who want to join, and
> our app cannot handle that. I want to filter the people joining based on interests and some cases.
> I want the entrance limited and only allowed by me upon approving the request and them having
> filled out some form, etc., so I can know them."

Answers given on 2026-08-13:

- **Purpose:** _"Need relevant folks to join + keep the number small."_ Both — quality of person AND a cap.
- **Before approval:** _"They see a lobby and wait."_

## The honest reframe, first

**Approving who gets in does not protect the machine.** This has to be said plainly because
protecting the machine was the founder's stated reason. Fifty approved people can still all press
`/grind` at once, and the door does nothing about that.

> ⚠️ **CORRECTED 2026-08-14.** This paragraph used to say the overflow past 8 **fails** rather than
> queues, and that the render waiting list was unbuilt and the next job. **Both were wrong.**
> `renderq.py` was built on 2026-08-11 and holds a real waiting line: 8 render at once, everyone
> else **waits and is served** (`_waiting` deque, FIFO, fair per person). Fifty people grinding
> together means 8 running and 42 queued — **zero failures.** A render is only ever refused when one
> person already has **3 waiting** (`max_queued_per_user`) or the whole line passes **200**
> (`max_queue`), and even then they get a plain sentence and an HTTP 429, not a mystery error.

So:

| Goal                              | The thing that actually delivers it                  |
| --------------------------------- | ---------------------------------------------------- |
| The right people                  | This door                                            |
| A small community                 | This door (the cap)                                  |
| Mixes stop failing under load     | **The render queue — already built, not this**       |
| Everyone hears their mix promptly | **More Grinder identities — still the real ceiling** |

Building the door is right, and it is not a substitute for the queue. But the capacity problem this
document worried about is **rendering**, and rendering is solved. What is left is the row underneath
it: a bot application holds one voice connection per server, so listening is still the bottleneck.

Second reality check: **listening rooms are capped by Grinder identities, not by member count.**
Two rooms can have sound at once today. A hundred approved members do not change that.

## What Discord already does, so we do not rebuild it

| Native feature    | What it does                            | Why it is not enough                                   |
| ----------------- | --------------------------------------- | ------------------------------------------------------ |
| Rules screening   | Newcomer must tick "I agree"            | The founder never sees them; nobody is refused         |
| Server onboarding | Asks interest questions, picks channels | Answers are never shown to an admin; nobody is refused |
| Invite links      | Limited-use / expiring                  | A real gate, but no form, and the link leaks           |

There is **no native "apply and be approved."** That part is genuinely ours to build.

## The design

### 1. A locked server with one open room

`@everyone` loses read access to every channel except **`#the-door`**. That single change is what
makes the server gated; everything else is bookkeeping.

A new role **`@Member`** carries the read/speak/grind permissions `@everyone` has today. Approving
somebody is exactly "give them `@Member`."

**This is the risky half**, and it touches the founder's hand-tuned live server. See "Applying it".

### 2. `#the-door` — the lobby

What a newcomer sees, and the only thing they can see. One pinned post: what Grinder is, that it is
small on purpose, and a button — **"Ask to join"**.

### 3. The form — the founder's own five questions

Discord modals allow **5 short text fields** — no dropdowns, no file uploads, no attachments. The
founder's list is exactly five, so it fits with nothing dropped:

1. **Your name**
2. **Your relation to music**
3. **What AI tools have you used?**
4. **Why do you want to join Grinder?**
5. **What are your expectations?**

The founder's stated purpose for question 3, in their words: _"I don't want random gamers or random
teams to join, but people who actually use Suno.ai, who use Midjourney, or who are actually DJs. I
want to spot them and give them first access."_ That is the sharpest filter in the set, and it is
why the answers must be **read**, not scored.

Answers are stored, so the founder ends up with a readable record of who is in the room and why.

### 4. The review

Each application posts to a **private `#applications` channel** the founder can see: the person, the
four answers, their Discord account age, and two buttons — **Approve** / **Not now**.

- **Approve** → grants `@Member`, and `@Founding Member` while under 100 (that role already exists in
  `server_setup.py` and already says "First 100 members. Hard cap."). The person gets a short DM,
  falling back to a mention in `#the-door` if their DMs are closed.
- **Not now** → they stay in the lobby and are told the room is small and it is not a no forever.
  **Deliberately not a kick**: a kick is irreversible, reads as a judgement, and the founder said
  "keep it small", not "throw people out".

Every decision records who decided and when.

### 5. The first fifty are CHOSEN, not queued

This is the correction that matters most, and it changes the review screen. The founder's words:

> "The first 50 users will be admitted. All the users who want to actually use the Discord bot would
> have to fill out a form, and I would be choosing whom to give access to based on the form."

So this is **not** first-come-first-served with a cap that slams at 50. It is a **pool the founder
picks from**. A card that arrives, gets approved or declined in isolation, and scrolls away makes
that impossible — by the time the good application arrives, the seats are gone.

What that requires:

- **Applications accumulate as a readable pool**, not a scrolling feed. `/applications` lists everyone
  still pending, newest first, with their five answers.
- **`/applications suno` (or `dj`, `midjourney`, any word) filters the pool** to applications
  mentioning it. This is the mechanical version of "I want to spot them" — a plain text search over
  answers the founder already has, not a judgement the bot is making.
- **A seat counter on every review card**: "23 of 50 taken". The founder is spending a scarce thing
  and should see the cost at the moment of the decision.
- At 50, Approve **warns and asks again** rather than refusing — the number is the founder's, and a
  tool that hard-blocks its owner is worse than one that asks "are you sure?".

**`MEMBER_CAP = 50`** in config, changeable in one place. Raising it is painless; lowering it means
removing people, so it starts where the validation bar is.

**What the bot must NOT do here.** It never scores, ranks, recommends, or flags an application as
good or bad. Searching for a word the founder typed is a filing cabinet; "this one looks promising"
is an opinion, and the standing rule that Grinder never judges exists because an opinion shown before
a human's own read poisons the human's read. The founder does the choosing.

## Applying it to the LIVE server — the dangerous part

⚠️ **`/setup` must never be run on the founder's server** (standing instruction; it recreates its
default channels beside the renamed ones). This work does not change that.

So the permission flip ships as a **narrow, targeted script** in the shape of `scripts/refresh_copy.py`:

- creates `@Member` and `#the-door` and `#applications` if absent,
- **grants `@Member` to every existing human member first** — so nobody who is already in loses
  access at the moment the door closes,
- only then removes `@everyone`'s read access,
- touches **no** channel name, topic, category or role the founder has hand-set,
- prints what it will do and requires an explicit confirmation before doing it,
- and is re-runnable.

**Order matters and is not negotiable:** grant first, restrict second. The other way round locks the
founder out of their own server for as long as the script takes.

## Non-goals

- No web-app gating. This is the Discord door only (founder, 2026-08-13).
- No automatic filtering, scoring, or bot-judged applications. The founder reads them and decides —
  consistent with the standing rule that **Grinder never judges**.
- No payment, no invite tree, no referrals.
- Not a fix for capacity. See the reframe above.

## How we will know it worked

- The founder can name why each member is there.
- Members who join actually grind — the first-grind rate among approved members is the number to
  watch, and it is already recorded.
- The founder is not spending real time on the queue: if reviewing becomes a chore, the door is
  too heavy and should shrink to invite-only.

## Testing

- Somebody without `@Member` can see `#the-door` and nothing else.
- Applying twice does not create a second card; re-applying updates the existing one.
- Approve grants the role; the person can then grind. "Not now" leaves them in the lobby with access
  unchanged.
- The pending pool survives a bot restart (it is in SQLite, not memory) — the whole point is that
  applications wait to be compared, and a restart must not empty the pool.
- `/applications suno` returns only applications whose answers contain that word, matched
  case-insensitively across all five fields.
- At 50 approved, Approve warns and requires a second confirmation; it never silently refuses.
- Existing members keep access across the permission flip (the script's grant-first order), proven
  against a throwaway server, never the founder's.
- The bot never scores, ranks, recommends or flags an applicant — a test reads every string the
  application flow can emit and fails on evaluative wording, mirroring the existing
  `test_no_card_ever_rates_or_predicts_a_grind`.
