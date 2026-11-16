"""Evaluation script, offline: fake agents stand in for the Coder and Tester (they copy the
golden clinic app), the hidden tests really run, and the CSV is checked. No model is called."""
import asyncio
import pathlib
import shutil

import pytest

from agents import orchestrator
from core.state import LogEntry
from eval import run as E

GOLDEN_APP = pathlib.Path(__file__).resolve().parent.parent / "golden" / "clinic" / "app"
BUG = ('raise HTTPException(409, "Phone number already registered")', "pass")


def fake_coder(bug=None, fixes=False):
    """A Coder that writes the golden app, optionally with a bug, optionally fixing it when sent back."""
    async def coder(state, emit):
        app = pathlib.Path(state.workspace) / "app"
        shutil.rmtree(app, ignore_errors=True)
        shutil.copytree(GOLDEN_APP, app, ignore=shutil.ignore_patterns("__pycache__"))
        if bug and not (fixes and state.tests_ok is False):
            main = app / "main.py"
            main.write_text(main.read_text().replace(*bug))
        state.build_ok = True
        state.logs.append(LogEntry(agent="coder", action="finish", tokens=1000, cost_usd=0.01, seconds=1.0))
        return state
    return coder


def fake_tester(finds_bug=False):
    async def tester(state, emit):
        first = state.tests_ok is None
        state.tests_ok = not (finds_bug and first)
        state.test_report = None if state.tests_ok else "- test_duplicate: expected 409, got 201."
        state.test_results = [{"file": "tests/test_api.py", "name": "test_duplicate", "outcome": "passed" if state.tests_ok else "failed"}]
        state.logs.append(LogEntry(agent="tester", action="run_tests", tokens=500 if first else 0, cost_usd=0.005 if first else 0))
        return state
    return tester


@pytest.fixture
def setup(tmp_path, monkeypatch):
    def use(coder, tester=fake_tester()):
        monkeypatch.setitem(orchestrator.AGENTS, "coder", coder)
        monkeypatch.setitem(orchestrator.AGENTS, "tester", tester)
    monkeypatch.setattr(E, "WORKSPACES", tmp_path / "ws")
    monkeypatch.setattr(orchestrator, "MAX_FIX_ROUNDS", 1)
    return use, tmp_path / "results.csv"


def go(path, label="team", system="team", names=("01-clinic",), repeat=1):
    return asyncio.run(E.run_all(label, system, list(names), repeat, 2, path))


def test_a_good_build_gets_a_full_score_and_a_row(setup):
    use, path = setup
    use(fake_coder())
    go(path)
    [row] = E.read(path)
    assert list(row) == E.COLUMNS
    assert (row["label"], row["system"], row["scenario"], row["run"]) == ("team", "team", "01-clinic", "1")
    assert row["build_ok"] == "True" and row["tests_ok"] == "True" and row["all_passed"] == "True"
    assert row["hidden_passed"] == row["hidden_total"] and int(row["hidden_total"]) >= 60 and row["hidden_score"] == "1.0"
    assert (row["tokens"], row["coder_tokens"], row["tester_tokens"], row["cost_usd"]) == ("1500", "1000", "500", "0.015")
    assert row["fix_rounds"] == "0" and row["failed"] == "" and row["error"] == ""
    assert not (E.WORKSPACES / "team" / "01-clinic-1" / "tests" / "test_hidden_rules.py").exists()   # hidden tests stay hidden


def test_a_bug_the_tester_misses_lowers_the_hidden_score(setup):
    use, path = setup
    use(fake_coder(bug=BUG))
    go(path)
    [row] = E.read(path)
    assert row["tests_ok"] == "True" and row["all_passed"] == "False" and 0 < float(row["hidden_score"]) < 1
    assert "test_duplicate_unique_field_is_409" in row["failed"]


def test_a_fix_round_is_counted_and_the_fixed_build_passes(setup):
    use, path = setup
    use(fake_coder(bug=BUG, fixes=True), fake_tester(finds_bug=True))
    go(path)
    [row] = E.read(path)
    assert row["fix_rounds"] == "1" and row["all_passed"] == "True" and row["coder_tokens"] == "2000"


def test_coder_only_runs_no_tester(setup):
    use, path = setup

    async def no_tester(state, emit):
        raise AssertionError("the coder-only system must not call the Tester")
    use(fake_coder(bug=BUG), no_tester)
    go(path, label="no-tester", system="coder")
    [row] = E.read(path)
    assert row["tests_ok"] == "" and row["tester_tokens"] == "0" and row["fix_rounds"] == "0" and row["all_passed"] == "False"


def test_finished_builds_are_not_run_again_but_errors_are(setup):
    use, path = setup
    calls = []

    async def broken(state, emit):
        calls.append(1)
        raise RuntimeError("no connection")
    use(broken)
    go(path)
    assert E.read(path)[0]["error"] == "RuntimeError: no connection"
    use(fake_coder())
    assert len(go(path)) == 1          # the failed one is tried again
    assert len(go(path)) == 0          # now it is done: nothing to run
    assert len(go(path, repeat=2)) == 1 and E.read(path)[-1]["run"] == "2"
    assert len(go(path, label="other")) == 1


def test_an_app_that_does_not_start_is_a_zero_not_a_crash(setup):
    use, path = setup

    async def bad_coder(state, emit):
        app = pathlib.Path(state.workspace) / "app"
        app.mkdir()
        (app / "main.py").write_text("raise RuntimeError('broken')\n")
        return state                       # build_ok stays False, so the Tester is skipped
    use(bad_coder)
    go(path)
    [row] = E.read(path)
    assert row["build_ok"] == "False" and row["hidden_passed"] == "0" and row["all_passed"] == "False"
    assert row["hidden_score"] == "0.0" and row["error"] == "" and row["failed"]   # a real result, so it is not run again
    assert len(go(path)) == 0


def test_summary_has_one_line_per_label(setup):
    use, path = setup
    use(fake_coder())
    go(path, label="team")
    use(fake_coder(bug=BUG))
    go(path, label="no-tester", system="coder")
    table = E.summary(E.read(path))
    assert [(t["label"], t["builds"], t["all_passed"]) for t in table] == [("team", 1, 1), ("no-tester", 1, 0)]
    assert table[0]["hidden_score"] == 1.0 > table[1]["hidden_score"] and table[0]["tokens_per_build"] == 1500
    text = E.as_text(table)
    assert text.splitlines()[0].split()[:3] == ["label", "model", "builds"] and len(text.splitlines()) == 3
    assert E.as_text([]) == "No results yet."
