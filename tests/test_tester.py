"""Tester agent, offline: a fake runner plays the model (writes a test file, calls the tools),
and pytest really runs on a copy of the golden clinic app. No model is called."""
import asyncio
import pathlib
import shutil

import pytest

from agents import tester as T
from core.sdk import allowed
from core.spec import Spec
from core.state import ProjectState

GOLDEN = pathlib.Path(__file__).resolve().parent.parent / "golden" / "clinic"
SPEC = Spec.model_validate_json((GOLDEN / "spec.json").read_text())

GOOD_TESTS = '''
def test_register_patient(client):
    r = client.post("/patients", json={"full_name": "Ama Mensah", "phone": "0244000001"})
    assert r.status_code == 201 and isinstance(r.json()["id"], int)


def test_duplicate_phone_is_rejected(client):
    body = {"full_name": "Ama Mensah", "phone": "0244000001"}
    assert client.post("/patients", json=body).status_code == 201
    assert client.post("/patients", json=body).status_code == 409


def test_each_test_starts_with_an_empty_database(client):
    assert client.get("/doctors").json() == []
'''
BUG = ("duplicate phones are accepted", 'raise HTTPException(409, "Phone number already registered")', "pass")
OPEN_LIST = ("anyone can list patients", '@app.get("/patients", response_model=list[Patient], dependencies=[ADMIN])',
             '@app.get("/patients", response_model=list[Patient])')
DUPLICATE = {"endpoint": "POST /patients", "test": "test_duplicate_phone_is_rejected", "expected": "409", "got": "201",
             "hint": "create_patient does not check the phone"}


async def emit(event):
    pass


@pytest.fixture
def state(tmp_path):
    """A project holding the golden app, as if the Coder had just written it."""
    shutil.copytree(GOLDEN / "app", tmp_path / "app", ignore=shutil.ignore_patterns("__pycache__"))
    return ProjectState(spec=SPEC, spec_approved=True, build_ok=True, workspace=str(tmp_path))


def break_app(state, bug):
    main = pathlib.Path(state.workspace) / "app" / "main.py"
    _, old, new = bug
    assert old in main.read_text()
    main.write_text(main.read_text().replace(old, new))


def run_with(state, tests=GOOD_TESTS, reports=((),), replies=None, runs=1, also=None):
    """Run the tester where the 'model' writes `tests`, calls run_tests `runs` times,
    then calls submit_report with each of `reports` in order."""
    async def fake_runner(system, prompt, tools, max_turns, max_usd, workspace, writable):
        ws = pathlib.Path(workspace)
        seen = replies if replies is not None else []
        seen.append({"prompt": prompt, "writable": writable})
        if tests:
            (ws / "tests" / "test_api.py").write_text(tests)
        if also:
            also(ws)
        for _ in range(runs):
            seen.append(await tools["run_tests"][2]({}))
        for failures in reports:
            seen.append(await tools["submit_report"][2]({"failures": list(failures)}))
        return {"tokens": 100, "cost_usd": 0.02}
    return asyncio.run(T.run(state, emit, runner=fake_runner))


def test_contract_tests_cover_health_and_access():
    source, expected = T.contract_tests(SPEC)
    compile(source, "test_contract.py", "exec")                       # it is valid Python
    assert expected["test_contract_health"][0] == "GET /health"
    assert "test_contract_401_get_patients_id" in expected            # needs sign-in
    assert "test_contract_403_post_doctors" in expected               # admin only
    assert "test_contract_401_post_patients" not in expected          # public: no auth check
    assert all(f"test_contract_exists_{s}" in expected for s in ("get_doctors", "post_appointments_id_cancel"))


def test_all_pass_on_the_golden_app(state):
    replies = []
    st = run_with(state, replies=replies)
    assert st.tests_ok is True and st.failures == [] and st.test_report is None
    assert "passed" in st.test_summary
    names = {r["name"] for r in st.test_results}
    assert {"test_register_patient", "test_contract_health", "test_contract_403_get_patients"} <= names
    assert all(r["outcome"] == "passed" and r["file"].startswith("tests/") for r in st.test_results)
    assert "<spec>" in replies[0]["prompt"] and replies[0]["writable"] == ("tests",)
    assert "All tests passed" in replies[1] and "accepted" in replies[2]
    log = st.logs[-1]
    assert (log.agent, log.action, log.tokens, log.cost_usd) == ("tester", "run_tests", 100, 0.02)


def test_the_tester_may_write_in_tests_only(tmp_path):
    ws = str(tmp_path)
    assert allowed("Write", "tests/test_api.py", ws, T.WRITABLE)
    assert not allowed("Write", "app/main.py", ws, T.WRITABLE)       # it cannot "fix" the code itself
    assert not allowed("Edit", "tests/../app/main.py", ws, T.WRITABLE)
    assert allowed("Read", "app/main.py", ws, T.WRITABLE)             # reading is fine, for the hints


