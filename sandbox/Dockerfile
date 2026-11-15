# Sandbox image for generated APIs (Role 3). Build once:  docker build -t prosit-sandbox sandbox/
# core/sandbox.py runs every check, test run and served API in a container from this image, with
# --read-only, no capabilities, memory/CPU/PID limits, and (for checks) no network.
FROM python:3.12-slim
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt
# Non-root. core/sandbox.py passes --user (the host user, never root) so data/ stays writable on Linux.
RUN useradd --create-home --uid 1000 runner
USER runner
WORKDIR /work
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp
EXPOSE 8000
