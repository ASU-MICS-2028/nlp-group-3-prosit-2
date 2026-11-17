"""Hidden tests for this scenario's change request. No agent ever sees this file."""
USER = {"X-Role": "user", "X-User-Id": "1"}
ADMIN = {"X-Role": "admin", "X-User-Id": "9"}


def ok(r, code=201):
    assert r.status_code == code, f"{r.status_code} {r.text[:200]}"
    return r.json()


def event(client, capacity=10):
    return ok(client.post("/events", json={"name": "Highlife Night", "starts_at": "2031-06-20T19:00:00", "capacity": capacity}, headers=ADMIN))


def ticket(client, event_id, name="Abena Osei"):
    return client.post("/tickets", json={"event_id": event_id, "holder_name": name}, headers=USER)


def cancel(client, event_id):
    return client.post(f"/events/{event_id}/cancel", headers=ADMIN)


def test_a_new_event_is_scheduled(client):
    assert event(client)["status"] == "scheduled"


def test_cancelling_an_event_cancels_its_valid_tickets(client):
    e, other = event(client), event(client)
    t1, t2 = ok(ticket(client, e["id"])), ok(ticket(client, e["id"], "Kwame"))
    ok(client.post(f"/tickets/{t2['id']}/cancel", headers=USER), 200)
    keep = ok(ticket(client, other["id"]))
    assert ok(cancel(client, e["id"]), 200)["status"] == "cancelled"
    assert client.get(f"/tickets/{t1['id']}", headers=USER).json()["status"] == "cancelled"
    assert client.get(f"/tickets/{keep['id']}", headers=USER).json()["status"] == "valid"   # other events untouched


def test_no_new_tickets_for_a_cancelled_event(client):
    e = event(client)
    ok(cancel(client, e["id"]), 200)
    assert ticket(client, e["id"]).status_code == 409


def test_cancelling_twice_is_409(client):
    e = event(client)
    ok(cancel(client, e["id"]), 200)
    assert cancel(client, e["id"]).status_code == 409


def test_only_an_admin_can_cancel_an_event(client):
    e = event(client)
    assert client.post(f"/events/{e['id']}/cancel", headers=USER).status_code == 403
