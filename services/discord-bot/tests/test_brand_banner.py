"""The bot's PROFILE banner — the strip behind its picture on the profile card.

This is a different Discord setting from the SERVER banner (`brand.BANNER`), which is locked behind
boost level 2. Confusing the two is the whole reason the profile sat flat purple for so long, so
these tests pin the distinction as much as the mechanics.
"""
import struct

import brand


def _jpeg_size(path):
    """Width/height from a JPEG's SOF marker — avoids a Pillow dependency in the test run."""
    data = path.read_bytes()
    i = 2
    while i < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    raise AssertionError("no JPEG frame header found")


def test_the_profile_banner_ships_and_is_a_separate_file_from_the_server_banner():
    assert brand.REMIX_BANNER.exists(), "the profile banner art must ship with the bot"
    assert brand.REMIX_BANNER != brand.BANNER, (
        "the profile banner and the SERVER banner are different Discord settings — the server one "
        "needs boost level 2, this one does not"
    )
    assert brand.image_bytes(brand.REMIX_BANNER) is not None


def test_the_profile_banner_matches_the_shape_discord_renders():
    """680x240 is the slot. Anything else and Discord centre-crops, which buried the tagline behind
    the avatar in every earlier attempt."""
    w, h = _jpeg_size(brand.REMIX_BANNER)
    assert abs(w / h - 680 / 240) < 0.01, f"{w}x{h} is not the 680:240 profile-banner shape"
    assert w >= 1360, "ship at 2x so it stays sharp on a high-DPI screen"


def test_the_profile_banner_stays_small_enough_to_be_worth_committing():
    """It is JPEG rather than PNG on purpose — the grain makes PNG ~14x bigger for no visible gain.
    A regression here means someone re-exported it as PNG."""
    kb = brand.REMIX_BANNER.stat().st_size / 1024
    assert kb < 400, f"{kb:.0f} KB — too big; export as JPEG, not PNG"


def test_art_is_only_re_uploaded_when_it_actually_changes(tmp_path, monkeypatch):
    """Discord rate-limits avatar and banner edits on one shared budget, so an unchanged file must
    not be re-sent on every restart."""
    art = tmp_path / "some-art.jpg"
    art.write_bytes(b"pretend-image-bytes")
    monkeypatch.setattr(brand, "ASSETS", tmp_path)
    brand._cache.pop(art, None)

    assert brand.art_needs_upload(art) is True, "never uploaded from this checkout -> send it"
    brand.mark_art_applied(art)
    assert brand.art_needs_upload(art) is False, "unchanged art must not be re-uploaded"

    art.write_bytes(b"a-new-export-from-the-founder")
    brand._cache.pop(art, None)
    assert brand.art_needs_upload(art) is True, "new art must apply itself on the next start"


def test_a_missing_file_is_skipped_rather_than_crashing(tmp_path, monkeypatch):
    """Branding is cosmetic. A missing asset must never stop the bot from making mixes."""
    monkeypatch.setattr(brand, "ASSETS", tmp_path)
    gone = tmp_path / "not-here.jpg"
    assert brand.art_fingerprint(gone) is None
    assert brand.art_needs_upload(gone) is False, "nothing to upload is not 'needs upload'"


class _FakeUser:
    """Mirrors only what `_apply_profile_banner` touches. `banner=None` is how discord.py reports
    'no banner set', which is exactly the state the profile was in before this shipped."""

    def __init__(self, banner=None, raises=None):
        self.banner = banner
        self.raises = raises
        self.edits: list[bytes] = []

    async def edit(self, **kwargs):
        if self.raises is not None:
            raise self.raises
        self.edits.append(kwargs["banner"])
        self.banner = "set"


def _apply(user):
    """Call the startup step directly — it never touches `self`, so no gateway is needed."""
    import asyncio

    import bot as botmod
    return asyncio.run(botmod.PromptDJBot._apply_profile_banner(None, user))


def _use_temp_art(tmp_path, monkeypatch, data=b"art"):
    art = tmp_path / "remix-banner.jpg"
    art.write_bytes(data)
    monkeypatch.setattr(brand, "ASSETS", tmp_path)
    monkeypatch.setattr(brand, "REMIX_BANNER", art)
    brand._cache.pop(art, None)
    return art


