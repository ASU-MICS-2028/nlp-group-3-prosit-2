"""Sandbox (Role 3): where generated code runs. Nothing the agents write runs anywhere else.

Two jobs:
  run(ws, argv)          the CHECK sandbox: the Coder's run_checks and the Tester's run_tests.
                         No network, code read-only, a throwaway database in /tmp, 120 s limit.
  serve(ws, root_path)   the SERVE sandbox: the running API the user tries and publishes.
                         Code read-only, only data/ writable, port bound to 127.0.0.1.
  stop(handle)           stops a served API.

SANDBOX=docker (the default) runs each job in a locked-down container from the prosit-sandbox image:

    docker build -t prosit-sandbox sandbox/

SANDBOX=local runs a plain process on this machine. It is NOT isolated: use it for development
without Docker, and for the hosted gateway until it can reach a Docker daemon (see the Dockerfile).
Even locally, generated code never gets this process's environment (API keys stay out).
"""
import asyncio
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx

IMAGE = os.getenv("SANDBOX_IMAGE", "prosit-sandbox")
LABEL = "mesora.sandbox"            # every container we start carries it, so orphans can be cleaned up
TIMEOUT = 120                       # seconds for one check or test run
LIMITS = ["--memory", "512m", "--cpus", "1", "--pids-limit", "128",
          "--read-only", "--tmpfs", "/tmp:rw,size=128m",
          "--cap-drop", "ALL", "--security-opt", "no-new-privileges"]
# The only host variables a local process gets (Python and pytest need these to start).
LOCAL_ENV = ("PATH", "LANG", "LC_ALL", "SYSTEMROOT", "TMPDIR")


def mode() -> str:
    """Read on every call, so tests and the hosted image can switch it with the env var."""
    value = os.getenv("SANDBOX", "docker")
    if value not in ("docker", "local"):
        raise RuntimeError(f"SANDBOX must be docker or local, not {value!r}")
    return value


def _user() -> str:
    """Run as this machine's user, so the API can write to data/ on a Linux bind mount. Never root."""
    uid, gid = (os.getuid(), os.getgid()) if hasattr(os, "getuid") else (1000, 1000)
    return f"{uid}:{gid}" if uid != 0 else "1000:1000"


async def _docker(*args: str) -> tuple[int, str]:
    try:
        proc = await asyncio.create_subprocess_exec("docker", *args, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.STDOUT)
    except FileNotFoundError:
        raise RuntimeError("Docker is not installed. Install Docker, or set SANDBOX=local for development "
                           "(NOT isolated).") from None
    out = (await proc.communicate())[0].decode(errors="replace")
    return proc.returncode, out


async def _require_image() -> None:
    code, out = await _docker("image", "inspect", "--format", "ok", IMAGE)
    if code != 0:
        if "daemon" in out.lower() or "connect" in out.lower():
            raise RuntimeError("Docker is not running. Start Docker, or set SANDBOX=local for development "
                               "(NOT isolated).")
        raise RuntimeError(f"The sandbox image {IMAGE} is missing. Build it once: docker build -t {IMAGE} sandbox/")


# ---------- the check sandbox ----------

@dataclass
class Result:
    code: int            # the process's exit code (-1 if it timed out)
    output: str          # stdout and stderr together
    timed_out: bool = False


def check_command(ws: Path, argv: list[str], env: dict, name: str) -> list[str]:
    """The docker run command for one check or test run (kept separate so it can be tested without Docker)."""
    flags = [f"--env={k}={v}" for k, v in env.items()]
    return ["run", "--rm", "--name", name, "--label", f"{LABEL}=check", "--network", "none",
            *LIMITS, "--user", _user(), "--volume", f"{ws.resolve()}:/work:ro", "--workdir", "/work",
            *flags, IMAGE, *argv]


