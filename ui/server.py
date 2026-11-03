"""Web UI backend: wraps the agents for the browser.

    .venv/bin/python -m ui        # http://127.0.0.1:7860

Agent work (chat, design, build) runs in a background thread; the page polls
GET /api/state and shows `busy` while it runs. One project is open at a time.
"""
import json
import os
import pathlib
import re
import socket
import subprocess
import threading
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agents import architect, coder, orchestrator, requirements
from core import sandbox
from core.llm import get_llm, load_env
from core.codemap import code_map
from core.scaffold import export_zip
from core.state import Message, ProjectState

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATIC = pathlib.Path(__file__).resolve().parent / "static"
WORKSPACES = coder.ROOT


class Session:
    # ponytail: one global session = single user; key sessions by cookie if this is ever shared
    def __init__(self):
        self.state = ProjectState()
        self.revisions: list[str] = []      # change requests the user made after the first spec
        self.busy: Optional[str] = None     # label of the running agent job
        self.error: Optional[str] = None
        self.llm = None
        self.server: Optional[tuple] = None  # (process, port) of the running generated API
        self.lock = threading.Lock()

    def get_llm(self):
        if self.llm is None:
            self.llm = get_llm()
        return self.llm


S = Session()


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "project"


def _project_dir() -> Optional[pathlib.Path]:
    if S.state.workspace:
        return pathlib.Path(S.state.workspace)
    if S.state.spec:
        return WORKSPACES / _slug(S.state.spec.project_name)
    return None


def _save():
    d = _project_dir()
    if d is None:
        return
    d.mkdir(parents=True, exist_ok=True)
    (d / "state.json").write_text(json.dumps({"state": S.state.model_dump(mode="json"), "revisions": S.revisions}, indent=1))


def _stop_server():
    if S.server:
        proc, port = S.server
        sandbox.stop(proc, port)
        S.server = None


def _job(label: str, fn):
    """Run fn in a background thread with S.busy set. 409 if another job is running."""
    with S.lock:
        if S.busy:
            raise HTTPException(409, f"Busy: {S.busy}")
        S.busy, S.error = label, None

    def work():
        try:
            fn()
        except Exception as e:  # surface to the page instead of killing the thread silently
            S.error = f"{type(e).__name__}: {str(e)[:400]}"
        finally:
            _save()
            S.busy = None

    threading.Thread(target=work, daemon=True).start()
    return snapshot()


def _phase() -> str:
    st = S.state
    if st.requirements is None or st.spec is None:
        return "chat"
    if not st.spec_approved:
        return "review"
    return "built" if st.build_ok else "build"


def snapshot() -> dict:
    llm = S.llm
    return {
        "state": S.state.model_dump(mode="json"),
        "revisions": S.revisions,
        "phase": _phase(),
        "busy": S.busy,
        "error": S.error,
        "server": {"port": S.server[1], "url": f"http://127.0.0.1:{S.server[1]}"} if S.server else None,
        "model": llm.model if llm else os.getenv("LLM_MODEL") or "",
        "tokens": llm.tokens if llm else 0,
    }


# ---------- agent flow ----------

def _design():
    S.busy = "Designing your API..."
    S.state = architect.run(S.state, S.get_llm())


def _build():
    S.busy = "Building your API..."
    _stop_server()
    S.state = orchestrator.build(S.state, S.get_llm())


class Text(BaseModel):
    text: str


@asynccontextmanager
async def lifespan(app):
    load_env()
    yield
    _stop_server()


app = FastAPI(title="Prosit 2 UI", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/state")
def get_state():
    return snapshot()


@app.post("/api/chat")
def chat(body: Text):
    """Composer message. Before a spec: talk to the requirements agent. After: it's a change request."""
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "Empty message")
    if _phase() in ("review", "built", "build") and S.state.spec:
        return change(body)

    def work():
        S.state.chat.append(Message(role="user", content=text))
        S.state = requirements.run(S.state, S.get_llm())
        if S.state.requirements is not None:
            _design()

    return _job("Thinking...", work)


@app.post("/api/spec/change")
def change(body: Text):
    text = body.text.strip()
    if not S.state.spec:
        raise HTTPException(409, "No spec yet")

    def work():
        S.revisions.append(text)
        S.state.change_request = text
        _design()

    return _job("Updating the design...", work)


@app.post("/api/spec/approve")
def approve():
    if not S.state.spec:
        raise HTTPException(409, "No spec yet")

    def work():
        S.state.spec_approved = True
        _build()

    return _job("Building your API...", work)


@app.post("/api/build")
def rebuild():
    if not S.state.spec_approved:
        raise HTTPException(409, "Approve the spec first")
    return _job("Building your API...", _build)


# ---------- projects ----------

@app.get("/api/projects")
def projects():
    out = []
    for f in sorted(WORKSPACES.glob("*/state.json")):
        try:
            st = json.loads(f.read_text())["state"]
            out.append({"slug": f.parent.name, "name": (st.get("spec") or {}).get("project_name", f.parent.name),
                        "built": st.get("build_ok", False)})
        except (json.JSONDecodeError, KeyError):
            continue
    cur = _project_dir()
    return {"projects": out, "current": cur.name if cur else None}


class Slug(BaseModel):
    slug: str


