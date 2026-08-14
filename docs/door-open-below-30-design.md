# The door opens below 30 — design

_Design, 2026-08-14. Founder decisions taken in session._

> **BUILT 2026-08-14** on branch `feat/door-opens-below-30`. `door.py` + `bot.py` + 25 new tests;
> **422 passed, 1 skipped** (was 397/1), no existing test modified or weakened. Two things the
> design did not anticipate were found while building and are recorded in "What building it
> changed" at the foot of this document.

Extends [door-policy-design.md](door-policy-design.md), which stays true in every respect except
**when** the form applies. Read that one first; this document only changes the trigger.

## What the founder asked for

> "Earlier we set a thing that whenever a random user wants to join, they have to first fill a form,
> and once approved by me those users will only be allowed in. But now what I want is that the form
> thing starts to happen after 30 server members. Before 30 members, anyone can join."

The job it does: **grow the first 30 with zero friction, then become selective.** An empty room is
the worst thing that can happen to a new community, and a form in front of an empty room is a
guaranteed empty room. Below 30 the scarce thing is people; above 30 the scarce thing is quality.

## The rule, in one line

**Fewer than 30 members → the door is OPEN: anyone who arrives is granted `@Member` immediately, no
form. 30 or more → the door is SHUT: newcomers see the form and wait for the founder.**

Tracked live, so it reopens if the count falls back below 30.

## What "30 members" counts — and what it does not

**It counts people holding the `@Member` role, excluding bots AND excluding the operators.** This is
a decision, not an inherited fact, and it is the single most load-bearing line in this document.

Founder's own words, 2026-08-14, when asked to confirm:

> "Yes I was talking about real people, excluding the Grinder bots + my two accounts (akshay5397 &
> bearwolf101)."

So the count is **real community members only**. Neither operator account counts toward the 30, and
neither do the Grinder identities.

### How the two operator accounts are identified — by ROLE, not by name

**Not hard-coded usernames, and not user ids in `.env`.** Both are excluded by what they already
are on the live server:

| Account       | What it is                                             | How it is excluded                |
| ------------- | ------------------------------------------------------ | --------------------------------- |
| `akshay5397`  | **the server owner** (measured by `server_status.py`)  | `member.id == guild.owner_id`     |
| `bearwolf101` | holds **`@Backup Admin`, which carries Administrator** | has Administrator or Manage Guild |

The rule generalises to: **bots, the owner, and anyone holding Administrator or Manage Guild do not
count as community members.** Staff are not community.

Why not the two obvious alternatives:

- **Usernames in a list** — Discord usernames are changeable, and a renamed operator would silently
  start counting, closing the door a person early with no error anywhere.
- **User ids in `.env`** — `.env` is on the dangerous-5% list, and it would mean asking the founder
  to hand-edit a secrets file to configure a feature. Configuration that requires the non-coder to
  edit a protected file is a bad trade for a rule the server already encodes.

**The one consequence, stated so it is never a surprise:** if a normal community member is ever made
an admin or moderator, they stop counting toward the 30, and the door closes one person later. That
is arguably correct (staff are not community) but it is a real behaviour, not an accident.

_Implementation note:_ checking `guild_permissions.administrator` is safe here. The
`Member.guild_permissions` trap found on 2026-08-13 — that it returns `Permissions.all()` for anyone
holding Administrator — makes it useless for asking "does this member hold some OTHER permission",
which is the opposite of what this does. Asking whether someone IS an administrator is exactly what
it answers correctly.

### The candidates that were rejected

Three ways of counting were considered before this one:

| Candidate                                                | Rejected because                                                                                                                                                                                                                                           |
| -------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Everyone in the Discord server                           | Bots are members. Grinder runs **2+ identities**, so the door would slam 2–3 people early. Worse, people queuing in the lobby are not _in_ — a queue of five would hold the door shut forever and the founder's reopen-below-30 decision would never fire. |
| `store.approved_count()` (exists today)                  | **Counts only people who came through the FORM.** It misses vouched friends (`/invitefriend`), admins, and — under this change — everyone who walks in free below 30. Using it would mean the door never closes, because free arrivals never increment it. |
| `@Member` holders, excluding bots only                   | Nearly right, and what this design said in its first draft. It still counts the founder's own two accounts, so the door would close at **28 real people, not 30**. Corrected by the founder on 2026-08-14.                                                 |
| **`@Member` holders, minus bots, the owner, and admins** | **Chosen.** The only number that means "real community members who are actually in".                                                                                                                                                                       |

That second row is a genuine trap and worth stating plainly: **the counter the app already has is
the wrong counter for this feature.** A reasonable implementer would reach for `approved_count()`
first, and the door would silently never close.

## Founder decisions

All four taken in session on 2026-08-14. Recorded here because two of them went against the
recommendation, and the reasoning should survive.

