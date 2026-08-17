"""The paid calls must be able to send a song. A 5-second default cannot.

THE INCIDENT, 2026-08-18. The first two real uploads ever attempted both failed with "The read
operation timed out" — the founder's own, and a catalogue re-ingest an hour before it. It looked
like a network fault and was not: Replicate's account endpoint answered in 0.8 s on the same
machine with the same token.

`replicate.run(...)` on the module builds a client with `timeout=None` and hands that to httpx,
whose default is **5 seconds for every operation, the upload included**. A normalised song is a
45-85 MB WAV, so finishing that upload inside five seconds needs 10-17 MB/s upstream. The call was
being cut off mid-send on any song of ordinary length — the feature could not have worked for
anybody.

These tests fail if the default ever comes back.
"""

from __future__ import annotations

import inspect

import httpx

from app.audio import analysis, replicate_client, stems


def test_the_client_can_survive_sending_a_whole_song():
    c = replicate_client.client()
    t = c._client.timeout
    assert isinstance(t, httpx.Timeout)
    assert (t.write or 0) >= 300, f"write timeout {t.write}s cannot upload a 50 MB song"
    assert (t.read or 0) >= 300, f"read timeout {t.read}s cannot wait for a GPU model"
    assert (t.connect or 0) >= 10


def test_it_is_not_httpxs_default():
    """The bug was a default nobody chose. Naming it here so a future 'simplification' back to
    `replicate.run` is caught rather than shipped."""
    assert replicate_client.client()._client.timeout != httpx.Timeout(5.0)


def test_both_paid_calls_go_through_that_client():
    """There are exactly two calls that cost money. Neither may use the bare module again."""
    for mod, fn in ((stems, stems.separate_stems), (analysis, analysis._cloud_structure)):
        src = inspect.getsource(fn)
        assert "replicate_client.run(" in src, f"{mod.__name__} does not use the shared client"
        assert "replicate.run(" not in src, f"{mod.__name__} still calls the bare module"
