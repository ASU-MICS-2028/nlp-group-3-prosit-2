"""Gateway end to end on the stub agents: chat -> spec -> approve -> build -> files -> run -> proxy."""
import importlib
import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("STUB_STEP_DELAY", "0")
    monkeypatch.setenv("REQUIREMENTS_AGENT", "stub")   # golden replay, no model calls
    (tmp_path / "traefik").mkdir()
    monkeypatch.setenv("TRAEFIK_DYNAMIC_DIR", str(tmp_path / "traefik"))
    import server.stubs
    import agents.orchestrator
    import server.app
    importlib.reload(server.stubs)
    importlib.reload(agents.orchestrator)   # picks its agents from the env vars above
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
    assert c.get("/health").json() == {"status": "ok"}

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
    assert s["state"]["result"]["docs_url"] == "/api/app/docs" and s["state"]["result"]["endpoints"]
    try:
        docs = c.get("/api/app/docs")
        assert docs.status_code == 200 and "/api/app/openapi.json" in docs.text
        r = c.get("/api/app/doctors", headers={"X-Role": "user", "X-User-Id": "1"})
        assert r.status_code == 200
        assert c.get("/api/app/health").json() == {"status": "ok"}
    finally:
        c.post("/api/run/stop")


def test_sessions_are_separate(client, tmp_path):
    from server.app import app
    client.post("/api/chat", json={"text": "hello"})
    wait_idle(client)
    other = TestClient(app)   # no `with`: one gateway lifespan, two browsers
    assert other.get("/api/state").json()["state"]["chat"] == []


def build_golden(c):
    c.post("/api/chat", json={"text": "I run a clinic"}); wait_idle(c)
    c.post("/api/chat", json={"text": "Patients and staff"}); wait_idle(c)
    c.post("/api/spec/approve")
    return wait_idle(c)


def test_publish_to_subdomain(client, tmp_path):
    from server.app import app
    c = client
    assert c.post("/api/publish", json={"subdomain": "clinic"}).status_code == 409   # nothing built
    build_golden(c)

    check = lambda sub: c.get("/api/publish/check", params={"sub": sub}).json()
    assert check("clinic")["available"]
    assert not check("www")["available"] and not check("-bad-")["available"] and not check("ab")["available"]

    s = c.post("/api/publish", json={"subdomain": "clinic"}).json()
    assert s["published"]["url"] == "http://clinic.localhost:8000"
    live = {"host": "clinic.localhost:8000"}
    r = c.get("/doctors", headers={**live, "X-Role": "user", "X-User-Id": "1"})
    assert r.status_code == 200 and "set-cookie" not in r.headers
    assert c.get("/", headers={"host": "nothing.localhost:8000"}).status_code == 404
    assert "Mesora Blocks" in c.get("/", headers={"host": "www.localhost:8000"}).text   # reserved names are the app
    route = (tmp_path / "traefik" / "mesora-clinic.yaml").read_text()   # hosted: an HTTPS route per subdomain
    assert "Host(`clinic.localhost`)" in route and "certResolver: letsencrypt" in route

    other = TestClient(app)   # another browser can't take or remove it
    assert not other.get("/api/publish/check", params={"sub": "clinic"}).json()["available"]
    assert other.delete("/api/publish").status_code == 404

    s = c.post("/api/publish", json={"subdomain": "my-clinic"}).json()   # rename moves it
    assert s["published"]["subdomain"] == "my-clinic"
    assert c.get("/doctors", headers=live).status_code == 404
    assert c.get("/openapi.json", headers={"host": "my-clinic.localhost"}).status_code == 200

    assert not (tmp_path / "traefik" / "mesora-clinic.yaml").exists()   # rename removed the old route
    c.delete("/api/publish")
    assert c.get("/api/state").json()["published"] is None
    assert not list((tmp_path / "traefik").iterdir())
    assert c.get("/openapi.json", headers={"host": "my-clinic.localhost"}).status_code == 404


def test_published_api_survives_restart(client):
    from server.app import app
    build_golden(client)
    client.post("/api/publish", json={"subdomain": "clinic"})
    client.__exit__(None, None, None)          # gateway shuts down, published API stops
    with TestClient(app) as fresh:             # and comes back on start-up
        assert fresh.get("/openapi.json", headers={"host": "clinic.localhost"}).status_code == 200


def test_api_without_health_check_is_refused(tmp_path):
    import asyncio
    from server.stubs import serve
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("")
    (tmp_path / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    with pytest.raises(RuntimeError, match="health check"):
        asyncio.run(serve(str(tmp_path), ""))


def test_installable_as_app(client):
    sw = client.get("/sw.js")
    assert sw.status_code == 200 and "javascript" in sw.headers["content-type"] and "/api/" in sw.text
    m = client.get("/static/site.webmanifest")
    assert m.headers["content-type"].startswith("application/manifest+json")
    icons = {(i["sizes"], i.get("purpose", "any")) for i in m.json()["icons"]}
    assert {("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")} <= icons
    for i in m.json()["icons"]:
        assert client.get(i["src"]).status_code == 200
    assert client.get("/static/offline.html").status_code == 200


def test_requirements_agent_through_the_gateway(client, monkeypatch):
    """Real agent code with a scripted model: question with quick replies, summary, Looks right -> design."""
    import json as _json
    import pathlib as _pl
    from agents import orchestrator
    from agents import requirements as R
    golden = _json.loads(_pl.Path("golden/clinic/requirements.json").read_text())
    script = iter([("ask_user", {"question": "Who uses it?", "options": ["Patients", "Patients and staff"]}),
                   ("propose_summary", golden)])

    async def runner(system, prompt, tools, schemas):
        name, args = next(script)
        await tools[name](args)
        return {}
    monkeypatch.setitem(orchestrator.AGENTS, "requirements", lambda st, emit: R.run(st, emit, runner=runner))

    client.post("/api/chat", json={"text": "I run a clinic"})
    s = wait_idle(client)
    assert s["reply_options"] == ["Patients", "Patients and staff"] and s["pending_summary"] is None
    client.post("/api/chat", json={"text": "Patients and staff"})
    s = wait_idle(client)
    assert s["pending_summary"]["project_name"] == golden["project_name"] and s["reply_options"] == []
    assert client.post("/api/requirements/confirm").status_code == 200
    s = wait_idle(client)
    assert s["phase"] == "review" and s["state"]["requirements"]["project_name"] == golden["project_name"]
    assert client.post("/api/requirements/confirm").status_code == 409   # nothing pending any more