### 1. At 30, the door closes BY ITSELF — the founder is told afterwards

No confirmation step. The 31st arrival meets the form; Grinder posts a note in `#applications`
saying it happened.

This **reverses a principle** from the original door design, where closing the door was a deliberate
`lock_the_door.py` run that prints its changes and demands a typed "yes". That ceremony was right for
the one-time server-wide permission flip, which is destructive and hard to undo. It is wrong here:
the alternative was 40 strangers walking in overnight while the founder slept. **Reversible and
automatic beats irreversible and manual.**

### 2. It REOPENS below 30 — against recommendation

The recommendation was a one-way latch: close once at 30 and stay closed. The founder chose live
tracking instead: below 30 open, 30+ shut, always.

**The cost, stated so nobody rediscovers it as a bug:** the door flaps. Person 31 fills a form and
waits. A member leaves. Person 32 strolls in free without a form. Person 31 is still waiting, and
watched it happen. **This is a known and accepted consequence, not a defect** — the founder's model
is a capacity valve ("keep letting people in until I have 30"), not a one-time event, and under that
model the behaviour is correct.

Mitigated only by not announcing openings (see "What people see").

### 3. Pending applications are NOT auto-approved when the door reopens — against recommendation

The recommendation was to let waiting applicants in automatically, on the grounds that someone who
queued should not watch a newcomer overtake them. The founder chose to keep deciding.

**Consequence, accepted:** the queue-jumping in decision 2 is not softened. Somebody can sit pending
while the door is open around them. The founder keeps full control of who is admitted by form, which
is the whole point of the door, and that outweighs the unfairness.

**Implementation consequence:** the door state affects **new arrivals only**. Nothing in this feature
ever writes to an existing application row. That is a hard boundary and should have a test.

### 4. The 50-seat counter is corrected to count real members

`MEMBER_CAP = 50` and the "23 of 50 taken" line on every review card currently use
`approved_count()` — form approvals only. Under this change that undercounts badly: 28 free arrivals
would still read **"0 of 50 seats taken"**, and the 50-seat warning would never fire.

Changed to count real community members — the same number the 30-threshold uses. **One
definition of "a member", used in both places.** Two different definitions of the same word in one
feature is how this kind of thing rots.

## What people see

| Situation                       | What happens                                                                                                                                   |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| Arrives while under 30          | Granted `@Member` on join. Gets the same welcome DM a vouched friend gets: head to the grind channel and type `/grind`. **No lobby, no form.** |
| Arrives at 30+                  | The existing door experience, unchanged: lobby, "Ask to join", the five questions, wait.                                                       |
| Already pending when it reopens | Nothing. Still pending. The founder still decides.                                                                                             |
| The count reaches 30            | Grinder posts once in `#applications`: the door has closed and newcomers now see the form.                                                     |
| The count drops below 30        | The door reopens **silently.**                                                                                                                 |

**Closings are announced; openings are not.** An opening is not actionable — the founder does not
need to do anything about it — and a member leaving and rejoining would otherwise post a pair of
messages every time. A closing changes what strangers experience, so it is worth one line.

## Where it plugs in

Three functions in `services/discord-bot/door.py`, plus one counter:

| Function                      | Today                                                       | Change                                                                                                                                                                                                                                                                          |
| ----------------------------- | ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `is_open()`                   | "is a door channel configured at all"                       | Keeps that meaning (the dormant-by-default guard) and gains the count check. **Two distinct questions — see the note below.**                                                                                                                                                   |
| `on_member_join()`            | lets a vouched arrival straight in, everyone else untouched | Gains a branch: under 30, grant `@Member` and welcome them. The vouch path is unchanged and still runs first.                                                                                                                                                                   |
| `blocked_reason()`            | blocks `/grind` for anyone without `@Member`                | Returns `None` while under 30 — nothing to block when everyone is admitted anyway.                                                                                                                                                                                              |
| new: `community_count(guild)` | —                                                           | `@Member` holders minus bots, the owner, and Administrator/Manage-Guild holders. **The single definition**, used by the threshold and by the seat counter. Named `community_`, not `member_`, because "member" is the ambiguous word this whole section exists to disambiguate. |

**A naming trap worth calling out.** `is_open()` currently means "is this feature configured"; this
change makes "open" also mean "letting people in freely". Those are different questions and
collapsing them would produce a door that is dormant and permissive for the same reason. They will
be **two separately named functions** — the configured check keeps its meaning, and the new
threshold check is its own thing.

## Testing

The bot's tests are plain `pytest` in `services/discord-bot/tests/` and are **not** a dangerous
surface (the dangerous list covers `**/conftest.py`, `*.test.ts`, `*.test.tsx` — not these). No
existing test file needs weakening.

