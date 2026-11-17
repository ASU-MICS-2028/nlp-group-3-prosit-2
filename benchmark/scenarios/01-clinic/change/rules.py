"""Hidden tests for this scenario's change request. No agent ever sees this file."""
USER = {"X-Role": "user", "X-User-Id": "1"}
ADMIN = {"X-Role": "admin", "X-User-Id": "9"}


def ok(r, code=201):
    assert r.status_code == code, f"{r.status_code} {r.text[:200]}"
    return r.json()


def setup(client):
    p = ok(client.post("/patients", json={"full_name": "Ama Mensah", "phone": "0244000001"}))
    d = ok(client.post("/doctors", json={"full_name": "Dr Kofi Boateng", "specialty": "general practice"}, headers=ADMIN))
    return p["id"], d["id"]


def book(client, p, d, start):
    return client.post("/appointments", json={"patient_id": p, "doctor_id": d, "start_time": start}, headers=USER)


def move(client, a, start):
    return client.post(f"/appointments/{a}/reschedule", json={"start_time": start}, headers=USER)


def test_reschedule_moves_the_appointment(client):
    p, d = setup(client)
    a = ok(book(client, p, d, "2031-03-10T09:00:00"))
    moved = ok(move(client, a["id"], "2031-03-11T10:00:00"), 200)
    assert moved["start_time"].startswith("2031-03-11T10:00")
    assert client.get(f"/appointments/{a['id']}", headers=USER).json()["start_time"].startswith("2031-03-11T10:00")


def test_reschedule_into_the_past_is_422(client):
    p, d = setup(client)
    a = ok(book(client, p, d, "2031-03-10T09:00:00"))
    assert move(client, a["id"], "2020-01-01T09:00:00").status_code == 422


def test_reschedule_onto_another_booking_is_409(client):
    p, d = setup(client)
    ok(book(client, p, d, "2031-03-10T09:00:00"))
    b = ok(book(client, p, d, "2031-03-10T11:00:00"))
    assert move(client, b["id"], "2031-03-10T09:15:00").status_code == 409


def test_reschedule_never_clashes_with_itself(client):
    p, d = setup(client)
    a = ok(book(client, p, d, "2031-03-10T09:00:00"))
    ok(move(client, a["id"], "2031-03-10T09:15:00"), 200)


def test_frees_the_old_slot(client):
    p, d = setup(client)
    a = ok(book(client, p, d, "2031-03-10T09:00:00"))
    ok(move(client, a["id"], "2031-03-12T09:00:00"), 200)
    ok(book(client, p, d, "2031-03-10T09:00:00"))


def test_cancelled_appointment_cannot_be_rescheduled(client):
    p, d = setup(client)
    a = ok(book(client, p, d, "2031-03-10T09:00:00"))
    ok(client.post(f"/appointments/{a['id']}/cancel", headers=USER), 200)
    assert move(client, a["id"], "2031-03-12T09:00:00").status_code == 409
