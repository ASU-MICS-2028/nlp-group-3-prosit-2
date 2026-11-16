"""Benchmark scenarios, offline: every scenario is well-formed, and the hidden tests really judge
(they pass on a correct app and fail on a broken one). No model is called."""
import ast
import asyncio
import pathlib
import re
import shutil

import pytest

import benchmark
from agents.architect import check_spec, snake

GOLDEN_APP = pathlib.Path(__file__).resolve().parent.parent / "golden" / "clinic" / "app"
ALL = benchmark.scenarios()
by_name = pytest.mark.parametrize("scenario", ALL, ids=[s.name for s in ALL])


def test_there_are_enough_scenarios():
    assert 20 <= len(ALL) <= 30
    assert len({s.spec.project_name for s in ALL}) == len(ALL)


@by_name
def test_the_reference_spec_is_one_the_architect_would_accept(scenario):
    assert check_spec(scenario.spec) == []
    for ep in scenario.spec.endpoints:
        expected = 201 if ep.method == "POST" and "{" not in ep.path else 204 if ep.method == "DELETE" else 200
        assert ep.status_code == expected, f"{ep.method} {ep.path}"


@by_name
def test_requirements_and_spec_describe_the_same_project(scenario):
    assert scenario.requirements.project_name == scenario.spec.project_name
    assert scenario.requirements.data and scenario.requirements.actions
    words = " ".join(scenario.requirements.data).lower()
    for entity in scenario.spec.entities:   # every stored thing is mentioned to the person, in plain words
        assert snake(entity.name).split("_")[-1][:4] in words, entity.name


@by_name
def test_examples_give_a_valid_body_for_every_entity_that_can_be_created(scenario):
    for entity in scenario.spec.entities:
        post = next((ep for ep in scenario.spec.endpoints
                     if ep.entity == entity.name and ep.method == "POST" and "{" not in ep.path), None)
        if post is None:
            continue
        assert entity.name in scenario.examples, f"no example for {entity.name}"
        body = scenario.examples[entity.name]["create"]
        foreign_keys = {f"{snake(parent)}_id" for parent in entity.belongs_to}   # filled in by the tests
        fields = {f.name: f for f in entity.fields}
        assert set(body) <= set(post.request_fields) - foreign_keys, entity.name
        required = {name for name in post.request_fields if fields[name].required} - foreign_keys
        assert required <= set(body), f"{entity.name}: the example lacks {required - set(body)}"
        assert set(scenario.examples[entity.name].get("update", {})) <= set(fields)


@by_name
def test_rule_tests_are_valid_and_use_the_client_fixture(scenario):
    tree = ast.parse((scenario.path / "rules.py").read_text())
    tests = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")]
    assert len(tests) >= 5
    assert all([a.arg for a in t.args.args] == ["client"] for t in tests)
    assert len({t.name for t in tests}) == len(tests)


@by_name
def test_rule_tests_only_call_endpoints_that_are_in_the_spec(scenario):
    """A hidden test for an endpoint the spec does not have would fail every build, whatever its quality."""
    source = (scenario.path / "rules.py").read_text()
    served = [re.sub(r"\{[^}]*\}", "{}", ep.path) for ep in scenario.spec.endpoints]
    for path in re.findall(r"""f?["'](/[a-z][^"'?]*)["']""", source):
        if "{" not in path:                                # a fixed path, e.g. "/rooms" or "/loans/987654/return"
            assert re.sub(r"\d+", "{}", path) in served, path
            continue
        start = path[:path.index("{")]                     # f"/loans/{loan['id']}/return" starts with "/loans/"
        assert any(p.startswith(start) for p in served), path
    for action in re.findall(r"""\}(/[a-z_]+)["']""", source):   # ... and ends with "/return"
        assert any(p.endswith("{}" + action) for p in served), action


def judge(scenario, app):
    return asyncio.run(benchmark.judge(scenario, app))


def test_the_golden_clinic_passes_its_hidden_tests():
    run = judge(benchmark.load("01-clinic"), GOLDEN_APP)
    assert run["ok"] and run["score"] == 1.0 and run["total"] >= 60, run["output"][-2000:]
    files = {r["file"] for r in run["results"]}
    assert files == {"tests/test_contract.py", "tests/test_hidden_generic.py", "tests/test_hidden_rules.py"}


BUGS = [   # (what is broken, old code, new code, a hidden test that must catch it)
    ("duplicate phones are accepted", 'raise HTTPException(409, "Phone number already registered")', "pass",
     "test_duplicate_unique_field_is_409"),
    ("double booking is allowed", 'raise HTTPException(409, "Doctor already has an appointment at that time")', "pass",
     "test_same_doctor_same_time_is_409"),
    ("cancel does nothing", 'a["status"] = "cancelled"', "pass", "test_cancel_sets_status_and_keeps_the_appointment"),
    ("anyone can list patients", "dependencies=[ADMIN])\ndef list_patients", ")\ndef list_patients", "test_contract_401_get_patients"),
    ("unknown doctors are accepted", '    get_or_404("doctors", body.doctor_id)\n', "", "test_unknown_parent_is_404"),
    ("delete keeps the doctor", '    del db["doctors"][id]\n', "", "test_delete_removes_the_record"),
]


@pytest.mark.parametrize("what,old,new,caught_by", BUGS, ids=[b[0] for b in BUGS])
def test_hidden_tests_catch_a_bug(tmp_path, what, old, new, caught_by):
    app = tmp_path / "app"
    shutil.copytree(GOLDEN_APP, app, ignore=shutil.ignore_patterns("__pycache__"))
    source = (app / "main.py").read_text()
    assert old in source
    (app / "main.py").write_text(source.replace(old, new))
    run = judge(benchmark.load("01-clinic"), app)
    failed = [r["name"].split("[")[0] for r in run["results"] if r["outcome"] != "passed"]
    assert caught_by in failed and 0 < run["score"] < 1, failed


def test_judging_leaves_the_project_untouched(tmp_path):
    app = tmp_path / "app"
    shutil.copytree(GOLDEN_APP, app, ignore=shutil.ignore_patterns("__pycache__"))
    before = sorted(p.name for p in tmp_path.rglob("*"))
    judge(benchmark.load("01-clinic"), app)
    assert sorted(p.name for p in tmp_path.rglob("*") if "__pycache__" not in p.parts) == before   # no hidden tests left behind


def test_an_app_that_does_not_start_scores_zero(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("raise RuntimeError('broken')\n")
    run = judge(benchmark.load("01-clinic"), tmp_path / "app")
    assert not run["ok"] and run["passed"] == 0 and run["score"] == 0.0
