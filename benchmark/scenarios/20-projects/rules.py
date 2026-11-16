"""Hidden tests for this scenario's business rules."""
USER = {"X-Role": "user", "X-User-Id": "1"}
OTHER = {"X-Role": "user", "X-User-Id": "2"}
ADMIN = {"X-Role": "admin", "X-User-Id": "9"}


def ok(r, code=201):
    assert r.status_code == code, f"{r.status_code} {r.text[:200]}"
    return r.json()


def project(client, name="Website"):
    return ok(client.post("/projects", json={"name": name}, headers=USER))["id"]


def task(client, project_id, title="Write the home page", **extra):
    return client.post("/tasks", json={"project_id": project_id, "title": title, **extra}, headers=USER)


def act(client, task_id, action):
    return client.post(f"/tasks/{task_id}/{action}", headers=USER)


def finish(client, task_id):
    ok(act(client, task_id, "start"), 200)
    return ok(act(client, task_id, "finish"), 200)


def archive(client, project_id):
    return client.post(f"/projects/{project_id}/archive", headers=ADMIN)


def progress(client, project_id):
    r = client.get(f"/projects/{project_id}/progress", headers=USER)
    assert r.status_code == 200, r.text
    return {k: r.json()[k] for k in ("project_id", "total", "done", "percent")}   # extra keys are allowed


def test_new_records(client):
    p = project(client)
    assert client.get(f"/projects/{p}", headers=USER).json()["archived"] is False
    t = ok(task(client, p))
    assert t["status"] == "todo" and t["blocked_by_id"] is None


def test_a_task_goes_from_todo_to_doing_to_done(client):
    t = ok(task(client, project(client)))["id"]
    assert ok(act(client, t, "start"), 200)["status"] == "doing"
    assert ok(act(client, t, "finish"), 200)["status"] == "done"
    assert client.get(f"/tasks/{t}", headers=USER).json()["status"] == "done"


def test_steps_cannot_be_skipped_or_repeated(client):
    t = ok(task(client, project(client)))["id"]
    assert act(client, t, "finish").status_code == 409    # not started
    act(client, t, "start")
    assert act(client, t, "start").status_code == 409     # already started
    act(client, t, "finish")
    assert act(client, t, "start").status_code == 409
    assert act(client, t, "finish").status_code == 409


def test_a_blocked_task_waits_for_its_blocker(client):
    p = project(client)
    first = ok(task(client, p, "Design"))["id"]
    second = ok(task(client, p, "Build", blocked_by_id=first))
    assert second["blocked_by_id"] == first
    assert act(client, second["id"], "start").status_code == 409     # the blocker is still todo
    act(client, first, "start")
    assert act(client, second["id"], "start").status_code == 409     # doing is not done
    act(client, first, "finish")
    assert ok(act(client, second["id"], "start"), 200)["status"] == "doing"


def test_the_blocker_must_be_a_task_of_the_same_project(client):
    p, other = project(client), project(client, "App")
    elsewhere = ok(task(client, other))["id"]
    assert task(client, p, blocked_by_id=987654).status_code == 404
    assert task(client, p, blocked_by_id=elsewhere).status_code == 422
    assert client.get("/tasks", headers=USER).json()[0]["id"] == elsewhere and len(client.get("/tasks", headers=USER).json()) == 1


def test_a_task_that_blocks_another_cannot_be_deleted(client):
    p = project(client)
    first = ok(task(client, p, "Design"))["id"]
    second = ok(task(client, p, "Build", blocked_by_id=first))["id"]
    assert client.delete(f"/tasks/{first}", headers=USER).status_code == 409
    assert client.delete(f"/tasks/{second}", headers=USER).status_code == 204
    assert client.delete(f"/tasks/{first}", headers=USER).status_code == 204     # nothing waits for it any more


def test_progress(client):
    p = project(client)
    assert progress(client, p) == {"project_id": p, "total": 0, "done": 0, "percent": 0}
    a, b, c = (ok(task(client, p, title))["id"] for title in ("One", "Two", "Three"))
    finish(client, a)
    act(client, b, "start")
    assert progress(client, p) == {"project_id": p, "total": 3, "done": 1, "percent": 33}
    finish_b = ok(act(client, b, "finish"), 200)
    assert finish_b["status"] == "done" and progress(client, p)["percent"] == 67
    finish(client, c)
    assert progress(client, p) == {"project_id": p, "total": 3, "done": 3, "percent": 100}


def test_progress_counts_only_the_projects_own_tasks(client):
    p, other = project(client), project(client, "App")
    finish(client, ok(task(client, p))["id"])
    ok(task(client, other))
    assert progress(client, p)["percent"] == 100 and progress(client, other) == {"project_id": other, "total": 1, "done": 0, "percent": 0}


def test_archive_needs_every_task_done(client):
    p = project(client)
    assert archive(client, p).status_code == 409                 # no tasks at all
    a, b = ok(task(client, p, "One"))["id"], ok(task(client, p, "Two"))["id"]
    finish(client, a)
    assert archive(client, p).status_code == 409                 # one is still todo
    assert client.get(f"/projects/{p}", headers=USER).json()["archived"] is False
    finish(client, b)
    assert ok(archive(client, p), 200)["archived"] is True
    assert archive(client, p).status_code == 409                 # already archived


def test_no_tasks_can_be_added_to_an_archived_project(client):
    p = project(client)
    finish(client, ok(task(client, p))["id"])
    archive(client, p)
    assert task(client, p, "Late idea").status_code == 409
    ok(task(client, project(client, "App"), "Fine here"))


def test_unknown_ids_are_404(client):
    assert client.get("/projects/987654/progress", headers=USER).status_code == 404
    assert archive(client, 987654).status_code == 404
    assert act(client, 987654, "start").status_code == 404
    assert act(client, 987654, "finish").status_code == 404
