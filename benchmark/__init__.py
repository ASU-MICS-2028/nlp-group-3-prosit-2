"""Benchmark (Role 4): scenarios to build, and hidden tests to judge what was built.

Each folder in benchmark/scenarios/ is one scenario:
  requirements.json   what the person asked for (core.spec.Requirements): the input of a full run
  spec.json           the reference spec (core.spec.Spec): what a correct design looks like, and
                      the input when only the Coder and Tester are being measured
  examples.json       one valid body per entity, {"Entity": {"create": {...}, "update": {...}}},
                      so the generic hidden tests can create records
  rules.py            hidden tests for this scenario's business rules

Hidden tests are the judge. No agent ever sees them: the Tester's own tests decide the fix
rounds, the hidden tests decide the score. A build is judged on three files:
  test_contract.py         from the spec (the same contract tests the Tester uses)
  test_hidden_generic.py   benchmark/generic_tests.py: create/read/update/delete, 404, 409, 422
  test_hidden_rules.py     the scenario's rules.py
"""
import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from agents import tester
from core.spec import Requirements, Spec

HERE = Path(__file__).parent
SCENARIOS = HERE / "scenarios"


@dataclass(frozen=True)
class Scenario:
    name: str               # the folder name, e.g. "03-library"
    path: Path
    requirements: Requirements
    spec: Spec
    examples: dict


def load(name: str) -> Scenario:
    path = SCENARIOS / name
    return Scenario(name=name, path=path,
                    requirements=Requirements.model_validate_json((path / "requirements.json").read_text()),
                    spec=Spec.model_validate_json((path / "spec.json").read_text()),
                    examples=json.loads((path / "examples.json").read_text()))


def scenarios() -> list[Scenario]:
    return [load(p.name) for p in sorted(SCENARIOS.iterdir()) if (p / "spec.json").exists()]


def write_hidden_tests(scenario: Scenario, project: Path) -> None:
    """Replace project/tests with the hidden tests (and the platform's conftest and contract tests)."""
    tests = project / "tests"
    shutil.rmtree(tests, ignore_errors=True)
    tester.write_platform_files(project, scenario.spec)        # pytest.ini, conftest.py, test_contract.py
    shutil.copy(HERE / "generic_tests.py", tests / "test_hidden_generic.py")
    shutil.copy(scenario.path / "rules.py", tests / "test_hidden_rules.py")
    (tests / "hidden_spec.json").write_text(scenario.spec.model_dump_json())
    (tests / "hidden_examples.json").write_text(json.dumps(scenario.examples))


async def judge(scenario: Scenario, app: Path) -> dict:
    """Run the hidden tests on a built app/ folder. The build itself is not touched: the app is
    copied to a temporary folder first, so the hidden tests never appear in the project.
    Returns the run from tester.run_pytest plus "passed", "total" and "score" (0..1)."""
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp)
        shutil.copytree(app, project / "app", ignore=shutil.ignore_patterns("__pycache__"))
        write_hidden_tests(scenario, project)
        run = await tester.run_pytest(project)
    passed = sum(r["outcome"] == "passed" for r in run["results"])
    total = sum(r["outcome"] in ("passed", "failed", "error") for r in run["results"])
    return {**run, "passed": passed, "total": total, "score": passed / total if total else 0.0}
