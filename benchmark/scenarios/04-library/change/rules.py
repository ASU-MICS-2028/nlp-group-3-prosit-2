"""Hidden tests for this scenario's change request. No agent ever sees this file."""
USER = {"X-Role": "user", "X-User-Id": "1"}
ADMIN = {"X-Role": "admin", "X-User-Id": "9"}


def ok(r, code=201):
    assert r.status_code == code, f"{r.status_code} {r.text[:200]}"
    return r.json()
from datetime import date, timedelta


def loan(client, due="2031-04-01"):
    b = ok(client.post("/books", json={"title": "Arrow of God", "author": "Chinua Achebe", "isbn": "9780385014809"}, headers=ADMIN))
    m = ok(client.post("/members", json={"full_name": "Efua Asante", "email": "efua@example.com"}))
    return ok(client.post("/loans", json={"book_id": b["id"], "member_id": m["id"], "due_date": due}, headers=USER))


def renew(client, loan_id):
    return client.post(f"/loans/{loan_id}/renew", headers=USER)


def test_a_new_loan_has_no_renewals(client):
    assert loan(client)["renewals"] == 0


def test_renewing_adds_14_days(client):
    l = loan(client, "2031-04-01")
    r = ok(renew(client, l["id"]), 200)
    assert r["due_date"] == str(date(2031, 4, 1) + timedelta(days=14)) and r["renewals"] == 1
    assert client.get(f"/loans/{l['id']}", headers=USER).json()["due_date"] == "2031-04-15"


def test_a_loan_can_be_renewed_only_once(client):
    l = loan(client)
    ok(renew(client, l["id"]), 200)
    assert renew(client, l["id"]).status_code == 409


def test_a_returned_loan_cannot_be_renewed(client):
    l = loan(client)
    ok(client.post(f"/loans/{l['id']}/return", headers=USER), 200)
    assert renew(client, l["id"]).status_code == 409
