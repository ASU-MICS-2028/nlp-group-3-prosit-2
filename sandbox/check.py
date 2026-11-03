"""Runs INSIDE the sandbox against a workspace holding app/main.py and spec.json.

Prints one JSON report: {"ok": bool, "import_error", "missing_endpoints", "extra_endpoints", "smoke", "pytest"}.
"""
import json
import subprocess
import sys
import traceback

sys.path.insert(0, ".")
report = {"ok": False, "import_error": None, "missing_endpoints": [], "extra_endpoints": [], "smoke": [], "pytest": None}

try:
    from app.main import app
except Exception:
    report["import_error"] = traceback.format_exc()[-2000:]
    print(json.dumps(report))
    sys.exit(0)

spec = json.load(open("spec.json"))
want = {(e["method"], e["path"]) for e in spec["endpoints"]}
have = {(m.upper(), path) for path, ops in app.openapi()["paths"].items() for m in ops}
report["missing_endpoints"] = sorted(f"{m} {p}" for m, p in want - have)
report["extra_endpoints"] = sorted(f"{m} {p}" for m, p in have - want)

# smoke: every GET without path params must not crash (5xx) for a user or an admin
from fastapi.testclient import TestClient
client = TestClient(app, raise_server_exceptions=False)
for m, p in sorted(want):
    if m == "GET" and "{" not in p:
        for role in ("user", "admin"):
            r = client.get(p, headers={"X-Role": role, "X-User-Id": "1"})
            if r.status_code >= 500:
                report["smoke"].append(f"GET {p} as {role} -> {r.status_code}: {r.text[:300]}")

import os
if os.path.isdir("tests"):
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-rA", "--tb=short", "tests"], capture_output=True, text=True)
    report["pytest"] = {"passed": proc.returncode == 0, "output": proc.stdout[-6000:]}

report["ok"] = (not report["missing_endpoints"] and not report["smoke"]
                and (report["pytest"] is None or report["pytest"]["passed"]))
print(json.dumps(report))
