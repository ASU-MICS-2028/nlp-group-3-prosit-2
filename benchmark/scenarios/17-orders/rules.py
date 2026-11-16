"""Hidden tests for this scenario's business rules."""
USER = {"X-Role": "user", "X-User-Id": "1"}
OTHER = {"X-Role": "user", "X-User-Id": "2"}
ADMIN = {"X-Role": "admin", "X-User-Id": "9"}


def ok(r, code=201):
    assert r.status_code == code, f"{r.status_code} {r.text[:200]}"
    return r.json()


def product(client, name="Rice 5kg", price=85.0, stock=10):
    return ok(client.post("/products", json={"name": name, "price": price, "stock": stock}, headers=ADMIN))["id"]


def order(client, headers=USER):
    return ok(client.post("/orders", headers=headers))


def add(client, order_id, product_id, quantity=1, headers=USER):
    return client.post("/items", json={"order_id": order_id, "product_id": product_id, "quantity": quantity}, headers=headers)


def stock(client, product_id):
    return client.get(f"/products/{product_id}").json()["stock"]


def get(client, order_id, headers=USER):
    return client.get(f"/orders/{order_id}", headers=headers).json()


def test_a_new_order_is_open_empty_and_owned_by_the_caller(client):
    o = order(client, OTHER)
    assert o["status"] == "open" and o["total"] == 0 and o["user_id"] == 2


def test_adding_an_item_takes_stock_and_sets_the_price_and_total(client):
    p, q, o = product(client, price=85.0, stock=10), product(client, "Oil 1L", 30.0, 5), order(client)["id"]
    item = ok(add(client, o, p, 2))
    assert abs(item["unit_price"] - 85.0) < 1e-6 and item["quantity"] == 2
    ok(add(client, o, q, 3))
    assert stock(client, p) == 8 and stock(client, q) == 2
    assert abs(get(client, o)["total"] - 260.0) < 1e-6
    assert len(client.get(f"/orders/{o}/items", headers=USER).json()) == 2


def test_quantity_must_be_at_least_one(client):
    p, o = product(client), order(client)["id"]
    assert add(client, o, p, 0).status_code == 422
    assert add(client, o, p, -1).status_code == 422


def test_more_than_stock_is_409_and_changes_nothing(client):
    p, o = product(client, stock=3), order(client)["id"]
    assert add(client, o, p, 4).status_code == 409
    assert stock(client, p) == 3 and get(client, o)["total"] == 0
    ok(add(client, o, p, 3))
    assert stock(client, p) == 0


def test_the_same_product_twice_in_one_order_is_409(client):
    p, o = product(client), order(client)["id"]
    ok(add(client, o, p, 1))
    assert add(client, o, p, 1).status_code == 409
    assert stock(client, p) == 9
    ok(add(client, order(client)["id"], p, 1))   # another order may have it


def test_removing_an_item_gives_the_stock_back_and_lowers_the_total(client):
    p, q, o = product(client, price=85.0), product(client, "Oil 1L", 30.0, 5), order(client)["id"]
    item = ok(add(client, o, p, 2))
    ok(add(client, o, q, 1))
    assert client.delete(f"/items/{item['id']}", headers=USER).status_code == 204
    assert stock(client, p) == 10 and abs(get(client, o)["total"] - 30.0) < 1e-6
    ok(add(client, o, p, 1))   # and the product can be added again


def test_each_order_has_its_own_total(client):
    p, o = product(client, price=85.0), order(client)["id"]
    ok(add(client, o, p, 2))
    other = order(client)["id"]
    ok(add(client, other, product(client, "Oil 1L", 30.0, 5), 1))
    assert abs(get(client, o)["total"] - 170.0) < 1e-6 and abs(get(client, other)["total"] - 30.0) < 1e-6


def test_paying(client):
    p, o = product(client), order(client)["id"]
    assert client.post(f"/orders/{o}/pay", headers=USER).status_code == 409    # nothing in it yet
    ok(add(client, o, p, 2))
    assert ok(client.post(f"/orders/{o}/pay", headers=USER), 200)["status"] == "paid"
    assert client.post(f"/orders/{o}/pay", headers=USER).status_code == 409    # already paid
    assert stock(client, p) == 8


def test_a_paid_order_cannot_be_edited(client):
    p, o = product(client), order(client)["id"]
    item = ok(add(client, o, p, 2))
    client.post(f"/orders/{o}/pay", headers=USER)
    assert add(client, o, product(client, "Oil 1L", 30.0, 5), 1).status_code == 409
    assert client.delete(f"/items/{item['id']}", headers=USER).status_code == 409
    assert stock(client, p) == 8


def test_cancelling_gives_all_the_stock_back(client):
    p, q = product(client), product(client, "Oil 1L", 30.0, 5)
    for pay_first in (False, True):
        o = order(client)["id"]
        ok(add(client, o, p, 2)), ok(add(client, o, q, 5))
        if pay_first:
            client.post(f"/orders/{o}/pay", headers=USER)
        assert ok(client.post(f"/orders/{o}/cancel", headers=USER), 200)["status"] == "cancelled"
        assert stock(client, p) == 10 and stock(client, q) == 5
        assert client.post(f"/orders/{o}/cancel", headers=USER).status_code == 409
        assert client.post(f"/orders/{o}/pay", headers=USER).status_code == 409
        assert add(client, o, product(client, f"Extra {pay_first}", 1.0, 1), 1).status_code == 409
        assert stock(client, p) == 10


def test_another_users_order_is_403(client):
    p, o = product(client), order(client, USER)["id"]
    item = ok(add(client, o, p, 1))
    assert client.get(f"/orders/{o}", headers=OTHER).status_code == 403
    assert client.get(f"/orders/{o}/items", headers=OTHER).status_code == 403
    assert add(client, o, product(client, "Oil 1L", 30.0, 5), 1, OTHER).status_code == 403
    assert client.delete(f"/items/{item['id']}", headers=OTHER).status_code == 403
    assert client.post(f"/orders/{o}/pay", headers=OTHER).status_code == 403
    assert client.post(f"/orders/{o}/cancel", headers=OTHER).status_code == 403
    assert get(client, o)["status"] == "open" and stock(client, p) == 9


def test_listing_orders(client):
    mine, theirs = order(client, USER)["id"], order(client, OTHER)["id"]
    assert [o["id"] for o in client.get("/orders", headers=USER).json()] == [mine]
    assert [o["id"] for o in client.get("/orders", headers=OTHER).json()] == [theirs]
    assert len(client.get("/orders", headers=ADMIN).json()) == 2
    assert client.get(f"/orders/{mine}", headers=ADMIN).status_code == 200


def test_unknown_ids_are_404(client):
    assert client.get("/orders/987654/items", headers=USER).status_code == 404
    assert client.post("/orders/987654/pay", headers=USER).status_code == 404
    assert client.post("/orders/987654/cancel", headers=USER).status_code == 404
