"""Hidden tests for this scenario's business rules."""
USER = {"X-Role": "user", "X-User-Id": "1"}
OTHER = {"X-Role": "user", "X-User-Id": "2"}
ADMIN = {"X-Role": "admin", "X-User-Id": "9"}


def ok(r, code=201):
    assert r.status_code == code, f"{r.status_code} {r.text[:200]}"
    return r.json()


def category(client, name="Food"):
    return ok(client.post("/categories", json={"name": name}, headers=USER))["id"]


def expense(client, category_id, amount, spent_on="2026-03-02"):
    return client.post("/expenses", json={"category_id": category_id, "amount": amount, "spent_on": spent_on}, headers=USER)


def test_amount_must_be_more_than_zero(client):
    c = category(client)
    assert expense(client, c, 0).status_code == 422
    assert expense(client, c, -10).status_code == 422


def test_amount_rule_also_applies_to_updates(client):
    c = category(client)
    e = ok(expense(client, c, 20))
    r = client.put(f"/expenses/{e['id']}", json={"category_id": c, "amount": 0, "spent_on": "2026-03-02"}, headers=USER)
    assert r.status_code == 422


def test_note_is_optional(client):
    assert ok(expense(client, category(client), 20))["note"] is None


def test_summary_of_nothing(client):
    r = client.get("/summary", headers=USER)
    assert r.status_code == 200 and r.json()["count"] == 0 and r.json()["total"] == 0


def test_summary_adds_up_every_expense(client):
    food, transport = category(client), category(client, "Transport")
    ok(expense(client, food, 45.5)), ok(expense(client, food, 4.5)), ok(expense(client, transport, 10))
    s = client.get("/summary", headers=USER).json()
    assert s["count"] == 3 and abs(s["total"] - 60.0) < 1e-6


def test_summary_follows_updates_and_deletes(client):
    c = category(client)
    a, b = ok(expense(client, c, 30)), ok(expense(client, c, 20))
    ok(client.put(f"/expenses/{a['id']}", json={"category_id": c, "amount": 35, "spent_on": "2026-03-02"}, headers=USER), 200)
    assert client.delete(f"/expenses/{b['id']}", headers=USER).status_code == 204
    s = client.get("/summary", headers=USER).json()
    assert s["count"] == 1 and abs(s["total"] - 35.0) < 1e-6


def test_summary_needs_sign_in(client):
    assert client.get("/summary").status_code == 401


def test_a_category_with_expenses_cannot_be_deleted(client):
    c = category(client)
    e = ok(expense(client, c, 20))
    assert client.delete(f"/categories/{c}", headers=ADMIN).status_code == 409
    client.delete(f"/expenses/{e['id']}", headers=USER)
    assert client.delete(f"/categories/{c}", headers=ADMIN).status_code == 204


def test_moving_an_expense_to_an_unknown_category_is_404(client):
    c = category(client)
    e = ok(expense(client, c, 20))
    r = client.put(f"/expenses/{e['id']}", json={"category_id": 987654, "amount": 20, "spent_on": "2026-03-02"}, headers=USER)
    assert r.status_code == 404
