"""Hidden tests for this scenario's business rules."""
USER = {"X-Role": "user", "X-User-Id": "1"}
OTHER = {"X-Role": "user", "X-User-Id": "2"}
ADMIN = {"X-Role": "admin", "X-User-Id": "9"}


def ok(r, code=201):
    assert r.status_code == code, f"{r.status_code} {r.text[:200]}"
    return r.json()


def vehicle(client, plate="GR-1234-24", rate=300.0):
    return ok(client.post("/vehicles", json={"plate": plate, "model": "Toyota Corolla", "daily_rate": rate}, headers=ADMIN))["id"]


def rent(client, vehicle_id, start="2031-07-01", end="2031-07-04"):
    return client.post("/rentals", headers=USER, json={
        "vehicle_id": vehicle_id, "customer_name": "Nana Agyeman", "start_date": start, "end_date": end})


def test_total_is_rate_times_days(client):
    r = ok(rent(client, vehicle(client, rate=300.0), "2031-07-01", "2031-07-04"))
    assert abs(r["total"] - 900.0) < 1e-6 and r["returned"] is False


def test_one_day_rental(client):
    assert abs(ok(rent(client, vehicle(client, rate=120.5), "2031-07-01", "2031-07-02"))["total"] - 120.5) < 1e-6


def test_end_must_be_after_start(client):
    v = vehicle(client)
    assert rent(client, v, "2031-07-04", "2031-07-01").status_code == 422
    assert rent(client, v, "2031-07-01", "2031-07-01").status_code == 422


def test_a_rental_in_the_past_is_422(client):
    assert rent(client, vehicle(client), "2020-07-01", "2020-07-04").status_code == 422


def test_overlapping_dates_are_409(client):
    v = vehicle(client)
    ok(rent(client, v, "2031-07-05", "2031-07-10"))
    for start, end in (("2031-07-05", "2031-07-10"), ("2031-07-08", "2031-07-12"), ("2031-07-01", "2031-07-06"),
                       ("2031-07-06", "2031-07-07"), ("2031-07-01", "2031-07-20")):
        assert rent(client, v, start, end).status_code == 409, (start, end)


def test_back_to_back_rentals_are_allowed(client):
    v = vehicle(client)
    ok(rent(client, v, "2031-07-05", "2031-07-10"))
    ok(rent(client, v, "2031-07-10", "2031-07-12"))
    ok(rent(client, v, "2031-07-01", "2031-07-05"))


def test_another_vehicle_is_free_for_the_same_dates(client):
    ok(rent(client, vehicle(client)))
    ok(rent(client, vehicle(client, "GR-9999-24")))


def test_return(client):
    r = ok(rent(client, vehicle(client)))
    assert ok(client.post(f"/rentals/{r['id']}/return", headers=USER), 200)["returned"] is True
    assert client.post(f"/rentals/{r['id']}/return", headers=USER).status_code == 409
    assert client.post("/rentals/987654/return", headers=USER).status_code == 404


def test_a_returned_rental_no_longer_blocks_the_dates(client):
    v = vehicle(client)
    r = ok(rent(client, v))
    client.post(f"/rentals/{r['id']}/return", headers=USER)
    ok(rent(client, v))
