"""Tests for the mix route: the async contract, caching, preconditions, and a real
end-to-end render on synthetic songs (no cloud, no AI network — the deterministic
fallback picks the drop).
"""

import dataclasses
import json
import time

import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient

from app import storage
from app.audio import analysis as analysis_mod
from app.audio import pitch
from app.audio import stems as stems_mod
from app.main import app
from app.planner import plan as plan_mod
from app.routes import mix as mix_route
from tests.test_fence import make_analysis

client = TestClient(app)

SONG1 = "a" * 64
SONG2 = "b" * 64


def _use_tmp(monkeypatch, tmp_path):
    for mod in (storage, analysis_mod, stems_mod, mix_route):
        monkeypatch.setattr(mod, "settings",
                            dataclasses.replace(mod.settings, data_dir=tmp_path))
    monkeypatch.setattr(mix_route, "_jobs", {})
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(plan_mod, "_ai_arrange", lambda opts, prompt, take: None)  # force fallback


def _tone(path, freq, secs=6.0, sr=44100):
    t = np.linspace(0, secs, int(sr * secs), endpoint=False)
    sf.write(path, (0.4 * np.sin(2 * np.pi * freq * t)).astype("float32"), sr, format="WAV")


def _write_analysis(tmp_path, sid, bpm, vocal_regions):
    d = make_analysis(bpm=bpm, vocal_regions=vocal_regions).model_dump(exclude={"status"})
    d["song_id"] = sid
    (tmp_path / f"{sid}.analysis.json").write_text(json.dumps(d))


def _setup_pair(tmp_path, song2_bpm=118.0):
    # uploaded songs
    _tone(tmp_path / f"{SONG1}.wav", 200.0)
    _tone(tmp_path / f"{SONG2}.wav", 300.0)
    # analyses (Song 1 sings a substantial passage 20-62s so it LEADS in a gap — both vocals trade)
    _write_analysis(tmp_path, SONG1, 120.0, [(20.0, 62.0)])
    _write_analysis(tmp_path, SONG2, song2_bpm, [(0.0, 4.0)])
    # stems (WAV content in .mp3-named files, as the real cache stores)
    for name, f in (("drums", 110.0), ("bass", 55.0), ("other", 330.0), ("vocals", 660.0)):
        _tone(tmp_path / f"{SONG1}.{name}.mp3", f)  # Song 1's own vocals feed the contrast move
    _tone(tmp_path / f"{SONG2}.vocals.mp3", 440.0)


def _poll(mix_id, want, tries=240):
    body = {}
    for _ in range(tries):
        body = client.get(f"/mix/{mix_id}").json()
        if body["status"] == want:
            return body
        time.sleep(0.05)
    return body


