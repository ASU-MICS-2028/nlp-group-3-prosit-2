"""Coder agent, offline: a fake runner plays the model (writes app/, calls the tools), and the
checks really run on the golden clinic app. No model is called."""
import asyncio
import pathlib
import shutil

import pytest

from agents import coder as C
from core.sdk import allowed
from core.spec import Spec
from core.state import ProjectState

GOLDEN = pathlib.Path(__file__).resolve().parent.parent / "golden" / "clinic"
SPEC = Spec.model_validate_json((GOLDEN / "spec.json").read_text())


async def emit(event):
    pass


@pytest.fixture
def state(tmp_path):
    return ProjectState(spec=SPEC, spec_approved=True, workspace=str(tmp_path), tasks=["Set up the project."])


def write_golden(ws: pathlib.Path) -> None:
    shutil.copytree(GOLDEN / "app", ws / "app", dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))


def edit(ws: pathlib.Path, old: str, new: str) -> None:
    main = ws / "app" / "main.py"
    assert old in main.read_text()
    main.write_text(main.read_text().replace(old, new))


def run_with(state, steps, seen=None):
    """Run the coder where the 'model' does `steps` in order: a function (writes files) or a tool name."""
    async def fake_runner(system, prompt, tools, max_turns, max_usd, workspace, writable):
        ws = pathlib.Path(workspace)
        log = seen if seen is not None else []
        log.append({"prompt": prompt, "writable": writable})
        for s in steps:
            log.append(await tools[s][2]({}) if isinstance(s, str) else s(ws))
        return {"tokens": 100, "cost_usd": 0.05}
    return asyncio.run(C.run(state, emit, runner=fake_runner))


def actions(state):
    return [l.action for l in state.logs if l.agent == "coder"]


def test_golden_app_passes_and_finishes(state):
    seen = []
    st = run_with(state, [write_golden, "run_checks", "finish_build"], seen)
    assert st.build_ok
    assert seen[0]["writable"] == ("app",)                       # the Coder may write in app/ only
    assert "All checks passed" in seen[2] and "accepted" in seen[3]
    assert actions(st) == ["run_checks", "write_files", "finish"]
    assert st.logs[-1].tokens == 100 and st.logs[-1].cost_usd == 0.05


def test_finish_is_refused_before_checks_pass(state):
    seen = []
    run_with(state, [write_golden, "finish_build"], seen)
    assert seen[2].startswith("Refused")


def test_finish_is_refused_after_a_change_until_checked_again(state):
    seen = []
    st = run_with(state, [write_golden, "run_checks",
                          lambda ws: edit(ws, 'title="Clinic Appointments"', 'title="Clinic"'),
                          "finish_build", "run_checks", "finish_build"], seen)
    assert seen[4].startswith("Refused") and "changed" in seen[4]
    assert "accepted" in seen[6] and st.build_ok


def test_verdict_comes_from_our_checks_not_the_model(state):
    """The model 'finishes', then breaks the code: the final run catches it."""
    st = run_with(state, [write_golden, "run_checks", "finish_build",
                          lambda ws: (ws / "app" / "main.py").write_text("def broken(:\n")])
    assert not st.build_ok and actions(st)[-1] == "gave_up"


def test_missing_endpoint_is_reported(state):
    seen = []
    st = run_with(state, [write_golden,
                          lambda ws: edit(ws, '@app.delete("/doctors/{id}"', '@app.get("/unused/{id}"'),
                          "run_checks"], seen)
    assert "DELETE /doctors/{id}" in seen[3] and not st.build_ok


def test_health_check_is_required(state):
    seen = []
    run_with(state, [write_golden, lambda ws: edit(ws, '@app.get("/health"', '@app.get("/healthz"'),
                     "run_checks"], seen)
    assert "GET /health" in seen[3]


def test_import_error_is_reported(state):
    seen = []
    run_with(state, [write_golden, lambda ws: edit(ws, "SLOT = ", "SLOT = undefined_name + "), "run_checks"], seen)
    assert "does not import" in seen[3] and "undefined_name" in seen[3]


def test_packages_outside_the_allowed_list_are_refused(state):
    seen = []
    run_with(state, [write_golden, lambda ws: (ws / "app" / "extra.py").write_text("import requests\n"),
                     "run_checks"], seen)
    assert "app/extra.py, line 1: imports requests" in seen[3]


def test_syntax_errors_name_the_file_and_line(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("x = 1\ndef f(:\n")
    assert C.static_problems(tmp_path)[0].startswith("app/main.py, line 2: syntax error")


@pytest.mark.parametrize("code, bad", [
    ('conn.execute(f"SELECT * FROM t WHERE id = {id}")', True),
    ('conn.execute("SELECT * FROM t WHERE id = " + str(id))', True),
    ('conn.execute("SELECT * FROM t WHERE id = %s" % id)', True),
    ('conn.execute("SELECT * FROM t WHERE id = {}".format(id))', True),
    ('conn.execute("SELECT * FROM t WHERE id = ?", (id,))', False),
    ('conn.execute(f"UPDATE t SET {cols} WHERE id = ?", values)', False),   # dynamic columns, values as parameters
    ('conn.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY)")', False),
])
def test_sql_with_values_pasted_in_is_refused(tmp_path, code, bad):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text(f"def f(conn, id, cols, values):\n    {code}\n")
    assert any("SQL built from values" in p for p in C.static_problems(tmp_path)) == bad


def test_coder_cannot_write_tests_or_outside_the_project(tmp_path):
    ws = str(tmp_path)
    assert allowed("Write", "app/main.py", ws, C.WRITABLE)
    assert not allowed("Write", "tests/test_api.py", ws, C.WRITABLE)
    assert not allowed("Edit", "../evil.py", ws, C.WRITABLE)
    assert allowed("Read", "tests/test_api.py", ws, C.WRITABLE)   # it may read the tests, not change them


def test_fix_round_gets_the_report_and_keeps_the_code(state):
    write_golden(pathlib.Path(state.workspace))
    state.build_ok, state.tests_ok = True, False
    state.test_report = "- test_duplicate_phone_is_rejected (POST /patients): expected 409, got 201."
    seen = []
    st = run_with(state, [lambda ws: (ws / "app" / "main.py").exists(), "run_checks", "finish_build"], seen)
    assert seen[1] is True                                        # app/ was not wiped
    assert "<failure_report>" in seen[0]["prompt"] and "test_duplicate_phone_is_rejected" in seen[0]["prompt"]
    assert st.build_ok


def test_rebuild_after_a_change_opens_the_mentioned_files(state):
    write_golden(pathlib.Path(state.workspace))
    state.change_files = ["app/main.py"]
    seen = []
    run_with(state, ["run_checks", "finish_build"], seen)
    prompt = seen[0]["prompt"]
    assert "already holds the code" in prompt and "- app/main.py" in prompt and "<failure_report>" not in prompt


def test_new_build_prompt_has_spec_and_tasks(state):
    seen = []
    run_with(state, [write_golden, "run_checks", "finish_build"], seen)
    prompt = seen[0]["prompt"]
    assert prompt.startswith("<spec>") and "1. Set up the project." in prompt and "app/ is empty" in prompt
