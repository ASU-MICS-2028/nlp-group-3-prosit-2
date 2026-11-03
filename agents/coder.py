"""Coder agent: builds a FastAPI app from the approved spec with a text ReAct loop.

Each step the LLM replies {"thought": ..., "action": <tool or "finish">, "args": {...}}.
Our code runs the tool and sends the observation back. Done when the sandbox
checks pass and the LLM calls finish; gives up after MAX_STEPS.
"""
import json
import pathlib
import re
import time
from typing import Callable, Optional

from core.llm import LLM, extract_json
from core.sandbox import run_checks
from core.state import LogEntry, ProjectState
from core.scaffold import scaffold
from core.tools import Tool, describe

MAX_STEPS = 20
MAX_FILE = 100_000
MAX_OBS = 4000
ROOT = pathlib.Path(__file__).resolve().parent.parent / "workspace"

SYSTEM = """You are the coder agent. You build a Python FastAPI backend that implements the given API spec exactly.

You work in steps. Each reply is ONE JSON object and nothing else:
{{"thought": "<one line: what this step does>", "action": "<tool name or finish>", "args": {{...}}}}

Tools:
{tools}
- finish: you are done. args: {{}}. Only allowed after run_checks passed with no file changes since.

Project layout (required; finish is refused until it exists):
  app/main.py              creates `app = FastAPI(title=...)` and includes the routers. Nothing else.
  app/dependencies.py      auth dependencies (reading X-Role / X-User-Id, role checks)
  app/database.py          in-memory storage and id generation
  app/schemas/<name>.py    Pydantic models per resource: <Entity>Create, <Entity>Update, <Entity> (response)
  app/routers/<name>.py    one APIRouter per resource (prefix + tags), thin handlers
  app/services/<name>.py   business rules and validation used by the routers (when the spec has rules)
  Use snake_case module names (e.g. food_entries.py). Absolute imports: `from app.schemas.food_entries import ...`.
  Add a module docstring to each file and type hints on functions. Keep files focused and readable.

Conventions (follow them, the tester relies on them):
- Implement every endpoint in the spec with the exact method and path, and the spec's status_code on success.
- Storage: in-memory dicts, ids are ints assigned by the server. No database, no files, no network.
- Auth via headers: X-Role ("user" or "admin") and X-User-Id (int).
  access "public": no header needed. "user": 401 if X-Role missing/invalid. "admin": 401 if missing, 403 if X-Role is "user".
  If the rules say users only see their own records, store the owner's X-User-Id and filter by it (404 for others' records).
- Pydantic models for request bodies: accept only the endpoint's request_fields; never accept read_only fields.
- 404 for unknown ids, 409 for uniqueness/conflict rules, 422 for invalid input. Enforce every rule in the spec.
- Only use fastapi, pydantic and the standard library. No secrets in code.

Work efficiently: write ALL files in one write_files call, then run_checks, fix what it reports, run_checks again, then finish."""

# layout the finish gate requires: files, and folders that need at least one module
REQUIRED_FILES = ["app/main.py", "app/dependencies.py", "app/database.py"]
REQUIRED_DIRS = ["app/routers", "app/schemas"]


def layout_problems(ws: pathlib.Path) -> list[str]:
    problems = [f"missing {f}" for f in REQUIRED_FILES if not (ws / f).is_file()]
    for d in REQUIRED_DIRS:
        if not [p for p in (ws / d).glob("*.py") if p.name != "__init__.py"]:
            problems.append(f"missing modules in {d}/")
    return problems


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "project"


