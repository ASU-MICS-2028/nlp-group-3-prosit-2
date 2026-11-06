"""Gateway: the only thing the browser talks to.

    python -m server        # http://localhost:8000

Each browser gets a session (cookie). Agent work runs as an asyncio task and every step is
pushed to the page over Server-Sent Events (GET /api/events); the page then re-reads
GET /api/state. The running generated API is reached through /api/app/..., never a
localhost port, so the same code works when hosted.
"""
import asyncio
import io
import json
import os
import re
import secrets
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.codemap import code_map
from core.events import Event
from core.state import Message, ProjectState
# Placeholders until the real agents (agents/*) and serve sandbox (core/sandbox) land.
from server.stubs import architect, build, requirements, serve, stop

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "ui" / "static"
WORKSPACES = Path(os.getenv("WORKSPACE_DIR", ROOT / "workspace")).resolve()
APP_PREFIX = "/api/app"   # where the running generated API is proxied
SID_RE = re.compile(r"[A-Za-z0-9_-]{16,64}")
SKIP = {"__pycache__", ".pytest_cache", "data", "state.json"}


class Session:
    # ponytail: the cookie only separates browsers; real sign-in comes with hosting
    def __init__(self, sid: str):
        self.root = WORKSPACES / sid
        self.state = ProjectState()
        self.revisions: list[str] = []      # change requests after the first spec
        self.busy: Optional[str] = None     # label of the running job
        self.error: Optional[str] = None
        self.user_name = "You"
        self.server = None                  # handle of the running generated API
        self.task: Optional[asyncio.Task] = None
        self.listeners: set[asyncio.Queue] = set()

    async def emit(self, ev: Event) -> None:
        for q in self.listeners:
            q.put_nowait(ev.model_dump())


SESSIONS: dict[str, Session] = {}


def sess(request: Request) -> Session:
    sid = request.state.sid
    if sid not in SESSIONS:
        SESSIONS[sid] = Session(sid)
    return SESSIONS[sid]


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "project"


def _project_dir(s: Session) -> Optional[Path]:
    if s.state.workspace:
        return Path(s.state.workspace)
    if s.state.spec:
        return s.root / _slug(s.state.spec.project_name)
    return None


def _save(s: Session) -> None:
    d = _project_dir(s)
    if d is None:
        return
    d.mkdir(parents=True, exist_ok=True)
    (d / "state.json").write_text(json.dumps({"state": s.state.model_dump(mode="json"), "revisions": s.revisions}, indent=1))


def _stop_server(s: Session) -> None:
    if s.server:
        stop(s.server)
        s.server = None


def _phase(s: Session) -> str:
    st = s.state
    if st.requirements is None or st.spec is None:
        return "chat"
    if not st.spec_approved:
        return "review"
    return "built" if st.build_ok else "build"


def snapshot(s: Session) -> dict:
    return {
        "state": s.state.model_dump(mode="json"),
        "revisions": s.revisions,
        "phase": _phase(s),
        "busy": s.busy,
        "error": s.error,
        "server": {"url": APP_PREFIX} if s.server else None,
        "model": os.getenv("LLM_MODEL", "stub agents"),
        "tokens": sum(l.tokens for l in s.state.logs),
    }


def _job(s: Session, label: str, fn) -> dict:
    """Run the coroutine function fn as a background task. 409 if one is already running.
    Call it from an async endpoint: the task needs the server's event loop."""
    if s.busy:
        raise HTTPException(409, f"Busy: {s.busy}")
    s.busy, s.error = label, None

    async def work():
        await s.emit(Event(type="status", detail=label))
        try:
            await fn()
        except Exception as e:  # surface to the page instead of losing it in the task
            s.error = f"{type(e).__name__}: {str(e)[:400]}"
            await s.emit(Event(type="error", detail=s.error))
        finally:
            _save(s)
            s.busy = None
            await s.emit(Event(type="status", detail="idle"))

    s.task = asyncio.create_task(work())
    return snapshot(s)


# ---------- app ----------

