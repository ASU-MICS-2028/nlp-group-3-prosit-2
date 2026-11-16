"""Hidden tests for this scenario's business rules."""
USER = {"X-Role": "user", "X-User-Id": "1"}
OTHER = {"X-Role": "user", "X-User-Id": "2"}
ADMIN = {"X-Role": "admin", "X-User-Id": "9"}


def ok(r, code=201):
    assert r.status_code == code, f"{r.status_code} {r.text[:200]}"
    return r.json()


def warehouse(client, name="Tema"):
    return ok(client.post("/warehouses", json={"name": name}, headers=ADMIN))["id"]


def item(client, sku="CEM-50"):
    return ok(client.post("/items", json={"sku": sku, "name": "Cement 50kg"}, headers=ADMIN))["id"]


def move(client, item_id, warehouse_id, kind, quantity, **extra):
    return client.post("/movements", headers=USER, json={
        "item_id": item_id, "warehouse_id": warehouse_id, "kind": kind, "quantity": quantity, **extra})


def held(client, warehouse_id):
    r = client.get(f"/warehouses/{warehouse_id}/stock", headers=USER)
    assert r.status_code == 200, r.text
    return {row["sku"]: row["quantity"] for row in r.json()}


def spread(client, item_id):
    r = client.get(f"/items/{item_id}/stock", headers=USER)
    assert r.status_code == 200, r.text
    return r.json()["total"], {row["warehouse_id"]: row["quantity"] for row in r.json()["by_warehouse"]}


def test_nothing_is_held_at_first(client):
    w, i = warehouse(client), item(client)
    assert held(client, w) == {}
    assert spread(client, i) == (0, {})
    assert client.get(f"/items/{i}/stock", headers=USER).json()["item_id"] == i


def test_receiving_and_shipping(client):
    w, i = warehouse(client), item(client)
    ok(move(client, i, w, "receive", 10)), ok(move(client, i, w, "receive", 5)), ok(move(client, i, w, "ship", 4))
    assert held(client, w) == {"CEM-50": 11}
    assert spread(client, i) == (11, {w: 11})


def test_shipping_more_than_is_held_is_409(client):
    w, other, i = warehouse(client), warehouse(client, "Kumasi"), item(client)
    ok(move(client, i, w, "receive", 3))
    assert move(client, i, w, "ship", 4).status_code == 409
    assert move(client, i, other, "ship", 1).status_code == 409    # the other warehouse has none
    assert held(client, w) == {"CEM-50": 3}
    assert len(client.get("/movements", headers=ADMIN).json()) == 1


def test_everything_can_be_shipped_and_then_it_is_not_listed(client):
    w, i = warehouse(client), item(client)
    ok(move(client, i, w, "receive", 3)), ok(move(client, i, w, "ship", 3))
    assert held(client, w) == {} and spread(client, i) == (0, {})


def test_transfer_moves_goods_between_warehouses(client):
    tema, kumasi, i = warehouse(client), warehouse(client, "Kumasi"), item(client)
    ok(move(client, i, tema, "receive", 10))
    moved = ok(move(client, i, tema, "transfer", 4, to_warehouse_id=kumasi))
    assert moved["to_warehouse_id"] == kumasi
    assert held(client, tema) == {"CEM-50": 6} and held(client, kumasi) == {"CEM-50": 4}
    assert spread(client, i) == (10, {tema: 6, kumasi: 4})


def test_transferring_more_than_is_held_is_409(client):
    tema, kumasi, i = warehouse(client), warehouse(client, "Kumasi"), item(client)
    ok(move(client, i, tema, "receive", 3))
    assert move(client, i, tema, "transfer", 4, to_warehouse_id=kumasi).status_code == 409
    assert held(client, tema) == {"CEM-50": 3} and held(client, kumasi) == {}


def test_a_transfer_needs_a_proper_destination(client):
    tema, i = warehouse(client), item(client)
    ok(move(client, i, tema, "receive", 5))
    assert move(client, i, tema, "transfer", 1).status_code == 422                          # no destination
    assert move(client, i, tema, "transfer", 1, to_warehouse_id=tema).status_code == 422    # the same warehouse
    assert move(client, i, tema, "transfer", 1, to_warehouse_id=987654).status_code == 404  # no such warehouse
    assert held(client, tema) == {"CEM-50": 5}


def test_kind_and_quantity_are_checked(client):
    w, i = warehouse(client), item(client)
    for bad in ("return", "", "Receive "):
        assert move(client, i, w, bad, 1).status_code == 422
    assert move(client, i, w, "receive", 0).status_code == 422
    assert move(client, i, w, "receive", -5).status_code == 422
    assert held(client, w) == {}


def test_items_are_counted_separately(client):
    w, cement, rods = warehouse(client), item(client), item(client, "ROD-12")
    ok(move(client, cement, w, "receive", 10)), ok(move(client, rods, w, "receive", 7))
    assert move(client, rods, w, "ship", 8).status_code == 409    # only 7 rods, although 10 bags of cement
    ok(move(client, rods, w, "ship", 2))
    assert held(client, w) == {"CEM-50": 10, "ROD-12": 5}
    rows = client.get(f"/warehouses/{w}/stock", headers=USER).json()
    assert sorted(row["item_id"] for row in rows) == sorted([cement, rods])


def test_stock_of_unknown_things_is_404(client):
    assert client.get("/warehouses/987654/stock", headers=USER).status_code == 404
    assert client.get("/items/987654/stock", headers=USER).status_code == 404


def test_stock_needs_sign_in(client):
    assert client.get(f"/warehouses/{warehouse(client)}/stock").status_code == 401
