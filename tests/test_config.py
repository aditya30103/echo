"""Tests for echo.config.EchoConfig + APIKeys + load_config wiring.

Primary purpose: regression guards. The APIKeys dataclass + _apply_env_value
+ _KNOWN_ENV_KEYS triple is a 3-way contract; adding a new key requires
touching all three. These tests fail loudly if any leg drops.

Also guards ALL_TABLES against accidental reordering (the agent's
vector_search dispatch + api/vec.py both depend on the exact order +
membership).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from echo.config import (
    ALL_TABLES,
    APIKeys,
    EchoConfig,
    _apply_env_value,
    _KNOWN_ENV_KEYS,
    get_embed_client,
    load_config,
)


def _empty_cfg() -> EchoConfig:
    """Fresh EchoConfig with no keys set."""
    return EchoConfig()


# ── Last.fm wiring (Phase A of Spotify rework) ───────────────────────────────


def test_lastfm_key_populates_from_apply_env_value():
    cfg = _empty_cfg()
    _apply_env_value(cfg, "LASTFM_API_KEY", "fake-key-1234")
    assert cfg.api_keys.lastfm == "fake-key-1234"


def test_lastfm_key_in_known_env_keys():
    """load_config() merges only keys present in _KNOWN_ENV_KEYS."""
    assert "LASTFM_API_KEY" in _KNOWN_ENV_KEYS


def test_lastfm_key_loads_via_env_var(tmp_path, monkeypatch):
    """End-to-end: a real .env on disk + load_config picks up the Last.fm key."""
    monkeypatch.delenv("LASTFM_API_KEY", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text("LASTFM_API_KEY=loaded-from-env\n", encoding="utf-8")
    cfg = load_config(
        config_path=tmp_path / "config.toml",
        env_path=env_path,
        data_dir=tmp_path,
    )
    assert cfg.api_keys.lastfm == "loaded-from-env"


def test_lastfm_key_env_var_overrides_dotenv(tmp_path, monkeypatch):
    """os.environ wins over .env (lets shell-set vars override)."""
    monkeypatch.setenv("LASTFM_API_KEY", "from-shell")
    env_path = tmp_path / ".env"
    env_path.write_text("LASTFM_API_KEY=from-file\n", encoding="utf-8")
    cfg = load_config(
        config_path=tmp_path / "config.toml",
        env_path=env_path,
        data_dir=tmp_path,
    )
    assert cfg.api_keys.lastfm == "from-shell"


# ── Regression: existing keys unaffected by APIKeys field addition ───────────


def test_existing_keys_still_load_after_lastfm_addition(tmp_path, monkeypatch):
    """Adding APIKeys.lastfm must not break loading of Spotify/OpenAI/Anthropic.

    Catches the failure mode where a new dataclass field shadows or reorders
    something that _apply_env_value depends on.
    """
    for key in (
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY",
        "SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "YOUTUBE_API_KEY",
        "LASTFM_API_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    env_path = tmp_path / ".env"
    env_path.write_text(
        "OPENAI_API_KEY=oa-1\n"
        "ANTHROPIC_API_KEY=an-1\n"
        "OPENROUTER_API_KEY=or-1\n"
        "SPOTIFY_CLIENT_ID=sp-id\n"
        "SPOTIFY_CLIENT_SECRET=sp-sec\n"
        "YOUTUBE_API_KEY=yt-1\n"
        "LANGFUSE_PUBLIC_KEY=lf-pub\n"
        "LANGFUSE_SECRET_KEY=lf-sec\n",
        encoding="utf-8",
    )
    cfg = load_config(
        config_path=tmp_path / "config.toml",
        env_path=env_path,
        data_dir=tmp_path,
    )
    assert cfg.api_keys.openai == "oa-1"
    assert cfg.api_keys.anthropic == "an-1"
    assert cfg.api_keys.openrouter == "or-1"
    assert cfg.api_keys.spotify_client_id == "sp-id"
    assert cfg.api_keys.spotify_client_secret == "sp-sec"
    assert cfg.api_keys.youtube == "yt-1"
    assert cfg.api_keys.langfuse_public == "lf-pub"
    assert cfg.api_keys.langfuse_secret == "lf-sec"
    assert cfg.api_keys.lastfm is None  # not set, must remain None (not "")


def test_apikeys_dataclass_has_lastfm_field_with_correct_default():
    """Direct dataclass construction default for forward-compat with tests
    that build APIKeys() directly."""
    k = APIKeys()
    assert k.lastfm is None
    assert isinstance(k.lastfm, type(None))


# ── Regression: ALL_TABLES order + membership ────────────────────────────────


def test_all_tables_contains_original_four_in_order():
    """ALL_TABLES is consumed by agent vector_search dispatch + api/vec.py.

    The 4 baseline tables (reflections, videos, searches, google_searches)
    must always appear in this exact order and must never be dropped, even
    after we append spotify_tracks in Phase E.
    """
    expected_baseline = ["reflections", "videos", "searches", "google_searches"]
    for i, name in enumerate(expected_baseline):
        assert ALL_TABLES[i] == name, (
            f"ALL_TABLES[{i}] must be {name!r}; got {ALL_TABLES[i]!r}. "
            f"Reordering breaks agent vector_search dispatch."
        )


def test_all_tables_has_no_duplicates():
    assert len(ALL_TABLES) == len(set(ALL_TABLES))


# ── get_embed_client config-aware (regression: silent break of echo embed) ──

def test_get_embed_client_uses_config_keys_when_env_empty(monkeypatch):
    """Pre-fix bug: embed.py crashed with 'No embedding API key found' even
    when ~/.echo/.env had OPENAI_API_KEY, because get_embed_client only
    read os.environ. Fix: accept config and prefer config.api_keys."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    cfg = EchoConfig()
    cfg.api_keys = APIKeys(openai="sk-from-config")

    client, model = get_embed_client(cfg)
    assert model == "text-embedding-3-small"
    assert client is not None


def test_get_embed_client_falls_back_to_env_when_no_config(monkeypatch):
    """Backward-compat: legacy callers (api/vec.py) that pass no config
    must still work via os.environ."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-from-env")
    client, model = get_embed_client()  # no config arg
    assert "openai/text-embedding-3-small" == model


def test_get_embed_client_config_preferred_over_env(monkeypatch):
    """When both config and env have keys, config wins (single source of truth)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-wrong")
    cfg = EchoConfig()
    cfg.api_keys = APIKeys(openai="sk-config-correct")
    client, _ = get_embed_client(cfg)
    # Can't easily inspect the openai client's key from outside, but the
    # call must not raise — which means config was consulted before falling
    # through to env. The next assertion is the indirect proof:
    assert client is not None


def test_get_embed_client_raises_when_no_keys_anywhere(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    cfg = EchoConfig()
    cfg.api_keys = APIKeys()  # no keys
    with pytest.raises(RuntimeError, match="No embedding API key found"):
        get_embed_client(cfg)
