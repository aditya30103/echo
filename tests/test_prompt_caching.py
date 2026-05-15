"""Tests for prompt caching in api/llm.py (Sprint 5).

Note: api/llm.py uses `client.messages.stream()` as a context manager (changed
in commit 6a5a073 to eliminate the 60s wall-clock timeout for long finish
calls). Tests mock the streaming interface accordingly.
"""

import os
from unittest.mock import patch, MagicMock


def _make_anthropic_resp(cache_read: int = 0, cache_creation: int = 0):
    resp = MagicMock()
    resp.content = [MagicMock(text="ok")]
    resp.usage.input_tokens = 100
    resp.usage.output_tokens = 10
    resp.usage.cache_read_input_tokens = cache_read
    resp.usage.cache_creation_input_tokens = cache_creation
    resp.stop_reason = "end_turn"
    return resp


def _wire_streaming_mock(mock_client, resp):
    """Wire a MagicMock anthropic client so `with client.messages.stream(...) as s: s.get_final_message()` returns resp."""
    stream_ctx = MagicMock()
    stream_ctx.__enter__.return_value.get_final_message.return_value = resp
    stream_ctx.__exit__.return_value = False
    mock_client.messages.stream.return_value = stream_ctx
    return stream_ctx


def test_chat_cache_prefix_wraps_system_into_two_blocks():
    """When cached_prefix is set on the Anthropic path, system becomes a two-block list."""
    from api.llm import chat

    with patch("anthropic.Anthropic") as mock_cls:
        mock_client = mock_cls.return_value
        _wire_streaming_mock(mock_client, _make_anthropic_resp())

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake"}):
            chat(
                [{"role": "system", "content": "phase instructions"}, {"role": "user", "content": "hi"}],
                cached_prefix="stable preamble",
            )

    call_kwargs = mock_client.messages.stream.call_args.kwargs
    system = call_kwargs["system"]
    assert isinstance(system, list), "system should be a list when cached_prefix is set"
    assert len(system) == 2
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    assert system[0]["text"] == "stable preamble"
    assert system[1]["text"] == "phase instructions"
    # Block 2 must also be cached (per commit 23710b3)
    assert system[1]["cache_control"] == {"type": "ephemeral"}


def test_chat_no_prefix_uses_string_system():
    """Without cached_prefix, system is a plain string — no caching overhead."""
    from api.llm import chat

    with patch("anthropic.Anthropic") as mock_cls:
        mock_client = mock_cls.return_value
        _wire_streaming_mock(mock_client, _make_anthropic_resp())

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake"}):
            chat([{"role": "system", "content": "instructions"}, {"role": "user", "content": "hi"}])

    call_kwargs = mock_client.messages.stream.call_args.kwargs
    assert isinstance(call_kwargs["system"], str)


def test_chat_cache_read_tokens_returned_in_usage():
    """Usage dict includes cache_read_input_tokens from Anthropic response."""
    from api.llm import chat

    with patch("anthropic.Anthropic") as mock_cls:
        mock_client = mock_cls.return_value
        _wire_streaming_mock(mock_client, _make_anthropic_resp(cache_read=150))

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake"}):
            _, _, usage, _ = chat([{"role": "user", "content": "hi"}])

    assert usage["cache_read_input_tokens"] == 150
    assert "cache_creation_input_tokens" in usage


def test_non_anthropic_path_injects_prefix_into_system_message():
    """On OpenAI path, cached_prefix is prepended to the system message content."""
    from api.llm import chat

    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content="ok"), finish_reason="stop")]
    mock_resp.usage.prompt_tokens = 100
    mock_resp.usage.completion_tokens = 10

    env = {"OPENAI_API_KEY": "fake-openai"}

    with patch("openai.OpenAI") as mock_cls, patch("api.llm._load_env"):
        mock_client = mock_cls.return_value
        mock_client.chat.completions.create.return_value = mock_resp

        with patch.dict(os.environ, env, clear=True):
            chat(
                [{"role": "system", "content": "instructions text"}, {"role": "user", "content": "hi"}],
                cached_prefix="preamble text",
            )

    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    system_msgs = [m for m in call_kwargs["messages"] if m["role"] == "system"]
    assert len(system_msgs) == 1
    combined = system_msgs[0]["content"]
    assert "preamble text" in combined
    assert "instructions text" in combined


def test_inject_prefix_no_system_message():
    """_inject_prefix creates a system message when none exists."""
    from api.llm import _inject_prefix

    result = _inject_prefix([{"role": "user", "content": "hi"}], "my preamble")
    assert result[0]["role"] == "system"
    assert result[0]["content"] == "my preamble"
    assert result[1]["role"] == "user"
