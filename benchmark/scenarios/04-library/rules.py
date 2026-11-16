"""Hidden tests for this scenario's business rules."""
USER = {"X-Role": "user", "X-User-Id": "1"}
OTHER = {"X-Role": "user", "X-User-Id": "2"}
ADMIN = {"X-Role": "admin", "X-User-Id": "9"}


def ok(r, code=201):
    assert r.status_code == code, f"{r.status_code} {r.text[:200]}"
    return r.json()


def book(client, isbn="9780385474542"):
    return ok(client.post("/books", json={"title": "Things Fall Apart", "author": "Chinua Achebe", "isbn": isbn}, headers=ADMIN))


def member(client, email="efua@example.com"):
    return ok(client.post("/members", json={"full_name": "Efua Asante", "email": email}))


def lend(client, book_id, member_id, due="2031-04-01"):
    return client.post("/loans", json={"book_id": book_id, "member_id": member_id, "due_date": due}, headers=USER)


def test_a_new_book_is_available(client):
    assert book(client)["available"] is True


def test_borrowing_makes_the_book_unavailable(client):
    b = book(client)
    loan = ok(lend(client, b["id"], member(client)["id"]))
    assert loan["returned"] is False
    assert client.get(f"/books/{b['id']}").json()["available"] is False


def test_a_book_on_loan_cannot_be_borrowed_again(client):
    b = book(client)
    ok(lend(client, b["id"], member(client)["id"]))
    assert lend(client, b["id"], member(client, "kofi@example.com")["id"]).status_code == 409


def test_returning_makes_the_book_available_again(client):
    b, m = book(client), member(client)
    loan = ok(lend(client, b["id"], m["id"]))
    assert ok(client.post(f"/loans/{loan['id']}/return", headers=USER), 200)["returned"] is True
    assert client.get(f"/books/{b['id']}").json()["available"] is True
    ok(lend(client, b["id"], m["id"]))   # and it can be borrowed again


def test_returning_twice_is_409(client):
    loan = ok(lend(client, book(client)["id"], member(client)["id"]))
    client.post(f"/loans/{loan['id']}/return", headers=USER)
    assert client.post(f"/loans/{loan['id']}/return", headers=USER).status_code == 409


def test_return_unknown_loan_is_404(client):
    assert client.post("/loans/987654/return", headers=USER).status_code == 404


def test_a_member_can_hold_at_most_three_books(client):
    m = member(client)
    books = [book(client, f"978000000000{i}") for i in range(4)]
    loans = [ok(lend(client, b["id"], m["id"])) for b in books[:3]]
    assert lend(client, books[3]["id"], m["id"]).status_code == 409
    assert client.get(f"/books/{books[3]['id']}").json()["available"] is True   # the refused loan changed nothing
    client.post(f"/loans/{loans[0]['id']}/return", headers=USER)
    ok(lend(client, books[3]["id"], m["id"]))                                    # one came back, so a new one is fine


def test_another_member_is_not_affected_by_the_limit(client):
    m = member(client)
    for i in range(3):
        ok(lend(client, book(client, f"978000000000{i}")["id"], m["id"]))
    ok(lend(client, book(client, "9780000000009")["id"], member(client, "kofi@example.com")["id"]))


def test_due_date_in_the_past_is_422(client):
    assert lend(client, book(client)["id"], member(client)["id"], "2020-01-01").status_code == 422


def test_a_book_on_loan_cannot_be_deleted(client):
    b = book(client)
    loan = ok(lend(client, b["id"], member(client)["id"]))
    assert client.delete(f"/books/{b['id']}", headers=ADMIN).status_code == 409
    assert client.get(f"/books/{b['id']}").status_code == 200
    client.post(f"/loans/{loan['id']}/return", headers=USER)
    assert client.delete(f"/books/{b['id']}", headers=ADMIN).status_code == 204