@app.post("/api/projects/open")
def open_project(body: Slug):
    f = (WORKSPACES / body.slug / "state.json").resolve()
    if WORKSPACES.resolve() not in f.parents or not f.exists():
        raise HTTPException(404, "No such project")
    if S.busy:
        raise HTTPException(409, f"Busy: {S.busy}")
    _stop_server()
    data = json.loads(f.read_text())
    S.state, S.revisions, S.error = ProjectState.model_validate(data["state"]), data.get("revisions", []), None
    return snapshot()


@app.post("/api/projects/new")
def new_project():
    if S.busy:
        raise HTTPException(409, f"Busy: {S.busy}")
    _stop_server()
    S.state, S.revisions, S.error = ProjectState(), [], None
    return snapshot()


# ---------- files & search ----------

def _files() -> list[pathlib.Path]:
    d = _project_dir()
    if not d or not d.exists():
        return []
    return [p for p in sorted(d.rglob("*")) if p.is_file() and "__pycache__" not in p.parts and p.name != "state.json"]


@app.get("/api/files")
def files():
    d = _project_dir()
    return {"files": [str(p.relative_to(d)) for p in _files()]}


@app.get("/api/file")
def read_file(path: str):
    d = _project_dir()
    if not d:
        raise HTTPException(404, "No project")
    p = (d / path).resolve()
    if d.resolve() not in p.parents or not p.is_file():
        raise HTTPException(404, "No such file")
    return {"path": path, "content": p.read_text(errors="replace")}


@app.get("/api/search")
def search(q: str):
    q = q.strip().lower()
    if not q:
        return {"results": []}
    d, out = _project_dir(), []
    for p in _files():
        for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
            if q in line.lower():
                out.append({"path": str(p.relative_to(d)), "line": i, "text": line.strip()[:200]})
    return {"results": out[:200]}


@app.get("/api/map")
def project_map():
    d = _project_dir()
    if not d or not (d / "app").is_dir():
        return {"nodes": [], "edges": []}
    return code_map(d)


@app.get("/api/export")
def export():
    d = _project_dir()
    if not d or not d.exists() or not _files():
        raise HTTPException(404, "Nothing to export yet")
    return Response(export_zip(d), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{d.name}.zip"'})


# ---------- run / try it ----------

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@app.post("/api/run")
def run_api():
    if not S.state.build_ok or not S.state.workspace:
        raise HTTPException(409, "Build the API first")
    if S.server:
        return snapshot()
    port = _free_port()
    proc = sandbox.serve(S.state.workspace, port)
    if not sandbox.wait_ready(proc, port):
        err = proc.stderr.read()[-500:] if proc.poll() is not None else "timed out"
        sandbox.stop(proc, port)
        raise HTTPException(500, f"API didn't start: {err}")
    S.server = (proc, port)
    return snapshot()


@app.post("/api/run/stop")
def stop_api():
    _stop_server()
    return snapshot()


class TryRequest(BaseModel):
    method: str
    path: str
    headers: dict[str, str] = {}
    body: Optional[str] = None


@app.post("/api/try")
def try_request(req: TryRequest):
    """Proxy a request to the running generated API (avoids CORS in the browser)."""
    if not S.server:
        raise HTTPException(409, "Start the API first")
    if not req.path.startswith("/"):
        raise HTTPException(422, "Path must start with /")
    url = f"http://127.0.0.1:{S.server[1]}{req.path}"
    content = req.body if req.body and req.method.upper() not in ("GET", "DELETE") else None
    headers = {**req.headers, **({"Content-Type": "application/json"} if content else {})}
    try:
        r = httpx.request(req.method.upper(), url, headers=headers, content=content, timeout=15)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Request failed: {e}")
    return {"status": r.status_code, "body": r.text[:20000], "ms": round(r.elapsed.total_seconds() * 1000)}


# ---------- settings ----------

def _git_name() -> str:
    try:
        return subprocess.run(["git", "config", "user.name"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    except OSError:
        return ""


class Settings(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None
    sandbox: Optional[str] = None
    user_name: Optional[str] = None


@app.get("/api/settings")
def get_settings():
    return {"provider": os.getenv("LLM_PROVIDER", "gemini"), "model": os.getenv("LLM_MODEL", ""),
            "sandbox": os.getenv("SANDBOX", "docker"), "user_name": os.getenv("UI_USER_NAME") or _git_name() or "You",
            "providers": ["gemini", "claude-code", "claude"]}


@app.post("/api/settings")
def set_settings(body: Settings):
    if body.provider is not None and body.provider not in ("gemini", "claude-code", "claude"):
        raise HTTPException(422, "Unknown provider")
    if body.sandbox is not None and body.sandbox not in ("docker", "local"):
        raise HTTPException(422, "Unknown sandbox")
    # ponytail: applies to this server process only, not written to .env
    for key, val in (("LLM_PROVIDER", body.provider), ("LLM_MODEL", body.model),
                     ("SANDBOX", body.sandbox), ("UI_USER_NAME", body.user_name)):
        if val is not None:
            if val.strip():
                os.environ[key] = val.strip()
            else:
                os.environ.pop(key, None)
    S.llm = None  # rebuilt with the new settings on next use
    return get_settings()
