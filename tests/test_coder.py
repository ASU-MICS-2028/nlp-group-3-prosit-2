"""Coder ReAct loop with FakeLLM. Sandbox runs locally (SANDBOX=local) so no Docker needed."""
import json
import pathlib

import pytest

from agents import coder
from core.llm import FakeLLM
from core.spec import Spec
from core.state import ProjectState

GOLDEN = pathlib.Path("golden/clinic")
GOLDEN_CODE = (GOLDEN / "app" / "main.py").read_text()


@pytest.fixture(autouse=True)
def local_sandbox(monkeypatch, request):
    monkeypatch.setenv("SANDBOX", "local")
    if "layout" not in request.node.name:  # most tests use the single-file golden app
        monkeypatch.setattr(coder, "REQUIRED_FILES", ["app/main.py"])
        monkeypatch.setattr(coder, "REQUIRED_DIRS", [])


def _state(tmp_path):
    spec = Spec.model_validate(json.loads((GOLDEN / "spec.json").read_text()))
    return ProjectState(spec=spec, spec_approved=True, tasks=["build it"], workspace=str(tmp_path / "ws"))


def step(action, thought="", **args):
    return json.dumps({"thought": thought, "action": action, "args": args})


def test_builds_and_finishes(tmp_path):
    llm = FakeLLM([step("write_file", path="app/main.py", content=GOLDEN_CODE), step("run_checks"), step("finish")])
    state = coder.run(_state(tmp_path), llm)
    assert state.build_ok
    assert (pathlib.Path(state.workspace) / "app" / "main.py").exists()
    assert (pathlib.Path(state.workspace) / "app" / "__init__.py").exists()
    assert [l.action for l in state.logs] == ["write_file", "run_checks", "finish", "done"]
    for f in ("README.md", "requirements.txt", "Dockerfile", ".gitignore"):  # scaffolded on success
        assert (pathlib.Path(state.workspace) / f).exists()
    assert "Clinic" in (pathlib.Path(state.workspace) / "README.md").read_text()
    # big file content is trimmed from the history sent back to the model
    assert "written to disk" in llm.calls[-1][1][1]["content"]


def test_finish_blocked_until_checks_pass(tmp_path):
    broken = "from fastapi import FastAPI\napp = FastAPI()\n"
    llm = FakeLLM([step("write_file", path="app/main.py", content=broken), step("finish"), step("run_checks"),
                   step("write_file", path="app/main.py", content=GOLDEN_CODE), step("run_checks"), step("finish")])
    state = coder.run(_state(tmp_path), llm)
    assert state.build_ok
    obs = [m["content"] for m in llm.calls[-1][1] if m["role"] == "user"]
    assert any("Cannot finish" in o for o in obs)
    assert any("missing_endpoints" in o and '"ok": false' in o for o in obs)


def test_write_outside_workspace_refused(tmp_path):
    llm = FakeLLM([step("write_file", path="../evil.py", content="x"), step("write_file", path="app/run.sh", content="x")]
                  + [step("list_files")] * (coder.MAX_STEPS - 2))
    state = coder.run(_state(tmp_path), llm)
    obs = [m["content"] for m in llm.calls[-1][1] if m["role"] == "user"]
    assert "outside the workspace" in obs[1] and "only write .py" in obs[2]
    assert not (tmp_path / "evil.py").exists()
    assert not state.build_ok and state.logs[-1].action == "gave_up"


def test_invalid_reply_and_unknown_tool_recover(tmp_path):
    llm = FakeLLM(["not json", step("delete_everything"), step("write_file", path="app/main.py", content=GOLDEN_CODE),
                   step("run_checks"), step("finish")])
    state = coder.run(_state(tmp_path), llm)
    assert state.build_ok
    obs = [m["content"] for m in llm.calls[-1][1] if m["role"] == "user"]
    assert "Invalid reply" in obs[1] and "Unknown action" in obs[2]


def test_test_report_is_sent_and_cleared(tmp_path):
    state = _state(tmp_path)
    state.test_report = "POST /appointments returned 500"
    llm = FakeLLM([step("write_file", path="app/main.py", content=GOLDEN_CODE), step("run_checks"), step("finish")])
    state = coder.run(state, llm)
    assert "POST /appointments returned 500" in llm.calls[0][1][0]["content"]
    assert state.build_ok and state.test_report is None


def test_needs_approved_spec(tmp_path):
    state = _state(tmp_path)
    state.spec_approved = False
    with pytest.raises(ValueError):
        coder.run(state, FakeLLM([]))


def test_on_step_reports_each_step_live(tmp_path):
    seen = []
    llm = FakeLLM([step("write_file", path="app/main.py", content=GOLDEN_CODE), step("run_checks"), step("finish")])
    coder.run(_state(tmp_path), llm, on_step=lambda e: seen.append(e.action))
    assert seen == ["write_file", "run_checks", "finish"]


# a small layered split of the golden app: main includes a router that re-exports the golden routes
LAYERED = [
    {"path": "app/legacy.py", "content": GOLDEN_CODE},
    {"path": "app/main.py", "content": "from app.legacy import app\n"},
    {"path": "app/dependencies.py", "content": "from app.legacy import require\n"},
    {"path": "app/database.py", "content": "from app.legacy import db\n"},
    {"path": "app/routers/patients.py", "content": "from app.legacy import app as router\n"},
    {"path": "app/schemas/patients.py", "content": "from app.legacy import Patient, PatientIn\n"},
]


def test_layout_gate_blocks_single_file_then_allows_split(tmp_path):
    llm = FakeLLM([step("write_file", path="app/main.py", content=GOLDEN_CODE), step("run_checks"), step("finish"),
                   step("write_files", files=LAYERED), step("run_checks"), step("finish")])
    state = coder.run(_state(tmp_path), llm)
    assert state.build_ok
    obs = [m["content"] for m in llm.calls[-1][1] if m["role"] == "user"]
    assert any("layout is incomplete" in o and "app/routers" in o for o in obs)
    ws = pathlib.Path(state.workspace)
    assert (ws / "app" / "routers" / "__init__.py").exists() and (ws / "app" / "schemas" / "__init__.py").exists()
    # write_files contents are trimmed in the history too
    assert "written to disk" in str(llm.calls[-1][1])


def test_export_zip_skips_internal_files(tmp_path):
    import io, zipfile
    from core.scaffold import export_zip
    ws = tmp_path / "my_api"
    (ws / "app" / "__pycache__").mkdir(parents=True)
    (ws / "app" / "main.py").write_text("x")
    (ws / "app" / "__pycache__" / "main.pyc").write_text("x")
    (ws / "state.json").write_text("{}")
    names = zipfile.ZipFile(io.BytesIO(export_zip(ws))).namelist()
    assert names == ["my_api/app/main.py"]
