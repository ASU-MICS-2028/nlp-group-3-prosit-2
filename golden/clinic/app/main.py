"""Golden example: Clinic Appointments API, hand-written to match spec.json.

Auth: header X-Role: user|admin. Missing header = public.
Storage: in-memory dicts (reset by restarting the process).
"""
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, Field

app = FastAPI(title="Clinic Appointments")

SLOT = timedelta(minutes=30)
db: dict[str, dict[int, dict]] = {"patients": {}, "doctors": {}, "appointments": {}}
_next_id = {"n": 0}  # ponytail: in-memory, swap for a real DB when persistence matters


def new_id() -> int:
    _next_id["n"] += 1
    return _next_id["n"]


# --- auth ---------------------------------------------------------------

def require(level: str):
    def check(x_role: Optional[str] = Header(default=None)):
        if x_role not in ("user", "admin"):
            raise HTTPException(401, "Missing or invalid X-Role header")
        if level == "admin" and x_role != "admin":
            raise HTTPException(403, "Admin only")
        return x_role
    return Depends(check)


USER, ADMIN = require("user"), require("admin")


# --- health (every generated API has this; the platform checks it) -------

@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}


# --- models -------------------------------------------------------------

class PatientIn(BaseModel):
    full_name: str
    phone: str
    email: Optional[str] = Field(None, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")  # ponytail: regex, use EmailStr if email-validator is added
    date_of_birth: Optional[date] = None


class Patient(PatientIn):
    id: int


class DoctorIn(BaseModel):
    full_name: str
    specialty: str
    phone: Optional[str] = None


class Doctor(DoctorIn):
    id: int


class AppointmentIn(BaseModel):
    patient_id: int
    doctor_id: int
    start_time: datetime
    reason: Optional[str] = None


class Appointment(AppointmentIn):
    id: int
    status: str


def get_or_404(table: str, id: int) -> dict:
    if id not in db[table]:
        raise HTTPException(404, f"{table[:-1].capitalize()} {id} not found")
    return db[table][id]


# --- patients -----------------------------------------------------------

@app.post("/patients", response_model=Patient, status_code=201)
def create_patient(body: PatientIn):
    if any(p["phone"] == body.phone for p in db["patients"].values()):
        raise HTTPException(409, "Phone number already registered")
    p = {"id": new_id(), **body.model_dump()}
    db["patients"][p["id"]] = p
    return p


@app.get("/patients", response_model=list[Patient], dependencies=[ADMIN])
def list_patients():
    return list(db["patients"].values())


@app.get("/patients/{id}", response_model=Patient, dependencies=[USER])
def get_patient(id: int):
    return get_or_404("patients", id)


# --- doctors ------------------------------------------------------------

@app.get("/doctors", response_model=list[Doctor])
def list_doctors():
    return list(db["doctors"].values())


@app.get("/doctors/{id}", response_model=Doctor)
def get_doctor(id: int):
    return get_or_404("doctors", id)


@app.post("/doctors", response_model=Doctor, status_code=201, dependencies=[ADMIN])
def create_doctor(body: DoctorIn):
    d = {"id": new_id(), **body.model_dump()}
    db["doctors"][d["id"]] = d
    return d


@app.put("/doctors/{id}", response_model=Doctor, dependencies=[ADMIN])
def update_doctor(id: int, body: DoctorIn):
    get_or_404("doctors", id).update(body.model_dump())
    return db["doctors"][id]


@app.delete("/doctors/{id}", status_code=204, dependencies=[ADMIN])
def delete_doctor(id: int):
    get_or_404("doctors", id)
    del db["doctors"][id]
    return Response(status_code=204)


# --- appointments -------------------------------------------------------

def _now_like(t: datetime) -> datetime:
    return datetime.now(timezone.utc) if t.tzinfo else datetime.now()


@app.post("/appointments", response_model=Appointment, status_code=201, dependencies=[USER])
def create_appointment(body: AppointmentIn):
    get_or_404("patients", body.patient_id)
    get_or_404("doctors", body.doctor_id)
    if body.start_time < _now_like(body.start_time):
        raise HTTPException(422, "Appointment cannot be in the past")
    for a in db["appointments"].values():
        if (a["doctor_id"] == body.doctor_id and a["status"] == "booked"
                and abs(a["start_time"] - body.start_time) < SLOT):
            raise HTTPException(409, "Doctor already has an appointment at that time")
    a = {"id": new_id(), "status": "booked", **body.model_dump()}
    db["appointments"][a["id"]] = a
    return a


@app.get("/appointments", response_model=list[Appointment], dependencies=[ADMIN])
def list_appointments():
    return list(db["appointments"].values())


@app.get("/appointments/{id}", response_model=Appointment, dependencies=[USER])
def get_appointment(id: int):
    return get_or_404("appointments", id)


@app.post("/appointments/{id}/cancel", response_model=Appointment, dependencies=[USER])
def cancel_appointment(id: int):
    a = get_or_404("appointments", id)
    a["status"] = "cancelled"
    return a
