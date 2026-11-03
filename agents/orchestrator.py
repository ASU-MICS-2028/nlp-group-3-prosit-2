"""Build orchestration after spec approval: coder, then tester, then one coder fix round if bugs were found.

The coder can't edit tests/ and can't finish until run_checks (which runs tests/) passes, so a
successful fix round means the tester's tests pass. If the fix round fails, the last working code
is restored and the known failures stay in state.test_report for the user.
"""
import pathlib
import shutil
import tempfile
from typing import Callable, Optional

from agents import coder, tester
from core.llm import LLM
from core.scaffold import scaffold
from core.state import LogEntry, ProjectState


def build(state: ProjectState, llm: LLM, on_step: Optional[Callable[[LogEntry], None]] = None) -> ProjectState:
    state = _build(state, llm, on_step)
    if state.build_ok:  # README again, now that tests/ exists
        scaffold(pathlib.Path(state.workspace), state.spec)
    return state


def _build(state: ProjectState, llm: LLM, on_step: Optional[Callable[[LogEntry], None]]) -> ProjectState:
    if state.workspace:  # fresh build: old tests may describe an older spec
        shutil.rmtree(pathlib.Path(state.workspace) / "tests", ignore_errors=True)
    state.test_report, state.tests_ok, state.test_summary, state.test_results = None, None, "", []
    state.logs.append(LogEntry(agent="orchestrator", action="build", detail="Build started"))  # UI groups steps from here

    state = coder.run(state, llm, on_step)
    if not state.build_ok:
        return state
    state = tester.run(state, llm, on_step)
    if state.tests_ok or not state.test_report:
        return state

    app = pathlib.Path(state.workspace) / "app"
    with tempfile.TemporaryDirectory() as tmp:
        backup = pathlib.Path(tmp) / "app"
        shutil.copytree(app, backup)
        report = state.test_report
        state = coder.run(state, llm, on_step)
        if state.build_ok:
            return tester.recheck(state, on_step)
        # fix round failed: put the working code back and keep the known failures
        shutil.rmtree(app)
        shutil.copytree(backup, app)
        state.build_ok, state.tests_ok, state.test_report = True, False, report
        state.logs.append(LogEntry(agent="orchestrator", action="restored",
                                   detail="Fix round failed; restored the last working code"))
        if on_step:
            on_step(state.logs[-1])
        return state
