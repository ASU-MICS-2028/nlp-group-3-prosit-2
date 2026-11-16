"""Hidden tests for this scenario's business rules."""
USER = {"X-Role": "user", "X-User-Id": "1"}
OTHER = {"X-Role": "user", "X-User-Id": "2"}
ADMIN = {"X-Role": "admin", "X-User-Id": "9"}


def ok(r, code=201):
    assert r.status_code == code, f"{r.status_code} {r.text[:200]}"
    return r.json()


def task(client, headers=USER, title="Pay rent"):
    return ok(client.post("/tasks", json={"title": title}, headers=headers))


def test_owner_comes_from_the_header(client):
    assert task(client, USER)["user_id"] == 1 and task(client, OTHER)["user_id"] == 2


def test_owner_cannot_be_set_in_the_body(client):
    r = client.post("/tasks", json={"title": "Sneaky", "user_id": 2}, headers=USER)
    assert r.status_code in (201, 422)
    if r.status_code == 201:
        assert r.json()["user_id"] == 1


def test_a_new_task_is_not_done(client):
    assert task(client)["done"] is False


def test_a_user_lists_only_their_own_tasks(client):
    task(client, USER, "Mine"), task(client, OTHER, "Theirs")
    assert [t["title"] for t in client.get("/tasks", headers=USER).json()] == ["Mine"]
    assert [t["title"] for t in client.get("/tasks", headers=OTHER).json()] == ["Theirs"]


def test_an_admin_lists_every_task(client):
    task(client, USER), task(client, OTHER)
    assert len(client.get("/tasks", headers=ADMIN).json()) == 2


def test_another_users_task_is_403(client):
    t = task(client, USER)
    assert client.get(f"/tasks/{t['id']}", headers=OTHER).status_code == 403
    assert client.patch(f"/tasks/{t['id']}", json={"title": "Hacked"}, headers=OTHER).status_code == 403
    assert client.post(f"/tasks/{t['id']}/complete", headers=OTHER).status_code == 403
    assert client.delete(f"/tasks/{t['id']}", headers=OTHER).status_code == 403
    assert client.get(f"/tasks/{t['id']}", headers=USER).json()["title"] == "Pay rent"   # untouched


def test_an_admin_can_access_any_task(client):
    t = task(client, USER)
    assert client.get(f"/tasks/{t['id']}", headers=ADMIN).status_code == 200
    assert client.delete(f"/tasks/{t['id']}", headers=ADMIN).status_code == 204


def test_complete_sets_done(client):
    t = task(client)
    assert ok(client.post(f"/tasks/{t['id']}/complete", headers=USER), 200)["done"] is True
    assert client.get(f"/tasks/{t['id']}", headers=USER).json()["done"] is True


def test_completing_twice_is_409(client):
    t = task(client)
    client.post(f"/tasks/{t['id']}/complete", headers=USER)
    assert client.post(f"/tasks/{t['id']}/complete", headers=USER).status_code == 409


def test_complete_unknown_task_is_404(client):
    assert client.post("/tasks/987654/complete", headers=USER).status_code == 404


def test_empty_title_is_422(client):
    assert client.post("/tasks", json={"title": ""}, headers=USER).status_code == 422
