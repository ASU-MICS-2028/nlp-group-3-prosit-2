"""Gateway end to end on the stub agents: chat -> spec -> approve -> build -> files -> run -> proxy."""
import importlib
import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("STUB_STEP_DELAY", "0")
    import server.stubs
    import server.app
    importlib.reload(server.stubs)
    gw = importlib.reload(server.app)
    with TestClient(gw.app) as c:
        yield c


def wait_idle(c, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        s = c.get("/api/state").json()
        if not s["busy"]:
            assert not s["error"], s["error"]
            return s
        time.sleep(0.05)
    raise TimeoutError


def test_full_flow(client):
    c = client
    assert c.get("/").status_code == 200 and "sid" in c.cookies

    c.post("/api/chat", json={"text": "I run a clinic"})
    s = wait_idle(c)
    assert s["phase"] == "chat" and s["state"]["chat"][-1]["role"] == "assistant"

    c.post("/api/chat", json={"text": "Patients and staff"})
    s = wait_idle(c)
    assert s["phase"] == "review" and s["state"]["spec"]["entities"]

    c.post("/api/spec/approve")
    s = wait_idle(c)
    assert s["phase"] == "built" and s["state"]["tests_ok"], s["state"]["test_report"]
    assert s["state"]["test_results"] and all(r["outcome"] == "passed" for r in s["state"]["test_results"])

    assert "app/main.py" in c.get("/api/files").json()["files"]
    assert c.get("/api/search", params={"q": "FastAPI"}).json()["results"]
    assert c.get("/api/map").json()["nodes"]
    assert c.get("/api/export").headers["content-type"] == "application/zip"
    assert c.get("/api/file", params={"path": "../../etc/passwd"}).status_code == 404

    assert c.get("/api/app/docs").status_code == 409            # not started yet
    s = c.post("/api/run").json()
    assert s["server"]["url"] == "/api/app"
    try:
        docs = c.get("/api/app/docs")
        assert docs.status_code == 200 and "/api/app/openapi.json" in docs.text
        r = c.get("/api/app/doctors", headers={"X-Role": "user", "X-User-Id": "1"})
        assert r.status_code == 200
    finally:
        c.post("/api/run/stop")


def test_sessions_are_separate(client, tmp_path):
    from server.app import app
    client.post("/api/chat", json={"text": "hello"})
    wait_idle(client)
    with TestClient(app) as other:
        assert other.get("/api/state").json()["state"]["chat"] == []
