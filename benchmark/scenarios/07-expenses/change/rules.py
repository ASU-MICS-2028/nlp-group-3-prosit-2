"""Hidden tests for this scenario's change request. No agent ever sees this file."""
USER = {"X-Role": "user", "X-User-Id": "1"}
ADMIN = {"X-Role": "admin", "X-User-Id": "9"}


def ok(r, code=201):
    assert r.status_code == code, f"{r.status_code} {r.text[:200]}"
    return r.json()


def category(client, name, **extra):
    return ok(client.post("/categories", json={"name": name, **extra}, headers=USER))


def expense(client, category_id, amount):
    return ok(client.post("/expenses", json={"category_id": category_id, "amount": amount, "spent_on": "2026-03-02"}, headers=USER))


def test_budget_is_optional_and_kept(client):
    assert category(client, "Food", monthly_budget=500.0)["monthly_budget"] == 500.0
    category(client, "Transport")


def test_budget_must_be_more_than_zero(client):
    for bad in (0, -10):
        assert client.post("/categories", json={"name": f"Bad {bad}", "monthly_budget": bad}, headers=USER).status_code == 422


def test_summary_shows_spending_per_category(client):
    food, transport, _ = category(client, "Food"), category(client, "Transport"), category(client, "Unused")
    expense(client, food["id"], 40.0); expense(client, food["id"], 10.5); expense(client, transport["id"], 20.0)
    s = client.get("/summary", headers=USER).json()
    assert abs(s["total"] - 70.5) < 1e-6 and s["count"] == 3
    by = {row["category_id"]: row for row in s["by_category"]}
    assert set(by) == {food["id"], transport["id"]}
    assert abs(by[food["id"]]["total"] - 50.5) < 1e-6 and by[food["id"]]["name"] == "Food"
    assert abs(by[transport["id"]]["total"] - 20.0) < 1e-6


def test_empty_summary_has_an_empty_list(client):
    assert client.get("/summary", headers=USER).json()["by_category"] == []
