"""Single-agent mode and the file-tool security rule, offline (no model calls)."""
import asyncio

import pytest

from agents import orchestrator as O
from agents import single
from core.sdk import allowed
from core.spec import Requirements
from core.state import ProjectState

REQ = Requirements(project_name="Shop", description="", users=[], data=[], actions=[])


async def emit(event):
    pass


def test_file_rule_reads_inside_the_project_only(tmp_path):
    ws = str(tmp_path)
    assert allowed("Read", "app/main.py", ws)
    assert allowed("Read", str(tmp_path / "spec.json"), ws)
    assert not allowed("Read", "../secret.txt", ws)
    assert not allowed("Read", "/etc/passwd", ws)


def test_file_rule_writes_only_in_app_or_tests(tmp_path):
    ws = str(tmp_path)
    assert allowed("Write", "app/main.py", ws) and allowed("Edit", "tests/test_api.py", ws)
    assert not allowed("Write", "spec.json", ws)                  # project folder, but not app/ or tests/
    assert not allowed("Write", "app/../run.py", ws)              # sneaks out of app/
    assert not allowed("Write", "/tmp/evil.py", ws)
    assert not allowed("Edit", "../other_project/app/main.py", ws)


def test_single_agent_writes_the_app_from_the_requirements(tmp_path):
    seen = {}

    async def fake_runner(system, prompt, tools, max_turns, max_usd, workspace):
        seen.update(prompt=prompt, tools=tools, workspace=workspace)
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "main.py").write_text("app = None")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_api.py").write_text("")
        return {"tokens": 500, "cost_usd": 0.1}

    st = ProjectState(requirements=REQ, workspace=str(tmp_path))
    st = asyncio.run(single.run(st, emit, runner=fake_runner))
    assert "<requirements>" in seen["prompt"] and seen["workspace"] == str(tmp_path)
    assert seen["tools"] == {}                                    # file tools only, none of ours
    assert st.build_ok and st.tests_ok is None                    # tests are run by the benchmark
    assert st.spec is None and "app/main.py" in st.logs[-1].detail   # no spec in this mode
    assert st.logs[-1].cost_usd == 0.1


def test_build_single_needs_confirmed_requirements(tmp_path):
    with pytest.raises(RuntimeError, match="Confirm the requirements"):
        asyncio.run(O.build_single(ProjectState(workspace=str(tmp_path)), emit))


def test_build_single_uses_one_agent_and_logs_it(tmp_path, monkeypatch):
    calls = []

    async def fake_single(state, emit):
        calls.append("single")
        return state

    monkeypatch.setitem(O.AGENTS, "single", fake_single)
    asyncio.run(O.build_single(ProjectState(requirements=REQ, workspace=str(tmp_path)), emit))
    assert calls == ["single"] and (tmp_path / "steps.jsonl").exists()
