"""Unit tests for app/services/ai_brain.py.

The Anthropic client is mocked — no real API calls are made.
"""

from unittest.mock import MagicMock, patch

import pytest

import app.services.ai_brain as ai_brain_module
from app.services.ai_brain import _summarise_disfluencies, generate_response


# ── _summarise_disfluencies ───────────────────────────────────────────────────

class TestSummariseDisfluencies:
    def test_empty_returns_none_detected(self):
        assert _summarise_disfluencies([]) == "none detected this turn"

    def test_single_type(self):
        events = [{"type": "repetition"}, {"type": "repetition"}]
        summary = _summarise_disfluencies(events)
        assert "2x repetition" in summary

    def test_multiple_types(self):
        events = [
            {"type": "repetition"},
            {"type": "block"},
            {"type": "block"},
        ]
        summary = _summarise_disfluencies(events)
        assert "1x repetition" in summary
        assert "2x block" in summary


# ── generate_response ─────────────────────────────────────────────────────────

@pytest.fixture()
def mock_claude():
    """Patch the Anthropic client with a fake that returns a canned message."""
    fake_message = MagicMock()
    fake_message.content = [MagicMock(text="That sounds fun! What's your favourite part?")]

    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_message

    # Reset the module-level singleton so the mock is used
    ai_brain_module._client = None
    with patch("app.services.ai_brain.anthropic.Anthropic", return_value=fake_client):
        yield fake_client


class TestGenerateResponse:
    def test_returns_string(self, mock_claude):
        result = generate_response(
            conversation_history=[{"role": "user", "content": "I like dogs"}],
            age=10,
            turn_number=1,
            disfluencies=[],
        )
        assert isinstance(result, str)
        assert len(result) > 0

    def test_calls_claude_with_correct_model(self, mock_claude):
        generate_response(
            conversation_history=[{"role": "user", "content": "hello"}],
            age=8,
            turn_number=1,
            disfluencies=[],
        )
        call_kwargs = mock_claude.messages.create.call_args.kwargs
        assert "haiku" in call_kwargs["model"].lower()

    def test_system_prompt_contains_character_name(self, mock_claude):
        from app.config.settings import settings
        generate_response(
            conversation_history=[{"role": "user", "content": "hello"}],
            age=10,
            turn_number=1,
            disfluencies=[],
        )
        call_kwargs = mock_claude.messages.create.call_args.kwargs
        assert settings.ai_character_name in call_kwargs["system"]

    def test_system_prompt_contains_age(self, mock_claude):
        generate_response(
            conversation_history=[{"role": "user", "content": "hi"}],
            age=7,
            turn_number=1,
            disfluencies=[],
        )
        call_kwargs = mock_claude.messages.create.call_args.kwargs
        assert "7" in call_kwargs["system"]

    def test_disfluency_note_in_system_prompt(self, mock_claude):
        disfluencies = [{"type": "repetition"}, {"type": "repetition"}]
        generate_response(
            conversation_history=[{"role": "user", "content": "hi"}],
            age=9,
            turn_number=2,
            disfluencies=disfluencies,
        )
        call_kwargs = mock_claude.messages.create.call_args.kwargs
        assert "repetition" in call_kwargs["system"]

    def test_fluency_support_policy_in_system_prompt(self, mock_claude):
        # db=None → fluency support defaults on → demand-reduction rules present.
        generate_response(
            conversation_history=[{"role": "user", "content": "hi"}],
            age=8, turn_number=2, disfluencies=[],
        )
        system = mock_claude.messages.create.call_args.kwargs["system"]
        assert "Do NOT ask a question every turn" in system
        assert "low-pressure partner" in system

    def test_history_trimmed_to_20_messages(self, mock_claude):
        # Build 30 messages (15 turns)
        long_history = []
        for i in range(30):
            role = "user" if i % 2 == 0 else "assistant"
            long_history.append({"role": role, "content": f"msg {i}"})

        generate_response(
            conversation_history=long_history,
            age=10,
            turn_number=16,
            disfluencies=[],
        )
        call_kwargs = mock_claude.messages.create.call_args.kwargs
        assert len(call_kwargs["messages"]) == 20

    def test_short_history_not_truncated(self, mock_claude):
        history = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello!"},
            {"role": "user", "content": "I like cats"},
        ]
        generate_response(
            conversation_history=history,
            age=10,
            turn_number=2,
            disfluencies=[],
        )
        call_kwargs = mock_claude.messages.create.call_args.kwargs
        assert len(call_kwargs["messages"]) == 3
