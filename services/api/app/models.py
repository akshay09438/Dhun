import hashlib
from typing import Literal

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
    build_bars: int = 0  # produced-drop: bars of rising filter+volume BUILD before this entry (0=none)
    echo: bool = False  # produced-drop: ring the vocal out with a decaying echo throw into the drop
    chop: bool = False  # Step 4: re-fire the hook onset over this entry's first bar (a vocal chop)
    # Per-bar phase-lock (M4d): (src_start, src_end, out_secs) per bar — stretch each bar of
    # the vocal to the matching Song 1 bar length so it re-locks to the beat and can't drift.
    # Empty => the legacy single global-atempo stretch (M3/M4a–c cached plans still parse).
    warp: list[tuple[float, float, float]] = []
    # Effect pool (2026-08-05): one optional SPACE effect + one optional WIDTH effect layered on
    # top of the base vocal chain, chosen per-take by the planner for regenerate variety. Both
    # additive + default None => the exact pre-pool render path (byte-identical). SPACE names:
    # room/hall/plate/predelay (length-preserving reverbs, any placement) and throw/freeze
    # (tail-extending, FINAL placement only — the referee enforces this). WIDTH: double.
    space: str | None = None  # one of the pool's SPACE effects, or None
    width: str | None = None  # one of the pool's WIDTH effects, or None
    # Rule 4 (simplified, 2026-08-05): when True, the engine adds a gap-sized echo at each line-end + a
    # continuous reverb bed on this vocal (always both together), sizing/containing the echo from the
    # vocal itself — there is no per-throw plan data. False => neither => byte-identical to the pre-Rule-4
    # render. (The old phrase-throw `throws` field was removed with the cut-ratio model.)
    reverb_bed: bool = False


class StemMove(BaseModel):
    """One auto-performed 'mixing board' move (Step 3): ride ONE of Song 1's bed stems'
    volume from gain_from to gain_to across an on-beat window [start, end], then it
    returns to 1.0 everywhere outside the window. A beat move isn't tied to a vocal
    entry, so it lives at the MixPlan top level.

    One primitive expresses every DJ move in this step: bass pull (1.0→0.0), hold-muted
    (0.0→0.0), duck (1.0→0.4), rebuild (0.0→1.0). Boosting a stem above 1.0 is out of
    scope in v1 — moves only duck/mute and return, which keeps clip-safety trivial (the
    master can never be pushed into clipping by a move). Wave 1 uses only the bass pull.
    """

    stem: str  # which Song-1 bed stem: "drums" | "bass" | "other"
    start: float  # secs into Song 1, on a downbeat
    end: float  # secs into Song 1, on a downbeat; start < end
    gain_from: float = 1.0  # linear gain at start …
    gain_to: float = 0.0  # … ramping to this at end (the stem is at 1.0 outside the window)


class CamelotFit(BaseModel):
    """Informational key-compatibility read for a pair (Phase 0: attached to the plan and
    LOGGED, never gated — we want to see how many 'good' pairs were quietly key-clashing).
    `compatible` is None when either song's key is unknown."""

    song1_camelot: str | None = None
    song2_camelot: str | None = None
    compatible: bool | None = None


class VocalChainConfig(BaseModel):
    """Global defaults for the nine-stage vocal processing chain (Phase 0). Ships OFF
    (`enabled=False`) — every stage independently toggleable, every dial bounded. The hard
    caps noted here are ENFORCED by the referee (validate.py rules P1–P5), not just documented.
    Lives here (not in the dangerous `config.py`) on purpose."""

    enabled: bool = False  # ships off; the tuning week flips this behind founder approval

    deess_enabled: bool = True
    deess_intensity: float = 0.4  # 0..1

    highpass_enabled: bool = True
    highpass_hz: int = 90  # 80..120

    pitch_enabled: bool = True
    # Slice 2d GATE — when True (and pitch_enabled), the planner COMPUTES the key-correction shift and
    # emits it as a real pitch_semitones (a clash beyond the cap DECLINES). OFF by default: pitch stays
    # 0 and nothing pitch-corrects — the founder flips this on after the sandbox ear-test, like `enabled`.
    pitch_repair_enabled: bool = False
    pitch_max_semitones: float = 3.0  # hard cap; rubberband present + formant=preserved (Phase-0 check)
    pitch_engine: Literal["rubberband", "librosa"] = "rubberband"

    compress_enabled: bool = True
    compress_ratio: float = 3.0
    compress_threshold_db: float = -18.0

    saturate_enabled: bool = True
    saturate_drive: float = 2.0  # tanh input gain
    saturate_wet: float = 0.25  # 🔒 hard-capped at 0.5 (referee P3)

    presence_enabled: bool = True
    presence_hz: int = 3000
    presence_gain_db: float = 2.5  # 🔒 hard-capped at 6.0 (referee P3)
    presence_q: float = 0.8

    reverb_enabled: bool = True
    reverb_wet: float = 0.12

    duck_enabled: bool = True
    duck_depth_db: float = 1.5  # bed reduction under the vocal; 1..2 typical, cap 6 (referee P4)
    duck_attack_ms: int = 5
    duck_release_ms: int = 120


def chain_config_hash(cfg: VocalChainConfig) -> str:
    """A short, stable hash of the vocal-chain config. Folded into the mix cache id so that a
    tuning-week dial change produces a FRESH render instead of serving a stale cached one (a
    day-of-debugging-a-non-bug trap). Default config → a fixed hash, so a no-op config never
    churns the cache."""
    return hashlib.sha256(cfg.model_dump_json().encode()).hexdigest()[:16]


