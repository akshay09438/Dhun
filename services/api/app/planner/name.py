"""A short, playful name for a finished mix.

Claude coins a catchy mashup name from the two song titles (song 1 = the beat, song 2 =
the vocals) — e.g. "Father Ocean" + "Tere Bina" -> "Tere Ocean". A deterministic "A × B"
fallback runs with no API key or on any failure, so a mix always has a name. One call per
mix (the route caches it). Never touches audio — mirrors planner.plan's LLM/rules shape.
"""

from __future__ import annotations

import json
import os
import re

from app.planner import llm

_MAX_LEN = 48

_NAME_SYSTEM = (
    "You name DJ mashups. Given two song titles (song 1 = the beat, song 2 = the vocals), "
    "coin ONE short, catchy, fun mix name — 2 to 4 words, Title Case, no quotes, no emoji, "
    "no explanation. You may blend the artist/song words playfully. "
    'Reply with STRICT JSON only: {"name": "..."}'
)


def _clean_title(filename: str) -> str:
    """A human title from an upload filename: drop the extension, tidy separators."""
    stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", filename or "").strip()
    stem = re.sub(r"[_\-]+", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem.title() if stem else "Untitled"


def _fallback(name1: str, name2: str) -> str:
    return f"{_clean_title(name1)} × {_clean_title(name2)}"[:_MAX_LEN]


def _ai_name(title1: str, title2: str, prompt: str) -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import anthropic

        # In-request call → short timeout so a hung API falls back fast (name is cosmetic).
        client = anthropic.Anthropic(api_key=key, timeout=8.0)
        payload = {
            "song1_beat": title1,
            "song2_vocals": title2,
            "user_request": prompt or "",
        }
        msg = client.messages.create(
            model=llm.MODEL,
            max_tokens=60,
            system=_NAME_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload)}],
        )
        name = str(llm.extract_json(llm.first_text(msg)).get("name", "")).strip()
        name = re.sub(r"^[\"']|[\"']$", "", name).strip()
        return name[:_MAX_LEN] or None
    except Exception:  # noqa: BLE001 — any failure falls back to the deterministic name
        return None


def mix_name(name1: str, name2: str, prompt: str = "") -> str:
    """A catchy AI name for the mix, with a deterministic 'A × B' fallback."""
    return _ai_name(_clean_title(name1), _clean_title(name2), prompt) or _fallback(
        name1, name2
    )