def make_tools(ws: pathlib.Path, status: dict) -> list[Tool]:
    """Tools bound to one workspace. `status` tracks whether checks passed since the last write."""

    def safe(path: str) -> pathlib.Path:
        p = (ws / path).resolve()
        if ws not in p.parents and p != ws:
            raise ValueError(f"path {path!r} is outside the workspace")
        return p

    def list_files() -> str:
        files = [str(p.relative_to(ws)) for p in sorted(ws.rglob("*")) if p.is_file() and "__pycache__" not in p.parts]
        return "\n".join(files) or "(empty)"

    def read_file(path: str) -> str:
        return safe(path).read_text()

    def write_file(path: str, content: str) -> str:
        p = safe(path)
        rel = p.relative_to(ws)
        if rel.parts[0] != "app" or p.suffix != ".py":  # tests/ belongs to the tester
            raise ValueError("you may only write .py files under app/")
        if len(content) > MAX_FILE:
            raise ValueError(f"file too large ({len(content)} chars, max {MAX_FILE})")
        p.parent.mkdir(parents=True, exist_ok=True)
        if rel.parts[0] == "app":  # every package folder under app/ needs an __init__.py
            for i in range(1, len(rel.parts)):
                init = ws.joinpath(*rel.parts[:i], "__init__.py")
                if not init.exists():
                    init.write_text("")
        p.write_text(content)
        status["passed"] = False
        return f"wrote {rel} ({len(content)} chars)"

    def write_files(files: list) -> str:
        if not isinstance(files, list) or not files:
            raise ValueError("files must be a non-empty list of {path, content}")
        return "\n".join(write_file(f["path"], f["content"]) for f in files)

    def checks() -> str:
        report = run_checks(str(ws))
        status["passed"] = bool(report.get("ok"))
        status["report"] = report
        return json.dumps(report, indent=1)

    return [
        Tool("list_files", "List files in the workspace.", {"type": "object", "properties": {}}, list_files),
        Tool("read_file", "Read a workspace file.",
             {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}, read_file),
        Tool("write_file", "Create or overwrite a .py file under app/ with the full content.",
             {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
              "required": ["path", "content"]}, write_file),
        Tool("write_files", "Create or overwrite several .py files at once (same rules as write_file).",
             {"type": "object", "properties": {"files": {"type": "array", "items": {
                 "type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                 "required": ["path", "content"]}}}, "required": ["files"]}, write_files),
        Tool("run_checks", "Run the app in the sandbox: import it, compare its routes to the spec, smoke-test GETs, "
             "run tests/ if present. Returns a JSON report with ok=true when everything passes.",
             {"type": "object", "properties": {}}, checks),
    ]


def _task(state: ProjectState) -> str:
    parts = [f"API spec:\n{state.spec.model_dump_json(indent=1)}", "Build tasks:\n" + "\n".join(f"- {t}" for t in state.tasks)]
    if state.test_report:
        parts.append("Your code is already in the workspace. Read the files involved and change only what the "
                     f"report needs; run_checks runs the tester's tests.\n\n{state.test_report}")
    return "\n\n".join(parts)


def _trim(step: dict) -> str:
    """History copy of a step: drop big file contents (the file is on disk, read_file gets it back)."""
    def short(c):
        return f"<{len(c)} chars, written to disk>" if isinstance(c, str) and len(c) > 300 else c
    args = step.get("args") or {}
    if isinstance(args, dict):
        args = {**args, "content": short(args["content"])} if "content" in args else args
        if isinstance(args.get("files"), list):
            args = {**args, "files": [{**f, "content": short(f.get("content"))} if isinstance(f, dict) else f
                                      for f in args["files"]]}
    return json.dumps({**step, "args": args})


def run(state: ProjectState, llm: LLM, on_step: Optional[Callable[[LogEntry], None]] = None) -> ProjectState:
    """on_step, if given, is called with each step's LogEntry as it happens (for live progress)."""
    if state.spec is None or not state.spec_approved:
        raise ValueError("coder needs an approved spec")
    ws = pathlib.Path(state.workspace) if state.workspace else ROOT / _slug(state.spec.project_name)
    ws = ws.resolve()
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "spec.json").write_text(state.spec.model_dump_json(indent=1))
    state.workspace = str(ws)

    status = {"passed": False, "report": None}
    tools = {t.name: t for t in make_tools(ws, status)}
    system = SYSTEM.format(tools=describe(list(tools.values())))
    msgs = [{"role": "user", "content": _task(state)}]
    state.build_ok = False

    for step_no in range(1, MAX_STEPS + 1):
        t0, tok0 = time.time(), llm.tokens
        try:
            reply = llm(system, msgs)
        except Exception as e:  # provider failure (quota, safety filter, network): stop, keep the workspace
            state.logs.append(LogEntry(agent="coder", action="gave_up",
                                       detail=f"LLM error at step {step_no}: {type(e).__name__}: {str(e)[:300]}"))
            return state
        try:
            step = extract_json(reply)
            action, args = step["action"], step.get("args") or {}
            if not isinstance(args, dict):
                raise ValueError("args must be an object")
        except (ValueError, KeyError, TypeError) as e:
            step, action, obs = {"thought": f"invalid reply: {e}", "raw": reply[:300]}, "invalid", f"Invalid reply ({e}). Reply with ONE JSON object: thought, action, args."
        else:
            if action == "finish":
                problems = layout_problems(ws)
                if problems:
                    obs = "Cannot finish: the project layout is incomplete: " + "; ".join(problems) + ". Split the code as described."
                elif not status["passed"]:
                    obs = "Cannot finish: run_checks has not passed since your last change. Run it and fix the failures."
                else:
                    obs = None
            elif action in tools:
                try:
                    obs = tools[action].fn(**args)
                except Exception as e:  # tool errors go back to the model as observations
                    obs = f"Tool error: {type(e).__name__}: {e}"
            else:
                obs = f"Unknown action {action!r}. Use one of: {', '.join(tools)}, finish."

        state.logs.append(LogEntry(agent="coder", action=action, detail=str(step.get("thought", ""))[:300],
                                   tokens=llm.tokens - tok0, seconds=round(time.time() - t0, 3)))
        if on_step:
            on_step(state.logs[-1])
        if action == "finish" and obs is None:
            scaffold(ws, state.spec)  # README, requirements, Dockerfile: written by us, not the LLM
            state.build_ok = True
            state.test_report = None
            state.logs.append(LogEntry(agent="coder", action="done", detail=f"{step_no} steps, {ws}"))
            return state
        msgs += [{"role": "assistant", "content": _trim(step)},
                 {"role": "user", "content": f"Observation:\n{obs[:MAX_OBS]}"}]

    state.logs.append(LogEntry(agent="coder", action="gave_up",
                               detail=f"{MAX_STEPS} steps; last report: {json.dumps(status['report'])[:500]}"))
    return state
