#!/usr/bin/env bash
# Launch Datasette as a lightweight browser for echo.db.
# Mirror of run.bat for macOS / Linux. See RUNBOOK.md for richer query options.
set -e
echo "Starting Echo archaeology browser..."
echo "Open: http://127.0.0.1:8001"
echo "Press Ctrl+C to stop."
exec datasette echo.db --metadata metadata.yaml --host 127.0.0.1 --port 8001 --open
