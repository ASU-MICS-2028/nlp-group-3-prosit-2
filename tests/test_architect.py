"""Architect agent, offline: a fake runner plays the model's tool calls, so no model is called."""
import asyncio
import json
import pathlib

import pytest

from agents import architect as A
from core.spec import Requirements, Spec
from core.state import ProjectState

GOLDEN = pathlib.Path(__file__).resolve().parent.parent / "golden" / "clinic"
GOLDEN_SPEC = json.loads((GOLDEN / "spec.json").read_text())
GOLDEN_REQ = Requirements.model_validate_json((GOLDEN / "requirements.json").read_text())


async def emit(event):
    pass


def run_with(state, *submissions, replies=None):
    """Run the architect where the 'model' calls submit_spec with each of these, in order."""
    async def fake_runner(system, prompt, tools):
        description, schema, submit_spec = tools["submit_spec"]
        for args in submissions:
            answer = await submit_spec(args)
            if replies is not None:
                replies.append(answer)
        if replies is not None:
            replies.append(prompt)   # last item: the prompt, so tests can look at it
        return {"tokens": 100, "cost_usd": 0.02}
    return asyncio.run(A.run(state, emit, runner=fake_runner))


def test_golden_spec_passes_the_checks():
    assert A.check_spec(Spec(**GOLDEN_SPEC)) == []


def test_good_spec_is_saved_and_needs_approval():
    st = run_with(ProjectState(requirements=GOLDEN_REQ, spec_approved=True), GOLDEN_SPEC)
    assert st.spec == Spec(**GOLDEN_SPEC)
    assert st.spec_approved is False                 # the user must approve it again
    assert st.logs[-1].agent == "architect" and st.logs[-1].tokens == 100
    assert st.logs[-1].cost_usd == 0.02                       # cost of every step is logged


def test_bad_spec_is_sent_back_then_fixed():
    broken = json.loads(json.dumps(GOLDEN_SPEC))
    broken["endpoints"][0]["request_fields"].append("shoe_size")   # Patient has no such field
    replies = []
    st = run_with(ProjectState(requirements=GOLDEN_REQ), broken, GOLDEN_SPEC, replies=replies)
    assert "no field called shoe_size" in replies[0]                # the model is told what is wrong
    assert "accepted" in replies[1]
    assert st.spec == Spec(**GOLDEN_SPEC)


def test_wrong_shape_is_sent_back():
    replies = []
    with pytest.raises(RuntimeError):                               # never fixed: no spec at all
        run_with(ProjectState(requirements=GOLDEN_REQ), {"project_name": "Clinic"}, replies=replies)
    assert "wrong shape" in replies[0]


def test_checks_find_broken_links():
    spec = Spec(project_name="Shop", description="", entities=[
        {"name": "Order", "belongs_to": ["Customer"], "fields": [{"name": "total", "type": "float"}]}],
        endpoints=[{"method": "GET", "path": "/orders", "summary": "List", "entity": "Order"},
                   {"method": "GET", "path": "/orders", "summary": "Again", "entity": "Order"}])
    problems = " ".join(A.check_spec(spec))
    assert "no entity called Customer" in problems
    assert "needs an int field customer_id" in problems
    assert "listed twice" in problems


def test_change_request_shows_the_old_spec_and_the_change():
    st = ProjectState(requirements=GOLDEN_REQ, spec=Spec(**GOLDEN_SPEC),
                      change_request="Add a notes field to Patient",
                      change_files=["app/main.py", "app/schemas/patient.py"])
    replies = []
    st = run_with(st, GOLDEN_SPEC, replies=replies)
    prompt = replies[-1]
    assert "<spec>" in prompt and "Add a notes field to Patient" in prompt
    assert "app/main.py" in prompt and "app/schemas/patient.py" in prompt
    assert st.change_request is None and st.logs[-1].action == "change"


def test_checks_reject_explicit_id_field():
    spec = Spec(project_name="Blog", description="", entities=[
        {"name": "Post", "fields": [{"name": "id", "type": "int"}, {"name": "title", "type": "str"}]}],
        endpoints=[{"method": "GET", "path": "/posts", "summary": "List", "entity": "Post"}])
    problems = A.check_spec(spec)
    assert any("do not list an 'id' field" in p for p in problems)


def test_checks_reject_non_int_foreign_key():
    spec = Spec(project_name="Shop", description="", entities=[
        {"name": "Customer", "fields": [{"name": "name", "type": "str"}]},
        {"name": "Order", "belongs_to": ["Customer"],
         "fields": [{"name": "customer_id", "type": "str"}, {"name": "total", "type": "float"}]}],
        endpoints=[{"method": "GET", "path": "/orders", "summary": "List", "entity": "Order"}])
    problems = A.check_spec(spec)
    assert any("customer_id must have type 'int'" in p for p in problems)


def test_checks_reject_get_with_request_body():
    spec = Spec(project_name="Blog", description="", entities=[
        {"name": "Post", "fields": [{"name": "title", "type": "str"}]}],
        endpoints=[{"method": "GET", "path": "/posts", "summary": "List", "entity": "Post",
                    "request_fields": ["title"]}])
    problems = A.check_spec(spec)
    assert any("GET endpoints cannot accept request_fields" in p for p in problems)
