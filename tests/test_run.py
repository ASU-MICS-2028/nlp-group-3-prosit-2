"""run.py, offline: the whole pipeline on the golden clinic with stub agents (no model calls)."""
import asyncio
import json

import run
from agents import orchestrator as O
from server import stubs


def test_golden_pipeline_offline(tmp_path, monkeypatch):
    monkeypatch.setattr(O, "AGENTS", dict(O.AGENTS))   # use_stubs() changes a copy
    monkeypatch.setattr(stubs, "STEP_DELAY", 0)
    run.use_stubs()
    st = asyncio.run(run.run(*_golden(), workspace=tmp_path, serve="check"))
    assert st.requirements and st.spec_approved and st.build_ok and st.tests_ok
    assert st.result.base_url.startswith("http://127.0.0.1:")    # it started and answered /health
    assert (tmp_path / "steps.jsonl").exists() and (tmp_path / "state.json").exists()
    agents = [l.agent for l in st.logs]
    assert agents.index("requirements") < agents.index("architect") < agents.index("coder") < agents.index("tester")

    summary = run.report(st, 1.0, "clinic")
    assert summary["spec_vs_golden"]["score"] == 1.0 and not summary["known_failures"]
    json.dumps(summary)   # summary.json must be plain JSON


def _golden():
    answer = run.golden_answers("clinic")
    return answer(""), answer, True


def test_golden_answers_then_nudge():
    answer = run.golden_answers("clinic")
    turns = [answer("") for _ in range(9)]
    assert turns[0].startswith("Hi, I run a small clinic")
    assert "exactly it" not in " ".join(turns)                   # the confirm turn is the button, not an answer
    assert turns[-1] == run.NUDGE
