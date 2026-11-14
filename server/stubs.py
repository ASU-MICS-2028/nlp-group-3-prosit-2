"""Placeholder agents and serve sandbox, so the UI and gateway work end to end (milestone M2).

They replay the golden clinic example: the requirements stub asks one question and then
summarises, the architect returns the golden spec, and the build copies the golden code and
runs its real tests. Each follows the agent format `async def run(state, emit) -> state`.

agents/orchestrator.py picks which agent does each job (its AGENTS table). Swap in the real
coder (Role 3) and tester (Role 4) there as they land, and the serve sandbox (Role 3) in server/app.py.
"""
import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import httpx

from core.events import Emit, Event
from core.spec import Requirements, Spec
from core.state import LogEntry, Message, ProjectState

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "golden" / "clinic"
CHAT = json.loads((GOLDEN / "chat.json").read_text())
REPLIES = [CHAT[1]["content"], CHAT[-2]["content"]]  # one question, then the summary
STEP_DELAY = float(os.getenv("STUB_STEP_DELAY", "0.5"))  # makes progress visible in the UI


async def _step(state: ProjectState, emit: Emit, agent: str, action: str, detail: str = "") -> None:
    state.logs.append(LogEntry(agent=agent, action=action, detail=detail))
    await emit(Event(type="step", agent=agent, detail=detail, data={"action": action}))
    await asyncio.sleep(STEP_DELAY)


async def requirements(state: ProjectState, emit: Emit) -> ProjectState:
    turn = sum(m.role == "assistant" for m in state.chat)
    await asyncio.sleep(STEP_DELAY)
    state.chat.append(Message(role="assistant", content=REPLIES[min(turn, len(REPLIES) - 1)]))
    if turn >= len(REPLIES) - 1:
        state.requirements = Requirements.model_validate_json((GOLDEN / "requirements.json").read_text())
    await _step(state, emit, "requirements", "reply", "Asked a question" if state.requirements is None else "Requirements complete")
    return state


async def architect(state: ProjectState, emit: Emit) -> ProjectState:
    if state.change_request:
        await _step(state, emit, "architect", "change", f"Change noted (stub keeps the golden spec): {state.change_request}")
        state.change_request = None
    state.spec = Spec.model_validate_json((GOLDEN / "spec.json").read_text())
    state.spec_approved = False
    await _step(state, emit, "architect", "spec", f"{len(state.spec.endpoints)} endpoints")
    await emit(Event(type="spec", agent="architect", detail=state.spec.project_name))
    return state


RESULT_RE = re.compile(r"^(PASSED|FAILED|ERROR|SKIPPED) (\S+?)::(\S+)", re.M)


async def coder(state: ProjectState, emit: Emit) -> ProjectState:
    """Placeholder Coder (Role 3 replaces it): copies the golden code into app/."""
    ws = Path(state.workspace)
    shutil.rmtree(ws / "app", ignore_errors=True)
    shutil.copytree(GOLDEN / "app", ws / "app", ignore=shutil.ignore_patterns("__pycache__"))
    await _step(state, emit, "coder", "write_file", "app/main.py")
    await _step(state, emit, "coder", "run_checks", "App imports and starts")
    await _step(state, emit, "coder", "finish", "Checks passed")
    state.build_ok = True
    return state


async def tester(state: ProjectState, emit: Emit) -> ProjectState:
    """Placeholder Tester (Role 4 replaces it): copies the golden tests into tests/ and runs them for real."""
    ws = Path(state.workspace)
    shutil.rmtree(ws / "tests", ignore_errors=True)
    shutil.copytree(GOLDEN / "tests", ws / "tests", ignore=shutil.ignore_patterns("__pycache__"))
    for f in ("conftest.py", "chat.json", "requirements.json", "spec.json"):  # the golden tests read these
        shutil.copy(GOLDEN / f, ws / f)
    await _step(state, emit, "tester", "write_test", "tests/test_api.py")
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "pytest", "-q", "-rA", "-p", "no:cacheprovider", "tests", cwd=ws,
        env={**os.environ, "PYTHONPATH": str(ROOT)}, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    out = (await proc.communicate())[0].decode(errors="replace")
    state.test_results = [{"file": f, "name": n, "outcome": o.lower()} for o, f, n in RESULT_RE.findall(out)]
    state.test_summary = out.strip().splitlines()[-1].strip("= ") if out.strip() else "no output"
    state.tests_ok = proc.returncode == 0
    state.test_report = None if state.tests_ok else out[-3000:]
    await _step(state, emit, "tester", "run_tests", state.test_summary)
    await emit(Event(type="test", agent="tester", detail=state.test_summary, data={"ok": state.tests_ok}))
    return state


# ---------- serve sandbox stand-in (Role 3 replaces with core/sandbox) ----------
# ponytail: plain local process, not isolated; fine for the trusted golden code only.

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def serve(workspace: str, root_path: str) -> tuple[subprocess.Popen, int]:
    """Start the API on 127.0.0.1 and wait until GET /health answers 200. root_path is the gateway
    prefix, so /docs finds its openapi.json. An API without a health check is refused."""
    port = _free_port()
    data = Path(workspace) / "data"   # each API keeps its own database (shared convention: DATABASE_PATH)
    data.mkdir(exist_ok=True)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--root-path", root_path],
        cwd=workspace, env={**os.environ, "DATABASE_PATH": str(data / "app.db")},
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    async with httpx.AsyncClient() as c:
        for _ in range(50):
            if proc.poll() is not None:
                raise RuntimeError(f"API didn't start: {proc.stderr.read()[-500:]}")
            try:
                r = await c.get(f"http://127.0.0.1:{port}/health", timeout=1)
            except httpx.HTTPError:
                await asyncio.sleep(0.2)
                continue
            if r.status_code == 200:
                return proc, port
            proc.kill()
            raise RuntimeError(f"The API's health check failed (GET /health returned {r.status_code}).")
    proc.kill()
    raise RuntimeError("API didn't start in time")


def stop(handle: tuple[subprocess.Popen, int]) -> None:
    proc, _ = handle
    proc.terminate()
    try:
        proc.wait(5)
    except subprocess.TimeoutExpired:
        proc.kill()