class VocalProcessMove(BaseModel):
    """A written vocal-processing instruction on the timeline — the renderer OBEYS it, it does
    not decide (Phase 0 G5). This is the `StemMove` pattern extended to vocal DSP: each dial is
    anchored to a bar range, so the same instruction a batch renderer runs today a live engine can
    edit tomorrow (a "more grit" command becomes: raise `saturate_wet` on the moves ahead of the
    playhead). Empty defaults ⇒ a no-op move (the stage does nothing)."""

    placement_id: str  # which vocal placement this applies to
    start_bar: int  # anchored to Song 1's grid, like StemMove
    end_bar: int

    pitch_semitones: float = 0.0
    deess: float = 0.0
    highpass_hz: int = 0
    compress_ratio: float = 1.0
    saturate_wet: float = 0.0
    presence_gain_db: float = 0.0
    reverb_wet: float = 0.0

    # WHY the dial was set — arithmetic (Phase 0), energy-curve (Phase 3), or genre recipe. Not
    # decoration: cross-adaptive processing later keys off this to know a value's source.
    reason: str = ""  # e.g. "key_correction: 8A->9A"


class DuckMove(BaseModel):
    """Stage 9 — a BED-side instruction, keyed by the placed vocal (NOT a vocal stage). The bed
    stems duck under the vocal's presence; runs at mix time, after placement, using the placed
    vocal as the sidechain key. Only ducks (never boosts) — mirrors the StemMove no-boost rule, so
    it can never push the master toward clipping (referee P4)."""

    target_stems: list[str] = ["drums", "bass", "other"]
    key_placement_id: str
    depth_db: float
    attack_ms: int
    release_ms: int


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
    bed_stretch: float = 1.0  # movable master: ratio Song 1's whole bed is stretched by (1.0 = native)
    vocal_src: tuple[float, float]  # [start, end] secs of Song 2's vocal to use
    anchor: float  # secs into Song 1 where the vocal enters (a phrase-start downbeat)
    beat_breath: bool = False  # drop Song 1's beat for one bar just before the vocal
    placements: list[Placement] = []  # the full arrangement; [] => single-placement (M3)
    s1_vocal_regions: list[tuple[float, float]] = []  # spans where Song 1's OWN vocal answers (contrast)
    stem_moves: list[StemMove] = []  # Step 3: auto-performed beat moves (bass pull, etc.); [] => today's flat bed
    rule: int = 1  # which mixing RULE made this: 1 = simple mix (default), 3 = chop & repeat, 4 = echo+reverb
    take: int = 1  # which regenerate iteration produced this (1-based)
    notes: str = ""  # DJ-language explanation of the move
    confidence: float = 0.0
    source: str = "rules"  # "ai" | "rules" — which brain picked it (honesty/debug)
    window: tuple[float, float] | None = None  # good-parts: Song-1 retimed-grid span the bed is cropped to; None = full track
    camelot_fit: CamelotFit | None = None  # Phase 0: informational key-fit (logged, never gates the mix)
    chain_config_hash: str = ""  # Phase 0: the vocal-chain config this mix was rendered under (cache + reproducibility)
    vocal_moves: list[VocalProcessMove] = []  # Phase 0 G5: vocal-processing instructions; [] = today's plain vocal
    duck_moves: list[DuckMove] = []  # Phase 0 stage 9: bed ducks under the vocal; [] = no ducking (today)
    # Effect pool (2026-08-05): a plain-language record of which pool effects this take selected
    # (e.g. ["space:hall", "width:double"]), so a take the founder likes tells him what produced
    # it. effect_variety records whether the pool ran (False => the fixed pre-pool treatment).
    effects_selected: list[str] = []
    effect_variety: bool = True
    # Set transitions (3.1): the rendered mix's OWN beat grid in OUTPUT seconds + its length, written
    # next to the WAV so joining mixes into a continuous set (set_render) is ARITHMETIC over the plans —
    # never a re-analysis of the output audio ("the pipeline must not listen to itself"). Derived at
    # render time from Song 1's cached grid + master_bpm + window (window.output_grid), the SAME grid
    # the referee judges against. Empty/None on pre-3.1 cached plans (they simply carry no set-grid).
    out_downbeats: list[float] = []       # bar starts ("the one") in the mix's output timeline
    out_phrase_starts: list[float] = []   # 8-bar phrase boundaries in the mix's output timeline
    mix_duration: float | None = None     # the rendered mix's length in seconds


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
    target: str | None = None  # single bus (Slice 1 back-compat); mirrors targets[0] when one part
    targets: list[str] = []  # the buses this op affects — may be several ("drop everything but the beat")
    when: str = "next_bar"
    say: str = ""  # DJ-language reply shown to the user
    reason: str | None = None  # why a command was declined (out of scope)


class LiveChip(BaseModel):
    """One tappable live suggestion: display text + the move it applies (from the closed
    vocabulary). op is "mute" | "unmute" | "fade"; targets are bus names."""

    text: str
    op: str
    targets: list[str] = []


class SectionSuggestions(BaseModel):
    """The 1-3 suggested moves for one section of Song 1's timeline."""

    start: float
    end: float
    label: str
    chips: list[LiveChip] = []
