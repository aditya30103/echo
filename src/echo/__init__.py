"""Echo — personal data archaeology, locally owned.

Pipeline scripts (in `echo.pipeline.*`) ingest your Google Takeout + Spotify
exports into a local SQLite + LanceDB store. The CLI (`echo` command, defined
in `echo.cli.main`) wraps the pipeline so friends can install once and run
without touching source code. The agent (FastAPI in `api/`, SvelteKit in
`ui/`, shipped via `echo serve`) provides interactive querying on top.

See SETUP.md (root) for the install + first-run walkthrough.
"""

__version__ = "0.1.0"
