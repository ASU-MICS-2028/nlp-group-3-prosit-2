"""Single-agent workflow, offline: a scripted 'model' drives the real tools and checks."""
import asyncio
import json
import shutil
from pathlib import Path

from agents import solo
from core.spec import Requirements
from core.state import ProjectState

GOLDEN = Path("golden/clinic")
REQ = Requirements.model_validate_json((GOLDEN / "requirements.json").read_text())
SPEC = json.loads((GOLDEN / "spec.json").read_text())


async def emit(ev):
    pass


def scripted(ws: Path, calls: list):
    """Plays the model: a bad spec first, then the golden one, then writes the golden app and tests it."""
    async def runner(system, prompt, tools, **kw):
        calls.append(prompt)
        assert kw["workspace"] == str(ws) and "submit_spec" in tools and "run_tests" in tools
        assert "Call submit_spec first" in await tools["run_tests"][2]({})
        bad = {**SPEC, "endpoints": SPEC["endpoints"] + [{**SPEC["endpoints"][0]}]}   # duplicate endpoint
        assert "listed twice" in await tools["submit_spec"][2](bad)
        assert "accepted" in await tools["submit_spec"][2](SPEC)
        shutil.copytree(GOLDEN / "app", ws / "app", dirs_exist_ok=True)
        assert "passed" in await tools["run_tests"][2]({})
        return {"tokens": 100, "cost_usd": 0.01}
    return runner


def test_one_agent_designs_builds_and_tests(tmp_path):
    calls = []
    st = ProjectState(requirements=REQ, workspace=str(tmp_path))
    st = asyncio.run(solo.run(st, emit, runner=scripted(tmp_path, calls)))
    assert st.spec and st.spec_approved and st.build_ok
    assert st.tests_ok, st.test_report                       # verdict from our own final run
    assert any(r["file"] == "tests/test_contract.py" for r in st.test_results)
    assert [l.action for l in st.logs if l.agent == "solo"] == ["design", "run_tests", "verdict"]
    assert "<requirements>" in calls[0] and "<spec>" not in calls[0]


def test_change_request_goes_to_the_same_agent_with_mentioned_files(tmp_path):
    calls = []
    st = ProjectState(requirements=REQ, workspace=str(tmp_path))
    st = asyncio.run(solo.run(st, emit, runner=scripted(tmp_path, calls)))
    st.change_request, st.change_files = "Let patients reschedule", ["app/main.py"]
    st = asyncio.run(solo.run(st, emit, runner=scripted(tmp_path, calls)))
    assert "<spec>" in calls[1] and "Let patients reschedule" in calls[1] and "app/main.py" in calls[1]
    assert st.change_request is None and st.change_files == []   # applied, so cleared


def test_no_valid_spec_is_an_error(tmp_path):
    async def lazy(system, prompt, tools, **kw):
        return {}
    import pytest
    with pytest.raises(RuntimeError, match="valid design"):
        asyncio.run(solo.run(ProjectState(requirements=REQ, workspace=str(tmp_path)), emit, runner=lazy))
