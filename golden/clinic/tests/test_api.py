import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from core.spec import Requirements, Spec
from core.state import Message

HERE = Path(__file__).parents[1]
USER, ADMIN = {"X-Role": "user"}, {"X-Role": "admin"}
client = TestClient(main.app)


@pytest.fixture(autouse=True)
def reset_db():
    for t in main.db.values():
        t.clear()


def future(hours=24):
    return (datetime.now() + timedelta(hours=hours)).replace(microsecond=0).isoformat()


def make_patient(phone="0244000001"):
    r = client.post("/patients", json={"full_name": "Ama Mensah", "phone": phone})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def make_doctor():
    r = client.post("/doctors", json={"full_name": "Dr Kofi Boateng", "specialty": "general practice"}, headers=ADMIN)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def book(pid, did, start, **kw):
    return client.post("/appointments", json={"patient_id": pid, "doctor_id": did, "start_time": start, **kw}, headers=USER)


# --- contracts ----------------------------------------------------------

def test_golden_files_match_contracts():
    for m in json.loads((HERE / "chat.json").read_text()):
        Message.model_validate(m)
    Requirements.model_validate_json((HERE / "requirements.json").read_text())
    Spec.model_validate_json((HERE / "spec.json").read_text())


def test_every_spec_endpoint_is_implemented():
    spec = Spec.model_validate_json((HERE / "spec.json").read_text())
    paths = main.app.openapi()["paths"]
    for e in spec.endpoints:
        assert e.method.lower() in paths.get(e.path, {}), f"missing {e.method} {e.path}"


# --- happy paths --------------------------------------------------------

def test_patient_register_and_get():
    pid = make_patient()
    assert client.get(f"/patients/{pid}", headers=USER).json()["full_name"] == "Ama Mensah"
    assert len(client.get("/patients", headers=ADMIN).json()) == 1


def test_doctor_crud():
    did = make_doctor()
    assert client.get("/doctors").json()[0]["id"] == did
    r = client.put(f"/doctors/{did}", json={"full_name": "Dr K. Boateng", "specialty": "paediatrics"}, headers=ADMIN)
    assert r.json()["specialty"] == "paediatrics"
    assert client.delete(f"/doctors/{did}", headers=ADMIN).status_code == 204
    assert client.get(f"/doctors/{did}").status_code == 404


def test_book_view_cancel():
    pid, did = make_patient(), make_doctor()
    r = book(pid, did, future(), reason="check-up")
    assert r.status_code == 201 and r.json()["status"] == "booked"
    aid = r.json()["id"]
    assert client.get(f"/appointments/{aid}", headers=USER).status_code == 200
    assert client.post(f"/appointments/{aid}/cancel", headers=USER).json()["status"] == "cancelled"
    assert client.get("/appointments", headers=ADMIN).json()[0]["status"] == "cancelled"  # kept, not deleted


# --- auth ---------------------------------------------------------------

def test_auth_missing_header_401():
    assert client.get("/patients/1").status_code == 401
    assert client.post("/doctors", json={"full_name": "x", "specialty": "y"}).status_code == 401
    assert client.get("/patients/1", headers={"X-Role": "hacker"}).status_code == 401


def test_auth_user_on_admin_endpoint_403():
    assert client.get("/patients", headers=USER).status_code == 403
    assert client.post("/doctors", json={"full_name": "x", "specialty": "y"}, headers=USER).status_code == 403


# --- rules --------------------------------------------------------------

def test_double_booking_409():
    pid, did = make_patient(), make_doctor()
    start = future()
    assert book(pid, did, start).status_code == 201
    assert book(pid, did, start).status_code == 409
    overlap = (datetime.fromisoformat(start) + timedelta(minutes=15)).isoformat()
    assert book(pid, did, overlap).status_code == 409
    later = (datetime.fromisoformat(start) + timedelta(minutes=30)).isoformat()
    assert book(pid, did, later).status_code == 201


def test_cancelled_slot_can_be_rebooked():
    pid, did = make_patient(), make_doctor()
    start = future()
    aid = book(pid, did, start).json()["id"]
    client.post(f"/appointments/{aid}/cancel", headers=USER)
    assert book(pid, did, start).status_code == 201


def test_past_date_422():
    pid, did = make_patient(), make_doctor()
    assert book(pid, did, future(-1)).status_code == 422


def test_duplicate_phone_409():
    make_patient()
    assert client.post("/patients", json={"full_name": "B", "phone": "0244000001"}).status_code == 409


def test_unknown_patient_or_doctor_404():
    did = make_doctor()
    assert book(999, did, future()).status_code == 404