@asynccontextmanager
async def lifespan(app):
    yield
    for s in SESSIONS.values():
        _stop_server(s)


app = FastAPI(title="Prosit Builder gateway", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def session_cookie(request: Request, call_next):
    sid = request.cookies.get("sid")
    fresh = not (sid and SID_RE.fullmatch(sid))
    request.state.sid = secrets.token_urlsafe(16) if fresh else sid
    resp = await call_next(request)
    if fresh:
        resp.set_cookie("sid", request.state.sid, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
    return resp


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/state")
def get_state(request: Request):
    return snapshot(sess(request))


@app.get("/api/events")
async def events(request: Request):
    s, q = sess(request), asyncio.Queue()
    s.listeners.add(q)

    async def stream():
        try:
            yield ": connected\n\n"
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), 15)
                    yield f"data: {json.dumps(ev)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"   # keeps proxies from closing an idle stream
        finally:
            s.listeners.discard(q)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------- agent flow ----------

class Text(BaseModel):
    text: str


async def _design(s: Session) -> None:
    s.busy = "Designing your API..."
    await s.emit(Event(type="status", detail=s.busy))
    s.state = await architect(s.state, s.emit)


async def _build(s: Session) -> None:
    s.busy = "Building your API..."
    await s.emit(Event(type="status", detail=s.busy))
    _stop_server(s)
    d = _project_dir(s)
    d.mkdir(parents=True, exist_ok=True)
    s.state.workspace = str(d)
    s.state = await build(s.state, s.emit)


@app.post("/api/chat")
async def chat(body: Text, request: Request):
    """Composer message. Before a spec it goes to the requirements agent; after, it's a change request."""
    s, text = sess(request), body.text.strip()
    if not text:
        raise HTTPException(422, "Empty message")
    if s.state.spec:
        return await change(body, request)

    async def work():
        s.state.chat.append(Message(role="user", content=text))
        s.state = await requirements(s.state, s.emit)
        if s.state.requirements is not None:
            await _design(s)

    return _job(s, "Thinking...", work)


@app.post("/api/spec/change")
async def change(body: Text, request: Request):
    s, text = sess(request), body.text.strip()
    if not s.state.spec:
        raise HTTPException(409, "No spec yet")

    async def work():
        s.revisions.append(text)
        s.state.change_request = text
        await _design(s)

    return _job(s, "Updating the design...", work)


@app.post("/api/spec/approve")
async def approve(request: Request):
    s = sess(request)
    if not s.state.spec:
        raise HTTPException(409, "No spec yet")

    async def work():
        s.state.spec_approved = True
        await _build(s)

    return _job(s, "Building your API...", work)


@app.post("/api/build")
async def rebuild(request: Request):
    s = sess(request)
    if not s.state.spec_approved:
        raise HTTPException(409, "Approve the spec first")
    return _job(s, "Building your API...", lambda: _build(s))


# ---------- projects ----------

@app.get("/api/projects")
def projects(request: Request):
    s, out = sess(request), []
    for f in sorted(s.root.glob("*/state.json")):
        try:
            st = json.loads(f.read_text())["state"]
            out.append({"slug": f.parent.name, "name": (st.get("spec") or {}).get("project_name", f.parent.name),
                        "built": st.get("build_ok", False)})
        except (json.JSONDecodeError, KeyError):
            continue
    cur = _project_dir(s)
    return {"projects": out, "current": cur.name if cur else None}


class Slug(BaseModel):
    slug: str


@app.post("/api/projects/open")
def open_project(body: Slug, request: Request):
    s = sess(request)
    f = (s.root / body.slug / "state.json").resolve()
    if s.root.resolve() not in f.parents or not f.exists():
        raise HTTPException(404, "No such project")
    if s.busy:
        raise HTTPException(409, f"Busy: {s.busy}")
    _stop_server(s)
    data = json.loads(f.read_text())
    s.state, s.revisions, s.error = ProjectState.model_validate(data["state"]), data.get("revisions", []), None
    return snapshot(s)


