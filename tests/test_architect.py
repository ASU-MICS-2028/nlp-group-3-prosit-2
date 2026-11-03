import json

import pytest

from agents import architect
from core.llm import FakeLLM
from core.spec import Requirements
from core.state import ProjectState

REQ = Requirements(
    project_name="Clinic", description="Book appointments",
    users=["patients", "staff"], data=["patients", "appointments"],
    actions=["patients book appointments"], rules=["no double booking"],
)

SPEC = {
    "project_name": "Clinic", "description": "Book appointments",
    "entities": [
        {"name": "Patient", "fields": [{"name": "name", "type": "str"}]},
        {"name": "Appointment", "belongs_to": ["Patient"],
         "fields": [{"name": "patient_id", "type": "int"}, {"name": "starts_at", "type": "datetime"}]},
    ],
    "endpoints": [
        {"method": "POST", "path": "/patients", "summary": "Register", "entity": "Patient",
         "access": "public", "request_fields": ["name"], "status_code": 201},
        {"method": "POST", "path": "/appointments", "summary": "Book", "entity": "Appointment",
         "request_fields": ["patient_id", "starts_at"], "status_code": 201},
    ],
    "rules": ["no double booking"],
}


def state():
    return ProjectState(requirements=REQ)


def test_valid_first_try():
    llm = FakeLLM([json.dumps(SPEC)])
    s = architect.run(state(), llm)
    assert s.spec.entities[1].name == "Appointment"
    assert len(s.tasks) == 2 + 2 + 1
    assert s.tasks[-1] == "Enforce rule: no double booking"
    assert s.logs[-1].action == "generate" and "1 attempt" in s.logs[-1].detail
    assert len(llm.calls) == 1


def test_invalid_json_then_valid():
    llm = FakeLLM(["not json at all", f"```json\n{json.dumps(SPEC)}\n```"])
    s = architect.run(state(), llm)
    assert s.spec is not None and len(llm.calls) == 2
    assert "problems" in llm.calls[1][1][-1]["content"]


def test_bad_entity_ref_fed_back():
    bad = json.loads(json.dumps(SPEC))
    bad["endpoints"][1]["entity"] = "Booking"
    assert any("unknown entity 'Booking'" in p
               for p in architect.check_spec(architect.Spec.model_validate(bad)))
    llm = FakeLLM([json.dumps(bad), json.dumps(SPEC)])
    architect.run(state(), llm)
    assert "Booking" in llm.calls[1][1][-1]["content"]


def test_check_spec_other_problems():
    bad = json.loads(json.dumps(SPEC))
    bad["entities"][1]["belongs_to"] = ["Doctor"]
    bad["endpoints"][0]["request_fields"] = ["phone"]
    bad["endpoints"][1]["path"] = "appointments"
    bad["endpoints"].append(dict(bad["endpoints"][0]))
    problems = " | ".join(architect.check_spec(architect.Spec.model_validate(bad)))
    for needle in ["unknown entity 'Doctor'", "'phone'", "must start with '/'", "duplicate endpoint"]:
        assert needle in problems


def test_three_failures_raise():
    with pytest.raises(RuntimeError):
        architect.run(state(), FakeLLM(["nope"] * 3))


def test_revise_clears_change_request():
    s = architect.run(state(), FakeLLM([json.dumps(SPEC)]))
    s.spec_approved = True
    s.change_request = "Add a notes field to appointments"
    revised = json.loads(json.dumps(SPEC))
    revised["entities"][1]["fields"].append({"name": "notes", "type": "str", "required": False})
    llm = FakeLLM([json.dumps(revised)])
    s = architect.run(s, llm)
    prompt = llm.calls[0][1][0]["content"]
    assert "Current spec" in prompt and "notes field" in prompt
    assert s.change_request is None and s.spec_approved is False
    assert s.logs[-1].action == "revise"
    assert "notes" in s.tasks[1]


def test_missing_requirements_raises():
    with pytest.raises(ValueError):
        architect.run(ProjectState(), FakeLLM([]))


def test_golden_spec_passes_checks():
    import json, pathlib
    from core.spec import Spec
    from agents.architect import check_spec
    spec = Spec.model_validate(json.loads(pathlib.Path("golden/clinic/spec.json").read_text()))
    assert check_spec(spec) == []
