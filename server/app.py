"""Gateway: the only thing the browser talks to.

    python -m server        # http://localhost:8000

Each browser gets a session (cookie). Agent work runs as an asyncio task and every step is
pushed to the page over Server-Sent Events (GET /api/events); the page then re-reads
GET /api/state. The running generated API is reached through /api/app/..., never a
localhost port, so the same code works when hosted.

Publishing gives a built API a permanent home at its own subdomain (PUBLISH_URL). The gateway
routes requests by Host header, so locally http://<name>.localhost:8000 works with no DNS
setup, and hosted it needs one wildcard DNS record pointing at this server.
"""
import asyncio
import io
import json
import mimetypes
import os
import re
import secrets
import zipfile
import shutil
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.codemap import code_map
from core.events import Event
from core.state import Message, ProjectState
from agents import orchestrator
from agents import requirements as req_agent
# Placeholder until the serve sandbox (core/sandbox) lands. Which agents run is set in agents/orchestrator.py.
from server.stubs import serve, stop

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "ui" / "static"
WORKSPACES = Path(os.getenv("WORKSPACE_DIR", ROOT / "workspace")).resolve()
APP_PREFIX = "/api/app"   # where the running generated API is proxied
SID_RE = re.compile(r"[A-Za-z0-9_-]{16,64}")
SKIP = {"__pycache__", ".pytest_cache", "data", "state.json"}
PUBLISH_URL = os.getenv("PUBLISH_URL", "http://{sub}.localhost:8000")   # {sub} is the user's subdomain
PUBLISH_SUFFIX = urlsplit(PUBLISH_URL.format(sub="x")).hostname[1:]       # ".localhost"
PUBLISHED_DIR = WORKSPACES / "_published"                                 # can't clash with a session id
REGISTRY = PUBLISHED_DIR / "registry.json"
SUB_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{1,30}[a-z0-9])")              # 3-32 chars, DNS-safe
TRAEFIK_DIR = os.getenv("TRAEFIK_DYNAMIC_DIR")                          # hosted behind Coolify's Traefik
TRAEFIK_TARGET = os.getenv("TRAEFIK_SERVICE_URL", "http://localhost:8000")  # this gateway, as Traefik reaches it
RESERVED = {"www", "api", "app", "admin", "mail", "static", "docs", "status", "dashboard", "mesora", "blocks"}


class Session:
    # ponytail: the cookie only separates browsers; real sign-in comes with hosting
    def __init__(self, sid: str):
        self.root = WORKSPACES / sid
        self.state = ProjectState()
        self.revisions: list[str] = []      # change requests after the first spec
        self.queued: list[str] = []         # messages sent while a job was running; sent when it ends
        self.busy: Optional[str] = None     # label of the running job
        self.error: Optional[str] = None
        self.user_name = "You"
        self.server = None                  # handle of the running generated API
        self.task: Optional[asyncio.Task] = None
        self.listeners: set[asyncio.Queue] = set()

    async def emit(self, ev: Event) -> None:
        if ev.type == "status" and self.busy:   # e.g. the orchestrator says "Designing your API..."
            self.busy = ev.detail
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
        "queued": s.queued,
        "phase": _phase(s),
        "busy": s.busy,
        "error": s.error,
        "server": {"url": APP_PREFIX} if s.server else None,
        "model": os.getenv("LLM_MODEL", "stub agents"),
        "tokens": sum(l.tokens for l in s.state.logs),
        "cost_usd": round(sum(l.cost_usd for l in s.state.logs), 4),
        "published": _published_for(s),
        "publish_url": PUBLISH_URL,
        **_chat_extras(s),
    }


def _chat_extras(s: Session) -> dict:
    """Quick replies for the last question, and the summary waiting for the user's OK."""
    pending = req_agent.pending_summary(s.state)
    last = next((l for l in reversed(s.state.logs) if l.agent == "requirements"), None)
    options = json.loads(last.detail).get("options", []) if last and last.action == "ask" and s.state.requirements is None else []
    return {"reply_options": options, "pending_summary": pending.model_dump() if pending else None}


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
            _send_queued(s)

    s.task = asyncio.create_task(work())
    return snapshot(s)


# ---------- app ----------

@asynccontextmanager
async def lifespan(app):
    for sub in _registry():   # published APIs come back after a restart
        if sub in LIVE:
            continue
        try:
            LIVE[sub] = await serve(str(PUBLISHED_DIR / sub), "")
            _edge_route(sub, True)
        except RuntimeError as e:
            print(f"Could not restart published API {sub}: {e}")
    yield
    for s in SESSIONS.values():
        _stop_server(s)
    for handle in LIVE.values():
        stop(handle)
    LIVE.clear()


app = FastAPI(title="Mesora Blocks gateway", lifespan=lifespan)
mimetypes.add_type("application/manifest+json", ".webmanifest")
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


