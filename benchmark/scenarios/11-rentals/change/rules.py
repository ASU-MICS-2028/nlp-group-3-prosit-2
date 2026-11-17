"""Hidden tests for this scenario's change request. No agent ever sees this file."""
USER = {"X-Role": "user", "X-User-Id": "1"}
ADMIN = {"X-Role": "admin", "X-User-Id": "9"}


def ok(r, code=201):
    assert r.status_code == code, f"{r.status_code} {r.text[:200]}"
    return r.json()


def vehicle(client, rate=300.0, plate="GR-1234-24"):
    return ok(client.post("/vehicles", json={"plate": plate, "model": "Toyota Corolla", "daily_rate": rate}, headers=ADMIN))


def rent(client, vehicle_id, start, end):
    return client.post("/rentals", json={"vehicle_id": vehicle_id, "customer_name": "Nana Agyeman", "start_date": start, "end_date": end}, headers=USER)


def extend(client, rental_id, end):
    return client.post(f"/rentals/{rental_id}/extend", json={"end_date": end}, headers=USER)


def test_extending_moves_the_end_and_the_total(client):
    v = vehicle(client, rate=300.0)
    r = ok(rent(client, v["id"], "2031-07-01", "2031-07-04"))
    e = ok(extend(client, r["id"], "2031-07-06"), 200)
    assert e["end_date"] == "2031-07-06" and abs(e["total"] - 1500.0) < 1e-6


def test_new_end_must_be_later(client):
    v = vehicle(client)
    r = ok(rent(client, v["id"], "2031-07-01", "2031-07-04"))
    assert extend(client, r["id"], "2031-07-04").status_code == 422
    assert extend(client, r["id"], "2031-07-03").status_code == 422


def test_cannot_extend_into_another_rental(client):
    v = vehicle(client)
    r = ok(rent(client, v["id"], "2031-07-01", "2031-07-04"))
    ok(rent(client, v["id"], "2031-07-06", "2031-07-08"))
    assert extend(client, r["id"], "2031-07-07").status_code == 409
    ok(extend(client, r["id"], "2031-07-06"), 200)   # ending on the day the next starts is fine


def test_other_vehicles_do_not_block(client):
    v, w = vehicle(client), vehicle(client, plate="GR-9999-24")
    r = ok(rent(client, v["id"], "2031-07-01", "2031-07-04"))
    ok(rent(client, w["id"], "2031-07-05", "2031-07-09"))
    ok(extend(client, r["id"], "2031-07-08"), 200)


def test_a_returned_rental_cannot_be_extended(client):
    v = vehicle(client)
    r = ok(rent(client, v["id"], "2031-07-01", "2031-07-04"))
    ok(client.post(f"/rentals/{r['id']}/return", headers=USER), 200)
    assert extend(client, r["id"], "2031-07-08").status_code == 409
