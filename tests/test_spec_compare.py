"""eval/spec_compare.py: compares by meaning, so renames are matches and real gaps are differences."""
import json
from pathlib import Path

from core.spec import Spec
from eval import spec_compare as C

GOLDEN = json.loads((Path(__file__).resolve().parent.parent / "golden" / "clinic" / "spec.json").read_text())


def golden() -> Spec:
    return Spec.model_validate(GOLDEN)


def renamed() -> Spec:
    """The golden spec with Appointment called Booking, start_time called starts_at, PUT made PATCH."""
    text = (json.dumps(GOLDEN).replace("Appointment", "Booking").replace("appointments", "bookings")
            .replace("start_time", "starts_at").replace('"PUT"', '"PATCH"'))
    return Spec.model_validate_json(text)


def test_same_spec_scores_one():
    r = C.compare(golden(), golden())
    assert r["score"] == 1.0 and r["notes"] == []


def test_renames_still_match():
    r = C.compare(renamed(), golden())
    assert r["entities"]["f1"] == r["fields"]["f1"] == r["endpoints"]["f1"] == 1.0
    assert r["access_agreement"] == 1.0 and r["request_fields"] == 1.0   # body fields mapped through renames
    assert "entity Booking = reference Appointment" in r["notes"]
    assert "field Booking.starts_at = reference Appointment.start_time" in r["notes"]
    assert any("different update method" in n for n in r["notes"])


def test_real_gaps_are_reported():
    gen = golden()
    gen.endpoints = [e for e in gen.endpoints if e.path != "/patients"]       # staff can't list patients
    next(e for e in gen.endpoints if e.method == "GET" and e.path == "/appointments").access = "user"
    r = C.compare(gen, golden())
    assert r["endpoints"]["recall"] < 1.0 and r["endpoints"]["precision"] == 1.0
    assert "missing endpoint GET /patients (admin)" in r["notes"]
    assert "GET /appointments: access user, reference admin" in r["notes"]
    assert r["access_agreement"] < 1.0 and r["score"] < 1.0


def test_unrelated_entities_do_not_match():
    gen = golden()
    gen.entities.append(Spec.model_validate({"project_name": "x", "description": "", "endpoints": [], "entities": [
        {"name": "Invoice", "fields": [{"name": "amount", "type": "float"}]}]}).entities[0])
    r = C.compare(gen, golden())
    assert "extra entity Invoice" in r["notes"] and r["entities"]["precision"] == 0.75


def test_cli_reads_state_json_and_appends_csv(tmp_path, capsys):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"spec": GOLDEN, "chat": []}))
    out = tmp_path / "results" / "specs.csv"
    for _ in range(2):
        assert C.main([str(state), "golden/clinic/spec.json", "--csv", str(out)]) == 0
    lines = out.read_text().splitlines()
    assert lines[0].startswith("generated,reference,score") and len(lines) == 3   # one header, two rows
    assert "Spec score 1.0" in capsys.readouterr().out
