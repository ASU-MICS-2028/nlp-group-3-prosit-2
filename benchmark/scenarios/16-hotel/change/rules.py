"""Hidden tests for this scenario's change request. No agent ever sees this file."""
USER = {"X-Role": "user", "X-User-Id": "1"}
ADMIN = {"X-Role": "admin", "X-User-Id": "9"}


def ok(r, code=201):
    assert r.status_code == code, f"{r.status_code} {r.text[:200]}"
    return r.json()


def room(client, number="101"):
    return ok(client.post("/rooms", json={"number": number, "nightly_rate": 400.0, "max_guests": 2}, headers=ADMIN))


def book(client, room_id, check_in="2031-08-10", check_out="2031-08-13"):
    return client.post("/bookings", json={"room_id": room_id, "guest_name": "Ama Serwaa", "guests": 1,
                                         "check_in": check_in, "check_out": check_out}, headers=USER)


def service(client, room_id, value):
    return client.patch(f"/rooms/{room_id}", json={"out_of_service": value}, headers=ADMIN)


def test_a_new_room_is_in_service(client):
    assert room(client)["out_of_service"] is False


def test_an_out_of_service_room_cannot_be_booked(client):
    r = room(client)
    assert ok(service(client, r["id"], True), 200)["out_of_service"] is True
    assert book(client, r["id"]).status_code == 409


def test_back_in_service_can_be_booked_again(client):
    r = room(client)
    ok(service(client, r["id"], True), 200)
    ok(service(client, r["id"], False), 200)
    ok(book(client, r["id"]))


def test_existing_bookings_are_kept(client):
    r = room(client)
    b = ok(book(client, r["id"]))
    ok(service(client, r["id"], True), 200)
    assert client.get(f"/bookings/{b['id']}", headers=USER).json()["status"] == "booked"


def test_other_rooms_are_not_affected(client):
    r, other = room(client), room(client, "102")
    ok(service(client, r["id"], True), 200)
    ok(book(client, other["id"]))
