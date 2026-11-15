"""Orchestrator rules, offline: fake agents stand in for the real ones, and record the order they ran in."""
import asyncio
import json

import pytest

from agents import orchestrator as O
from core.spec import Failure, Requirements, Spec
from core.state import ProjectState

REQ = Requirements(project_name="Shop", description="", users=[], data=[], actions=[])
SPEC = Spec(project_name="Shop", description="", entities=[],
            endpoints=[{"method": "GET", "path": "/items", "summary": "List items"}])
EVENTS = []


async def emit(event):
    EVENTS.append(event)


def fake_agents(monkeypatch, tests_pass, coder_breaks=()):
    """Install fake agents. tests_pass[i] is the Tester's verdict on run i.
    coder_breaks lists the Coder runs (0, 1, ...) whose code does not even start."""
    calls = []

    async def coder(state, emit):
        n = sum(c == "coder" for c in calls)
        calls.append("coder")
        (O.Path(state.workspace) / "app").mkdir(exist_ok=True)
        (O.Path(state.workspace) / "app" / "main.py").write_text(f"version {n}")
        state.build_ok = n not in coder_breaks
        return state

    async def tester(state, emit):
        n = sum(c == "tester" for c in calls)
        calls.append("tester")
        state.tests_ok = tests_pass[n]
        state.test_summary = "all passed" if state.tests_ok else "1 failed"
        state.test_report = None if state.tests_ok else "test_booking failed"
        state.failures = [] if state.tests_ok else [
            Failure(endpoint="POST /bookings", test="test_booking", expected="409", got="201")]
        return state

    async def architect(state, emit):
        calls.append("architect")
        state.spec, state.spec_approved = SPEC, False
        return state

    monkeypatch.setitem(O.AGENTS, "coder", coder)
    monkeypatch.setitem(O.AGENTS, "tester", tester)
    monkeypatch.setitem(O.AGENTS, "architect", architect)
    return calls


def approved(tmp_path):
    return ProjectState(requirements=REQ, spec=SPEC, spec_approved=True, workspace=str(tmp_path))


def test_no_build_before_the_user_approves(tmp_path):
    with pytest.raises(RuntimeError, match="Approve the spec"):
        asyncio.run(O.build(ProjectState(spec=SPEC, workspace=str(tmp_path)), emit))


def test_no_design_before_requirements_are_confirmed():
    with pytest.raises(RuntimeError, match="Confirm the requirements"):
        asyncio.run(O.design(ProjectState(), emit))


def test_tests_pass_first_time(tmp_path, monkeypatch):
    calls = fake_agents(monkeypatch, tests_pass=[True])
    st = asyncio.run(O.build(approved(tmp_path), emit))
    assert calls == ["coder", "tester"]                      # no fix round needed
    assert st.build_ok and st.tests_ok
    assert EVENTS[-1].type == "result"
    assert st.result.endpoints == ["GET /items"] and st.result.test_summary == "all passed"
    assert st.result.known_failures == []


def test_failure_goes_back_to_the_coder_once(tmp_path, monkeypatch):
    calls = fake_agents(monkeypatch, tests_pass=[False, True])
    st = asyncio.run(O.build(approved(tmp_path), emit))
    assert calls == ["coder", "tester", "coder", "tester"]   # one fix round, then it passes
    assert st.tests_ok and any(l.action == "fix_round" for l in st.logs)


def test_fix_rounds_stop_at_the_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(O, "MAX_FIX_ROUNDS", 2)
    calls = fake_agents(monkeypatch, tests_pass=[False, False, False, False])
    st = asyncio.run(O.build(approved(tmp_path), emit))
    assert calls.count("coder") == 3                          # first try + 2 fix rounds, then stop
    assert st.tests_ok is False and st.test_report == "test_booking failed"   # failures reported honestly
    assert [f.test for f in st.result.known_failures] == ["test_booking"]


def test_a_fix_that_breaks_the_build_is_undone(tmp_path, monkeypatch):
    calls = fake_agents(monkeypatch, tests_pass=[False], coder_breaks=[1])
    st = asyncio.run(O.build(approved(tmp_path), emit))
    assert calls == ["coder", "tester", "coder"]              # broken fix is never tested
    assert (tmp_path / "app" / "main.py").read_text() == "version 0"   # last working code is back
    assert st.build_ok and st.tests_ok is False and st.test_summary == "1 failed"
    assert st.logs[-1].action == "restored"


def test_every_step_is_saved_as_jsonl(tmp_path, monkeypatch):
    fake_agents(monkeypatch, tests_pass=[True])
    asyncio.run(O.build(approved(tmp_path), emit))
    lines = (tmp_path / "steps.jsonl").read_text().splitlines()
    assert json.loads(lines[0])["action"] == "build"


def test_spec_is_split_into_build_tasks():
    golden = Spec.model_validate_json((O.Path(__file__).parent.parent / "golden/clinic/spec.json").read_text())
    tasks = O.plan_tasks(golden)
    assert len(tasks) == 1 + 3 + 1                            # setup, Patient, Doctor, Appointment, rules
    assert "GET /health" in tasks[0]
    assert tasks[3].startswith("Appointment:") and "POST /appointments (user)" in tasks[3]
    assert "Belongs to: Patient, Doctor" in tasks[3]
    assert tasks[-1].startswith("Business rules:")


def test_build_fills_in_the_tasks(tmp_path, monkeypatch):
    fake_agents(monkeypatch, tests_pass=[True])
    st = asyncio.run(O.build(approved(tmp_path), emit))
    assert st.tasks[0].startswith("Set up the project") and "GET /items (user)" in st.tasks[-1]


def test_chat_designs_only_after_the_user_confirms(monkeypatch):
    calls = fake_agents(monkeypatch, tests_pass=[])

    async def still_asking(state, emit):
        return state

    async def confirmed(state, emit):
        state.requirements = REQ
        return state

    monkeypatch.setitem(O.AGENTS, "requirements", still_asking)
    asyncio.run(O.chat(ProjectState(), emit))
    assert calls == []                                        # still chatting: no design yet

    monkeypatch.setitem(O.AGENTS, "requirements", confirmed)
    st = asyncio.run(O.chat(ProjectState(), emit))
    assert calls == ["architect"] and st.spec == SPEC and not st.spec_approved
