"""One Replicate client, with a timeout long enough to actually send a song.

WHY THIS EXISTS. The first two real uploads both died with "The read operation timed out" — the
founder's, and a catalogue re-ingest an hour earlier. Neither was a network fault: a plain call to
Replicate's account endpoint answers in 0.8 s and the token is fine.

The cause is a default nobody set. `replicate.run(...)` on the module builds a client with
`timeout=None`, and the client hands that straight to httpx — whose own default is **5 seconds for
every operation, including the upload**. A normalised song is a 45–85 MB WAV, so sending one inside
five seconds needs 10–17 MB/s upstream. Almost nobody has that. The call was being cut off
mid-upload, every time, on any song of ordinary length.

So the timeout is set here, once, and both paid calls use this client. The numbers:

  connect  30 s   — reaching the API at all; if this is slow, something else is wrong
  write   600 s   — sending the audio. This is the one that was breaking, at 5 s.
  read    600 s   — waiting for the model. Separation is minutes of GPU time by nature.
  pool     30 s   — waiting for a free connection

Long, deliberately. A slow upload that finishes is a song; a fast failure is 12 cents and a person
told their track "did not come out". The stuck-forever case is handled elsewhere and differently:
the stem download has its own 180 s cap, and a hung ingest holds a slot rather than hanging a user.
"""

from __future__ import annotations

import logging
import os

import httpx
import replicate

log = logging.getLogger("promptdj.replicate")

_CONNECT_S = 30.0
_TRANSFER_S = 600.0

_client: replicate.Client | None = None


def client() -> replicate.Client:
    """The shared client. Built once, lazily, so importing this module never needs a token."""
    global _client
    if _client is None:
        _client = replicate.Client(
            api_token=os.environ.get("REPLICATE_API_TOKEN"),
            timeout=httpx.Timeout(_TRANSFER_S, connect=_CONNECT_S, pool=_CONNECT_S),
        )
        log.info("replicate client: connect %.0fs, transfer %.0fs (httpx's own default is 5s, "
                 "which cannot upload a 50 MB song)", _CONNECT_S, _TRANSFER_S)
    return _client


def run(model_ref: str, **kwargs):
    """`replicate.run`, but on the client that can survive sending a song."""
    return client().run(model_ref, **kwargs)