async def run(ws: Path, argv: list[str], env: dict | None = None, timeout: int = TIMEOUT) -> Result:
    """Run argv (e.g. ["python", "-m", "pytest", "tests"]) in the project folder, in the check sandbox.
    DATABASE_PATH always points at a throwaway file, so a check never touches the real data."""
    ws = Path(ws)
    with tempfile.TemporaryDirectory() as tmp:
        if mode() == "docker":
            await _require_image()
            name = f"mesora-check-{secrets.token_hex(6)}"
            env = {"HOME": "/tmp", "PYTHONDONTWRITEBYTECODE": "1", "DATABASE_PATH": "/tmp/check.db", **(env or {})}
            cmd = ["docker", *check_command(ws, argv, env, name)]
        else:
            name = None
            env = {**{k: os.environ[k] for k in LOCAL_ENV if k in os.environ}, "HOME": tmp,
                   "PYTHONDONTWRITEBYTECODE": "1", "DATABASE_PATH": str(Path(tmp) / "check.db"), **(env or {})}
            cmd = [sys.executable if argv[0] == "python" else argv[0], *argv[1:]]
        proc = await asyncio.create_subprocess_exec(*cmd, cwd=ws, env=env if name is None else None,
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        try:
            out = (await asyncio.wait_for(proc.communicate(), timeout))[0].decode(errors="replace")
        except asyncio.TimeoutError:
            if name:   # killing the docker CLI does not stop the container
                await _docker("kill", name)
            proc.kill()
            await proc.wait()
            return Result(-1, f"Did not finish within {timeout} seconds.", timed_out=True)
    if name and proc.returncode in (125, 126, 127):   # docker itself failed, not the code
        raise RuntimeError(f"The sandbox could not start: {out.strip()[-300:]}")
    return Result(proc.returncode, out)


# ---------- the serve sandbox ----------

def free_port() -> int:
    """A free port on 127.0.0.1, inside SERVE_PORT_RANGE (e.g. 8100-8199) when it is set."""
    low, _, high = os.getenv("SERVE_PORT_RANGE", "").partition("-")
    candidates = range(int(low), int(high) + 1) if low and high else [0]
    for port in candidates:
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
            return s.getsockname()[1]
    raise RuntimeError(f"No free port in SERVE_PORT_RANGE {low}-{high}: stop a running API first.")


def serve_command(ws: Path, root_path: str, port: int, name: str) -> list[str]:
    """The docker run command for a served API. Only app/ (read-only) and data/ are mounted."""
    return ["run", "--detach", "--name", name, "--label", f"{LABEL}=serve",
            "--publish", f"127.0.0.1:{port}:8000", *LIMITS, "--user", _user(),
            "--volume", f"{(ws / 'app').resolve()}:/work/app:ro", "--volume", f"{(ws / 'data').resolve()}:/data",
            "--workdir", "/work", "--env", "HOME=/tmp", "--env", "DATABASE_PATH=/data/app.db",
            "--env", "PYTHONDONTWRITEBYTECODE=1", IMAGE,
            "python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--root-path", root_path]


@dataclass
class Container:
    name: str


async def _logs(handle) -> str:
    if isinstance(handle, Container):
        return (await _docker("logs", "--tail", "30", handle.name))[1][-500:]
    return handle.stderr.read()[-500:] if handle.poll() is not None else ""


async def _running(handle) -> bool:
    if isinstance(handle, Container):
        code, out = await _docker("inspect", "--format", "{{.State.Running}}", handle.name)
        return code == 0 and out.strip() == "true"
    return handle.poll() is None


async def serve(workspace: str, root_path: str) -> tuple:
    """Start the API and wait until GET /health answers 200. Returns a handle for stop(): (process or
    container, port). root_path is the gateway prefix, so /docs finds its openapi.json.
    An API without a working health check is refused."""
    ws = Path(workspace)
    (ws / "data").mkdir(exist_ok=True)   # each API keeps its own database here
    port = free_port()
    if mode() == "docker":
        await _require_image()
        handle = Container(f"mesora-serve-{secrets.token_hex(6)}")
        code, out = await _docker(*serve_command(ws, root_path, port, handle.name))
        if code != 0:
            raise RuntimeError(f"API didn't start: {out.strip()[-500:]}")
    else:   # ponytail: not isolated; SANDBOX=local is for development only
        env = {**{k: os.environ[k] for k in LOCAL_ENV if k in os.environ},
               "DATABASE_PATH": str((ws / "data" / "app.db").resolve()), "PYTHONDONTWRITEBYTECODE": "1"}
        handle = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port),
             "--root-path", root_path], cwd=ws, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)

    async with httpx.AsyncClient() as c:
        for _ in range(75):
            if not await _running(handle):
                logs = await _logs(handle)
                stop((handle, port))
                raise RuntimeError(f"API didn't start: {logs}")
            try:
                r = await c.get(f"http://127.0.0.1:{port}/health", timeout=1)
            except httpx.HTTPError:
                await asyncio.sleep(0.2)
                continue
            if r.status_code == 200:
                return handle, port
            stop((handle, port))
            raise RuntimeError(f"The API's health check failed (GET /health returned {r.status_code}).")
    stop((handle, port))
    raise RuntimeError("API didn't start in time")


def stop(handle: tuple) -> None:
    """Stop a served API. Safe to call twice."""
    target, _ = handle
    if isinstance(target, Container):
        subprocess.run(["docker", "rm", "--force", target.name], capture_output=True)
        return
    target.terminate()
    try:
        target.wait(5)
    except subprocess.TimeoutExpired:
        target.kill()


def cleanup() -> None:
    """Remove containers left over from a gateway that crashed. Called when the gateway starts."""
    if mode() != "docker" or not shutil.which("docker"):
        return
    ids = subprocess.run(["docker", "ps", "--all", "--quiet", "--filter", f"label={LABEL}"],
                         capture_output=True, text=True).stdout.split()
    if ids:
        subprocess.run(["docker", "rm", "--force", *ids], capture_output=True)
