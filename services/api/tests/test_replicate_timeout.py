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


# ==================================================================================================
# WAITING YOUR TURN, rather than calling it a failure.
#
# THE INCIDENT, 2026-08-18 15:23. The founder uploaded a song through the new `/grind my_song:` and
# got back: "ReplicateError Details: status: 429 detail: Request was throttled. Your rate limit for
# creating predictions is reduced to 6 requests per minute with a burst of 1 requests while you
# have less than $5.0".
#
# NOT AN OUTAGE, AND NOT AN EMPTY ACCOUNT. Measured against Replicate's own API afterwards: the
# token is valid, and the last 100 predictions on the account ALL SUCCEEDED - seven of them that
# same afternoon. Below $5 Replicate does not refuse work, it RATIONS it: one prediction at a time.
# An upload needs two (separate the stems, then read the structure), so an upload that arrives
# while another is still running is refused at the door.
#
# A REFUSAL AT THE DOOR CREATES NO PREDICTION, which is why the failure left no trace on Replicate's
# side at all and why the app was the only place it was visible. It also means retrying is FREE:
# nothing was started, so nothing was charged.
#
# THE BUG IS THAT THE APP GAVE UP INSTANTLY. There was no retry anywhere in the three modules that
# talk to Replicate. "You are in a queue" was rendered to a person as "That did not come out".
# ==================================================================================================

class _Throttled(Exception):
    """What the replicate library raises when the account is being rationed."""

    def __init__(self):
        super().__init__(
            "ReplicateError Details:\nstatus: 429\ndetail: Request was throttled. Your rate limit "
            "for creating predictions is reduced to 6 requests per minute with a burst of 1 "
            "requests while you have less than $5.0")
        self.status = 429


class _RealFailure(Exception):
    """Anything else - the model fell over, the audio was rejected, the upload broke."""


def test_a_throttle_is_recognised():
    assert replicate_client.is_throttled(_Throttled()) is True


def test_a_real_failure_is_not_mistaken_for_a_throttle():
    """THE DANGEROUS DIRECTION. A throttle created no prediction, so retrying is free. Any OTHER
    error may have started work that is already being charged for, and retrying it would pay
    twice."""
    assert replicate_client.is_throttled(_RealFailure("the model crashed")) is False


def test_a_plain_429_with_no_message_still_counts():
    class _Bare(Exception):
        status = 429
    assert replicate_client.is_throttled(_Bare()) is True


def test_a_throttled_call_waits_and_succeeds(monkeypatch):
    """The founder's exact case: refused once, fine a moment later."""
    slept = []
    monkeypatch.setattr(replicate_client.time, "sleep", slept.append)
    calls = []

    class _Client:
        def run(self, ref, **kw):
            calls.append(ref)
            if len(calls) == 1:
                raise _Throttled()
            return "the output"

    monkeypatch.setattr(replicate_client, "client", lambda: _Client())
    assert replicate_client.run("some/model", input={}) == "the output"
    assert len(calls) == 2, "it did not try again"
    assert slept and slept[0] > 0, "it retried instantly, which is what got it refused"


def test_a_real_failure_is_never_retried(monkeypatch):
    """Retrying a call that already started work is how one upload becomes two bills."""
    monkeypatch.setattr(replicate_client.time, "sleep", lambda _s: None)
    calls = []

    class _Client:
        def run(self, ref, **kw):
            calls.append(ref)
            raise _RealFailure("the model crashed")

    monkeypatch.setattr(replicate_client, "client", lambda: _Client())
    try:
        replicate_client.run("some/model", input={})
    except _RealFailure:
        pass
    assert len(calls) == 1, f"a real failure was retried {len(calls)} times - that pays twice"


def test_it_gives_up_eventually_and_says_what_happened(monkeypatch):
    """Waiting forever is its own bug: the person is watching a card, and the bot's own poll gives
    up at 900s."""
    monkeypatch.setattr(replicate_client.time, "sleep", lambda _s: None)
    calls = []

    class _Client:
        def run(self, ref, **kw):
            calls.append(ref)
            raise _Throttled()

    monkeypatch.setattr(replicate_client, "client", lambda: _Client())
    try:
        replicate_client.run("some/model", input={})
        raise AssertionError("it should have given up and raised")
    except _Throttled:
        pass
    assert 1 < len(calls) <= 6, f"tried {len(calls)} times - too few to help, or too many to wait for"


def test_the_total_wait_is_bounded(monkeypatch):
    """The bot stops polling at 900 seconds. A retry ladder longer than that hands somebody a
    'took longer than expected' card instead of their song."""
    slept = []
    monkeypatch.setattr(replicate_client.time, "sleep", slept.append)

    class _Client:
        def run(self, ref, **kw):
            raise _Throttled()

    monkeypatch.setattr(replicate_client, "client", lambda: _Client())
    try:
        replicate_client.run("some/model", input={})
    except _Throttled:
        pass
    assert sum(slept) <= 120, f"it would wait {sum(slept)}s before admitting defeat"


def test_both_paid_calls_go_through_the_retrying_wrapper():
    """The retry is worth nothing if a call reaches the bare module instead. Same guard as the
    timeout above, stated for the retry."""
    for mod in (stems, analysis):
        src = inspect.getsource(mod)
        assert "replicate.run(" not in src, (
            f"{mod.__name__} calls replicate.run directly and would skip both the timeout and the "
            "retry")
