"""Hidden tests for this scenario's business rules."""
USER = {"X-Role": "user", "X-User-Id": "1"}
OTHER = {"X-Role": "user", "X-User-Id": "2"}
ADMIN = {"X-Role": "admin", "X-User-Id": "9"}


def ok(r, code=201):
    assert r.status_code == code, f"{r.status_code} {r.text[:200]}"
    return r.json()


def account(client, owner="Adwoa Boakye"):
    return ok(client.post("/accounts", json={"owner_name": owner}, headers=USER))["id"]


def move(client, account_id, kind, amount):
    return client.post("/transactions", json={"account_id": account_id, "kind": kind, "amount": amount}, headers=USER)


def balance(client, account_id):
    return client.get(f"/accounts/{account_id}", headers=USER).json()["balance"]


def test_a_new_account_is_empty(client):
    assert balance(client, account(client)) == 0


def test_balance_cannot_be_set_when_opening(client):
    r = client.post("/accounts", json={"owner_name": "Rich", "balance": 1000000}, headers=USER)
    assert r.status_code in (201, 422)
    if r.status_code == 201:
        assert r.json()["balance"] == 0


def test_deposits_and_withdrawals_change_the_balance(client):
    a = account(client)
    ok(move(client, a, "deposit", 100)), ok(move(client, a, "deposit", 50.5)), ok(move(client, a, "withdrawal", 30))
    assert abs(balance(client, a) - 120.5) < 1e-6


def test_withdrawing_more_than_the_balance_is_409(client):
    a = account(client)
    ok(move(client, a, "deposit", 40))
    assert move(client, a, "withdrawal", 40.01).status_code == 409
    assert abs(balance(client, a) - 40) < 1e-6
    assert len(client.get(f"/accounts/{a}/transactions", headers=USER).json()) == 1   # the refused one was not recorded


def test_the_whole_balance_can_be_withdrawn(client):
    a = account(client)
    ok(move(client, a, "deposit", 40)), ok(move(client, a, "withdrawal", 40))
    assert abs(balance(client, a)) < 1e-6


def test_withdrawing_from_an_empty_account_is_409(client):
    assert move(client, account(client), "withdrawal", 1).status_code == 409


def test_kind_must_be_deposit_or_withdrawal(client):
    a = account(client)
    for bad in ("transfer", "", "Deposit "):
        assert move(client, a, bad, 10).status_code == 422
    assert balance(client, a) == 0


def test_amount_must_be_more_than_zero(client):
    a = account(client)
    assert move(client, a, "deposit", 0).status_code == 422
    assert move(client, a, "deposit", -5).status_code == 422


def test_accounts_do_not_affect_each_other(client):
    a, b = account(client), account(client, "Kwesi Appiah")
    ok(move(client, a, "deposit", 100))
    assert balance(client, b) == 0
    assert move(client, b, "withdrawal", 10).status_code == 409


def test_transactions_of_one_account(client):
    a, b = account(client), account(client, "Kwesi Appiah")
    ok(move(client, a, "deposit", 100)), ok(move(client, a, "withdrawal", 20)), ok(move(client, b, "deposit", 5))
    rows = client.get(f"/accounts/{a}/transactions", headers=USER).json()
    assert sorted((row["kind"], row["amount"]) for row in rows) == [("deposit", 100), ("withdrawal", 20)]
    assert client.get(f"/accounts/{b}/transactions", headers=USER).json()[0]["account_id"] == b
    assert len(client.get("/transactions", headers=ADMIN).json()) == 3


def test_transactions_of_an_unknown_account_are_404(client):
    assert client.get("/accounts/987654/transactions", headers=USER).status_code == 404