def test_a_bug_becomes_a_failure_for_the_coder(state):
    break_app(state, BUG)
    replies = []
    st = run_with(state, reports=[[DUPLICATE]], replies=replies)
    assert "1 failed" in replies[1]                                   # the model sees the failing run
    assert "accepted" in replies[2]
    assert st.tests_ok is False and len(st.failures) == 1
    assert st.failures[0].model_dump() == DUPLICATE                   # the model's entry, with its hint
    assert "test_duplicate_phone_is_rejected (POST /patients): expected 409, got 201" in st.test_report
    assert {"file": "tests/test_api.py", "name": "test_duplicate_phone_is_rejected", "outcome": "failed"} in st.test_results


def test_a_report_that_does_not_match_the_run_is_sent_back(state):
    break_app(state, BUG)
    invented = {**DUPLICATE, "test": "test_register_patient"}         # this test passed
    replies = []
    st = run_with(state, reports=[[], [DUPLICATE, invented], [DUPLICATE]], replies=replies)
    assert "failed but are not in your report: test_duplicate_phone_is_rejected" in replies[2]
    assert "did not fail in the latest run, so take them out: test_register_patient" in replies[3]
    assert "accepted" in replies[4]
    assert [f.test for f in st.failures] == ["test_duplicate_phone_is_rejected"]


def test_the_verdict_comes_from_the_run_not_from_the_model(state):
    break_app(state, BUG)
    st = run_with(state, reports=[])                                  # the model never reports
    assert st.tests_ok is False
    f = st.failures[0]                                                # built from pytest's own output
    assert f.test == "test_duplicate_phone_is_rejected" and f.expected == "the test passes" and "assert" in f.got


def test_contract_failures_are_reported_without_the_model(state):
    break_app(state, OPEN_LIST)
    st = run_with(state, reports=[[]])                                # an empty report is fine: our code adds them
    by_name = {f.test: f for f in st.failures}
    assert set(by_name) == {"test_contract_401_get_patients", "test_contract_403_get_patients"}
    f = by_name["test_contract_403_get_patients"]
    assert (f.endpoint, f.expected) == ("GET /patients", "403 for a user (admin only)") and "got 200" in f.got


def test_the_model_cannot_weaken_the_platform_tests(state):
    break_app(state, OPEN_LIST)

    def cheat(ws):
        (ws / "tests" / "test_contract.py").write_text("def test_nothing():\n    pass\n")
        (ws / "tests" / "conftest.py").write_text("")
    st = run_with(state, also=cheat)
    assert st.tests_ok is False                                       # both files were put back before the run
    assert "test_contract_403_get_patients" in {f.test for f in st.failures}


def test_run_tests_is_limited(state, monkeypatch):
    monkeypatch.setattr(T, "MAX_RUNS", 1)
    replies = []
    run_with(state, runs=2, replies=replies)
    assert "All tests passed" in replies[1] and "No test runs left" in replies[2]


def test_tests_that_cannot_start_are_a_failure(state):
    st = run_with(state, tests="def test_broken(:\n", reports=[])
    assert st.tests_ok is False and st.failures[0].test == "tests"


def test_fix_round_runs_the_same_tests_without_the_model(state):
    break_app(state, BUG)
    st = run_with(state, reports=[[DUPLICATE]])
    assert st.tests_ok is False
    tests_before = (pathlib.Path(st.workspace) / "tests" / "test_api.py").read_text()

    async def no_model(*args, **kwargs):
        raise AssertionError("a fix round must not call the model")

    # The Coder's fix did not work: same failure, and the model's hint is kept.
    st = asyncio.run(T.run(st, emit, runner=no_model))
    assert st.tests_ok is False and st.failures[0].model_dump() == DUPLICATE
    assert st.logs[-1].action == "retest" and st.logs[-1].tokens == 0

    # Now the Coder really fixes it.
    _, old, new = BUG
    main = pathlib.Path(st.workspace) / "app" / "main.py"
    main.write_text(main.read_text().replace(new, old, 1))
    st = asyncio.run(T.run(st, emit, runner=no_model))
    assert st.tests_ok is True and st.failures == [] and st.test_report is None
    assert (pathlib.Path(st.workspace) / "tests" / "test_api.py").read_text() == tests_before


def test_a_new_build_does_not_reuse_old_tests(state):
    old = pathlib.Path(state.workspace) / "tests"
    old.mkdir()
    (old / "test_old_project.py").write_text("def test_old():\n    assert False\n")
    st = run_with(state)                                              # tests_ok is None: a fresh build
    assert st.tests_ok is True and not (old / "test_old_project.py").exists()
