"""Run sandbox/check.py against a workspace, or serve the built API.

SANDBOX=docker (default): locked-down container, no network, 512 MB, 1 CPU, read-only mount, 120 s.
SANDBOX=local: plain subprocess, for machines without Docker. Not isolated.
"""
import json
import os
import pathlib
import subprocess
import sys

CHECK = pathlib.Path(__file__).resolve().parent.parent / "sandbox" / "check.py"
IMAGE = "prosit-sandbox"
TIMEOUT = 120


def run_checks(workspace: str) -> dict:
    ws = str(pathlib.Path(workspace).resolve())
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    if os.getenv("SANDBOX", "docker") == "docker":
        cmd = ["docker", "run", "--rm", "--network", "none", "--memory", "512m", "--cpus", "1",
               "--pids-limit", "128", "--read-only", "--tmpfs", "/tmp",
               "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "PYTEST_ADDOPTS=-p no:cacheprovider",
               "-v", f"{ws}:/work:ro", "-v", f"{CHECK}:/check.py:ro", IMAGE, "python", "/check.py"]
        cwd = None
    else:
        cmd, cwd = [sys.executable, str(CHECK)], ws
        env["PYTEST_ADDOPTS"] = "-p no:cacheprovider"
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"checks timed out after {TIMEOUT}s (infinite loop or blocking call?)"}
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {"ok": False, "error": (proc.stderr or proc.stdout)[-2000:]}


def serve(workspace: str, port: int = 8000) -> subprocess.Popen:
    """Start the API on http://127.0.0.1:<port>. Docker: same limits as checks, port bound to localhost only."""
    ws = str(pathlib.Path(workspace).resolve())
    if os.getenv("SANDBOX", "docker") == "docker":
        cmd = ["docker", "run", "--rm", "--name", f"prosit-serve-{port}", "--memory", "512m", "--cpus", "1",
               "--pids-limit", "128", "--read-only", "--tmpfs", "/tmp", "-e", "PYTHONDONTWRITEBYTECODE=1",
               "-p", f"127.0.0.1:{port}:8000", "-v", f"{ws}:/work:ro", IMAGE,
               "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
        return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    return subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
                            cwd=ws, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)


def stop(proc: subprocess.Popen, port: int = 8000) -> None:
    if os.getenv("SANDBOX", "docker") == "docker":
        subprocess.run(["docker", "stop", "-t", "2", f"prosit-serve-{port}"], capture_output=True)
    proc.terminate()
    proc.wait(timeout=10)


def wait_ready(proc: subprocess.Popen, port: int = 8000, timeout: float = 30) -> bool:
    """Poll /openapi.json until the server answers, the process dies, or timeout."""
    import time
    import httpx
    end = time.time() + timeout
    while time.time() < end and proc.poll() is None:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/openapi.json", timeout=1).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    return False
