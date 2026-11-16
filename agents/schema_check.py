"""Schema check (Role 4): throw generated inputs at a built API and report every crash.

The Tester's tests are written by a model from the spec, so they try the inputs a person would
think of. This check is the opposite: Schemathesis reads the API's own OpenAPI document (the one
behind the Swagger page) and generates many requests for every endpoint, valid ones and broken
ones: missing fields, wrong types, empty strings, huge numbers. That is property-based testing:
we do not say which inputs to try, we state a property that must hold for ALL of them:

    whatever is sent, the API answers. It never crashes (no 500, no uncaught exception).

A refusal (401, 404, 409, 422) is a correct answer here. Only a crash is a failure.

How it works, step by step:
  1. The app is copied to a temporary folder, with the Tester's `client` fixture (a fresh app
     on an empty database) and the test file below.
  2. pytest runs it in a separate process. Schemathesis calls every endpoint many times.
  3. For each endpoint that crashed, we keep the smallest request that still crashes it
     (Hypothesis shrinks the failing input), so the report is short and easy to act on.

It is a separate check: nothing in the build pipeline calls it yet. No model is involved, so
it costs nothing to run.

    result = await schema_check.check(Path(workspace) / "app")
    result["crashes"]   # [{"endpoint": "GET /doctors/{id}", "request": "GET /doctors/9223372036854775808", "error": "OverflowError: ..."}]
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from agents import tester
from core.spec import Failure

EXAMPLES = int(os.getenv("SCHEMA_CHECK_EXAMPLES", "40"))   # generated requests per endpoint
TIMEOUT = 300                                              # seconds for the whole check
REPORT = "schema_check.json"

# The test file. Written by our code; {examples} is filled in.
TEST = '''"""Written by the platform: Schemathesis calls every endpoint with generated inputs."""
import json

import pytest
import schemathesis
from hypothesis import HealthCheck, settings

ADMIN = {{"X-Role": "admin", "X-User-Id": "1"}}   # signed in as an admin, so the requests reach the code
seen, crashes = set(), {{}}


@pytest.fixture
def api(client):
    return schemathesis.openapi.from_asgi("/openapi.json", client.app)


schema = schemathesis.pytest.from_fixture("api")


@schema.parametrize()
@settings(max_examples={examples}, derandomize=True, deadline=None, database=None,
          suppress_health_check=list(HealthCheck))
def test_no_input_crashes_the_api(case):
    endpoint = case.operation.label
    seen.add(endpoint)
    try:
        response = case.call(headers=ADMIN)
        crash = f"answered {{response.status_code}}: {{response.text[:200]}}" if response.status_code >= 500 else None
    except Exception as e:                       # the app raised instead of answering
        crash = f"{{type(e).__name__}}: {{e}}"[:300]
    if crash:
        body = "" if isinstance(case.body, schemathesis.core.NotSet) else " body " + json.dumps(case.body, default=str)[:300]
        query = " query " + json.dumps(case.query, default=str)[:200] if case.query else ""
        # The last crash recorded for an endpoint is the smallest one: Hypothesis shrinks the input.
        crashes[endpoint] = {{"endpoint": endpoint, "request": f"{{case.method}} {{case.formatted_path}}{{query}}{{body}}", "error": crash}}
        raise AssertionError(crash)


@pytest.fixture(scope="session", autouse=True)
def write_report():
    yield
    with open("{report}", "w") as f:
        json.dump({{"endpoints": sorted(seen), "crashes": [crashes[e] for e in sorted(crashes)]}}, f)
'''


async def check(app: Path, examples: int = EXAMPLES) -> dict:
    """Fuzz the app in `app` (a folder holding main.py). The folder itself is not changed.
    Returns {"ok", "endpoints", "crashes", "summary"}; "ok" is True when nothing crashed.
    ponytail: a plain local process, not isolated. Role 3's check sandbox replaces this call."""
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp)
        shutil.copytree(app, project / "app", ignore=shutil.ignore_patterns("__pycache__"))
        (project / "tests").mkdir()
        (project / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n")
        (project / "tests" / "conftest.py").write_text(tester.CONFTEST)
        (project / "tests" / "test_schema.py").write_text(TEST.format(examples=examples, report=REPORT))
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pytest", "-q", "--tb=no", "-p", "no:cacheprovider", "tests",
            cwd=project, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        try:
            output = (await asyncio.wait_for(proc.communicate(), TIMEOUT))[0].decode(errors="replace")
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {"ok": False, "endpoints": [], "crashes": [], "summary": f"The schema check timed out after {TIMEOUT}s."}
        report = project / REPORT
        if not report.exists() or not json.loads(report.read_text())["endpoints"]:
            # Nothing was called: the app does not start, or schemathesis is not installed.
            return {"ok": False, "endpoints": [], "crashes": [],
                    "summary": "The schema check could not run: " + (output.strip().splitlines() or ["no output"])[-1][:300]}
        result = json.loads(report.read_text())
    crashed = len(result["crashes"])
    summary = (f"{crashed} of {len(result['endpoints'])} endpoints crashed on generated input" if crashed
               else f"No crash on generated input ({len(result['endpoints'])} endpoints)")
    return {"ok": crashed == 0, **result, "summary": summary}


def as_failures(result: dict) -> list[Failure]:
    """The crashes in the shared failure-report format, ready to hand to the Coder."""
    return [Failure(endpoint=c["endpoint"], test="schema_check", expected="an answer below 500 for any input",
                    got=c["error"], hint="Smallest request that crashes it: " + c["request"])
            for c in result["crashes"]]
