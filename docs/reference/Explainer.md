Prompt-DJ -- The Complete Plain-Language
Guide to Version 1

What we're building, why, how it works under the hood, and exactly what it will and won't do --
written so anyone can follow it, no technical background needed.

Part 0 -- How to read this document

This is the companion to the technical spec. The technical spec is for the engineer (or Opus) who builds
it. This document is for you and anyone you want to explain the product to -- an investor, a
teammate, a friend. It assumes zero knowledge of audio technology. Where a technical idea matters, it's
explained in everyday words with a comparison you already understand.
It has three jobs: (1) capture the full story of what we've decided and why, so nothing gets lost; (2)
explain, from first principles, how DJ mixing actually works mechanically -- so you understand what's
genuinely hard and what's easy; and (3) lay out Version 1 completely -- the two features, what happens
step by step, what's possible, and what isn't.

Part 1 -- The story so far (context)

The core idea, in one line

The same way modern tools made it so that people who never learned to code can now build software
just by describing what they want -- we want to do that for DJing. A person who knows nothing about
mixing should be able to make a real, good-sounding mix just by typing what they want.

Where the idea sits

There's a company called Suno that lets anyone generate a brand-new song from a text prompt. That's
powerful, but it's a different thing from what we're doing. We are not generating new music. We are
mixing existing songs -- taking real tracks and blending them the way a DJ would. Suno is a songwriter
in a box; we are a DJ in a box. That distinction matters, because it changes everything about how we
build, what it costs, and what the legal picture looks like.

The journey to Version 1

We started broad -- imagining a full "type anything and it DJs" product with continuous live sets, many
songs, live performance. That's the long-term vision, and it's real. But a first version has to be small

