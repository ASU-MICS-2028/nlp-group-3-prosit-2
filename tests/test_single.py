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
    assert list(seen["tools"]) == ["search_patterns"]             # file tools + the same RAG search as the Coder
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


def test_spec_mode_gets_the_teams_tools_and_is_judged_by_our_code(tmp_path):
    """Comparison mode: same spec, the Coder's and Tester's tools, writes app/ and tests/; verdicts from our code."""
    import pathlib
    import shutil
    from core.spec import Spec
    golden = pathlib.Path(__file__).resolve().parent.parent / "golden" / "clinic"
    spec = Spec.model_validate_json((golden / "spec.json").read_text())
    seen = {}

    async def fake_runner(system, prompt, tools, max_turns, max_usd, workspace, writable):
        seen.update(system=system, prompt=prompt, tools=list(tools), writable=writable, max_usd=max_usd)
        ws = pathlib.Path(workspace)
        assert "Refused" in await tools["finish_build"][2]({})            # the finish gate holds
        shutil.copytree(golden / "app", ws / "app", dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
        (ws / "tests" / "test_api.py").write_text(   # what the agent would write: tests on the `client` fixture
            "def test_doctors_are_public(client):\n    assert client.get('/doctors').status_code == 200\n")
        seen["checks"] = await tools["run_checks"][2]({})
        seen["tests"] = await tools["run_tests"][2]({})
        seen["finish"] = await tools["finish_build"][2]({})
        return {"tokens": 900, "cost_usd": 0.3}

    st = ProjectState(spec=spec, spec_approved=True, workspace=str(tmp_path))
    st = asyncio.run(single.run(st, emit, runner=fake_runner))
    assert sorted(seen["tools"]) == ["finish_build", "run_checks", "run_tests", "search_patterns"]
    assert seen["writable"] == ("app", "tests") and seen["max_usd"] == 1.5
    assert "<spec>" in seen["prompt"] and "Build tasks:" in seen["prompt"]
    assert "One behaviour per test" in seen["system"] and "GET /health is not in the spec" in seen["system"]
    assert "All checks passed" in seen["checks"] and "passed" in seen["tests"] and "accepted" in seen["finish"]
    assert st.build_ok and st.tests_ok and st.test_results
    assert [l.action for l in st.logs if l.agent == "single"][-1] == "finish" and st.logs[-1].tokens == 900
