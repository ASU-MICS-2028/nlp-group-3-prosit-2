"""Hidden tests for this scenario's business rules."""
USER = {"X-Role": "user", "X-User-Id": "1"}
OTHER = {"X-Role": "user", "X-User-Id": "2"}
ADMIN = {"X-Role": "admin", "X-User-Id": "9"}


def ok(r, code=201):
    assert r.status_code == code, f"{r.status_code} {r.text[:200]}"
    return r.json()


def employee(client, annual_days=20, email="esi@example.com"):
    return ok(client.post("/employees", json={"full_name": "Esi Mensah", "email": email, "annual_days": annual_days}, headers=ADMIN))["id"]


def ask(client, employee_id, start="2031-09-01", end="2031-09-05"):
    return client.post("/leaves", json={"employee_id": employee_id, "start_date": start, "end_date": end}, headers=USER)


def act(client, leave_id, action, headers=ADMIN):
    return client.post(f"/leaves/{leave_id}/{action}", headers=headers)


def balance(client, employee_id):
    r = client.get(f"/employees/{employee_id}/balance", headers=USER)
    assert r.status_code == 200, r.text
    keys = ("employee_id", "annual_days", "used_days", "pending_days", "remaining_days")
    return {k: r.json()[k] for k in keys}   # extra keys are allowed


def test_days_are_counted_with_both_ends(client):
    e = employee(client)
    five, one = ok(ask(client, e, "2031-09-01", "2031-09-05")), ok(ask(client, e, "2031-10-01", "2031-10-01"))
    assert (five["days"], five["status"]) == (5, "pending") and one["days"] == 1


def test_dates_must_make_sense(client):
    e = employee(client)
    assert ask(client, e, "2031-09-05", "2031-09-01").status_code == 422
    assert ask(client, e, "2020-09-01", "2020-09-05").status_code == 422
    assert client.post("/employees", json={"full_name": "X", "email": "x@example.com", "annual_days": -1}, headers=ADMIN).status_code == 422


def test_balance_of_a_new_employee(client):
    e = employee(client, 20)
    assert balance(client, e) == {"employee_id": e, "annual_days": 20, "used_days": 0, "pending_days": 0, "remaining_days": 20}


def test_balance_follows_the_requests(client):
    e = employee(client, 20)
    first, second = ok(ask(client, e, "2031-09-01", "2031-09-05"))["id"], ok(ask(client, e, "2031-10-01", "2031-10-03"))["id"]
    b = balance(client, e)
    assert (b["used_days"], b["pending_days"], b["remaining_days"]) == (0, 8, 20)    # pending days are not used yet
    assert ok(act(client, first, "approve"), 200)["status"] == "approved"
    b = balance(client, e)
    assert (b["used_days"], b["pending_days"], b["remaining_days"]) == (5, 3, 15)
    assert ok(act(client, second, "reject"), 200)["status"] == "rejected"
    b = balance(client, e)
    assert (b["used_days"], b["pending_days"], b["remaining_days"]) == (5, 0, 15)


def test_asking_for_more_than_remains_is_409(client):
    e = employee(client, 5)
    assert ask(client, e, "2031-09-01", "2031-09-06").status_code == 409    # 6 days, 5 remain
    first = ok(ask(client, e, "2031-09-01", "2031-09-03"))["id"]            # 3 days
    act(client, first, "approve")
    assert ask(client, e, "2031-10-01", "2031-10-03").status_code == 409    # 3 days, 2 remain
    ok(ask(client, e, "2031-10-01", "2031-10-02"))                          # 2 days fits


def test_overlapping_requests_are_409(client):
    e = employee(client, 30)
    ok(ask(client, e, "2031-09-10", "2031-09-15"))
    for start, end in (("2031-09-10", "2031-09-15"), ("2031-09-15", "2031-09-16"), ("2031-09-08", "2031-09-10"),
                       ("2031-09-12", "2031-09-12"), ("2031-09-01", "2031-09-30")):
        assert ask(client, e, start, end).status_code == 409, (start, end)
    ok(ask(client, e, "2031-09-16", "2031-09-17"))                                   # the next day is free
    ok(ask(client, employee(client, 30, "kofi@example.com"), "2031-09-10", "2031-09-15"))   # so is another employee


def test_rejected_and_cancelled_leave_does_not_block_the_dates(client):
    e = employee(client, 30)
    rejected, cancelled = ok(ask(client, e, "2031-09-10", "2031-09-12"))["id"], ok(ask(client, e, "2031-10-10", "2031-10-12"))["id"]
    act(client, rejected, "reject"), act(client, cancelled, "cancel", USER)
    ok(ask(client, e, "2031-09-10", "2031-09-12"))
    ok(ask(client, e, "2031-10-10", "2031-10-12"))


def test_approval_checks_the_days_again(client):
    e = employee(client, 5)
    first, second = ok(ask(client, e, "2031-09-01", "2031-09-03"))["id"], ok(ask(client, e, "2031-10-01", "2031-10-03"))["id"]
    ok(act(client, first, "approve"), 200)                       # 3 of 5 used
    assert act(client, second, "approve").status_code == 409     # 3 more do not fit
    assert client.get(f"/leaves/{second}", headers=USER).json()["status"] == "pending"
    assert balance(client, e)["used_days"] == 3


def test_a_request_is_decided_once(client):
    e = employee(client, 30)
    approved, rejected = ok(ask(client, e, "2031-09-01", "2031-09-02"))["id"], ok(ask(client, e, "2031-10-01", "2031-10-02"))["id"]
    act(client, approved, "approve"), act(client, rejected, "reject")
    for leave in (approved, rejected):
        assert act(client, leave, "approve").status_code == 409
        assert act(client, leave, "reject").status_code == 409
    assert act(client, rejected, "cancel", USER).status_code == 409


def test_cancelling_approved_leave_gives_the_days_back(client):
    e = employee(client, 5)
    leave = ok(ask(client, e, "2031-09-01", "2031-09-05"))["id"]
    act(client, leave, "approve")
    assert balance(client, e)["remaining_days"] == 0
    assert ok(act(client, leave, "cancel", USER), 200)["status"] == "cancelled"
    assert balance(client, e)["remaining_days"] == 5 and balance(client, e)["used_days"] == 0
    assert act(client, leave, "cancel", USER).status_code == 409
    assert act(client, leave, "approve").status_code == 409


def test_unknown_ids_are_404(client):
    assert client.get("/employees/987654/balance", headers=USER).status_code == 404
    for action, headers in (("approve", ADMIN), ("reject", ADMIN), ("cancel", USER)):
        assert act(client, 987654, action, headers).status_code == 404
