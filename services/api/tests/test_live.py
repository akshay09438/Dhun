from app.planner.live import parse_command


def test_take_the_bass_out_mutes_bass():
    op = parse_command("take the bass out")
    assert op.op == "mute" and op.target == "bass" and op.when == "next_bar"
    assert "bass" in op.say.lower()


def test_drop_the_bass_is_also_a_mute():
    assert parse_command("drop the bass").op == "mute"


def test_bring_it_back_unmutes():
    op = parse_command("bring it back")
    assert op.op == "unmute" and op.target == "bass"


def test_out_of_scope_is_declined_plainly():
    op = parse_command("add a third song")
    assert op.op == "decline" and op.target is None
    assert op.say  # a plain-language message pointing at what V1 can do


def test_empty_command_declines():
    assert parse_command("   ").op == "decline"


def test_remove_the_vocals_mutes_vocals():
    op = parse_command("remove the vocals")
    assert op.op == "mute" and op.targets == ["vocals"]


def test_bring_the_vocals_back_unmutes_vocals():
    op = parse_command("bring the vocals back")
    assert op.op == "unmute" and op.targets == ["vocals"]


def test_drop_everything_but_the_beat_mutes_all_but_drums():
    op = parse_command("drop everything but the beat")
    assert op.op == "mute" and set(op.targets) == {"bass", "other", "vocals"}
    assert "drums" not in op.targets


def test_bring_it_all_back_unmutes_everything():
    op = parse_command("bring it all back")
    assert op.op == "unmute" and set(op.targets) == {"drums", "bass", "other", "vocals"}


def test_take_the_melody_out_mutes_other():
    op = parse_command("take the melody out")
    assert op.op == "mute" and op.targets == ["other"]


def test_bass_command_still_sets_both_target_and_targets():
    op = parse_command("take the bass out")
    assert op.op == "mute" and op.target == "bass" and op.targets == ["bass"]
