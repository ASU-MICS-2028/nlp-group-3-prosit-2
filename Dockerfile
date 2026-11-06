# Mesora Blocks gateway (web app + API). Deployed with Coolify; see README "Deploying".
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd --create-home --uid 1000 mesora && mkdir -p /data/workspace && chown -R mesora /data /app
USER mesora
ENV HOST=0.0.0.0 PORT=8000 WORKSPACE_DIR=/data/workspace PYTHONUNBUFFERED=1
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/favicon.ico')"
CMD ["python", "-m", "server"]
