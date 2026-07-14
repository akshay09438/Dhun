"""The AI-response helper. Regression: newer models return a THINKING block as the first
content item, so the old `msg.content[0].text` raised AttributeError and every AI call
silently fell back to rules. `first_text` must skip non-text blocks and return the JSON text."""

import types

import pytest

from app.planner.llm import first_text


def test_first_text_skips_a_leading_thinking_block():
    thinking = types.SimpleNamespace(type="thinking", thinking="let me think")  # no .text
    text = types.SimpleNamespace(type="text", text='{"ok": true}')
    msg = types.SimpleNamespace(content=[thinking, text])
    assert first_text(msg) == '{"ok": true}'


def test_first_text_plain_text_first():
    msg = types.SimpleNamespace(content=[types.SimpleNamespace(text="hello")])
    assert first_text(msg) == "hello"


def test_first_text_raises_when_no_text_block():
    thinking = types.SimpleNamespace(type="thinking", thinking="only thinking")
    with pytest.raises(ValueError):
        first_text(types.SimpleNamespace(content=[thinking]))