@app.post("/api/projects/new")
def new_project(request: Request):
    s = sess(request)
    if s.busy:
        raise HTTPException(409, f"Busy: {s.busy}")
    _stop_server(s)
    s.state, s.revisions, s.error = ProjectState(), [], None
    return snapshot(s)


# ---------- files, search, map, export ----------

def _files(s: Session) -> list[Path]:
    d = _project_dir(s)
    if not d or not d.exists():
        return []
    return [p for p in sorted(d.rglob("*")) if p.is_file() and not SKIP & set(p.relative_to(d).parts)]


@app.get("/api/files")
def files(request: Request):
    s = sess(request)
    d = _project_dir(s)
    return {"files": [str(p.relative_to(d)) for p in _files(s)]}


@app.get("/api/file")
def read_file(path: str, request: Request):
    d = _project_dir(sess(request))
    if not d:
        raise HTTPException(404, "No project")
    p = (d / path).resolve()
    if d.resolve() not in p.parents or not p.is_file():
        raise HTTPException(404, "No such file")
    return {"path": path, "content": p.read_text(errors="replace")}


@app.get("/api/search")
def search(q: str, request: Request):
    s, q = sess(request), q.strip().lower()
    if not q:
        return {"results": []}
    d, out = _project_dir(s), []
    for p in _files(s):
        for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
            if q in line.lower():
                out.append({"path": str(p.relative_to(d)), "line": i, "text": line.strip()[:200]})
    return {"results": out[:200]}


@app.get("/api/map")
def project_map(request: Request):
    d = _project_dir(sess(request))
    if not d or not (d / "app").is_dir():
        return {"nodes": [], "edges": []}
    return code_map(d)


@app.get("/api/export")
def export(request: Request):
    s = sess(request)
    d, paths = _project_dir(s), _files(s)
    if not paths:
        raise HTTPException(404, "Nothing to export yet")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in paths:
            z.write(p, f"{d.name}/{p.relative_to(d)}")
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{d.name}.zip"'})


# ---------- run the generated API ----------

@app.post("/api/run")
async def run_api(request: Request):
    s = sess(request)
    if not s.state.build_ok or not s.state.workspace:
        raise HTTPException(409, "Build the API first")
    if not s.server:
        try:
            s.server = await serve(s.state.workspace, APP_PREFIX)
        except RuntimeError as e:
            raise HTTPException(500, str(e))
    return snapshot(s)


@app.post("/api/run/stop")
def stop_api(request: Request):
    s = sess(request)
    _stop_server(s)
    return snapshot(s)


HOP = {"host", "cookie", "content-length", "connection", "accept-encoding"}


@app.api_route(APP_PREFIX + "/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(path: str, request: Request):
    """Forward to this session's running API. The gateway's cookie is never passed on."""
    s = sess(request)
    if not s.server:
        raise HTTPException(409, "Start the API first")
    url = f"http://127.0.0.1:{s.server[1]}/{path}"
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
    async with httpx.AsyncClient() as c:
        try:
            r = await c.request(request.method, url, params=request.query_params, headers=headers,
                                content=await request.body(), timeout=15)
        except httpx.HTTPError as e:
            raise HTTPException(502, f"Request failed: {e}")
    keep = {k: v for k, v in r.headers.items() if k.lower() in ("content-type", "location")}
    return Response(r.content, status_code=r.status_code, headers=keep)


# ---------- settings ----------

class Settings(BaseModel):
    user_name: Optional[str] = None


def _settings(s: Session) -> dict:
    return {"model": os.getenv("LLM_MODEL", "stub agents"), "sandbox": os.getenv("SANDBOX", "docker"),
            "user_name": s.user_name}


@app.get("/api/settings")
def get_settings(request: Request):
    return _settings(sess(request))


@app.post("/api/settings")
def set_settings(body: Settings, request: Request):
    s = sess(request)
    if body.user_name is not None:
        s.user_name = body.user_name.strip()[:60] or "You"
    return _settings(s)