Prompt-DJ -- Version 1 Guide                                                                              1
enough to actually build and prove. So we deliberately narrowed, again and again, until we landed on the
smallest thing that still feels like magic. Along the way we established a few truths that shape everything:

   · The AI plans; a separate audio engine does the sound. The AI never touches the actual audio. It
     reads what you want and writes a "recipe." A separate, dumb-but-precise engine follows the recipe.
     This one decision is what makes the whole thing buildable, cheap, and reliable.

   · Things happen on the beat, not the instant you ask. When you type a command, it lands a beat
     or two later -- right on the musical grid. That tiny wait isn't lag; it's exactly what a real DJ does, and
     it's what makes it sound skilled instead of glitchy.

   · We prepare the songs before we play with them. When songs load, we quietly study them and
     split them into parts up front. So when you ask for something live, the material is already sitting there
     ready -- no waiting, no failing on stage.

   · Version 1 uses songs you upload, not streaming songs. You can't get the actual audio file out of
     Spotify or Apple (it's locked), and mixing famous catalog songs at scale is an expensive legal world.
     So V1 works on files you own. That's also the safe path.

The end goal

A world where making a great mix is as easy as describing it. Where a bedroom listener, a content
creator, or a working DJ can all say what they hear in their head and get it -- from a quick two-song blend
to, eventually, a whole live set steered entirely by words. Version 1 is the first honest step toward that:
prove that "describe a mix, get a real mix" works for two songs. If that lands, everything else is expansion.

Part 2 -- First principles: how DJ mixing actually works

(This section is built on the mechanics research you provided. It's here so you understand what's
genuinely hard versus easy -- because that's what decides how good Version 1 can be. In plain words.)

The one-sentence version of a DJ's job

A DJ takes two songs that were never meant to go together and makes them sound like one continuous
piece of music, at the right moment. Everything else is detail. And making "two things" become "one
thing" always comes down to solving the same five problems:

  1. Speed -- the two songs play at different speeds. Fix: match their speeds (beatmatching).
  2. Timing -- even at the same speed, the drum hits don't land together. Fix: nudge one so the beats

     line up exactly (sync).
  3. Key -- the two songs are in different musical "pitch families" and can clash. Fix: pick compatible

     songs or gently shift one (harmonic mixing).
  4. Frequency clash -- play both full-volume and it's mud. Fix: use volume and tone controls so each

     song has room (EQ).
  5. The story -- when do you start the change, and when do you bring the new song to the crowd? Fix:

     taste and timing (this is the human art).

Prompt-DJ -- Version 1 Guide                                                                                     2
Problems 1­4 are math-and-physics problems. Computers are now excellent at them -- often better than
people. Problem 5 is a taste-and-context problem, and it's where humans still win. Keep this in your
head: the machine is great at the mechanics and weak at the judgment. Our whole product is about
giving the machine as much good judgment as rules can buy, while it does the mechanics perfectly.

What a "song" is to a computer before it can mix it

A raw audio file is just a long list of numbers describing a wave of sound. Before any mixing, the software
has to turn that into understanding. A human DJ hears a track once and just knows "128 speed, minor
key, drops at about a minute, nice breakdown near the end." A computer has to work all that out from the
raw sound. This studying step is called analysis, and it happens once, when a song is loaded -- not live.
There are six things it works out:

1. Speed (BPM). It looks for the repeating "hits" in the sound (kick, snare, clap), measures the gap
between them, and that gap tells it the speed. Honest catch: a slow song and a song twice its speed can
look mathematically identical, so the software sometimes guesses "half or double" wrong -- which is why
every DJ app has a manual half/double button. Otherwise this is basically solved (right within about 1 unit
on normal music with a steady beat). It gets shakier on live drummers, songs that speed up and slow
down, or very sparse acoustic tracks.

2. Beat map (beatgrid). Knowing the speed isn't enough -- you need to know where every single beat
falls in time. So the software lays a ruler over the whole song marking every beat and every bar. This is
the single most important piece of data in the whole system -- every automatic feature is built on
trusting it. If it's slightly off, the mix mysteriously drifts out of time over half a minute, which is a nightmare
live. It's reliable (~90%) on modern electronic/pop/hip-hop, and worse on swing, live drummers, or odd
time signatures.

3. Key. It figures out the song's musical "pitch family" and translates it into a simple DJ code (the Camelot
system -- like "8A"), specifically so you don't need to know music theory. The rule that falls out is
beautifully simple: same code = always fits; same number different letter = fits (subtle mood change); one
number up or down = fits (small energy step); anything else = risk of clash. This is solved (~85­95%) for
Western pop/rock/EDM. Important catch for us: it's weaker on music that isn't built on Western major/
minor -- a lot of Indian, Bollywood, Punjabi, and Middle-Eastern music trips up these tools. Worth
knowing if we ever target those catalogs.

4. Energy/loudness. It measures how loud and dense each part is, section by section, to build a rough
"energy curve." Honest catch: the number is real but crude -- a stripped-back quiet moment can hit a
crowd harder than a "high-energy" number suggests. The number is real; its meaning isn't fully
capturable.

5. Structure (sections). Where's the intro, the verse, the chorus/drop, the breakdown, the outro? This is
the thing DJs care about most, and it's the least solved of everything. Even the best research
models get section boundaries right only about 70­80% of the time on well-behaved pop, and there is no
reliable off-the-shelf tool today that just hands you "the drop is at 1:04" for any song you throw at it. This
one fact is the biggest limiter on how good our "place the vocal at the perfect moment" feature can be --
so we design around it (more below), rather than pretending it's solved.

Prompt-DJ -- Version 1 Guide                                                                                         3
6. Vocal map. Where in the song is someone actually singing? This lets us know where a song has a
vocal to use, and where its own vocal would clash with another.

Pulling a song into parts (stems)

This is the newest and most transformative piece. A finished song is a blend of separate parts -- vocals,
drums, bass, and everything else -- mixed down into one file. Once mixed, you can't perfectly un-mix it.
But modern AI can make an educated reconstruction: it has studied tens of thousands of songs where it
did have the separate parts, so it learned roughly what a vocal "looks like" versus a drum versus a bass,
and for a brand-new song it makes its best guess and hands you four separate files: vocals / drums /
bass / other.

Honest catches you must respect: the split is never 100% clean -- expect a little bleed (cymbals leaking
into the vocal, reverb tails hanging around, bass blurring between the bass and "other"). Quality is better
on clean recordings and worse on dense, heavily-compressed modern mixes and low-quality files. And
separating a copyrighted song into stems doesn't give you rights to those stems -- fine for personal use,
a real legal question if you let people export and redistribute them. For us that means: V1 uses stems in
the moment, for the user's own performance, not as a stem-export product.

Matching speed without ruining the sound (time-stretching)

To make two songs the same speed, you stretch one. The naive way (just play it faster/slower) also
changes the pitch -- the "chipmunk" or "demon voice" effect. The clever technique used across the whole
industry changes speed without touching pitch (and can also do the reverse -- change pitch without
touching speed, which is how we fit a vocal into a new key). It works well for small changes and starts to
sound robotic for big ones. This is genuinely hard engineering, which is why good time-stretch software is
a paid product category.

Locking the beats together (sync)

Once you have an accurate beat map for both songs and a good stretch tool, matching them is just
arithmetic: stretch song B to song A's speed, then slide B until its beats sit exactly on A's. That's literally
all the "SYNC" button does on every DJ setup, and it's been fully solved for over a decade. It handles
problems 1 and 2 (speed and timing) -- and nothing else. Key, frequency, and "when/why to mix" are still
on you.

The actual blend (EQ, filters, effects)

Even perfectly speed- and beat-locked, two full songs on top of each other are mud, because they fight
for the same frequency space -- two kicks, two basslines, two vocals. So the fundamental DJ move is the
bass swap: as the new song comes in, cut its bass so it doesn't fight the old bass, then hand the low end
over cleanly so only one bassline is ever dominant. Add filter sweeps (gradually remove the low or high
end as a transition effect), simple volume crossfades, and effects (echo, reverb) to smooth or dramatize.
Executing these on the beat is something software does more precisely than a human hand -- once it's
been told which move to run. Deciding which move fits this moment is the judgment part.

Prompt-DJ -- Version 1 Guide                                                                                     4
The part that's barely automatable: choosing what and when

Before any mixing, a DJ chooses what to play next and when to make the move -- reading the room,
managing the energy of a whole night, knowing that this specific edit will land with this specific crowd.
None of that is in the audio file. Today's "AI DJ" tools mostly do a fancy "songs like this" match on speed
and key; they have no eyes or ears on the actual room. This is the honest frontier: the machine can't feel
a room. Our answer isn't to fake reading a room -- it's to let you supply the intent through
prompts. Your words are the context the machine is missing.

The bottom line of the mechanics

Everything computers do well here is a clean, well-defined problem with a right answer (what's the speed,
the key, what does a vocal look like, how to stretch audio). All of it is available as free, off-the-shelf
building blocks -- which means that layer alone is nobody's secret advantage; any team can assemble it.
Everything computers do badly needs context that isn't in the file -- the room, the moment, the taste.
That's not a "wait for a bigger model" problem; it's a "the information simply isn't there" problem. So the
real question for any DJ product is: are you building a better mechanical executor (a commodity), or a
better decision-maker (genuinely unsolved, and where the value is)? We're aiming at the decision-
maker -- using the user's own words as the missing context.

Part 3 -- What Version 1 is (exactly two features)

We deliberately froze V1 to two features. Not three. Two. Everything else waits.

Feature 1 -- "The Mix" (make a finished track)

You upload two songs: Song 1 (whose beat/instrumental we'll use) and Song 2 (whose vocals we'll use).
You ask for something like "use Song 1's beat, put Song 2's vocals on top, and mix it like a DJ." The
product produces one finished, continuous mixed track.

The important word is "like a DJ." A blind program would just mute Song 1's singer and paste Song 2's
singer across the entire track start to finish -- flat and lifeless. A real DJ, given the same instruction, does
something smarter: they bring Song 2's vocal in where it hits (over a drop or a chorus), sometimes let
Song 1's own vocal play for contrast, sometimes drop the beat out for a moment so a vocal can breathe
before the beat slams back, and they land every one of those moves on the beat. Version 1's Feature 1
is that smarter behavior -- a varied, intentional arrangement, not a paste.

Feature 2 -- "Instant Changes" (steer it live as it plays)

While that mix is playing, you type short commands and the mix obeys on the next beat: - "beat up" --
bring the drums up - "fade away" -- fade the whole thing out - "remove song two's vocals" -- mute the
added vocal - "take the bass out" -- mute the bass - "bring the vocals back" -- un-mute the vocal - "drop
everything but the beat" -- leave only the drums

That's the entire Version 1. Two features. Two songs. It's small on purpose -- small enough to build and
prove, big enough to feel like magic.

Prompt-DJ -- Version 1 Guide                                                                                      5
Part 4 -- The mechanical side of V1 (what physically happens, step
by step)

When you upload the two songs

Before anything else, the system studies each song once and works out the six things from Part 2 --
speed, beat map, key, structure, energy, vocal map -- and splits each song into its four parts (vocals /
drums / bass / other). All of this is saved. It's the "knowledge" everything else runs on. (This takes a little
time on first upload and is then remembered, so it never has to happen again for those songs.)

