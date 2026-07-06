from pydantic import BaseModel


class Song(BaseModel):
    """A processed song the client can play back."""

    id: str
    original_name: str
    url: str
    status: str = "ready"


class KeyInfo(BaseModel):
    """The song's musical key, as DJs use it (Camelot code)."""

    camelot: str  # e.g. "8A"
    tonic: str  # e.g. "A"
    mode: str  # "major" | "minor"
    confidence: float  # 0..1 — key detection is a known weak spot


class Section(BaseModel):
    start: float  # seconds
    end: float
    label: str  # intro / verse / chorus / bridge / outro / ...


class TrackAnalysis(BaseModel):
    """Everything the DJ brain needs to know about one song, plus job status.

    status: "processing" | "ready" | "error" | "idle" (mirrors the async
    stems flow). All musical fields are only meaningful when status=="ready".
    Every field the mixing rules lean on carries a confidence signal — the
    planner must distrust shaky data (DJ Handbook Part 9).
    """

    song_id: str
    status: str
    bpm: float | None = None
    bpm_confidence: float | None = None
    beats: list[float] = []  # every beat, in seconds
    downbeats: list[float] = []  # bar starts ("the one")
    phrase_starts: list[float] = []  # 8-bar block starts
    key: KeyInfo | None = None
    sections: list[Section] = []
    sections_confidence: float | None = None
    energy_curve: list[float] = []  # 0..1 per bar
    vocal_regions: list[tuple[float, float]] = []  # [start,end] secs where vocals sing
    vocal_confidence: float | None = None


class StemSet(BaseModel):
    """The separated parts of one song, plus the split job's status.

    status is one of: "processing" (split running), "ready" (done, stems
    populated), "error" (split failed). stems maps a part name
    (vocals/drums/bass/other) to the URL that serves it.
    """

    song_id: str
    status: str
    stems: dict[str, str] = {}


class Placement(BaseModel):
    """One vocal moment in an arrangement: where it enters and which slice sings."""

    anchor: float  # secs into Song 1, on a downbeat
    vocal_src: tuple[float, float]  # [start, end] secs of Song 2's vocal
    beat_breath: bool = False  # one-bar tension dip in the bed right before this entry
    fx: str | None = None  # optional entry effect; Slice B supports "sweep_in" (filter sweep)
    # Per-bar phase-lock (M4d): (src_start, src_end, out_secs) per bar — stretch each bar of
    # the vocal to the matching Song 1 bar length so it re-locks to the beat and can't drift.
    # Empty => the legacy single global-atempo stretch (M3/M4a–c cached plans still parse).
    warp: list[tuple[float, float, float]] = []


class MixPlan(BaseModel):
    """The recipe for one mix — what the brain decided, for the engine to run.

    The brain (rules + Claude) writes this structured plan; the deterministic
    render engine executes it. The LLM never touches audio samples — it only
    picks among options the rules already declared legal (technical-spec's one
    architectural principle). M3 was a single vocal placement; M4 grows this into
    a full arrangement via `placements` (the scalar anchor/vocal_src stay as the
    single-placement fallback, so M3-era cached plans still parse).
    """

    mix_id: str
    song1_id: str  # the beat / instrumental bed (its own vocal is dropped)
    song2_id: str  # the source of the vocal we lay on top
    master_bpm: float  # everything locks to Song 1's tempo (the master clock)
    vocal_stretch: float  # atempo ratio applied to Song 2's vocal (~master/song2 bpm)
    vocal_src: tuple[float, float]  # [start, end] secs of Song 2's vocal to use
    anchor: float  # secs into Song 1 where the vocal enters (a phrase-start downbeat)
    beat_breath: bool = False  # drop Song 1's beat for one bar just before the vocal
    placements: list[Placement] = []  # the full arrangement; [] => single-placement (M3)
    s1_vocal_regions: list[tuple[float, float]] = []  # spans where Song 1's OWN vocal answers (contrast)
    take: int = 1  # which regenerate iteration produced this (1-based)
    notes: str = ""  # DJ-language explanation of the move
    confidence: float = 0.0
    source: str = "rules"  # "ai" | "rules" — which brain picked it (honesty/debug)


class Mix(BaseModel):
    """An async mix job and its result (mirrors StemSet / TrackAnalysis status).

    status: "processing" | "ready" | "error" | "idle". When ready, url serves the
    exported WAV and plan explains the move. message carries a plain-language note
    or a decline reason (e.g. tempos too far apart to blend cleanly).
    """

    mix_id: str
    status: str
    url: str | None = None
    plan: MixPlan | None = None
    message: str | None = None


class LiveOp(BaseModel):
    """One live steering instruction the browser executes on the beat.

    The brain (deterministic parser now; the LLM later) turns a typed command into
    this structured op; the browser schedules it on the next bar. The LLM never
    touches audio — it only fills this. op is "mute" | "unmute" | "decline".
    """

    op: str
    target: str | None = None  # which bus: "bass" | "drums" | "other" | ...
    when: str = "next_bar"
    say: str = ""  # DJ-language reply shown to the user
    reason: str | None = None  # why a command was declined (out of scope)
