"""Shared helpers for talking to Claude from the planners.

One place for the model id and for reading a structured reply, so the arrangement brain
(`plan.py`) and the live-suggestion brain (`suggest.py`) stay in sync. `first_text` exists
because newer models can return a THINKING block as the first content item — reading
`msg.content[0].text` on that raises AttributeError, which used to be swallowed and drop
every AI call to the deterministic fallback. The LLM only ever fills structured JSON here;
it never touches audio.
"""

from __future__ import annotations

import json

# A fast, reliable Sonnet that returns the answer directly (no thinking block to unwrap) —
# right for picking among pre-vetted options. Kept in one place so both planners agree.
MODEL = "claude-sonnet-4-5"


def first_text(msg) -> str:
    """The first usable text from a messages response, skipping thinking/other blocks."""
    for block in getattr(msg, "content", []) or []:
        t = getattr(block, "text", None)
        if isinstance(t, str) and t.strip():
            return t
    raise ValueError("no text block in model response")


def extract_json(text: str) -> dict:
    """Tolerate a model that wraps its JSON in prose or a code fence."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model output")
    return json.loads(text[start : end + 1])
