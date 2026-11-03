"""UI backend: project files are sandboxed and settings are validated. No LLM calls."""
from fastapi.testclient import TestClient

from core.state import ProjectState
from ui import server

client = TestClient(server.app)


def test_index_and_state():
    assert client.get("/").status_code == 200
    assert client.get("/api/state").json()["phase"] in ("chat", "review", "build", "built")


def test_file_reads_stay_inside_project(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("app = 1\n")
    (tmp_path.parent / "secret.txt").write_text("nope")
    server.S.state = ProjectState(workspace=str(tmp_path))
    assert client.get("/api/files").json()["files"] == ["app/main.py"]
    assert client.get("/api/file", params={"path": "app/main.py"}).json()["content"] == "app = 1\n"
    assert client.get("/api/file", params={"path": "../secret.txt"}).status_code == 404
    assert client.get("/api/search", params={"q": "APP"}).json()["results"][0]["line"] == 1


def test_open_project_rejects_traversal():
    assert client.post("/api/projects/open", json={"slug": "../../etc"}).status_code == 404


def test_settings_validation():
    assert client.post("/api/settings", json={"provider": "evil"}).status_code == 422
    assert client.post("/api/settings", json={"sandbox": "none"}).status_code == 422


def test_try_needs_running_api():
    server.S.server = None
    assert client.post("/api/try", json={"method": "GET", "path": "/x"}).status_code == 409
