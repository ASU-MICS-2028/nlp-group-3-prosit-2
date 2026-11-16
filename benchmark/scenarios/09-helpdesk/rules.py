"""Hidden tests for this scenario's business rules."""
USER = {"X-Role": "user", "X-User-Id": "1"}
OTHER = {"X-Role": "user", "X-User-Id": "2"}
ADMIN = {"X-Role": "admin", "X-User-Id": "9"}


def ok(r, code=201):
    assert r.status_code == code, f"{r.status_code} {r.text[:200]}"
    return r.json()


def issue(client, priority="medium"):
    return client.post("/issues", json={"title": "Printer jam", "description": "Stuck again.", "priority": priority}, headers=USER)


def move(client, id, action, headers=ADMIN):
    return client.post(f"/issues/{id}/{action}", headers=headers)


def test_a_new_issue_is_open(client):
    assert ok(issue(client))["status"] == "open"


def test_priority_must_be_one_of_three(client):
    for good in ("low", "medium", "high"):
        ok(issue(client, good))
    for bad in ("urgent", "", "HIGH "):
        assert issue(client, bad).status_code == 422


def test_priority_rule_also_applies_to_edits(client):
    i = ok(issue(client))
    assert client.patch(f"/issues/{i['id']}", json={"priority": "urgent"}, headers=USER).status_code == 422
    assert client.get(f"/issues/{i['id']}", headers=USER).json()["priority"] == "medium"


def test_the_whole_path_open_to_resolved_and_back(client):
    i = ok(issue(client))["id"]
    assert ok(move(client, i, "start"), 200)["status"] == "in_progress"
    assert ok(move(client, i, "resolve"), 200)["status"] == "resolved"
    assert ok(move(client, i, "reopen", USER), 200)["status"] == "open"
    assert client.get(f"/issues/{i}", headers=USER).json()["status"] == "open"


def test_an_open_issue_cannot_be_resolved_or_reopened(client):
    i = ok(issue(client))["id"]
    assert move(client, i, "resolve").status_code == 409
    assert move(client, i, "reopen", USER).status_code == 409
    assert client.get(f"/issues/{i}", headers=USER).json()["status"] == "open"


def test_an_issue_in_progress_cannot_be_started_or_reopened(client):
    i = ok(issue(client))["id"]
    move(client, i, "start")
    assert move(client, i, "start").status_code == 409
    assert move(client, i, "reopen", USER).status_code == 409


def test_a_resolved_issue_cannot_be_started_or_resolved(client):
    i = ok(issue(client))["id"]
    move(client, i, "start"), move(client, i, "resolve")
    assert move(client, i, "start").status_code == 409
    assert move(client, i, "resolve").status_code == 409


def test_status_cannot_be_edited_directly(client):
    i = ok(issue(client))["id"]
    r = client.patch(f"/issues/{i}", json={"status": "resolved"}, headers=USER)
    assert r.status_code in (200, 422)
    assert client.get(f"/issues/{i}", headers=USER).json()["status"] == "open"


def test_actions_on_an_unknown_issue_are_404(client):
    assert move(client, 987654, "start").status_code == 404
    assert move(client, 987654, "resolve").status_code == 404
    assert move(client, 987654, "reopen", USER).status_code == 404
