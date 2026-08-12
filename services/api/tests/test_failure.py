"""A failure has to say WHY, and it must not lie in the flattering direction.

The bug these pin down (docs/concurrency-diagnosis.md): a catalog sweep on a starved
machine reported 17 of 82 pairs "broken", and the same pairs passed 10/10 and 6/6 once
the host had room. Every one of those had reported the same sentence as a real quality
rejection, so the 20.7% was uncountable - nobody could say how much of it was the songs.
"""
from __future__ import annotations

import errno

import pytest

from app import failure


class _Declined(Exception):
    """Stands in for planner.MixDeclined - it carries its own plain-language reason."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class _Referee(Exception):
    """Stands in for validate.ValidationError / workers.render.RenderError."""


@pytest.fixture
def healthy(monkeypatch):
    monkeypatch.setattr(failure, "machine_state",
                        lambda data_dir=None: {"free_disk_gb": 40.0, "free_ram_gb": 8.0,
                                               "starved": False})


@pytest.fixture
def starved(monkeypatch):
    monkeypatch.setattr(failure, "machine_state",
                        lambda data_dir=None: {"free_disk_gb": 1.2, "free_ram_gb": 0.4,
                                               "starved": True})


def test_a_referee_verdict_is_NEVER_downgraded_to_a_resource_excuse(starved):
    """THE asymmetry. The referee reached this verdict by measuring audio it had actually
    produced; a busy host does not get to explain that away. If this ever flips, a real
    quality problem starts hiding behind 'the machine was busy' and never gets fixed."""
    f = failure.classify(_Referee("crest factor 10.76 -> 5.33"), quality=_Referee)
    assert f.kind == failure.QUALITY
    assert not f.is_resources


def test_an_unexplained_crash_on_a_starved_host_is_reported_as_resources(starved):
    """The other direction DOES escalate: a crash we cannot explain, on a host with no room
    left, is overwhelmingly the host. This is the 20.7% case."""
    f = failure.classify(RuntimeError("ffmpeg died"), quality=_Referee)
    assert f.kind == failure.RESOURCES
    assert f.is_resources


def test_the_same_unexplained_crash_on_a_healthy_host_is_a_bug(healthy):
    """Same exception, different host state, different verdict - which is the entire point."""
    f = failure.classify(RuntimeError("ffmpeg died"), quality=_Referee)
    assert f.kind == failure.BUG


def test_running_out_of_memory_is_resources_even_on_a_host_that_looks_fine(healthy):
    """MemoryError is proof in itself; it does not need the host snapshot to agree."""
    assert failure.classify(MemoryError()).kind == failure.RESOURCES


def test_a_full_disk_is_resources_even_on_a_host_that_looks_fine(healthy):
    exc = OSError(errno.ENOSPC, "No space left on device")
    assert failure.classify(exc).kind == failure.RESOURCES


def test_an_ordinary_os_error_is_not_mistaken_for_a_full_disk(healthy):
    """Only ENOSPC means out of space. A missing file is a bug, not a disk excuse."""
    exc = OSError(errno.ENOENT, "No such file or directory")
    assert failure.classify(exc).kind == failure.BUG


def test_a_decline_keeps_the_planners_own_words(healthy):
    """The planner already explains itself in plain language ('no steady beat to lock to').
    Replacing that with a generic sentence would be a downgrade for the user."""
    f = failure.classify(_Declined("This song has no steady beat to lock to."),
                         declined=_Declined)
    assert f.kind == failure.DECLINED
    assert f.user_message == "This song has no steady beat to lock to."


def test_the_resource_message_never_tells_the_user_to_change_their_songs(starved):
    """The founder's decision, 2026-08-11. 'Try another pair' for a host problem sends people
    off changing their song choice to fix something that was never theirs."""
    msg = failure.classify(RuntimeError("boom")).user_message.lower()
    assert "another pair" not in msg
    assert "your songs" in msg or "room" in msg


def test_every_failure_records_what_the_host_actually_had(starved):
    """So a wrong guess here is always visible in the data, never baked in."""
    f = failure.classify(RuntimeError("boom"))
    assert f.machine["free_disk_gb"] == 1.2
    assert f.machine["starved"] is True


def test_the_detail_keeps_the_engines_own_words_for_the_dashboard(healthy):
    f = failure.classify(_Referee("crest factor 10.76 -> 5.33"), quality=_Referee)
    assert "crest factor 10.76 -> 5.33" in f.detail
    assert "_Referee" in f.detail


def test_machine_state_reads_real_disk_and_never_raises(tmp_path):
    """Unpatched, against a real path. An unknown must not read as starved - inventing a
    resource excuse from missing information is exactly the failure mode to avoid."""
    state = failure.machine_state(tmp_path)
    assert state["free_disk_gb"] is not None and state["free_disk_gb"] > 0
    assert isinstance(state["starved"], bool)


def test_machine_state_survives_a_path_it_cannot_stat():
    state = failure.machine_state("Q:/nope/not/a/real/path")
    assert state["free_disk_gb"] is None
    assert state["starved"] is False       # unknown is NOT starved


def test_the_four_kinds_are_a_stable_contract():
    """These strings land in events.db. Renaming one silently splits historical counts."""
    assert failure.ALL_KINDS == ("declined", "quality", "resources", "bug")
