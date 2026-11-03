"""Tester agent and coder<->tester orchestration, with FakeLLM and the local sandbox (no Docker)."""
import json
import pathlib
import shutil

import pytest

from agents import orchestrator, tester
from core.llm import FakeLLM
from core.spec import Spec
from core.state import ProjectState

GOLDEN = pathlib.Path("golden/clinic")
SPEC = Spec.model_validate_json((GOLDEN / "spec.json").read_text())
PASSING = 'from fastapi.testclient import TestClient\nfrom app.main import app\nclient = TestClient(app)\n\n' \
          'def test_list_doctors():\n    assert client.get("/doctors").status_code == 200\n'
FAILING = PASSING + '\ndef test_impossible():\n    assert client.get("/doctors").status_code == 418\n'


@pytest.fixture(autouse=True)
def local_sandbox(monkeypatch):
    monkeypatch.setenv("SANDBOX", "local")


def step(action, thought="", **args):
    return json.dumps({"thought": thought, "action": action, "args": args})


def _state(tmp_path, code=None):
    ws = tmp_path / "ws"
    shutil.copytree(GOLDEN / "app", ws / "app", ignore=shutil.ignore_patterns("__pycache__"))
    (ws / "spec.json").write_text(SPEC.model_dump_json())
    if code:
        (ws / "app" / "main.py").write_text(code)
    return ProjectState(spec=SPEC, spec_approved=True, build_ok=True, workspace=str(ws))


def test_contract_tests_pass_on_golden_and_catch_broken_auth(tmp_path):
    state = _state(tmp_path)
    (pathlib.Path(state.workspace) / "tests").mkdir()
    (pathlib.Path(state.workspace) / tester.CONTRACT_FILE).write_text(tester.contract_tests(SPEC))
    assert tester.recheck(state).tests_ok, state.test_report

    # mutant: admins-only check removed -> users reach admin endpoints -> 403 tests fail
    broken = (GOLDEN / "app" / "main.py").read_text().replace('raise HTTPException(403, "Admin only")', "pass")
    state = _state(tmp_path / "mutant", broken)
    (pathlib.Path(state.workspace) / "tests").mkdir()
    (pathlib.Path(state.workspace) / tester.CONTRACT_FILE).write_text(tester.contract_tests(SPEC))
    state = tester.recheck(state)
    assert not state.tests_ok and "test_user_cannot_call_admin_endpoint" in state.test_report


def test_pass_verdict(tmp_path):
    llm = FakeLLM([step("write_test", path="tests/test_behaviour.py", content=PASSING), step("run_tests"),
                   step("finish", verdict="pass")])
    state = tester.run(_state(tmp_path), llm)
    assert state.tests_ok and state.test_report is None
    assert "passed" in state.test_summary
    names = {(r["file"], r["name"], r["outcome"]) for r in state.test_results}
    assert ("tests/test_behaviour.py", "test_list_doctors", "passed") in names
    assert any(r["file"] == tester.CONTRACT_FILE for r in state.test_results)
    assert [l.action for l in state.logs] == ["contract", "write_test", "run_tests", "finish", "verdict"]


def test_finish_gates_and_fail_report(tmp_path):
    bug = {"test": "test_impossible", "rule": "GET /doctors", "expected": "418", "got": "200"}
    llm = FakeLLM([
        step("write_test", path="tests/test_contract.py", content="x"),   # generated file is protected
        step("write_test", path="app/main.py", content="x"),              # tests only
        step("write_test", path="tests/test_behaviour.py", content=FAILING),
        step("finish", verdict="fail", failures=[bug]),                    # refused: not run since the write
        step("run_tests"),
        step("finish", verdict="pass"),                                    # refused: tests failed
        step("finish", verdict="fail", failures=[]),                       # refused: no failures listed
        step("finish", verdict="fail", failures=[bug]),
    ])
    state = tester.run(_state(tmp_path), llm)
    obs = [m["content"] for m in llm.calls[-1][1] if m["role"] == "user"][1:]
    assert "generated" in obs[0] and "tests/test_" in obs[1]
    assert sum("Cannot finish" in o for o in obs) == 3
    assert state.tests_ok is False
    assert {"file": "tests/test_behaviour.py", "name": "test_impossible", "outcome": "failed"} in state.test_results
    assert "test_impossible" in state.test_report and "You cannot change the tests" in state.test_report
    assert (pathlib.Path(state.workspace) / "app" / "main.py").read_text() != "x"


def test_orchestrator_restores_working_code_when_fix_round_fails(tmp_path, monkeypatch):
    state = _state(tmp_path)
    main = pathlib.Path(state.workspace) / "app" / "main.py"
    good = main.read_text()
    calls = []

    def fake_coder(st, llm, on_step=None):
        calls.append(st.test_report)
        if len(calls) == 2:  # fix round: breaks the code, then gives up
            main.write_text("broken")
            st.build_ok = False
        else:
            st.build_ok = True
        return st

    def fake_tester(st, llm, on_step=None):
        st.tests_ok, st.test_report = False, "Tester report: 1 failed"
        return st

    monkeypatch.setattr(orchestrator.coder, "run", fake_coder)
    monkeypatch.setattr(orchestrator.tester, "run", fake_tester)
    state = orchestrator.build(state, FakeLLM([]))
    assert calls == [None, "Tester report: 1 failed"]  # the report sent the coder back in
    assert main.read_text() == good and state.build_ok and state.tests_ok is False
    assert state.logs[-1].action == "restored"
