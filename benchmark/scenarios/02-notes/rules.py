"""Hidden tests for this scenario's business rules."""
USER = {"X-Role": "user", "X-User-Id": "1"}
OTHER = {"X-Role": "user", "X-User-Id": "2"}
ADMIN = {"X-Role": "admin", "X-User-Id": "9"}


def ok(r, code=201):
    assert r.status_code == code, f"{r.status_code} {r.text[:200]}"
    return r.json()


def test_empty_title_is_422(client):
    assert client.post("/notes", json={"title": ""}, headers=USER).status_code == 422


def test_empty_title_on_update_is_422(client):
    note = ok(client.post("/notes", json={"title": "Ideas"}, headers=USER))
    assert client.put(f"/notes/{note['id']}", json={"title": ""}, headers=USER).status_code == 422


def test_pinned_is_false_when_not_sent(client):
    note = ok(client.post("/notes", json={"title": "Ideas"}, headers=USER))
    assert note["pinned"] is False and note["body"] is None


def test_pinned_true_is_kept(client):
    note = ok(client.post("/notes", json={"title": "Ideas", "pinned": True}, headers=USER))
    assert client.get(f"/notes/{note['id']}", headers=USER).json()["pinned"] is True


def test_list_has_every_note(client):
    for title in ("One", "Two", "Three"):
        ok(client.post("/notes", json={"title": title}, headers=USER))
    assert sorted(n["title"] for n in client.get("/notes", headers=USER).json()) == ["One", "Three", "Two"]
