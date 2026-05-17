FROM python:3.11-slim

WORKDIR /app

# Install the echo package (deps come from pyproject.toml).
# Copy only what's needed to install first so this layer caches across api/ edits.
COPY pyproject.toml ./
COPY src/ ./src/
COPY LICENSE ./
RUN pip install --no-cache-dir -e .

# Copy the FastAPI backend. Lives outside the echo package so api/ edits
# don't bust the pip install layer above.
COPY api/ ./api/

# Default data dir inside the container. Docker compose overrides this and
# mounts the host's actual data dir at /data; standalone `docker run` users
# can `-v /your/echo/data:/data` to do the same.
ENV ECHO_DATA_DIR=/data

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