def test_a_bot_with_no_banner_gets_one_on_startup(tmp_path, monkeypatch):
    _use_temp_art(tmp_path, monkeypatch)
    user = _FakeUser(banner=None)
    _apply(user)
    assert user.edits == [b"art"], "a profile with no banner must have one uploaded"


def test_an_unchanged_banner_is_not_re_uploaded_on_every_restart(tmp_path, monkeypatch):
    """on_ready fires again on every reconnect. Re-uploading each time would burn the rate limit
    the bot shares with its avatar."""
    art = _use_temp_art(tmp_path, monkeypatch)
    user = _FakeUser(banner=None)
    _apply(user)
    assert len(user.edits) == 1

    brand._cache.pop(art, None)
    _apply(user)          # same art, banner now set
    assert len(user.edits) == 1, "an unchanged banner must not be re-sent"


def test_new_artwork_applies_itself_on_the_next_start(tmp_path, monkeypatch):
    art = _use_temp_art(tmp_path, monkeypatch)
    user = _FakeUser(banner=None)
    _apply(user)

    art.write_bytes(b"a-new-export")
    brand._cache.pop(art, None)
    _apply(user)
    assert user.edits == [b"art", b"a-new-export"], "a re-export must reach Discord"


def test_discord_refusing_the_banner_never_stops_the_bot(tmp_path, monkeypatch):
    """Branding is cosmetic. If Discord rejects the upload, the bot must still come up and mix."""
    _use_temp_art(tmp_path, monkeypatch)
    user = _FakeUser(banner=None, raises=RuntimeError("400 Bad Request"))
    _apply(user)          # must not raise
    assert user.banner is None


def test_a_missing_banner_file_is_skipped_quietly(tmp_path, monkeypatch):
    monkeypatch.setattr(brand, "ASSETS", tmp_path)
    monkeypatch.setattr(brand, "REMIX_BANNER", tmp_path / "not-here.jpg")
    user = _FakeUser(banner=None)
    _apply(user)
    assert user.edits == [], "nothing to upload means no call to Discord"


def test_startup_actually_calls_the_banner_step(tmp_path, monkeypatch):
    """The tests above drive `_apply_profile_banner` directly, so every one of them would still
    pass if the call were dropped from `_apply_brand` and the banner silently stopped being set.
    This is the test that notices."""
    import asyncio

    import bot as botmod
    import ui

    _use_temp_art(tmp_path, monkeypatch)
    # `_use_temp_art` repoints brand.ASSETS at an empty tmp dir, which makes the avatar look
    # never-uploaded. Pin it to "up to date" so this test is about the banner step and nothing else.
    monkeypatch.setattr(brand, "avatar_needs_upload", lambda: False)

    class _AvatarUser(_FakeUser):
        avatar = "already-set"                       # so the avatar branch is a no-op
        display_avatar = type("A", (), {"url": "https://cdn.example/icon.png"})()

        async def edit(self, **kwargs):
            if "avatar" in kwargs:
                raise AssertionError("the avatar is already set; it must not be re-uploaded")
            return await super().edit(**kwargs)

    user = _AvatarUser(banner=None)
    # The real banner step, so this exercises the actual wiring rather than a stub of it.
    fake_self = type("S", (), {
        "user": user,
        "_apply_profile_banner": botmod.PromptDJBot._apply_profile_banner,
    })()
    try:
        asyncio.run(botmod.PromptDJBot._apply_brand(fake_self))
    finally:
        ui.set_avatar_url(None)                      # module-level state - don't leak

    assert user.edits == [b"art"], "startup branding must set the profile banner, not just the avatar"


def test_the_avatar_keeps_its_original_marker_file(tmp_path, monkeypatch):
    """The avatar's marker is `.applied-avatar`, not `.applied-icon`. Renaming it would read as
    'the art changed' on every existing install and burn a strict rate limit re-sending an
    identical avatar."""
    monkeypatch.setattr(brand, "ASSETS", tmp_path)
    brand.mark_avatar_applied()
    assert (tmp_path / ".applied-avatar").exists()
    assert not (tmp_path / ".applied-icon").exists()
