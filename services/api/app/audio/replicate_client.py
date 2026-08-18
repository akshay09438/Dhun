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
import time

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


# Waiting your turn. Below $5 of credit Replicate rations an account to ONE prediction at a time
# ("6 requests per minute with a burst of 1"), and an upload needs two - so a second upload landing
# while the first is mid-flight is refused at the door. The founder hit exactly that on 2026-08-18.
#
# THE LADDER IS SHORT ON PURPOSE. The bot stops polling at 900s and a person is watching a card, so
# admitting defeat beats waiting forever. 12s, 24s, 36s: the throttle window is a minute, so a
# single wait usually clears it, and the whole ladder costs at most 72s.
_THROTTLE_TRIES = 4
_THROTTLE_WAIT_S = 12.0


def is_throttled(exc: BaseException) -> bool:
    """Was this refused AT THE DOOR, before any work started?

    THE ANSWER DECIDES WHETHER RETRYING IS FREE OR EXPENSIVE, which is why it is narrow. A throttle
    creates no prediction, so trying again costs nothing. Every other error may have started work
    that is already being charged for, and retrying THAT pays twice for one upload - so anything
    not clearly a throttle is treated as a real failure.
    """
    if getattr(exc, "status", None) == 429:
        return True
    text = str(exc).lower()
    return "status: 429" in text or "throttled" in text or "rate limit" in text


def run(model_ref: str, **kwargs):
    """`replicate.run`, on the client that can survive sending a song, and patient about queues.

    A refusal at the door is not a failure, it is a "not yet" - and rendering it to somebody as
    "That did not come out" is what this fixes. Nothing else is retried.
    """
    # `wait=False` IS LOAD-BEARING, AND IT IS THE 60-SECOND WALL.
    #
    # `replicate.run()` defaults to `wait=True`, and the library then throws away the timeout this
    # module so carefully sets:
    #
    #     read_timeout = 60.0 if isinstance(wait, bool) else wait
    #     return httpx.Timeout(5.0, read=read_timeout + 0.5)
    #
    # connect 30s / transfer 600s becomes connect 5s / read 60.5s for the request that starts a
    # job - so ANY job Replicate does not finish inside about a minute dies with "The read
    # operation timed out", which is what a person then sees on their card.
    #
    # MEASURED 2026-08-18, and the correlation is total: every analysis that finished under 60s
    # succeeded (53s, 58s, 58s, and a 47s probe); the one that took 124s failed 65 seconds in -
    # 60.5 plus the handshake. It was never the balance and never random. It is SONG LENGTH: a
    # short song analyses in under a minute, a real one does not. The 2026-08-18 timeout fix was
    # correct and was being silently overridden on exactly the call that mattered.
    #
    # With no blocking header the library leaves our client alone and polls instead, so a job may
    # take as long as it takes.
    kwargs.setdefault("wait", False)
    for attempt in range(1, _THROTTLE_TRIES + 1):
        try:
            return client().run(model_ref, **kwargs)
        except Exception as e:  # noqa: BLE001 — re-raised unless it is a throttle we can wait out
            if attempt == _THROTTLE_TRIES or not is_throttled(e):
                raise
            wait = _THROTTLE_WAIT_S * attempt
            log.warning("replicate rationed us (attempt %d of %d); waiting %.0fs and trying again. "
                        "This is what a balance under $5 looks like, not an outage.",
                        attempt, _THROTTLE_TRIES, wait)
            time.sleep(wait)
