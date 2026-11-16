"""Hidden tests for this scenario's business rules."""
USER = {"X-Role": "user", "X-User-Id": "1"}
OTHER = {"X-Role": "user", "X-User-Id": "2"}
ADMIN = {"X-Role": "admin", "X-User-Id": "9"}


def ok(r, code=201):
    assert r.status_code == code, f"{r.status_code} {r.text[:200]}"
    return r.json()


def table(client, label="T1", seats=4):
    return ok(client.post("/tables", json={"label": label, "seats": seats}, headers=ADMIN))["id"]


def reserve(client, table_id, starts_at="2031-05-05T18:00:00", party_size=2):
    return client.post("/reservations", headers=USER, json={
        "table_id": table_id, "guest_name": "Kwame Addo", "party_size": party_size, "starts_at": starts_at})


def test_a_new_reservation_is_booked(client):
    assert ok(reserve(client, table(client)))["status"] == "booked"


def test_the_group_must_fit_at_the_table(client):
    t = table(client, seats=4)
    assert reserve(client, t, party_size=5).status_code == 422
    assert reserve(client, t, party_size=0).status_code == 422
    ok(reserve(client, t, party_size=4))


def test_a_reservation_in_the_past_is_422(client):
    assert reserve(client, table(client), "2020-05-05T18:00:00").status_code == 422


def test_overlapping_reservations_are_409(client):
    t = table(client)
    ok(reserve(client, t, "2031-05-05T18:00:00"))
    for clash in ("2031-05-05T18:00:00", "2031-05-05T19:30:00", "2031-05-05T16:30:00"):
        assert reserve(client, t, clash).status_code == 409


def test_two_hours_later_or_earlier_is_free(client):
    t = table(client)
    ok(reserve(client, t, "2031-05-05T18:00:00"))
    ok(reserve(client, t, "2031-05-05T20:00:00"))
    ok(reserve(client, t, "2031-05-05T16:00:00"))


def test_another_table_is_free_at_the_same_time(client):
    ok(reserve(client, table(client)))
    ok(reserve(client, table(client, "T2")))


def test_cancel_keeps_the_reservation_and_frees_the_table(client):
    t = table(client)
    r = ok(reserve(client, t))
    assert ok(client.post(f"/reservations/{r['id']}/cancel", headers=USER), 200)["status"] == "cancelled"
    assert client.get(f"/reservations/{r['id']}", headers=USER).json()["status"] == "cancelled"
    ok(reserve(client, t))
    assert len(client.get("/reservations", headers=ADMIN).json()) == 2


def test_cancel_unknown_reservation_is_404(client):
    assert client.post("/reservations/987654/cancel", headers=USER).status_code == 404
