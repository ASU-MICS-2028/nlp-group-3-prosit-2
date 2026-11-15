"""Hidden tests for this scenario's business rules."""
USER = {"X-Role": "user", "X-User-Id": "1"}
OTHER = {"X-Role": "user", "X-User-Id": "2"}
ADMIN = {"X-Role": "admin", "X-User-Id": "9"}


def ok(r, code=201):
    assert r.status_code == code, f"{r.status_code} {r.text[:200]}"
    return r.json()


def pet(client, name="Simba"):
    return ok(client.post("/pets", json={"name": name, "species": "dog"}, headers=ADMIN))["id"]


def apply(client, pet_id, name="Akosua Frimpong"):
    return client.post("/applications", json={"pet_id": pet_id, "applicant_name": name}, headers=USER)


def decide(client, application_id, action):
    return client.post(f"/applications/{application_id}/{action}", headers=ADMIN)


def status(client, application_id):
    return client.get(f"/applications/{application_id}", headers=USER).json()["status"]


def test_new_records_start_as_not_adopted_and_pending(client):
    p = pet(client)
    assert client.get(f"/pets/{p}").json()["adopted"] is False
    assert ok(apply(client, p))["status"] == "pending"


def test_approving_marks_the_pet_as_adopted(client):
    p = pet(client)
    a = ok(apply(client, p))["id"]
    assert ok(decide(client, a, "approve"), 200)["status"] == "approved"
    assert client.get(f"/pets/{p}").json()["adopted"] is True


def test_approving_rejects_the_other_pending_applications_for_that_pet(client):
    p, other_pet = pet(client), pet(client, "Nala")
    first, second, third = (ok(apply(client, p, n))["id"] for n in ("One", "Two", "Three"))
    elsewhere = ok(apply(client, other_pet))["id"]
    decide(client, second, "approve")
    assert (status(client, first), status(client, second), status(client, third)) == ("rejected", "approved", "rejected")
    assert status(client, elsewhere) == "pending"                        # another pet's application is untouched
    assert client.get(f"/pets/{other_pet}").json()["adopted"] is False


def test_nobody_can_apply_for_an_adopted_pet(client):
    p = pet(client)
    decide(client, ok(apply(client, p))["id"], "approve")
    assert apply(client, p, "Too Late").status_code == 409


def test_rejecting_leaves_the_pet_available(client):
    p = pet(client)
    a = ok(apply(client, p))["id"]
    assert ok(decide(client, a, "reject"), 200)["status"] == "rejected"
    assert client.get(f"/pets/{p}").json()["adopted"] is False
    ok(apply(client, p, "Next Person"))


def test_an_application_is_decided_only_once(client):
    p = pet(client)
    approved, rejected = ok(apply(client, pet(client, "Nala")))["id"], ok(apply(client, p))["id"]
    decide(client, approved, "approve"), decide(client, rejected, "reject")
    for application in (approved, rejected):
        assert decide(client, application, "approve").status_code == 409
        assert decide(client, application, "reject").status_code == 409
    assert client.get(f"/pets/{p}").json()["adopted"] is False           # the refused approve changed nothing


def test_deciding_an_unknown_application_is_404(client):
    assert decide(client, 987654, "approve").status_code == 404
    assert decide(client, 987654, "reject").status_code == 404
