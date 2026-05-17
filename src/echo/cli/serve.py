"""`echo serve` implementation.

Starts the FastAPI backend (api.main:app) and, if a pre-built SvelteKit UI
exists under src/echo/ui/dist, mounts it at "/" via StaticFiles. Friends
without Docker get the full Echo experience by pointing a browser at
http://localhost:8000.

Build the UI once, locally:

    cd ui
    npm install
    npm run build
    cp -r build ../src/echo/ui/dist   # or move; both work

Then re-run `pip install -e .` so the dist/ directory ships in the editable
install (pyproject.toml [tool.hatch.build.targets.wheel] includes it via
the package layout).

When src/echo/ui/dist is absent, `echo serve` still starts the API — useful
for headless or programmatic use, or while iterating on the UI via the
SvelteKit dev server (`cd ui && npm run dev` on :5173, proxying to the API
running here on :8000).
"""

from __future__ import annotations

from pathlib import Path

import typer


def _ui_dist_path() -> Path:
    """Locate the bundled UI directory inside the installed package.

    Independent of the configured data_dir - the UI ships with the wheel,
    not with the user's data.
    """
    return Path(__file__).resolve().parent.parent / "ui" / "dist"


def run(host: str = "127.0.0.1", port: int = 8000, reload: bool = False) -> None:
    """Configure the FastAPI app and start uvicorn.

    Args:
        host:   Bind interface (default 127.0.0.1; pass 0.0.0.0 to expose
                on the local network).
        port:   TCP port (default 8000).
        reload: Pass through to uvicorn for dev-mode auto-reload.
    """
    # Import lazily so `echo --help` doesn't pay the FastAPI startup cost.
    from fastapi.staticfiles import StaticFiles
    import uvicorn

    from api.main import app  # type: ignore[import-not-found]

    ui_dist = _ui_dist_path()
    if ui_dist.is_dir():
        # Mount AFTER all routers so /api/* + explicit routes win.
        # html=True turns missing files into index.html lookups so SvelteKit
        # SPA-style routing works.
        app.mount("/", StaticFiles(directory=str(ui_dist), html=True), name="ui")
        typer.echo(f"UI mounted from {ui_dist}")
    else:
        typer.echo(f"UI not bundled. Build it first:")
        typer.echo(f"  cd ui && npm install && npm run build")
        typer.echo(f"  cp -r build ../src/echo/ui/dist")
        typer.echo(f"API will start without a browse UI - hit /api/health to verify.")

    typer.echo(f"\nStarting on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, reload=reload)