New tests, written before the change:

1. Under 30, a joiner is granted `@Member` and never sees the form.
2. At exactly 30, a joiner gets the form. **The boundary is `>= 30` shut, not `> 30`.**
3. **Bots do not count** toward 30 (add two bots at 29 real people, door stays open).
4. **The server owner does not count** (`akshay5397`).
5. **An Administrator / Manage-Guild holder does not count** (`bearwolf101` via `@Backup Admin`).
   Together with 3 and 4: a server showing **34** in Discord's own member list, made of 30 real
   people + 2 bots + 2 operators, must read as exactly **30** — and a server of 28 real people +
   2 bots + 2 operators must read **28** and leave the door OPEN.
6. Lobby-sitters do not count toward 30.
7. Dropping below 30 reopens the door.
8. **A pending application is never mutated by any door-state change** (decision 3's hard boundary).
9. The closing announcement fires once on crossing, not on every join above 30.
10. The seat counter reports real members, including free arrivals.
11. With no door configured, every behaviour is exactly as it is today (the dormant guard).

**Test 11 is the regression that matters most:** this feature must remain invisible on a server that
has never set the door up.

**Tests 3–5 are the ones that encode the founder's actual sentence** and are the easiest to get
subtly wrong — an implementation that counts Discord's own member number passes tests 1, 2, 6 and 7
and still closes the door four people early.

## Non-goals

- **Not changing the form, the five questions, the review flow, or `/invitefriend`.** Only when the
  form applies.
- **Not touching the live server.** No `/setup`, no `lock_the_door.py` run. This is bot logic; it
  takes effect wherever the bot runs.
- **Not making 30 configurable from Discord.** It is a constant beside `MEMBER_CAP`, changed in one
  place, same as the 50.
- **Not backfilling.** Existing members keep whatever they have; nobody is granted or removed by
  this change.

## Blast radius

**Light.** `door.py` and its tests, both outside the dangerous-5% list. No audio path, no render, no
validator, no storage, no secrets, no CI. Reversible by changing one constant.

The one genuinely irreversible risk is **letting the wrong people in while the door is open** —
which is the founder's explicit intent, not a defect, and is bounded at 30.

---

## What building it changed (2026-08-14)

Two things the design did not anticipate. Both were found by tests failing, and both matter more
than anything in the original plan.

### 1. UNKNOWN MUST COUNT AS SHUT — the cold-cache hole

`community_count` reads `guild.members`, which is a **cache** fed by a privileged intent, not a
live query. The design never asked what happens when that cache is empty or half-filled.

The answer is the worst possible one: an empty cache counts **zero** real members, zero is under
30, so the door reads as **wide open** — and every stranger arriving in that window is handed
`@Member` on a server that is supposed to be shut. Silent, irreversible, and precisely the
direction `door.py` says never to be wrong in.

`taking_all_comers` now refuses to answer "open" unless it can see the whole server:

- **no guild at all** (a DM, say) -> shut;
- **member list empty** -> shut, because that is never true of a real server the bot is in;
- **Discord's own `member_count` higher than what we hold** (not fully chunked) -> shut.

**Mutation-verified:** deleting this guard turns **8 tests red**, including two that predate this
feature. A person wrongly asked to fill a form can just be approved; a stranger wrongly let in
cannot be un-let-in.

### 2. A NOTE MUST NEVER COST SOMEBODY THEIR ENTRY

The first implementation ran the closing announcement **before** the grant, to catch the moment the
door was still open. A guild whose channel lookup raised therefore took the whole arrival down with
it — and **a vouched friend was silently left in the lobby by a cosmetic notification.** The
existing suite caught it immediately.

Split in two, by value:

- `note_door_is_open()` — pure bookkeeping, no network, runs before the grant. It is what makes a
  genuine reopen-then-close get announced a second time.
- `announce_if_just_closed()` — does the sending, runs after, and **swallows every exception**.

The founder missing one message is a nuisance; a promised friend stuck in the lobby is a broken
promise. Pinned by `test_a_broken_announcement_never_costs_somebody_their_entry`.

### Also settled while building

- **The 30th person walks in free, and shuts the door behind them.** discord.py caches the arriving
  member before dispatching `on_member_join`, but they hold no `@Member` yet, so they do not count
  until granted. 29 in -> they walk in -> 30 -> the next person meets the form. This matches
  "after 30 members the form starts" exactly, and is pinned by its own test.
- **A vouch is spent before the size check.** Below 30 the person would have got in either way, but
  silently leaving their single-use link alive would let it be forwarded later, once the door is
  shut — turning a spent vouch into a permanent hole.
- **`store.approved_count()` was left alone**, not deleted. It still answers a real question (how
  many came through the form). It is simply no longer used for anything that means "how big is the
  community".
