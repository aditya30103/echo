"""Tests for api/llm.py:available_models() — pure env-var logic."""

import pytest
import api.llm as llm_module


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    """Prevent _load_env() from re-reading .env and overwriting monkeypatched vars."""
    monkeypatch.setattr(llm_module, "_load_env", lambda: None)


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
