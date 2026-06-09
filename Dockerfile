FROM python:3.11-slim

WORKDIR /app

# Install the echo package (deps come from pyproject.toml). The FastAPI backend
# now lives inside the package at src/echo/api, so it installs with everything else.
COPY pyproject.toml ./
COPY src/ ./src/
COPY LICENSE ./
RUN pip install --no-cache-dir -e .

# Default data dir inside the container. Docker compose overrides this and
# mounts the host's actual data dir at /data; standalone `docker run` users
# can `-v /your/echo/data:/data` to do the same.
ENV ECHO_DATA_DIR=/data

EXPOSE 8000
CMD ["uvicorn", "echo.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
