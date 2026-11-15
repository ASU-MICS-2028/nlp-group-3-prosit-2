"""Hidden tests for this scenario's business rules."""
USER = {"X-Role": "user", "X-User-Id": "1"}
OTHER = {"X-Role": "user", "X-User-Id": "2"}
ADMIN = {"X-Role": "admin", "X-User-Id": "9"}


def ok(r, code=201):
    assert r.status_code == code, f"{r.status_code} {r.text[:200]}"
    return r.json()


def product(client, name="Gari 1kg", price=12.5, stock=10):
    return ok(client.post("/products", json={"name": name, "price": price, "stock": stock}, headers=ADMIN))


def order(client, product_id, quantity):
    return client.post("/orders", json={"product_id": product_id, "quantity": quantity}, headers=USER)


def stock(client, product_id):
    return client.get(f"/products/{product_id}").json()["stock"]


def test_price_must_be_more_than_zero(client):
    for price in (0, -5):
        assert client.post("/products", json={"name": "Free", "price": price, "stock": 1}, headers=ADMIN).status_code == 422


def test_stock_cannot_be_negative(client):
    assert client.post("/products", json={"name": "Ghost", "price": 5, "stock": -1}, headers=ADMIN).status_code == 422
    assert product(client, stock=0)["stock"] == 0   # zero is allowed


def test_changing_a_product_keeps_the_same_rules(client):
    p = product(client)
    assert client.patch(f"/products/{p['id']}", json={"price": 0}, headers=ADMIN).status_code == 422
    assert client.patch(f"/products/{p['id']}", json={"stock": -3}, headers=ADMIN).status_code == 422


def test_quantity_must_be_at_least_one(client):
    p = product(client)
    assert order(client, p["id"], 0).status_code == 422
    assert order(client, p["id"], -2).status_code == 422


def test_an_order_takes_from_stock_and_gets_its_total(client):
    p = product(client, price=12.5, stock=10)
    o = ok(order(client, p["id"], 4))
    assert o["status"] == "placed" and abs(o["total"] - 50.0) < 1e-6 and o["quantity"] == 4
    assert stock(client, p["id"]) == 6


def test_ordering_more_than_stock_is_409_and_changes_nothing(client):
    p = product(client, stock=3)
    assert order(client, p["id"], 4).status_code == 409
    assert stock(client, p["id"]) == 3
    assert client.get("/orders", headers=ADMIN).json() == []


def test_the_last_items_can_be_ordered(client):
    p = product(client, stock=3)
    ok(order(client, p["id"], 3))
    assert stock(client, p["id"]) == 0
    assert order(client, p["id"], 1).status_code == 409


def test_cancel_puts_the_items_back(client):
    p = product(client, stock=10)
    o = ok(order(client, p["id"], 4))
    cancelled = ok(client.post(f"/orders/{o['id']}/cancel", headers=USER), 200)
    assert cancelled["status"] == "cancelled" and stock(client, p["id"]) == 10
    assert client.get(f"/orders/{o['id']}", headers=USER).json()["status"] == "cancelled"   # kept


def test_cancelling_twice_is_409_and_stock_is_returned_once(client):
    p = product(client, stock=10)
    o = ok(order(client, p["id"], 4))
    client.post(f"/orders/{o['id']}/cancel", headers=USER)
    assert client.post(f"/orders/{o['id']}/cancel", headers=USER).status_code == 409
    assert stock(client, p["id"]) == 10


def test_total_uses_the_price_at_the_time_of_the_order(client):
    p = product(client, price=10.0, stock=10)
    o = ok(order(client, p["id"], 2))
    ok(client.patch(f"/products/{p['id']}", json={"price": 99.0}, headers=ADMIN), 200)
    assert abs(client.get(f"/orders/{o['id']}", headers=USER).json()["total"] - 20.0) < 1e-6


def test_cancel_unknown_order_is_404(client):
    assert client.post("/orders/987654/cancel", headers=USER).status_code == 404
