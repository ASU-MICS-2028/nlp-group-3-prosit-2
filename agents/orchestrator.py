"""Orchestrator (Role 2): runs the agents in the right order and enforces the rules.

It is plain Python, NOT an AI. These rules must hold every time, so no model gets to decide them:
  - no design before the user confirms the requirements
  - no code before the user approves the spec (human-in-the-loop)
  - at most MAX_FIX_ROUNDS Coder <-> Tester fix rounds (stop rule)
  - if a fix breaks the build, the last working code is put back

The three jobs, in order:
  chat()    user message -> Requirements agent; once the summary is confirmed -> design()
  design()  Architect makes (or changes) the spec. Then we wait for the user to approve it.
  build()   split the spec into tasks -> Coder -> Tester -> fix rounds -> result

For the evaluation, build_single() lets ONE agent do everything, to compare against the team.

Every agent has the same shape (shared contract): async def run(state, emit) -> state
"""
import os
import shutil
import tempfile
from pathlib import Path

from agents import architect, requirements, single, solo, tester
from core import layout
from core.events import Emit, Event
from core.spec import Spec
from core.state import BuildResult, LogEntry, ProjectState
from server import stubs

MAX_FIX_ROUNDS = int(os.getenv("MAX_FIX_ROUNDS", "1"))

# ---------- who does each job ----------
# REQUIREMENTS_AGENT=stub replays the golden clinic example offline (no model calls).
# ARCHITECT_AGENT=stub does the same for the architect; if unset, it follows REQUIREMENTS_AGENT.
STUB_REQUIREMENTS = os.getenv("REQUIREMENTS_AGENT") == "stub"
STUB_ARCHITECT = os.getenv("ARCHITECT_AGENT", os.getenv("REQUIREMENTS_AGENT")) == "stub"
STUB_TESTER = os.getenv("TESTER_AGENT", os.getenv("REQUIREMENTS_AGENT")) == "stub"   # same rule for the tester

AGENTS = {
    "requirements": stubs.requirements if STUB_REQUIREMENTS else requirements.run,
    "architect": stubs.architect if STUB_ARCHITECT else architect.run,
    "coder": stubs.coder,     # placeholder until Role 3's agents/coder.py lands
    "tester": stubs.tester if STUB_TESTER else tester.run,
    "single": single.run,     # single-agent mode, for the comparison in the evaluation
    "solo": solo.run,         # single-agent WORKFLOW in the app: one agent designs, codes and tests
}


def solo_mode() -> bool:
    """PIPELINE=solo (the default here): after the chat, one agent does everything.
    PIPELINE=team: architect -> approval -> coder <-> tester.
    The offline replay (REQUIREMENTS_AGENT=stub, e.g. the hosted site) stays on the team flow."""
    return os.getenv("PIPELINE", "team" if STUB_REQUIREMENTS else "solo") == "solo"


async def step(state: ProjectState, emit: Emit, action: str, detail: str = "") -> None:
    """Write one orchestrator step to the log and show it in the UI."""
    state.logs.append(LogEntry(agent="orchestrator", action=action, detail=detail))
    await emit(Event(type="step", agent="orchestrator", detail=detail, data={"action": action}))


# ---------- 1. understand ----------

async def chat(state: ProjectState, emit: Emit) -> ProjectState:
    """The user sent a message (already added to state.chat)."""
    state = await AGENTS["requirements"](state, emit)
    if state.requirements is not None and not solo_mode():   # confirmed: design (solo: the gateway builds)
        state = await design(state, emit)
    return state


# ---------- 2. design ----------

async def design(state: ProjectState, emit: Emit) -> ProjectState:
    """Architect makes the spec, or changes it if state.change_request is set."""
    if state.requirements is None:
        raise RuntimeError("Confirm the requirements before designing.")
    await emit(Event(type="status", agent="orchestrator", detail="Designing your API..."))
    state = await AGENTS["architect"](state, emit)
    # The architect leaves spec_approved = False. Nothing else happens until the user approves.
    return state


# ---------- 3. build ----------