def test_mix_is_async_then_ready_and_plays(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    _setup_pair(tmp_path)

    r = client.post("/mix", json={"song1_id": SONG1, "song2_id": SONG2})
    assert r.status_code == 202
    assert r.json()["status"] == "processing"  # returned at once, not blocked

    mix_id = r.json()["mix_id"]
    ready = _poll(mix_id, "ready")
    assert ready["status"] == "ready"
    assert ready["plan"]["source"] == "rules"
    assert ready["url"] == f"/mix/{mix_id}/audio"

    audio = client.get(ready["url"])
    assert audio.status_code == 200
    assert audio.headers["content-type"] == "audio/wav"
    assert len(audio.content) > 1000  # a real WAV, not empty

    # 3.1 (set transitions): the persisted plan carries the mix's OWN beat grid + length, so a set-join
    # is arithmetic over the plans (no re-analysis of the WAV).
    plan = ready["plan"]
    assert plan["out_downbeats"], "the mix's output-time downbeats must be persisted on the plan"
    assert plan["mix_duration"] and plan["mix_duration"] > 0
    assert plan["out_downbeats"][0] >= 0.0
    assert set(plan["out_phrase_starts"]) <= set(plan["out_downbeats"])  # phrase boundaries are downbeats


def test_mix_serves_best_parts_highlight_keeping_full_render(tmp_path, monkeypatch):
    """Best-parts is the default output: the audio endpoint serves the ~180s highlight derivative, while
    the FULL render stays on disk as the canonical source for Regenerate + set-joining."""
    _use_tmp(monkeypatch, tmp_path)
    _setup_pair(tmp_path)

    r = client.post("/mix", json={"song1_id": SONG1, "song2_id": SONG2})
    mix_id = r.json()["mix_id"]
    _poll(mix_id, "ready")

    full = mix_route._mix_wav(mix_id)
    highlight = mix_route._bestparts_wav(mix_id)
    assert full.exists(), "the FULL render must stay on disk (canonical for Regenerate + set-joining)"
    assert highlight.exists(), "the best-parts highlight is built by default"

    audio = client.get(f"/mix/{mix_id}/audio")
    assert audio.status_code == 200
    assert audio.content == highlight.read_bytes(), "the endpoint serves the best-parts highlight, not the full render"


def test_mix_is_cached(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    _setup_pair(tmp_path)
    mix_id = mix_route.mix_id_for(SONG1, SONG2, "")
    r1 = client.post("/mix", json={"song1_id": SONG1, "song2_id": SONG2})
    _poll(mix_id, "ready")

    # second identical request must be an instant cache hit (200, ready)
    r2 = client.post("/mix", json={"song1_id": SONG1, "song2_id": SONG2})
    assert r2.status_code == 200
    assert r2.json()["status"] == "ready"


def test_mix_blocks_when_not_analyzed(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    _tone(tmp_path / f"{SONG1}.wav", 200.0)
    _tone(tmp_path / f"{SONG2}.wav", 300.0)  # uploaded but not analyzed/split

    r = client.post("/mix", json={"song1_id": SONG1, "song2_id": SONG2})
    assert r.status_code == 409
    assert "analyzed" in r.json()["detail"].lower()


def test_mix_far_tempo_forces_instead_of_declining(tmp_path, monkeypatch):
    # Founder rule 2026-08-07: a far-apart pair (this used to error with a tempo reason) now FORCES a
    # full match and produces a mix — never declined for tempo.
    _use_tmp(monkeypatch, tmp_path)
    _setup_pair(tmp_path, song2_bpm=158.0)

    r = client.post("/mix", json={"song1_id": SONG1, "song2_id": SONG2})
    assert r.status_code == 202
    body = _poll(r.json()["mix_id"], "ready")
    assert body["status"] == "ready", body.get("message")
    assert body["plan"]["tempo_forced"] is True


def test_mix_carries_contrast(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    _setup_pair(tmp_path)
    r = client.post("/mix", json={"song1_id": SONG1, "song2_id": SONG2})
    body = _poll(r.json()["mix_id"], "ready")
    assert body["status"] == "ready"
    assert body["plan"]["s1_vocal_regions"]  # Song 1's own vocal answers (contrast) flows through


def test_regenerate_is_a_distinct_cached_take(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    _setup_pair(tmp_path)
    r1 = client.post("/mix", json={"song1_id": SONG1, "song2_id": SONG2, "take": 1})
    r2 = client.post("/mix", json={"song1_id": SONG1, "song2_id": SONG2, "take": 2})
    assert r1.json()["mix_id"] != r2.json()["mix_id"]  # different take -> different cache slot


def test_mix_rejects_bad_song_id(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    assert client.post("/mix", json={"song1_id": "nothex", "song2_id": SONG2}).status_code == 404
    assert client.get("/mix/deadbeef").status_code == 404
    assert client.get("/mix/" + "a" * 64 + "/audio").status_code == 404


def test_engine_version_is_current():
    # bumped when the engine/plan changes so a stale cached mix is never served
    # base is m12match (empirical chroma key-match fallback when labels are untrusted); tags ride along
    assert mix_route.ENGINE_VERSION.startswith("m12match")


def test_shipped_chain_is_enabled_with_the_founder_approved_dials():
    """Guards the product's shipped SOUND. The vocal chain is turned on in the shipped pipeline via
    SHIPPED_CHAIN (routes/mix.py). If it silently reverted to enabled=False, or a dial were fat-fingered,
    every other backend test would still pass — the golden gate only protects the DISABLED path, so it
    stays green on a regression to OFF — while the app shipped a different-sounding mix. Lock the
    founder-approved config here so any such revert fails loudly.
    """
    c = mix_route.SHIPPED_CHAIN
    assert c.enabled is True
    assert (
        c.saturate_wet,
        c.presence_gain_db,
        c.reverb_wet,
        c.duck_depth_db,
        c.compress_ratio,
        c.highpass_hz,
        c.deess_intensity,
    ) == (0.3, 4.0, 0.08, 1.0, 2.0, 120, 0.4)
    # The MODEL default must stay OFF, so the disabled path (and the golden gate) is unaffected:
    # the shipped sound is opted in via SHIPPED_CHAIN, not by changing the VocalChainConfig default.
    from app.models import VocalChainConfig

    assert VocalChainConfig().enabled is False


def test_mix_id_folds_the_chain_config_hash(monkeypatch):
    """Phase 0 T1.4: the vocal-chain config hash is part of the mix cache id, so a tuning-week
    dial change invalidates the cache (never serves a stale render)."""
    base = mix_route.mix_id_for(SONG1, SONG2, "")
    monkeypatch.setattr(mix_route, "_CHAIN_CONFIG_HASH", "deadbeefdeadbeef")
    assert mix_route.mix_id_for(SONG1, SONG2, "") != base


def test_mix_carries_camelot_fit(tmp_path, monkeypatch):
    """Phase 0 T1.2: the informational key-fit flows through the route onto the served plan."""
    _use_tmp(monkeypatch, tmp_path)
    _setup_pair(tmp_path)
    r = client.post("/mix", json={"song1_id": SONG1, "song2_id": SONG2})
    body = _poll(r.json()["mix_id"], "ready")
    assert body["status"] == "ready"
    assert body["plan"]["camelot_fit"] is not None  # attached, logged, never gated


# ---------------------------------------------------------------- Change ②: key-matching in the route
# The route's job on the key-match surface: when resolve_key_shift returns a NONZERO shift, run the vocal
# through pitch.shifted_vocal, re-check it with the K1 referee, and render the SHIFTED vocal — and if the
# pitch executor can't produce a clean shift (PitchError), DECLINE VISIBLY, never ship a silently
# un-shifted "key-matched" mix. These stub the audio-heavy pieces (pitch.shifted_vocal, render_mix) so
# the wiring is proven hermetically, without launching node or the real render.


def _spy_render_to(out_recorder):
    """A render_mix stand-in that records the vocal path it was handed and writes a valid, audible,
    non-clipping WAV to `out`, so the real finished-audio referee (assert_render) still passes."""
    def _spy(plan, stems, s2_voc, out):
        out_recorder["s2_voc"] = str(s2_voc)
        t = np.linspace(0, 4.0, int(44100 * 4.0), endpoint=False)
        sf.write(str(out), (0.3 * np.sin(2 * np.pi * 220.0 * t)).astype("float32"), 44100)
    return _spy


def test_key_match_shifts_the_vocal_and_renders_the_shifted_stem(tmp_path, monkeypatch):
    """When the key decision is nonzero, the route must (1) call pitch.shifted_vocal for Song 2 at the
    resolved shift, (2) re-check it via the K1 referee, and (3) feed the SHIFTED vocal to the render —
    not the original stem. All three are asserted; the audio engine is stubbed to stay hermetic."""
    _use_tmp(monkeypatch, tmp_path)
    _setup_pair(tmp_path)

    shifted_path = tmp_path / "shifted_vocal.wav"
    _tone(shifted_path, 500.0)  # a distinct file so "the shifted stem was rendered" is unambiguous

    shift_call, k1_call, rendered = {}, {}, {}

    def fake_shifted_vocal(song_id, vocal_wav, semitones, formant=True):
        shift_call.update(song_id=song_id, vocal_wav=str(vocal_wav), semitones=semitones)
        return shifted_path

    def fake_assert_key_shift(original_vocal, shifted_vocal, semitones):
        k1_call.update(original=str(original_vocal), shifted=str(shifted_vocal), semitones=semitones)

    monkeypatch.setattr(mix_route, "resolve_key_shift", lambda a1, a2: (2, "key-match test +2"))
    monkeypatch.setattr(pitch, "shifted_vocal", fake_shifted_vocal)
    monkeypatch.setattr(mix_route.validate, "assert_key_shift", fake_assert_key_shift)
    monkeypatch.setattr(mix_route, "render_mix", _spy_render_to(rendered))

    r = client.post("/mix", json={"song1_id": SONG1, "song2_id": SONG2})
    body = _poll(r.json()["mix_id"], "ready")
    assert body["status"] == "ready"

    # (1) the pitch executor was invoked for Song 2 at the resolved +2 shift
    assert shift_call.get("song_id") == SONG2, shift_call
    assert shift_call.get("semitones") == 2, shift_call
    # (2) the K1 referee re-checked the shifted vocal at the same +2
    assert k1_call.get("semitones") == 2, k1_call
    assert k1_call.get("shifted") == str(shifted_path), k1_call
    # (3) the render was fed the SHIFTED vocal, never the original stem
    assert rendered.get("s2_voc") == str(shifted_path), rendered


def test_key_match_pitch_error_ships_native_key_never_refuses(tmp_path, monkeypatch):
    """NEVER-REFUSE (founder rule 2026-08-10, supersedes the old loud-decline): if pitch.shifted_vocal
    raises PitchError (no clean shift possible), the mix STILL completes — with the vocal in its NATIVE
    key — instead of declining. The un-shifted vocal is never mislabelled as key-matched: the fallback
    is recorded as a visible 'key_shift_fallback' anomaly and the plan records shipped_key_shift == 0."""
    _use_tmp(monkeypatch, tmp_path)
    _setup_pair(tmp_path)

    def boom(song_id, vocal_wav, semitones, formant=True):
        raise pitch.PitchError("pitch helper non-deterministic after 3 renders — declining")

    monkeypatch.setattr(mix_route, "resolve_key_shift", lambda a1, a2: (2, "needs +2"))
    monkeypatch.setattr(pitch, "shifted_vocal", boom)
    rendered: dict = {}
    monkeypatch.setattr(mix_route, "render_mix", _spy_render_to(rendered))

    r = client.post("/mix", json={"song1_id": SONG1, "song2_id": SONG2, "prompt": "native-fallback"})
    mix_id = r.json()["mix_id"]
    body = _poll(mix_id, "ready")
    assert body["status"] == "ready", body
    # the render was fed the ORIGINAL stem (native key), not a phantom shifted path
    assert rendered.get("s2_voc", "").endswith(f"{SONG2}.vocals.mp3"), rendered
    # and the shipped key is recorded as native, so the live Play bus reproduces it
    assert json.loads(mix_route._plan_path(mix_id).read_text())["shipped_key_shift"] == 0


def test_engine_version_tags_key_matching_when_enabled():
    """The key-match off-switch is folded into ENGINE_VERSION (so flipping it auto-invalidates the mix
    cache). With key-matching live, the version string MUST carry the +m10key tag — a cached pre-key
    mix can never be served as if it were key-matched."""
    assert mix_route.key_match_enabled() is True
    assert "+m10key" in mix_route.ENGINE_VERSION, mix_route.ENGINE_VERSION


# ---- CHANGE 1/2: auto rule assignment via the deterministic shuffler ----------------------------

def test_auto_rule_assignment_is_deterministic_and_cache_stable(monkeypatch, tmp_path):
    """A user_id + generation index drives the shuffler: the rule is auto-assigned and the generation
    is the take (cache slot). The same (user, pair, generation) must always yield the same mix id (a
    regenerate hits cache), and that id must equal the plain cache formula with the shuffled rule +
    take = generation + 1 (so the mix_id_for formula itself is UNCHANGED)."""
    _use_tmp(monkeypatch, tmp_path)
    _setup_pair(tmp_path)
    monkeypatch.setattr(mix_route, "_run_mix", lambda *a, **k: None)  # id-only check; skip the render
    from app.planner import rule_shuffle

    body = {"song1_id": SONG1, "song2_id": SONG2, "user_id": "u-test", "generation": 0}
    id1 = client.post("/mix", json=body).json()["mix_id"]
    id2 = client.post("/mix", json=body).json()["mix_id"]
    assert id1 == id2  # same (user, pair, generation) -> same id, forever

    expected_rule = rule_shuffle.rule_for("u-test", SONG1, SONG2, 0)
    expected_id = mix_route.mix_id_for(SONG1, SONG2, "", 1, expected_rule)  # take = generation + 1
    assert id1 == expected_id


def test_auto_rule_two_users_can_diverge_on_the_same_pair(monkeypatch, tmp_path):
    """Different users get different orderings for the same pair (R3): at generation 0 the two users
    below get different rules, so their generation-0 mix ids differ."""
    _use_tmp(monkeypatch, tmp_path)
    _setup_pair(tmp_path)
    monkeypatch.setattr(mix_route, "_run_mix", lambda *a, **k: None)

    def gen0_id(user):
        return client.post("/mix", json={"song1_id": SONG1, "song2_id": SONG2,
                                         "user_id": user, "generation": 0}).json()["mix_id"]

    # creator-02 and creator-03 get different first rules (4 vs 1) for this pair (see the shuffler tests).
    assert gen0_id("creator-02") != gen0_id("creator-03")


def test_explicit_rule_still_works_without_a_user_id(monkeypatch, tmp_path):
    """Back-compat: with no user_id/generation, the explicit rule + take are used unchanged (the set
    path and older callers)."""
    _use_tmp(monkeypatch, tmp_path)
    _setup_pair(tmp_path)
    monkeypatch.setattr(mix_route, "_run_mix", lambda *a, **k: None)

    got = client.post("/mix", json={"song1_id": SONG1, "song2_id": SONG2, "rule": 3, "take": 2}).json()
    assert got["mix_id"] == mix_route.mix_id_for(SONG1, SONG2, "", 2, 3)


def test_vocal_rich_beat_never_gets_the_chop_rule(monkeypatch):
    """A vocal-rich beat (guest-verse-marked) must never be handed rule 3 (chop): the chop renderer
    discards the beat's guest verse, so the beat's OWN lyrics vanish (the Wake Me Up x Wari Jawa bug —
    it worked on Lean On only because that landed on rule 1/4). The effective rule must avoid chop."""
    from app.planner import beat_guest_verse, rule_shuffle
    beat, voc = "e" * 64, "d" * 64
    # Sanity: the shuffler DOES deal rule 3 to this pair on some generation (else the test is vacuous).
    assert 3 in [rule_shuffle.rule_for("u1", beat, voc, g) for g in range(30)]
    # Mark the beat vocal-rich; now the EFFECTIVE rule for every generation must avoid the chop.
    monkeypatch.setattr(beat_guest_verse, "guest_verse_for",
                        lambda sid: (10.0, 25.0) if sid == beat else None)
    effective = [mix_route._resolve_rule_take(
        mix_route.MixRequest(song1_id=beat, song2_id=voc, user_id="u1", generation=g))[0]
        for g in range(30)]
    assert 3 not in effective, f"a vocal-rich beat was sent to the chop renderer: {effective}"
