"""Plumbing tests for echo.pipeline.reflect — the GPT-4o narrative step.

reflect.py had zero coverage. These do NOT test reflection *quality* (that's the
deferred LLM-as-judge eval in TODOS.md); they pin the mechanics:

  - --dry-run makes no API call and writes no rows
  - a live run appends a reflections row (and re-running appends again — the
    documented idempotency contract is APPEND, not replace)
  - private/annotations.yaml LIFE CONTEXT is injected into the prompt

The LLM client is mocked throughout, so no key and no network are needed. The
echo.db under test is built from the synthetic Takeout fixtures via the real
ingest -> detect -> signals pipeline, so reflect runs against a real schema.
"""

from __future__ import annotations

import sqlite_utils
import pytest

from echo.config import APIKeys, EchoConfig, TakeoutPaths
from echo.pipeline import detect, ingest, reflect, signals

from tests.fixtures import build_activity_zip, build_youtube_zip, build_calendar_zip


@pytest.fixture
def built_config(tmp_path):
    """A tmp echo.db carried through ingest -> signals -> detect, so chapters +
    chapter_fingerprints exist for reflect to assemble context from."""
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    cfg = EchoConfig(
        data_dir=tmp_path / "data",
        takeout=TakeoutPaths(
            youtube_zip=build_youtube_zip(fixtures),
            activity_zip=build_activity_zip(fixtures),
            calendar_zip=build_calendar_zip(fixtures),
        ),
        api_keys=APIKeys(),
    )
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    ingest.run(cfg)
    signals.run(cfg)
    detect.run(cfg, penalty=3.0, dry_run=False, plot=False)
    return cfg


def _reflections_count(cfg, kind: str | None = None) -> int:
    db = sqlite_utils.Database(cfg.db_path)
    if "reflections" not in {t.name for t in db.tables}:
        return 0
    if kind:
        return db.execute("SELECT COUNT(*) FROM reflections WHERE kind = ?", [kind]).fetchone()[0]
    return db["reflections"].count


def test_dry_run_makes_no_api_call_and_writes_nothing(built_config, monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(reflect, "call_gpt4o",
                        lambda *a, **k: calls.__setitem__("n", calls["n"] + 1) or "should not run")
    # If dry-run wrongly tried to build a client, this would raise.
    monkeypatch.setattr(reflect, "get_openai_client",
                        lambda: (_ for _ in ()).throw(AssertionError("dry-run must not build a client")))

    reflect.run(built_config, dry_run=True, chapter=1)

    assert calls["n"] == 0, "dry-run must not call the LLM"
    assert _reflections_count(built_config) == 0, "dry-run must not write rows"


def test_live_run_appends_and_rerun_appends_again(built_config, monkeypatch):
    monkeypatch.setattr(reflect, "get_openai_client", lambda: (object(), "gpt-4o-test"))
    monkeypatch.setattr(reflect, "call_gpt4o", lambda *a, **k: "a canned reflection")

    reflect.run(built_config, dry_run=False, chapter=1)
    assert _reflections_count(built_config, kind="chapter") == 1

    db = sqlite_utils.Database(built_config.db_path)
    row = db.execute("SELECT reflection, model, kind FROM reflections LIMIT 1").fetchone()
    assert row[0] == "a canned reflection"
    assert row[1] == "gpt-4o-test"
    assert row[2] == "chapter"

    # Documented contract: reflect APPENDS. Re-running adds another row.
    reflect.run(built_config, dry_run=False, chapter=1)
    assert _reflections_count(built_config, kind="chapter") == 2


def test_annotations_life_context_injected_into_prompt(built_config, monkeypatch):
    # Write a LIFE CONTEXT annotation at the path run() reads (data_dir/private).
    ann_path = built_config.annotations_path
    ann_path.parent.mkdir(parents=True, exist_ok=True)
    ann_path.write_text(
        "annotations:\n"
        "  - start: '2023-01-01'\n"
        "    end: '2025-12-31'\n"
        "    note: 'Moved to a new city and started a job'\n",
        encoding="utf-8",
    )

    captured = {"user_prompt": ""}

    def fake_call(client, model, system, user):
        captured["user_prompt"] = user
        return "canned"

    monkeypatch.setattr(reflect, "get_openai_client", lambda: (object(), "gpt-4o-test"))
    monkeypatch.setattr(reflect, "call_gpt4o", fake_call)

    reflect.run(built_config, dry_run=False, chapter=1)

    assert "LIFE CONTEXT" in captured["user_prompt"]
    assert "Moved to a new city" in captured["user_prompt"]
