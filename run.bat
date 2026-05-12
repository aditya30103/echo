@echo off
echo Starting Echo archaeology browser...
echo Open: http://127.0.0.1:8001
echo Press Ctrl+C to stop.
echo.
datasette echo.db --metadata metadata.yaml --host 127.0.0.1 --port 8001 --open
