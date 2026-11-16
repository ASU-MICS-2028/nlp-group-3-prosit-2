"""Hidden tests for the clinic's business rules."""
USER = {"X-Role": "user", "X-User-Id": "1"}
ADMIN = {"X-Role": "admin", "X-User-Id": "1"}


def patient(client, phone="0244000001"):
    r = client.post("/patients", json={"full_name": "Ama Mensah", "phone": phone})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def doctor(client, name="Dr Kofi Boateng"):
    r = client.post("/doctors", json={"full_name": name, "specialty": "general practice"}, headers=ADMIN)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def book(client, patient_id, doctor_id, start="2031-03-10T09:00:00"):
    return client.post("/appointments", json={"patient_id": patient_id, "doctor_id": doctor_id, "start_time": start},
                       headers=USER)


def test_a_new_appointment_is_booked(client):
    r = book(client, patient(client), doctor(client))
    assert r.status_code == 201 and r.json()["status"] == "booked"


def test_same_doctor_same_time_is_409(client):
    d = doctor(client)
    assert book(client, patient(client), d).status_code == 201
    assert book(client, patient(client, "0244000002"), d).status_code == 409


def test_overlap_within_30_minutes_is_409(client):
    d, p = doctor(client), patient(client)
    assert book(client, p, d, "2031-03-10T09:00:00").status_code == 201
    assert book(client, p, d, "2031-03-10T09:20:00").status_code == 409
    assert book(client, p, d, "2031-03-10T08:45:00").status_code == 409


def test_next_slot_is_free(client):
    d, p = doctor(client), patient(client)
    assert book(client, p, d, "2031-03-10T09:00:00").status_code == 201
    assert book(client, p, d, "2031-03-10T09:30:00").status_code == 201
    assert book(client, p, d, "2031-03-10T08:30:00").status_code == 201


def test_another_doctor_is_free_at_the_same_time(client):
    p = patient(client)
    assert book(client, p, doctor(client)).status_code == 201
    assert book(client, p, doctor(client, "Dr Esi Owusu")).status_code == 201


def test_past_appointment_is_422(client):
    assert book(client, patient(client), doctor(client), "2020-01-01T09:00:00").status_code == 422


def test_cancel_sets_status_and_keeps_the_appointment(client):
    booked = book(client, patient(client), doctor(client)).json()
    r = client.post(f"/appointments/{booked['id']}/cancel", headers=USER)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert client.get(f"/appointments/{booked['id']}", headers=USER).json()["status"] == "cancelled"
    assert len(client.get("/appointments", headers=ADMIN).json()) == 1


def test_a_cancelled_slot_can_be_booked_again(client):
    d, p = doctor(client), patient(client)
    booked = book(client, p, d).json()
    client.post(f"/appointments/{booked['id']}/cancel", headers=USER)
    assert book(client, p, d).status_code == 201


def test_cancel_unknown_appointment_is_404(client):
    assert client.post("/appointments/987654/cancel", headers=USER).status_code == 404


def test_status_cannot_be_set_by_the_client(client):
    r = client.post("/appointments", headers=USER, json={
        "patient_id": patient(client), "doctor_id": doctor(client), "start_time": "2031-03-10T09:00:00", "status": "cancelled"})
    assert r.status_code in (201, 422)          # ignored or refused, but never accepted
    if r.status_code == 201:
        assert r.json()["status"] == "booked"
