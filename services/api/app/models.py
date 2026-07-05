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
