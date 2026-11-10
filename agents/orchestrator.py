"""Orchestrator (Role 2): runs the agents in the right order and enforces the rules.

It is plain Python, NOT an AI. These rules must hold every time, so no model gets to decide them:
  - no design before the user confirms the requirements
  - no code before the user approves the spec (human-in-the-loop)
  - at most MAX_FIX_ROUNDS Coder <-> Tester fix rounds (stop rule)
  - if a fix breaks the build, the last working code is put back

The three jobs, in order:
  chat()    user message -> Requirements agent; once the summary is confirmed -> design()
  design()  Architect makes (or changes) the spec. Then we wait for the user to approve it.
  build()   Coder -> Tester -> fix rounds -> result

Every agent has the same shape (shared contract): async def run(state, emit) -> state
"""
import os
import shutil
import tempfile
from pathlib import Path

from agents import architect, requirements
from core.events import Emit, Event
from core.state import LogEntry, ProjectState
from server import stubs

MAX_FIX_ROUNDS = int(os.getenv("MAX_FIX_ROUNDS", "1"))

# ---------- who does each job ----------
# REQUIREMENTS_AGENT=stub replays the golden clinic example offline (no model calls).
# ARCHITECT_AGENT=stub does the same for the architect; if unset, it follows REQUIREMENTS_AGENT.
STUB_REQUIREMENTS = os.getenv("REQUIREMENTS_AGENT") == "stub"
STUB_ARCHITECT = os.getenv("ARCHITECT_AGENT", os.getenv("REQUIREMENTS_AGENT")) == "stub"

AGENTS = {
    "requirements": stubs.requirements if STUB_REQUIREMENTS else requirements.run,
    "architect": stubs.architect if STUB_ARCHITECT else architect.run,
    "coder": stubs.coder,     # placeholder until Role 3's agents/coder.py lands
    "tester": stubs.tester,   # placeholder until Role 4's agents/tester.py lands
}


async def step(state: ProjectState, emit: Emit, action: str, detail: str = "") -> None:
    """Write one orchestrator step to the log and show it in the UI."""
    state.logs.append(LogEntry(agent="orchestrator", action=action, detail=detail))
    await emit(Event(type="step", agent="orchestrator", detail=detail, data={"action": action}))


# ---------- 1. understand ----------

async def chat(state: ProjectState, emit: Emit) -> ProjectState:
    """The user sent a message (already added to state.chat)."""
    state = await AGENTS["requirements"](state, emit)
    if state.requirements is not None:   # the user confirmed the summary, so move on
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
    await step(state, emit, "build", "Build started")

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

    write_log(state)
    await emit(Event(type="result", agent="orchestrator", detail="Build finished",
                     data={"build_ok": state.build_ok, "tests_ok": state.tests_ok}))
    return state


async def fix_round(state: ProjectState, emit: Emit) -> ProjectState:
    """One fix attempt. If the Coder's fix breaks the build, put the last working code back."""
    app = Path(state.workspace) / "app"
    results_before = {k: getattr(state, k) for k in ("tests_ok", "test_summary", "test_results", "test_report")}

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
