"""Tests for echo.api.llm: available_models() env-var logic + chat() Ollama routing."""

from unittest.mock import MagicMock, patch

import pytest
import echo.api.llm as llm_module


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    """Prevent _load_env() from re-reading .env and overwriting monkeypatched vars."""
    monkeypatch.setattr(llm_module, "_load_env", lambda: None)


def _clear_cloud_keys(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)


def _openai_compat_mock():
    """A patch target for openai.OpenAI returning a canned chat completion."""
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content="local answer"), finish_reason="stop")]
    resp.usage.prompt_tokens = 42
    resp.usage.completion_tokens = 7
    client = MagicMock()
    client.chat.completions.create.return_value = resp
    return client


def test_no_keys_returns_empty(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert llm_module.available_models() == []


def test_anthropic_key_returns_claude(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert llm_module.available_models() == ["claude"]


def test_openai_key_returns_gpt4o(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert llm_module.available_models() == ["gpt4o"]


def test_both_keys_returns_both(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-oai")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = llm_module.available_models()
    assert "claude" in result
    assert "gpt4o" in result


def test_openrouter_key_provides_both_when_no_direct_keys(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
    result = llm_module.available_models()
    assert "claude" in result
    assert "gpt4o" in result


# ── available_models(): Ollama ────────────────────────────────────────────────

def test_ollama_base_url_adds_ollama_last(monkeypatch):
    _clear_cloud_keys(monkeypatch)
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    assert llm_module.available_models() == ["ollama"]


def test_no_ollama_base_url_excludes_ollama(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    assert "ollama" not in llm_module.available_models()


# ── chat(): Ollama routing (2A) ───────────────────────────────────────────────

def test_explicit_ollama_routes_local_with_v1_suffix(monkeypatch):
    """model='ollama' → openai client at {base}/v1, default model slug, ollama label."""
    _clear_cloud_keys(monkeypatch)
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    client = _openai_compat_mock()

    with patch("openai.OpenAI", return_value=client) as mock_cls:
        text, label, usage, stop = llm_module.chat(
            [{"role": "user", "content": "hi"}], model="ollama"
        )

    assert mock_cls.call_args.kwargs["base_url"] == "http://localhost:11434/v1"
    assert mock_cls.call_args.kwargs["api_key"] == "ollama"
    assert client.chat.completions.create.call_args.kwargs["model"] == llm_module.DEFAULT_OLLAMA_MODEL
    assert client.chat.completions.create.call_args.kwargs["timeout"] == llm_module.OLLAMA_TIMEOUT
    assert label == f"ollama:{llm_module.DEFAULT_OLLAMA_MODEL}"
    assert text == "local answer"


def test_explicit_ollama_keeps_existing_v1_suffix(monkeypatch):
    """A base that already ends in /v1 is not doubled."""
    _clear_cloud_keys(monkeypatch)
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    client = _openai_compat_mock()
    with patch("openai.OpenAI", return_value=client) as mock_cls:
        llm_module.chat([{"role": "user", "content": "hi"}], model="ollama")
    assert mock_cls.call_args.kwargs["base_url"] == "http://localhost:11434/v1"


def test_explicit_ollama_honors_OLLAMA_MODEL(monkeypatch):
    _clear_cloud_keys(monkeypatch)
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:14b")
    client = _openai_compat_mock()
    with patch("openai.OpenAI", return_value=client):
        _, label, _, _ = llm_module.chat([{"role": "user", "content": "hi"}], model="ollama")
    assert client.chat.completions.create.call_args.kwargs["model"] == "qwen2.5:14b"
    assert label == "ollama:qwen2.5:14b"


def test_explicit_ollama_without_base_raises(monkeypatch):
    _clear_cloud_keys(monkeypatch)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="OLLAMA_BASE_URL"):
        llm_module.chat([{"role": "user", "content": "hi"}], model="ollama")


def test_explicit_ollama_with_cloud_key_but_no_base_does_not_use_cloud(monkeypatch):
    """Asking for local must never silently spend a cloud key when base is unset."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-oai")
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    with patch("openai.OpenAI") as mock_cls:
        with pytest.raises(RuntimeError, match="OLLAMA_BASE_URL"):
            llm_module.chat([{"role": "user", "content": "hi"}], model="ollama")
    mock_cls.assert_not_called()  # the OpenAI client was never constructed


def test_auto_falls_back_to_ollama_when_no_cloud_key(monkeypatch):
    """No cloud key + OLLAMA_BASE_URL set → auto routes local instead of erroring."""
    _clear_cloud_keys(monkeypatch)
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    client = _openai_compat_mock()
    with patch("openai.OpenAI", return_value=client):
        _, label, _, _ = llm_module.chat([{"role": "user", "content": "hi"}], model="auto")
    assert label.startswith("ollama:")


def test_auto_prefers_cloud_over_ollama(monkeypatch):
    """With both a cloud key AND OLLAMA_BASE_URL, auto uses cloud — never the weak local."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-oai")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    client = _openai_compat_mock()
    with patch("openai.OpenAI", return_value=client) as mock_cls:
        _, label, _, _ = llm_module.chat([{"role": "user", "content": "hi"}], model="auto")
    # GPT-4o direct path: default OpenAI endpoint (base_url=None), gpt-4o slug — not ollama.
    assert mock_cls.call_args.kwargs["base_url"] is None
    assert client.chat.completions.create.call_args.kwargs["model"] == llm_module.GPT4O_DIRECT
    assert label == "gpt-4o"
