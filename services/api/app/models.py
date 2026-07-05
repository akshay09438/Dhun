from pydantic import BaseModel


class Song(BaseModel):
    """A processed song the client can play back."""

    id: str
    original_name: str
    url: str
    status: str = "ready"


class StemSet(BaseModel):
    """The separated parts of one song, each a playable URL.

    stems maps a part name (vocals/drums/bass/other) to the URL that serves it.
    """

    song_id: str
    stems: dict[str, str]
