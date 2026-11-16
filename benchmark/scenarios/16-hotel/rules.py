"""Hidden tests for this scenario's business rules."""
USER = {"X-Role": "user", "X-User-Id": "1"}
OTHER = {"X-Role": "user", "X-User-Id": "2"}
ADMIN = {"X-Role": "admin", "X-User-Id": "9"}


def ok(r, code=201):
    assert r.status_code == code, f"{r.status_code} {r.text[:200]}"
    return r.json()


def room(client, number="101", rate=400.0, max_guests=2):
    return ok(client.post("/rooms", json={"number": number, "nightly_rate": rate, "max_guests": max_guests}, headers=ADMIN))["id"]


def book(client, room_id, check_in="2031-08-10", check_out="2031-08-13", guests=2):
    return client.post("/bookings", headers=USER, json={
        "room_id": room_id, "guest_name": "Ama Serwaa", "guests": guests, "check_in": check_in, "check_out": check_out})


def act(client, booking_id, action, headers=ADMIN):
    return client.post(f"/bookings/{booking_id}/{action}", headers=headers)


def change(client, booking_id, **fields):
    return client.patch(f"/bookings/{booking_id}", json=fields, headers=USER)


def test_room_values_must_make_sense(client):
    assert client.post("/rooms", json={"number": "1", "nightly_rate": 0, "max_guests": 2}, headers=ADMIN).status_code == 422
    assert client.post("/rooms", json={"number": "1", "nightly_rate": 100, "max_guests": 0}, headers=ADMIN).status_code == 422
    r = room(client)
    assert client.patch(f"/rooms/{r}", json={"nightly_rate": -1}, headers=ADMIN).status_code == 422


def test_a_new_booking_is_booked_and_priced_per_night(client):
    b = ok(book(client, room(client, rate=400.0), "2031-08-10", "2031-08-13"))
    assert b["status"] == "booked" and abs(b["total"] - 1200.0) < 1e-6


def test_the_group_must_fit(client):
    r = room(client, max_guests=2)
    assert book(client, r, guests=3).status_code == 422
    assert book(client, r, guests=0).status_code == 422


def test_dates_must_make_sense(client):
    r = room(client)
    assert book(client, r, "2031-08-13", "2031-08-10").status_code == 422
    assert book(client, r, "2031-08-10", "2031-08-10").status_code == 422
    assert book(client, r, "2020-08-10", "2020-08-13").status_code == 422


def test_overlapping_nights_are_409(client):
    r = room(client)
    ok(book(client, r, "2031-08-10", "2031-08-13"))
    for check_in, check_out in (("2031-08-10", "2031-08-13"), ("2031-08-12", "2031-08-15"), ("2031-08-08", "2031-08-11"),
                                ("2031-08-11", "2031-08-12"), ("2031-08-01", "2031-08-30")):
        assert book(client, r, check_in, check_out).status_code == 409, (check_in, check_out)


def test_back_to_back_and_other_rooms_are_free(client):
    r = room(client)
    ok(book(client, r, "2031-08-10", "2031-08-13"))
    ok(book(client, r, "2031-08-13", "2031-08-15"))
    ok(book(client, r, "2031-08-07", "2031-08-10"))
    ok(book(client, room(client, "102"), "2031-08-10", "2031-08-13"))


def test_the_whole_stay(client):
    b = ok(book(client, room(client)))["id"]
    assert ok(act(client, b, "checkin"), 200)["status"] == "checked_in"
    assert ok(act(client, b, "checkout"), 200)["status"] == "checked_out"
    assert client.get(f"/bookings/{b}", headers=USER).json()["status"] == "checked_out"


def test_steps_cannot_be_skipped_or_repeated(client):
    b = ok(book(client, room(client)))["id"]
    assert act(client, b, "checkout").status_code == 409          # not checked in yet
    act(client, b, "checkin")
    assert act(client, b, "checkin").status_code == 409           # already checked in
    assert act(client, b, "cancel", USER).status_code == 409      # too late to cancel
    act(client, b, "checkout")
    for action in ("checkin", "checkout"):
        assert act(client, b, action).status_code == 409
    assert act(client, b, "cancel", USER).status_code == 409


def test_cancel_keeps_the_booking_and_frees_the_room(client):
    r = room(client)
    b = ok(book(client, r))["id"]
    assert ok(act(client, b, "cancel", USER), 200)["status"] == "cancelled"
    assert act(client, b, "cancel", USER).status_code == 409
    assert act(client, b, "checkin").status_code == 409
    ok(book(client, r))
    assert len(client.get("/bookings", headers=ADMIN).json()) == 2


def test_a_checked_in_booking_still_blocks_and_a_checked_out_one_does_not(client):
    r = room(client)
    b = ok(book(client, r))["id"]
    act(client, b, "checkin")
    assert book(client, r).status_code == 409
    act(client, b, "checkout")
    ok(book(client, r))


def test_changing_dates_works_out_the_total_again(client):
    r = room(client, rate=400.0)
    b = ok(book(client, r, "2031-08-10", "2031-08-13"))["id"]
    changed = ok(change(client, b, check_in="2031-08-10", check_out="2031-08-15"), 200)
    assert changed["check_out"] == "2031-08-15" and abs(changed["total"] - 2000.0) < 1e-6


def test_a_change_uses_the_rooms_current_rate(client):
    r = room(client, rate=400.0)
    b = ok(book(client, r, "2031-08-10", "2031-08-13"))["id"]
    ok(client.patch(f"/rooms/{r}", json={"nightly_rate": 500.0}, headers=ADMIN), 200)
    assert abs(client.get(f"/bookings/{b}", headers=USER).json()["total"] - 1200.0) < 1e-6    # the old booking keeps its price
    assert abs(ok(change(client, b, check_out="2031-08-12"), 200)["total"] - 1000.0) < 1e-6   # 2 nights at the new rate


def test_a_booking_does_not_clash_with_itself(client):
    b = ok(book(client, room(client), "2031-08-10", "2031-08-13"))["id"]
    ok(change(client, b, check_in="2031-08-11", check_out="2031-08-14"), 200)


def test_a_change_must_follow_the_same_rules(client):
    r = room(client, max_guests=2)
    b = ok(book(client, r, "2031-08-10", "2031-08-13"))["id"]
    ok(book(client, r, "2031-08-20", "2031-08-25"))
    assert change(client, b, check_in="2031-08-19", check_out="2031-08-21").status_code == 409   # clashes with the other one
    assert change(client, b, guests=3).status_code == 422
    assert change(client, b, check_in="2031-08-13", check_out="2031-08-10").status_code == 422
    kept = client.get(f"/bookings/{b}", headers=USER).json()
    assert (kept["check_in"], kept["check_out"], kept["guests"]) == ("2031-08-10", "2031-08-13", 2)


def test_only_a_booked_booking_can_be_changed(client):
    r = room(client)
    cancelled, staying = ok(book(client, r))["id"], ok(book(client, r, "2031-09-01", "2031-09-03"))["id"]
    act(client, cancelled, "cancel", USER), act(client, staying, "checkin")
    assert change(client, cancelled, guests=1).status_code == 409
    assert change(client, staying, guests=1).status_code == 409


def test_actions_on_an_unknown_booking_are_404(client):
    for action, headers in (("checkin", ADMIN), ("checkout", ADMIN), ("cancel", USER)):
        assert act(client, 987654, action, headers).status_code == 404