When you ask for the mix (Feature 1)

The system builds the finished track as a sequence: 1. Take Song 1's instrumental (its drums + bass +
other, without its vocal) as the musical bed for the whole track. 2. Take Song 2's vocal as the topping. 3.
Match the speed -- stretch Song 2's vocal to Song 1's speed, keeping it sounding natural (works cleanly
when the two speeds are close; gets rough if they're very far apart). 4. Match the key -- if Song 2's vocal
would clash, nudge its pitch slightly to fit (small nudges only; big ones sound off). 5. Decide the
arrangement -- this is the judgment step (Part 5): where Song 2's vocal appears, where Song 1's own
vocal stays, where the beat drops out for a breath. This produces a plan. 6. Line everything up to the
beat -- every vocal section starts exactly on one of Song 1's bar lines, so the words sit in musically
correct spots. 7. Render -- mix it all down into one finished track: one vocal at a time, one bassline at a
time, balanced volume, no distortion.

When you steer it live (Feature 2)

The finished mix plays back with its parts still kept separate underneath -- think of it as a small mixing
board with a few sliders (Song 1's drums, bass, other; Song 2's vocal). Every command just moves a
slider (or adds a simple effect), and always lands on the next beat so it sounds deliberate: - "beat up" 
slide the drums up - "fade away"  slide everything down over a few beats - "remove song two's vocals"
 slide that vocal to silent - "take the bass out"  slide the bass to silent - "drop everything but the beat"
 keep drums up, everything else down

Nothing is fetched from outside. It's all the two songs' own parts, rearranged on the beat.

Part 5 -- The judgment side of V1 (how one line means many things)

This is the heart of the product, and the reason it's more than a toy. When you type "use Song 1's beat,
put Song 2's vocals, make it like a DJ," that one short line is secretly asking the system to answer a
whole list of hidden questions. A blind system ignores them and pastes. A DJ-like system answers them:

   · Which song is which? Song 1 = the beat, Song 2 = the vocal.
   · What speed and key? Song 1's speed. Are the keys compatible? If not, how far must Song 2's vocal

     shift to fit -- and is that shift small enough to sound good, or should the vocal only appear where a
     clash won't be noticed?

Prompt-DJ -- Version 1 Guide                                                                                     6
   · Where should Song 2's vocal appear? Not everywhere. Good spots: Song 1's big moments -- a
     drop or chorus where a vocal hook lands hard -- or right after a breakdown where there's space. Bad
     spots: over Song 1's own singing (two voices = mess), or over its quiet intro (often better left
     instrumental to build anticipation).

   · Should Song 1's own vocal ever play? Sometimes yes -- keeping a signature line of Song 1, or
     alternating between the two, makes it feel like a conversation between the songs instead of a robotic
     overlay.

   · When should the beat drop out? A DJ will kill the beat for a bar so a vocal stands alone, then slam
     it back in on the drop. Those little moves are what make it feel human.

   · How long should each vocal section be? Lined up to musical phrases (usually 8 or 16 bars), never
     random lengths.

   · What must it never do? Two voices at once, two basslines at once, a vocal starting off the beat, a
     vocal in a badly clashing key.