async def build(state: ProjectState, emit: Emit) -> ProjectState:
    """Coder writes the code, Tester tests it, failures go back to the Coder."""
    if not state.spec_approved:   # human-in-the-loop: no code before the user approves the spec
        raise RuntimeError("Approve the spec before building.")
    await emit(Event(type="status", agent="orchestrator", detail="Building your API..."))
    state.build_ok, state.tests_ok, state.test_report, state.test_summary, state.test_results = False, None, None, "", []
    state.failures, state.result = [], None
    await step(state, emit, "build", "Build started")

    # Decomposition: split the approved spec into small tasks the Coder works through one by one.
    state.tasks = plan_tasks(state.spec)
    await step(state, emit, "plan", f"{len(state.tasks)} build tasks")

    # Coder first. Only test code that passed the Coder's own checks.
    state = await AGENTS["coder"](state, emit)
    if state.build_ok:
        state = await AGENTS["tester"](state, emit)

    # Fix rounds: the Tester's failure report sends the Coder back in (self-reflection),
    # but only MAX_FIX_ROUNDS times, so it can never loop forever.
    rounds = 0
    while state.build_ok and state.tests_ok is False and rounds < MAX_FIX_ROUNDS:
        rounds += 1
        await step(state, emit, "fix_round", f"Fix round {rounds} of {MAX_FIX_ROUNDS}")
        state = await fix_round(state, emit)

    # The BuildResult: what the user gets. The gateway adds base_url and docs_url when it starts the API.
    state.result = BuildResult(endpoints=[f"{e.method} {e.path}" for e in state.spec.endpoints],
                               test_summary=state.test_summary, known_failures=state.failures)
    layout.scaffold(Path(state.workspace), state.spec)   # README, requirements.txt, Dockerfile, spec.json
    write_log(state)
    await emit(Event(type="result", agent="orchestrator", detail="Build finished",
                     data={"build_ok": state.build_ok, "tests_ok": state.tests_ok}))
    return state


# ---------- single-agent workflow (PIPELINE=solo) ----------

async def build_solo(state: ProjectState, emit: Emit) -> ProjectState:
    """One agent designs, writes the code and tests, runs them and fixes, in one session.
    No approval step. Also used for change requests and rebuilds (it edits the existing project)."""
    if state.requirements is None:
        raise RuntimeError("Confirm the requirements before building.")
    await emit(Event(type="status", agent="orchestrator", detail="Building your API..."))
    state.result = None
    await step(state, emit, "build", "Single-agent build started")
    state = await AGENTS["solo"](state, emit)
    state.result = BuildResult(endpoints=[f"{e.method} {e.path}" for e in state.spec.endpoints],
                               test_summary=state.test_summary, known_failures=state.failures)
    layout.scaffold(Path(state.workspace), state.spec)
    write_log(state)
    await emit(Event(type="result", agent="orchestrator", detail="Build finished",
                     data={"build_ok": state.build_ok, "tests_ok": state.tests_ok}))
    return state


# ---------- single-agent mode (baseline for the evaluation) ----------

async def build_single(state: ProjectState, emit: Emit) -> ProjectState:
    """One agent builds everything from the requirements: no spec, no approval, no tester, no fix rounds.
    Called by the benchmark (Role 4) to compare against the multi-agent pipeline, not by the web app."""
    if state.requirements is None:
        raise RuntimeError("Confirm the requirements before building.")
    await step(state, emit, "build_single", "Single-agent build started")
    state = await AGENTS["single"](state, emit)
    write_log(state)
    return state


def plan_tasks(spec: Spec) -> list[str]:
    """One task for the setup, one per entity (its table and its endpoints), one for the rules."""
    tasks = ["Set up the project: app/main.py, the SQLite database, and GET /health."]
    for entity in spec.entities:
        fields = ", ".join(f.name for f in entity.fields)
        endpoints = ", ".join(f"{e.method} {e.path} ({e.access})" for e in spec.endpoints if e.entity == entity.name)
        tasks.append(f"{entity.name}: table and schemas with {fields}. Endpoints: {endpoints or 'none'}.")
    others = [f"{e.method} {e.path} ({e.access})" for e in spec.endpoints if e.entity is None]
    if others:
        tasks.append("Other endpoints: " + ", ".join(others) + ".")
    if spec.rules:
        tasks.append("Business rules: " + " ".join(spec.rules))
    return tasks


async def fix_round(state: ProjectState, emit: Emit) -> ProjectState:
    """One fix attempt. If the Coder's fix breaks the build, put the last working code back."""
    app = Path(state.workspace) / "app"
    results_before = {k: getattr(state, k) for k in ("tests_ok", "test_summary", "test_results", "test_report", "failures")}

    with tempfile.TemporaryDirectory() as tmp:
        backup = Path(tmp) / "app"
        shutil.copytree(app, backup)                    # keep a copy of the last working code
        state = await AGENTS["coder"](state, emit)      # the Coder reads state.test_report

        if not state.build_ok:                          # the fix broke the build: undo it
            shutil.rmtree(app, ignore_errors=True)
            shutil.copytree(backup, app)
            state.build_ok = True
            for k, v in results_before.items():         # report the known failures honestly
                setattr(state, k, v)
            await step(state, emit, "restored", "The fix broke the build, so the last working code was kept")
            return state

    return await AGENTS["tester"](state, emit)


def write_log(state: ProjectState) -> None:
    """Save every step (all agents) as JSON Lines in the project folder, for evaluation (Role 4)."""
    lines = [entry.model_dump_json() + "\n" for entry in state.logs]
    (Path(state.workspace) / "steps.jsonl").write_text("".join(lines))
