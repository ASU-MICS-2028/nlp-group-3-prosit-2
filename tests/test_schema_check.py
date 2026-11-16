"""Schema check, offline: Schemathesis really runs against copies of the golden clinic app.
No model is called."""
import asyncio
import pathlib
import shutil

import pytest

from agents import schema_check as C

GOLDEN_APP = pathlib.Path(__file__).resolve().parent.parent / "golden" / "clinic" / "app"

# (what is broken, old code, new code, endpoint that must be reported, part of the error)
BUGS = [
    ("an empty specialty crashes", "    d = {\"id\": new_id(), **body.model_dump()}\n",
     "    d = {\"id\": new_id(), **body.model_dump(), \"initial\": body.specialty[0]}\n", "POST /doctors", "IndexError"),
    ("a huge id crashes", "def get_patient(id: int):\n",
     "def get_patient(id: int):\n    id.to_bytes(8, signed=True)   # what SQLite does with an id\n", "GET /patients/{id}", "OverflowError"),
    ("an endpoint answers 500", "def list_doctors():\n", "def list_doctors():\n    raise HTTPException(500, \"oops\")\n",
     "GET /doctors", "answered 500"),
]


def check(app, examples=25):
    return asyncio.run(C.check(app, examples=examples))


@pytest.fixture
def app(tmp_path):
    shutil.copytree(GOLDEN_APP, tmp_path / "app", ignore=shutil.ignore_patterns("__pycache__"))
    return tmp_path / "app"


def test_the_golden_app_survives_generated_input(app):
    before = sorted(p.name for p in app.parent.rglob("*"))
    result = check(app)
    assert result["ok"] and result["crashes"] == [] and C.as_failures(result) == []
    assert {"POST /patients", "GET /doctors/{id}", "POST /appointments/{id}/cancel", "GET /health"} <= set(result["endpoints"])
    assert result["summary"] == f"No crash on generated input ({len(result['endpoints'])} endpoints)"
    assert sorted(p.name for p in app.parent.rglob("*") if "__pycache__" not in p.parts) == before   # the project is untouched


@pytest.mark.parametrize("what,old,new,endpoint,error", BUGS, ids=[b[0] for b in BUGS])
def test_a_crash_is_found_and_reported_with_the_request(app, what, old, new, endpoint, error):
    source = (app / "main.py").read_text()
    assert old in source
    (app / "main.py").write_text(source.replace(old, new))
    result = check(app)
    assert not result["ok"] and [c["endpoint"] for c in result["crashes"]] == [endpoint]
    crash = result["crashes"][0]
    assert error in crash["error"] and crash["request"].startswith(endpoint.split()[0] + " /")
    assert result["summary"] == f"1 of {len(result['endpoints'])} endpoints crashed on generated input"
    [failure] = C.as_failures(result)      # the same crash, in the format the Coder reads
    assert failure.endpoint == endpoint and failure.test == "schema_check" and crash["request"] in failure.hint


def test_the_smallest_crashing_request_is_kept_and_the_result_repeats(app):
    source = (app / "main.py").read_text()
    (app / "main.py").write_text(source.replace(BUGS[0][1], BUGS[0][2]))
    first, second = check(app), check(app)
    assert first == second                                             # same inputs every time (derandomize)
    assert '"specialty": ""' in first["crashes"][0]["request"]         # shrunk to the empty string that causes it


def test_a_refusal_is_not_a_crash(app):
    """401, 404, 409 and 422 are correct answers to bad input."""
    source = (app / "main.py").read_text()
    (app / "main.py").write_text(source.replace("def list_doctors():\n", "def list_doctors():\n    raise HTTPException(409, \"busy\")\n"))
    assert check(app)["ok"]


def test_an_app_that_does_not_start_is_reported_not_raised(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("raise RuntimeError('broken')\n")
    result = check(tmp_path / "app")
    assert not result["ok"] and result["crashes"] == [] and result["summary"].startswith("The schema check could not run")