The system answers all of this using the structure, energy, key, and beat map it worked out when the
songs were uploaded, guided by a set of DJ rules (land on the beat, one voice at a time, put vocals at
the big moments, leave breathing room, keep it in key, vary it so it's not monotonous). That's how one line
becomes a full, musical arrangement instead of a blind paste.

The honest ceiling of the judgment (so you build with clear eyes)

   · The system decides from structure, energy, key, and beat -- it does not understand what the lyrics
     mean or whether this particular pairing is inspired. So it makes sensible, musical choices, not
     creative-genius ones. It can't know that a specific line of Song 2 is emotionally perfect over a specific
     moment of Song 1. A human feels that; the system can't.

   · Because structure detection is the weakest link (Part 2), it will sometimes misjudge where a
     "drop" is and place a vocal slightly off. That's exactly why V1 needs a "regenerate / try again"
     button and the live tweaks -- so when a choice feels off, you fix it in one command rather than the
     whole thing being ruined.

   · It works best on clearly-structured, compatible pairs and worst on messy or mismatched ones.
     For a demo, you hand-pick pairs that are close in speed and compatible in key. That isn't cheating --
     that's a DJ choosing records that go together.

One line, as your product manager: Feature 1's success is roughly 80% song selection, 20% code.
Build the mechanical pipeline well, approximate the DJ judgment with rules, give the user "regenerate"
plus the live tweaks to correct it -- then, for demos, choose compatible song pairs. That combination
hides the weak spots and shows the magic.

Prompt-DJ -- Version 1 Guide                                                                                    7
Part 6 -- What's possible, partially possible, and not possible

Capability                                      Verdict Why
Split both songs into voice / drums / bass /
other                                           Yes  Standard technology; expect minor artifacts
Use Song 1's beat + Song 2's vocal
Lock them to the same speed                     Yes  The core recombination is solid
Lock them to the same key
Place vocals at musically smart spots           Yes  Solved; degrades only on large speed gaps
Vary it "like a real DJ"
Understand what the lyrics mean / artistic fit  Partial Small pitch shifts fine; large key gaps sound off

Instant changes (beat up, fade, mute a vocal)   Partial Depends on structure detection (the weak link)

                                                Partial Sensible and musical, not creative-genius

                                                No   The system has no sense of lyric meaning or

                                                     "vibe"

                                                Yes  Simple on-the-beat slider moves

The two features you asked for are both achievable. Feature 2 is fully achievable. Feature 1 is achievable
mechanically and approximately achievable on judgment -- good and musical, with quality that depends
on the songs you feed it.

Part 7 -- Twenty scenarios: what V1 will and won't do

Prompts Version 1 WILL execute

  1. "Use Song 1's beat and put Song 2's vocals on top, mix it like a DJ." -- the core Mix.
  2. "Make a track with Song 1's instrumental and Song 2's singing." -- same, plainly stated.
  3. "Only bring Song 2's vocals in on the drops." -- a placement instruction (structure-dependent, but

     supported).
  4. "Keep Song 1's vocals in the verses, use Song 2's vocals in the chorus." -- an alternating

     arrangement.
  5. "Start with just Song 1, then bring Song 2's vocal in later." -- instrumental intro, then vocal.
  6. "Let the vocal breathe -- drop the beat out for a moment before the drop." -- the "breath then slam

     back" move.
  7. "Bring the beat up." / "beat up." -- live: boost the drums.
  8. "Fade it out." / "fade away." -- live: fade the whole mix.
  9. "Remove Song 2's vocals." -- live: mute that vocal.
10. "Take the bass out." -- live: mute the bass.

Prompt-DJ -- Version 1 Guide                                                                                8
 11. "Bring the vocals back." -- live: un-mute the vocal.
12. "Drop everything but the beat." -- live: keep drums, mute the rest.
13. "Lower Song 2's vocal a little, it's too loud." -- live: reduce that slider.
14. "Make the vocal come in on the beat, in key." -- align and key-fit (with quality caveat).
15. "Try again -- put the vocal in a different spot." -- regenerate the arrangement.

Prompts Version 1 will NOT execute

  1. "Add a trap hi-hat / add some drums that aren't in either song." -- V1 only uses the two songs' own
     parts; there's no outside instrument library.

  2. "Bring in a third song / transition into Song 3." -- V1 is strictly two songs.
  3. "Generate a beat / write me a new song." -- we're a mixer, not a generator (that's Suno's job).
  4. "Mix this Spotify track." -- no streaming audio; uploads only (the files are locked and it's a licensing

     problem).
  5. "Change the lyrics / make the singer say something else." -- no vocal rewriting.
  6. "Autotune the vocal / fix the singer's pitch." -- not a production or tuning tool.
  7. "Make it sound like [famous artist]'s style." -- no style generation.
  8. "Pick the best song from my library to pair with this." -- no library or recommendation engine in V1.
  9. "Make me a one-hour continuous set." -- V1 makes one two-song mix, not a long multi-track set.
10. "Pair them cleverly based on what the lyrics are about." -- no understanding of lyric meaning.
 11. "Make these two work perfectly even though they're in totally different keys and speeds." -- it will

     attempt it, but honestly can't guarantee good results across large gaps. This is a limit of physics, not
     effort.

Part 8 -- How it's built, in plain words

Think of the product as an assembly line with a brain bolted on.

The pieces (what does the work): - A studier that listens to each uploaded song once and works out its
speed, beat map, key, structure, energy, and vocal spots. - A splitter that separates each song into
vocals / drums / bass / other. - A planner (the AI) that reads your request and writes the arrangement
recipe. - A mixer engine that follows the recipe -- stretching, key-fitting, lining up to the beat, and
blending -- to produce the finished track. - A live player that plays the finished mix with its parts kept
separate, so your live commands can move sliders on the beat.

The outside services we rely on (the APIs): - The AI (Claude) -- the planner's brain. Cheap, because it
only handles text, never audio. - A stem splitter -- a ready-made service to start (Music.ai or
AudioShake), or the free open-source splitter (Demucs) if we run it ourselves. - Rented computing
power (a service like Modal) to run the heavier studying and splitting jobs only when needed. - File
storage for the songs and the finished mixes.

Prompt-DJ -- Version 1 Guide                                                                                   9
The paid things (what costs money): - The AI planning: pennies per mix (it's just text). - Splitting songs
into parts: the main variable cost -- a few cents per song with a paid service, or cheaper if we self-host --
and we split each song once and remember it, so repeats are basically free. - Rented computing and
storage: modest. - One licensing note to decide early: the best speed-stretching tool (Rubber Band) is
free only for open-source projects; for a commercial product you either buy its license or use the free-for-
commercial alternative (SoundTouch). And we use the standard, free version of the core audio tool
(FFmpeg).

The big cost we're deliberately avoiding in V1: licensing real catalog music. The moment we let
people mix famous songs from a catalog (instead of files they upload), we enter an expensive legal world.
V1 skips it entirely by working on user-uploaded songs. That keeps V1 cheap and clean.

Roughly what it costs to build: since you're building it yourself with Opus, the real cost is your time (a
couple of months to a solid V1) plus a small bill for AI and splitting while you test -- realistically a few
hundred to a couple thousand dollars out of pocket. It's cheap because we're assembling proven building
blocks, not inventing new technology.

Part 9 -- The honest limits (so nothing surprises you)

   · Structure detection is the weak link. No tool reliably knows exactly where "the drop" is. We work
     around it with confidence checks, an energy-based fallback, and a "regenerate" button -- but
     sometimes a vocal will land slightly off, and the fix is one command, not a redo of everything.

   · Stem splitting isn't perfect. Isolated vocals can have faint bleed or leftover reverb. It's better on
     clean songs, worse on dense, heavily-processed ones. Test your demo songs' split quality before
     building the fancy parts.

   · Big speed or key gaps sound rough. The tech works best when the two songs are reasonably
     close. Force two very different songs together and it'll sound stretched or off -- an honest physical
     limit.

   · It doesn't understand meaning. It arranges by structure and energy, not by what the words say or
     feel. It's musical, not inspired.

   · This is why the demo uses hand-picked pairs. Choosing compatible songs isn't cheating -- it's
     the DJ's first and most important skill. It's how you show the product at its best while the weak spots
     stay hidden.

Part 10 -- What comes after Version 1

V1 exists to prove one thing: describe a two-song mix, get a real, DJ-style mix back, and steer it live. If
that lands, the natural expansions are clear and each is a clean addition on the same foundation: - A
third song and beyond -- real transitions between tracks, toward continuous sets. - The live, always-
playing set steered entirely by prompts (the original vision). - An outside sound library so "add drums"
can mean loops that aren't in the loaded songs. - Learning from real users -- logging which
arrangements people keep versus regenerate, so the judgment improves from real taste, which is the

Prompt-DJ -- Version 1 Guide                                                                                  10
moat no one can copy. - Eventually, licensed catalog music, once the workflow is proven and worth the
legal investment.
But none of that is V1. V1 is two features, two songs, done well enough that the magic is undeniable.
Prove that, and the rest follows.

This document is the plain-language companion to the Version 1 Technical PRD. The mechanics in Part 2
are distilled from the first-principles research on how DJ mixing works; the product decisions throughout
reflect what we've deliberately scoped for a buildable, provable first version.

Prompt-DJ -- Version 1 Guide  11
