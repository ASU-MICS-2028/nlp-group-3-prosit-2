"""Sandbox: the docker commands are checked without Docker; local mode runs for real; the Docker tests
run only where Docker and the prosit-sandbox image are available (they are skipped otherwise)."""
import asyncio
import shutil
import subprocess

import httpx
import pytest

from core import sandbox

HEALTHY_APP = '''from fastapi import FastAPI
import os, sqlite3

app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/notes")
def add(text: str):
    with sqlite3.connect(os.environ["DATABASE_PATH"]) as c:
        c.execute("CREATE TABLE IF NOT EXISTS notes (text TEXT)")
        c.execute("INSERT INTO notes VALUES (?)", (text,))
    return {"ok": True}


@app.get("/notes")
def notes():
    with sqlite3.connect(os.environ["DATABASE_PATH"]) as c:
        c.execute("CREATE TABLE IF NOT EXISTS notes (text TEXT)")
        return [r[0] for r in c.execute("SELECT text FROM notes")]
'''


def project(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("")
    (tmp_path / "app" / "main.py").write_text(HEALTHY_APP)
    return tmp_path


def py(ws, code, **kw):
    return asyncio.run(sandbox.run(ws, ["python", "-c", code], **kw))


# ---------- the docker commands (no Docker needed) ----------

def test_check_container_is_locked_down(tmp_path):
    cmd = sandbox.check_command(tmp_path, ["python", "-m", "pytest"], {"DATABASE_PATH": "/tmp/check.db"}, "c1")
    line = " ".join(cmd)
    assert "--network none" in line                                   # no network at all
    assert f"{tmp_path.resolve()}:/work:ro" in line                   # code is read-only
    assert "--read-only" in cmd and "--tmpfs" in cmd                  # nothing else writable but /tmp
    assert "--memory 512m" in line and "--cpus 1" in line and "--pids-limit 128" in line
    assert "--cap-drop ALL" in line and "no-new-privileges" in line
    assert not cmd[cmd.index("--user") + 1].startswith("0:")          # never root
    assert "--env=DATABASE_PATH=/tmp/check.db" in cmd
    assert cmd[-2:] == ["-m", "pytest"]


def test_served_container_mounts_only_app_and_data(tmp_path):
    cmd = sandbox.serve_command(tmp_path, "/api/app", 8123, "s1")
    line = " ".join(cmd)
    assert "--publish 127.0.0.1:8123:8000" in line                    # reachable from this machine only
    assert f"{(tmp_path / 'app').resolve()}:/work/app:ro" in line      # code read-only
    assert f"{(tmp_path / 'data').resolve()}:/data " in line + " "     # the database is the only writable mount
    assert "--read-only" in cmd and "DATABASE_PATH=/data/app.db" in cmd
    assert sum(c == "--volume" for c in cmd) == 2                     # nothing else from the project (state, tests)
    assert cmd[-2:] == ["--root-path", "/api/app"]


def test_unknown_mode_is_refused(monkeypatch):
    monkeypatch.setenv("SANDBOX", "none")
    with pytest.raises(RuntimeError, match="docker or local"):
        sandbox.mode()


def test_ports_come_from_the_serve_range(monkeypatch):
    monkeypatch.setenv("SERVE_PORT_RANGE", "8150-8199")
    assert 8150 <= sandbox.free_port() <= 8199


# ---------- local mode (runs for real) ----------

@pytest.fixture
def local(monkeypatch):
    monkeypatch.setenv("SANDBOX", "local")


def test_generated_code_never_sees_our_secrets(tmp_path, local, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")
    r = py(tmp_path, "import os; print(os.environ.get('ANTHROPIC_API_KEY'))")
    assert r.code == 0 and r.output.strip() == "None"


def test_checks_get_a_throwaway_database(tmp_path, local):
    r = py(tmp_path, "import os; print(os.environ['DATABASE_PATH'])")
    db = r.output.strip()
    assert db.endswith("check.db") and not db.startswith(str(tmp_path))


def test_a_run_that_hangs_is_stopped(tmp_path, local):
    r = py(tmp_path, "import time; time.sleep(30)", timeout=1)
    assert r.timed_out and "1 seconds" in r.output


def test_local_serve_keeps_data_in_the_project(tmp_path, local):
    ws = project(tmp_path)
    handle = asyncio.run(sandbox.serve(str(ws), ""))
    try:
        url = f"http://127.0.0.1:{handle[1]}"
        assert httpx.post(f"{url}/notes", params={"text": "hi"}).status_code == 200
        assert httpx.get(f"{url}/notes").json() == ["hi"]
        assert (ws / "data" / "app.db").exists()
    finally:
        sandbox.stop(handle)


def test_an_api_that_crashes_on_start_is_reported(tmp_path, local):
    ws = project(tmp_path)
    (ws / "app" / "main.py").write_text("raise SystemExit('boom')\n")
    with pytest.raises(RuntimeError, match="didn't start"):
        asyncio.run(sandbox.serve(str(ws), ""))


# ---------- docker mode (only where Docker and the image exist) ----------

def docker_ready() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "image", "inspect", sandbox.IMAGE], capture_output=True).returncode == 0


needs_docker = pytest.mark.skipif(not docker_ready(), reason="needs Docker and the prosit-sandbox image")


@pytest.fixture
def docker(monkeypatch):
    monkeypatch.setenv("SANDBOX", "docker")


@needs_docker
def test_docker_check_has_no_network(tmp_path, docker):
    r = py(tmp_path, "import socket; socket.create_connection(('1.1.1.1', 53), timeout=3)")
    assert r.code != 0 and ("Network is unreachable" in r.output or "OSError" in r.output)


@needs_docker
def test_docker_check_cannot_change_the_code(tmp_path, docker):
    project(tmp_path)
    r = py(tmp_path, "open('app/main.py', 'a').write('# changed')")
    assert r.code != 0 and "Read-only file system" in r.output
    assert "# changed" not in (tmp_path / "app" / "main.py").read_text()


@needs_docker
def test_docker_check_runs_python_as_non_root(tmp_path, docker):
    r = py(tmp_path, "import os; print(os.getuid())")
    assert r.code == 0 and r.output.strip() != "0"


@needs_docker
def test_docker_serve_keeps_data_and_stops(tmp_path, docker):
    ws = project(tmp_path)
    handle = asyncio.run(sandbox.serve(str(ws), ""))
    try:
        url = f"http://127.0.0.1:{handle[1]}"
        assert httpx.post(f"{url}/notes", params={"text": "hi"}).status_code == 200
        assert httpx.get(f"{url}/notes").json() == ["hi"]
        assert (ws / "data" / "app.db").exists()                      # data lands in the project's data/
    finally:
        sandbox.stop(handle)
    out = subprocess.run(["docker", "ps", "-a", "-q", "--filter", f"name={handle[0].name}"],
                         capture_output=True, text=True).stdout
    assert out.strip() == ""                                          # the container is gone
