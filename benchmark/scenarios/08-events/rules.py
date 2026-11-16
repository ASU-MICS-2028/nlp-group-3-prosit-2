"""Hidden tests for this scenario's business rules."""
USER = {"X-Role": "user", "X-User-Id": "1"}
OTHER = {"X-Role": "user", "X-User-Id": "2"}
ADMIN = {"X-Role": "admin", "X-User-Id": "9"}


def ok(r, code=201):
    assert r.status_code == code, f"{r.status_code} {r.text[:200]}"
    return r.json()


def event(client, capacity=2, starts_at="2031-06-20T19:00:00"):
    return client.post("/events", json={"name": "Highlife Night", "starts_at": starts_at, "capacity": capacity}, headers=ADMIN)


def ticket(client, event_id, holder="Abena Osei"):
    return client.post("/tickets", json={"event_id": event_id, "holder_name": holder}, headers=USER)


def test_an_event_in_the_past_is_422(client):
    assert event(client, starts_at="2020-01-01T19:00:00").status_code == 422


def test_capacity_must_be_at_least_one(client):
    assert event(client, capacity=0).status_code == 422


def test_a_new_ticket_is_valid(client):
    assert ok(ticket(client, ok(event(client))["id"]))["status"] == "valid"


def test_a_full_event_is_409(client):
    e = ok(event(client, capacity=2))["id"]
    ok(ticket(client, e, "One")), ok(ticket(client, e, "Two"))
    assert ticket(client, e, "Three").status_code == 409
    assert len(client.get("/tickets", headers=ADMIN).json()) == 2


def test_a_full_event_does_not_block_another_event(client):
    full, other = ok(event(client, capacity=1))["id"], ok(event(client, capacity=1))["id"]
    ok(ticket(client, full))
    ok(ticket(client, other))


def test_cancel_keeps_the_ticket_and_frees_the_place(client):
    e = ok(event(client, capacity=1))["id"]
    t = ok(ticket(client, e))
    assert ticket(client, e, "Late").status_code == 409
    assert ok(client.post(f"/tickets/{t['id']}/cancel", headers=USER), 200)["status"] == "cancelled"
    assert client.get(f"/tickets/{t['id']}", headers=USER).json()["status"] == "cancelled"
    ok(ticket(client, e, "Late"))
    assert len(client.get("/tickets", headers=ADMIN).json()) == 2


def test_cancelling_twice_is_409(client):
    t = ok(ticket(client, ok(event(client))["id"]))
    client.post(f"/tickets/{t['id']}/cancel", headers=USER)
    assert client.post(f"/tickets/{t['id']}/cancel", headers=USER).status_code == 409


def test_cancel_unknown_ticket_is_404(client):
    assert client.post("/tickets/987654/cancel", headers=USER).status_code == 404
