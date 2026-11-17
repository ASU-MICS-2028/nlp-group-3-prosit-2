"""Hidden tests for this scenario's change request. No agent ever sees this file."""
USER = {"X-Role": "user", "X-User-Id": "1"}
ADMIN = {"X-Role": "admin", "X-User-Id": "9"}


def ok(r, code=201):
    assert r.status_code == code, f"{r.status_code} {r.text[:200]}"
    return r.json()


def product(client, **extra):
    return ok(client.post("/products", json={"name": "Gari 1kg", "price": 20.0, "stock": 50, **extra}, headers=ADMIN))


def order(client, product_id, quantity):
    return ok(client.post("/orders", json={"product_id": product_id, "quantity": quantity}, headers=USER))


def test_no_discount_by_default(client):
    p = product(client)
    assert p["discount_percent"] == 0
    assert abs(order(client, p["id"], 2)["total"] - 40.0) < 1e-6


def test_order_uses_the_discounted_price(client):
    p = product(client, discount_percent=25)
    assert abs(order(client, p["id"], 2)["total"] - 30.0) < 1e-6


def test_discount_must_be_between_0_and_90(client):
    for bad in (-1, 91):
        r = client.post("/products", json={"name": f"Bad {bad}", "price": 5.0, "stock": 1, "discount_percent": bad}, headers=ADMIN)
        assert r.status_code == 422
    p = product(client)
    assert client.patch(f"/products/{p['id']}", json={"discount_percent": 95}, headers=ADMIN).status_code == 422


def test_a_discount_set_later_applies_to_new_orders_only(client):
    p = product(client)
    first = order(client, p["id"], 1)
    ok(client.patch(f"/products/{p['id']}", json={"discount_percent": 50}, headers=ADMIN), 200)
    second = order(client, p["id"], 1)
    assert abs(second["total"] - 10.0) < 1e-6
    assert abs(client.get(f"/orders/{first['id']}", headers=USER).json()["total"] - 20.0) < 1e-6
