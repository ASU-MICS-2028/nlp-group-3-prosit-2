# Base image for running generated APIs. Build: docker build -t prosit-sandbox sandbox/
FROM python:3.12-slim
RUN pip install --no-cache-dir fastapi pydantic httpx pytest uvicorn
RUN useradd -m runner
USER runner
WORKDIR /work
