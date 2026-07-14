"""The AI mix-name planner + route: a catchy name with a deterministic fallback."""

from fastapi.testclient import TestClient

from app.main import app
from app.planner.name import _clean_title, _fallback, mix_name

client = TestClient(app)


def test_clean_title_strips_extension_and_separators():
    assert _clean_title("father_ocean.mp3") == "Father Ocean"
    assert _clean_title("tere-bina.wav") == "Tere Bina"
    assert _clean_title("") == "Untitled"


def test_fallback_joins_the_two_titles():
    assert _fallback("father ocean.mp3", "tere bina.wav") == "Father Ocean × Tere Bina"


def test_mix_name_uses_the_fallback_without_an_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    name = mix_name("father ocean.mp3", "tere bina.wav")
    assert "Father Ocean" in name and "Tere Bina" in name


def test_name_route_returns_a_name(monkeypatch):
    # No key → deterministic fallback (never calls the real API in the test).
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = client.post(
        "/mix/name",
        json={"song1_name": "unique_beat_zzz.mp3", "song2_name": "unique_vox_zzz.wav"},
    )
    assert r.status_code == 200
    assert "×" in r.json()["name"]
