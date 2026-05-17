"""Tests for `echo serve` static-mount + SPA fallback behavior.

Verifies the _SPAStaticFiles wrapper that backs `echo serve`:
  - real static files resolve normally (200)
  - directory roots resolve to index.html (200)
  - unknown deep paths fall back to index.html for SPA routing (200, HTML)
  - /api/* misses stay 404 (not eclipsed by the SPA fallback)
  - registered API routes still win over the static mount

Uses a tmp directory as the "dist" so the test doesn't depend on whether
the actual SvelteKit build has been copied into src/echo/ui/dist/.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from echo.cli.serve import _SPAStaticFiles


@pytest.fixture
def synthetic_dist(tmp_path: Path) -> Path:
    """Build a minimum-viable SPA dist directory:
      - index.html (the SPA shell)
      - assets/app.js (a real static asset)
    """
    (tmp_path / "index.html").write_text(
        "<!doctype html><html><body><div id=app></div></body></html>",
        encoding="utf-8",
    )
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log('echo')", encoding="utf-8")
    return tmp_path


@pytest.fixture
def app_with_api_and_spa(synthetic_dist: Path) -> FastAPI:
    """A small FastAPI app with one /api route + the SPA mount, matching
    the shape `echo serve` produces against api.main:app."""
    app = FastAPI()

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    app.mount("/", _SPAStaticFiles(synthetic_dist), name="ui")
    return app


def test_root_serves_index_html(app_with_api_and_spa):
    r = TestClient(app_with_api_and_spa).get("/")
    assert r.status_code == 200
    assert "<html" in r.text.lower()


def test_real_static_asset_served(app_with_api_and_spa):
    r = TestClient(app_with_api_and_spa).get("/assets/app.js")
    assert r.status_code == 200
    assert "console.log" in r.text


def test_spa_fallback_for_unknown_deep_path(app_with_api_and_spa):
    """An arbitrary client-side route falls back to index.html for SvelteKit."""
    r = TestClient(app_with_api_and_spa).get("/some/spa/route/that/doesnt/exist")
    assert r.status_code == 200
    assert "<html" in r.text.lower()
    assert "id=app" in r.text  # confirms it's actually our index, not generic 404


def test_api_route_wins_over_static_mount(app_with_api_and_spa):
    r = TestClient(app_with_api_and_spa).get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_api_miss_stays_404_not_spa_fallback(app_with_api_and_spa):
    """Critical: unknown /api/* must not return the SPA shell. JSON APIs need
    machine-readable misses (404), not HTML."""
    r = TestClient(app_with_api_and_spa).get("/api/nonexistent-route")
    assert r.status_code == 404
    # Should not be the SPA shell
    assert "<html" not in r.text.lower()


def test_api_double_slash_is_still_treated_as_api(app_with_api_and_spa):
    """Defense in depth: /api/foo/bar shouldn't slip through to SPA fallback either."""
    r = TestClient(app_with_api_and_spa).get("/api/totally/nested/missing")
    assert r.status_code == 404
