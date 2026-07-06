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
