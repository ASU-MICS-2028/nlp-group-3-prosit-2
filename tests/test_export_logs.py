"""eval/export_logs.py: reads run.py runs and web app projects into runs.csv and steps.csv."""
import csv
import json
from pathlib import Path

from core.spec import Spec
from core.state import LogEntry, Message, ProjectState
from eval import export_logs as X

GOLDEN_SPEC = Spec.model_validate_json((Path(__file__).resolve().parent.parent / "golden/clinic/spec.json").read_text())
STEPS = [LogEntry(agent="requirements", action="ask", detail="Who uses it?", tokens=100, cost_usd=0.001, seconds=2),
         LogEntry(agent="architect", action="spec", tokens=300, cost_usd=0.004, seconds=5),
         LogEntry(agent="orchestrator", action="fix_round"),
         LogEntry(agent="coder", action="finish", detail="line one\nline two", tokens=1000, cost_usd=0.02, seconds=40),
         LogEntry(agent="tester", action="run_tests", tokens=200, cost_usd=0.005, seconds=10)]


def state() -> ProjectState:
    return ProjectState(chat=[Message(role="user", content="hi")], spec=GOLDEN_SPEC, build_ok=True, tests_ok=False,
                        test_summary="1 failed, 87 passed in 1.28s", logs=STEPS)


def rows(path: Path) -> list[dict]:
    return list(csv.DictReader(path.open()))


def test_exports_cli_runs_and_web_projects(tmp_path):
    ws, out = tmp_path / "workspace", tmp_path / "results"
    cli = ws / "golden-clinic-20261115-164419"            # a run.py run
    cli.mkdir(parents=True)
    (cli / "state.json").write_text(state().model_dump_json())
    (cli / "steps.jsonl").write_text("".join(s.model_dump_json() + "\n" for s in STEPS))
    (cli / "summary.json").write_text(json.dumps({"model": "claude-haiku-5-5", "seconds": 90.5}))
    web = ws / "abc123" / "clinic"                        # a web app project: state.json wraps the state
    web.mkdir(parents=True)
    (web / "state.json").write_text(json.dumps({"state": state().model_dump(mode="json"), "revisions": []}))
    (ws / "_published" / "x").mkdir(parents=True)
    (ws / "_published" / "x" / "state.json").write_text("{}")   # published copies are not runs

    assert X.export(ws, out) == (2, 10)
    runs = {r["run"]: r for r in rows(out / "runs.csv")}
    a, b = runs["golden-clinic-20261115-164419"], runs["abc123/clinic"]
    assert (a["source"], a["model"], a["mode"], a["stub"]) == ("cli", "claude-haiku-5-5", "multi", "False")
    assert (a["tests_passed"], a["tests_failed"], a["fix_rounds"], a["questions"]) == ("87", "1", "1", "1")
    assert (a["tokens"], a["cost_usd"], a["coder_tokens"], a["wall_seconds"]) == ("1600", "0.03", "1000", "90.5")
    assert a["spec_score"] == "1.0" and a["spec_reference"] == "golden/clinic/spec.json"   # golden run: compared
    assert b["source"] == "web" and b["spec_score"] == ""                                  # no reference known
    steps = rows(out / "steps.csv")
    assert [s["agent"] for s in steps[:5]] == ["requirements", "architect", "orchestrator", "coder", "tester"]
    assert steps[3]["detail"] == "line one line two"     # one line per step


def test_reference_flag_compares_every_run(tmp_path):
    d = tmp_path / "ws" / "abc" / "shop"
    d.mkdir(parents=True)
    (d / "state.json").write_text(json.dumps({"state": state().model_dump(mode="json")}))
    X.export(tmp_path / "ws", tmp_path / "out", reference=Path("golden/clinic/spec.json"))
    assert rows(tmp_path / "out" / "runs.csv")[0]["spec_score"] == "1.0"


def test_count_tests():
    assert X.count_tests("1 failed, 87 passed in 1.28s") == (87, 1)
    assert X.count_tests("2 passed, 1 error in 0.5s") == (2, 1)
    assert X.count_tests("") == (0, 0)