@app.get("/health", include_in_schema=False)
def gateway_health():
    return {"status": "ok"}


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    # served from the root so it controls the whole app; never cached, so updates reach users
    return FileResponse(STATIC / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(STATIC / "favicon-32.png", media_type="image/png")


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
    s.state = await orchestrator.design(s.state, s.emit)


async def _build(s: Session) -> None:
    _stop_server(s)
    d = _project_dir(s) or s.root / _slug(s.state.requirements.project_name)   # solo: no spec yet
    d.mkdir(parents=True, exist_ok=True)
    s.state.workspace = str(d)
    s.state = await (orchestrator.build_solo if orchestrator.solo_mode() else orchestrator.build)(s.state, s.emit)


async def _after_requirements(s: Session) -> None:
    """Requirements confirmed: the team designs (then waits for approval); solo builds straight away."""
    await (_build(s) if orchestrator.solo_mode() else _design(s))


MENTION_RE = re.compile(r"(?:^|\s)@([\w./-]+)")


def mentions(s: Session, text: str) -> list[str]:
    """Workspace files the user @mentioned, e.g. "@app/main.py". Anything else is left as plain text."""
    known = {str(p.relative_to(_project_dir(s))) for p in _files(s)}
    return list(dict.fromkeys(m.rstrip(".,") for m in MENTION_RE.findall(text) if m.rstrip(".,") in known))


def _send_queued(s: Session) -> None:
    """A job ended: send what the user typed meanwhile, as one message."""
    if not s.queued:
        return
    text, s.queued = "\n\n".join(s.queued), []
    if s.error:   # don't run on top of a failure; hand the words back instead of losing them
        s.error += f"\n\nNot sent (please send again): {text}"
        return
    _dispatch(s, text)


def _dispatch(s: Session, text: str) -> dict:
    """Before a spec, a message goes to the requirements agent; after, it's a change request."""
    if s.state.spec or (orchestrator.solo_mode() and s.state.requirements):
        return _change(s, text)

    async def work():
        s.state.chat.append(Message(role="user", content=text))
        s.state = await orchestrator.chat(s.state, s.emit)
        if orchestrator.solo_mode() and s.state.requirements is not None:   # typed "looks right"
            await _build(s)

    return _job(s, "Thinking...", work)


@app.post("/api/chat")
async def chat(body: Text, request: Request):
    """Composer message. While a job runs it is queued (shown in the chat) and sent when the job ends."""
    s, text = sess(request), body.text.strip()
    if not text:
        raise HTTPException(422, "Empty message")
    if s.busy:
        s.queued.append(text)
        await s.emit(Event(type="status", detail=s.busy))
        return snapshot(s)
    return _dispatch(s, text)


@app.post("/api/requirements/confirm")
async def confirm_requirements(request: Request):
    """The "Looks right" button: lock in the pending summary (no model call), then design."""
    s = sess(request)
    if req_agent.pending_summary(s.state) is None:
        raise HTTPException(409, "No summary is waiting for your OK")

    async def work():
        s.state.chat.append(Message(role="user", content="Looks right."))
        s.state = await req_agent.confirm(s.state, s.emit)
        await _after_requirements(s)

    return _job(s, "Designing your API...", work)


@app.post("/api/spec/change")
async def change(body: Text, request: Request):
    s, text = sess(request), body.text.strip()
    if not s.state.spec:
        raise HTTPException(409, "No spec yet")
    return _change(s, text)


def _change(s: Session, text: str) -> dict:
    """Change request. @mentioned files go to state.change_files for the Architect and Coder."""
    async def work():
        s.revisions.append(text)
        s.state.change_request, s.state.change_files = text, mentions(s, text)
        await (_build(s) if orchestrator.solo_mode() else _design(s))

    return _job(s, "Updating your API..." if orchestrator.solo_mode() else "Updating the design...", work)


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
    s.state, s.revisions, s.error, s.queued = ProjectState.model_validate(data["state"]), data.get("revisions", []), None, []
    return snapshot(s)


@app.post("/api/projects/new")
def new_project(request: Request):
    s = sess(request)
    if s.busy:
        raise HTTPException(409, f"Busy: {s.busy}")
    _stop_server(s)
    s.state, s.revisions, s.error, s.queued = ProjectState(), [], None, []
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
        if s.state.result:   # the API is reached through the gateway, never a localhost port
            s.state.result.base_url, s.state.result.docs_url = APP_PREFIX, APP_PREFIX + "/docs"
    return snapshot(s)


@app.post("/api/run/stop")
def stop_api(request: Request):
    s = sess(request)
    _stop_server(s)
    return snapshot(s)


HOP = {"host", "cookie", "content-length", "connection", "accept-encoding"}


async def _forward(request: Request, port: int, path: str) -> Response:
    """Send the request on to an API on 127.0.0.1. The gateway's cookie is never passed on."""
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
    async with httpx.AsyncClient() as c:
        try:
            r = await c.request(request.method, f"http://127.0.0.1:{port}/{path}", params=request.query_params,
                                headers=headers, content=await request.body(), timeout=15)
        except httpx.HTTPError as e:
            return Response(f"Request failed: {e}", status_code=502)
    keep = {k: v for k, v in r.headers.items() if k.lower() in ("content-type", "location")}
    return Response(r.content, status_code=r.status_code, headers=keep)


@app.api_route(APP_PREFIX + "/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(path: str, request: Request):
    """Forward to this session's running API (the Run view's "try it")."""
    s = sess(request)
    if not s.server:
        raise HTTPException(409, "Start the API first")
    return await _forward(request, s.server[1], path)


# ---------- publish: a permanent URL at <subdomain>PUBLISH_SUFFIX ----------
# ponytail: the session cookie stands in for an account, so whoever holds it owns the subdomain;
# real sign-in, per-user limits and the serve sandbox for public traffic come with hosting.

LIVE: dict[str, tuple] = {}   # subdomain -> handle of the running published API


def _registry() -> dict:
    return json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {}


def _save_registry(reg: dict) -> None:
    PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(reg, indent=1))


def _published_for(s: Session) -> Optional[dict]:
    d = _project_dir(s)
    for sub, e in _registry().items():
        if d and e["owner"] == s.root.name and e["project"] == str(d):
            return {"subdomain": sub, "url": PUBLISH_URL.format(sub=sub), "published_at": e["published_at"]}
    return None


def _edge_route(sub: str, on: bool) -> None:
    """Hosted: give each published subdomain its own HTTPS route in Traefik, so Let's Encrypt issues
    its certificate on the first visit. (A wildcard certificate would need DNS API access instead.)"""
    if not TRAEFIK_DIR:
        return
    f = Path(TRAEFIK_DIR) / f"mesora-{sub}.yaml"   # sub is validated by SUB_RE, safe in a file name and YAML
    if not on:
        f.unlink(missing_ok=True)
        return
    host = urlsplit(PUBLISH_URL.format(sub=sub)).hostname
    f.write_text(f"""http:
  routers:
    mesora-{sub}:
      rule: Host(`{host}`)
      entryPoints: [https]
      service: mesora-{sub}
      tls:
        certResolver: letsencrypt
  services:
    mesora-{sub}:
      loadBalancer:
        servers:
          - url: "{TRAEFIK_TARGET}"
""")


def _check(sub: str, s: Session) -> Optional[str]:
    """Why this subdomain can't be used, or None if it can."""
    if not SUB_RE.fullmatch(sub):
        return "Use 3-32 lowercase letters, numbers or dashes, starting and ending with a letter or number."
    if sub in RESERVED:
        return "That name is reserved."
    e = _registry().get(sub)
    if e and not (e["owner"] == s.root.name and e["project"] == str(_project_dir(s))):
        return "That name is taken."
    return None


@app.get("/api/publish/check")
def publish_check(sub: str, request: Request):
    reason = _check(sub.strip().lower(), sess(request))
    return {"available": reason is None, "reason": reason}


class Publish(BaseModel):
    subdomain: str


@app.post("/api/publish")
async def publish(body: Publish, request: Request):
    """Publish (or update) the current build. The live copy is a snapshot: later builds change it only when published again."""
    s, sub = sess(request), body.subdomain.strip().lower()
    if not s.state.build_ok or not s.state.workspace:
        raise HTTPException(409, "Build the API first")
    if reason := _check(sub, s):
        raise HTTPException(422, reason)
    old = _published_for(s)
    if old:   # one subdomain per project: updating or renaming replaces the old one
        await _unpublish(old["subdomain"])
    dest = PUBLISHED_DIR / sub
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(Path(s.state.workspace) / "app", dest / "app", ignore=shutil.ignore_patterns("__pycache__"))
    try:
        LIVE[sub] = await serve(str(dest), "")
    except RuntimeError as e:
        shutil.rmtree(dest, ignore_errors=True)
        raise HTTPException(500, str(e))
    reg = _registry()
    reg[sub] = {"owner": s.root.name, "project": s.state.workspace,
                "published_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    _save_registry(reg)
    _edge_route(sub, True)
    await s.emit(Event(type="status", agent="gateway", detail=f"Published at {PUBLISH_URL.format(sub=sub)}"))
    return snapshot(s)


async def _unpublish(sub: str) -> None:
    if sub in LIVE:
        stop(LIVE.pop(sub))
    shutil.rmtree(PUBLISHED_DIR / sub, ignore_errors=True)
    _edge_route(sub, False)
    reg = _registry()
    reg.pop(sub, None)
    _save_registry(reg)


@app.delete("/api/publish")
async def unpublish(request: Request):
    s = sess(request)
    cur = _published_for(s)
    if not cur:
        raise HTTPException(404, "Not published")
    await _unpublish(cur["subdomain"])
    return snapshot(s)


@app.middleware("http")
async def published_host(request: Request, call_next):
    """Requests to <sub>PUBLISH_SUFFIX go straight to that published API, with no session."""
    host = (request.headers.get("host") or "").split(":")[0].lower()
    if host.endswith(PUBLISH_SUFFIX) and host != PUBLISH_SUFFIX[1:]:
        sub = host[: -len(PUBLISH_SUFFIX)]
        if sub in RESERVED:   # www.<domain> and friends are the app itself
            return await call_next(request)
        if sub not in LIVE:
            return Response("No API is published at this address.", status_code=404, media_type="text/plain")
        return await _forward(request, LIVE[sub][1], request.url.path.lstrip("/"))
    return await call_next(request)


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
