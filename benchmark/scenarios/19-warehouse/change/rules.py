"""Hidden tests for this scenario's change request. No agent ever sees this file."""
USER = {"X-Role": "user", "X-User-Id": "1"}
ADMIN = {"X-Role": "admin", "X-User-Id": "9"}


def ok(r, code=201):
    assert r.status_code == code, f"{r.status_code} {r.text[:200]}"
    return r.json()


def warehouse(client, name):
    return ok(client.post("/warehouses", json={"name": name}, headers=ADMIN))


def item(client, sku, **extra):
    return ok(client.post("/items", json={"sku": sku, "name": f"Item {sku}", **extra}, headers=ADMIN))


def receive(client, item_id, warehouse_id, quantity):
    ok(client.post("/movements", json={"item_id": item_id, "warehouse_id": warehouse_id, "kind": "receive", "quantity": quantity}, headers=USER))


def test_reorder_level_defaults_to_zero(client):
    assert item(client, "CEM-50")["reorder_level"] == 0


def test_reorder_level_cannot_be_negative(client):
    assert client.post("/items", json={"sku": "BAD-1", "name": "Bad", "reorder_level": -1}, headers=ADMIN).status_code == 422


def test_low_stock_lists_items_below_their_level(client):
    tema, kumasi = warehouse(client, "Tema"), warehouse(client, "Kumasi")
    low, fine, zero = item(client, "CEM-50", reorder_level=10), item(client, "ROD-12", reorder_level=5), item(client, "NAIL-3")
    receive(client, low["id"], tema["id"], 4); receive(client, low["id"], kumasi["id"], 5)   # 9 in total, below 10
    receive(client, fine["id"], tema["id"], 5)                                               # exactly 5: not below
    rows = client.get("/items/low-stock", headers=USER)
    assert rows.status_code == 200
    rows = rows.json()
    assert [r["item_id"] for r in rows] == [low["id"]]
    assert rows[0]["sku"] == "CEM-50" and rows[0]["total"] == 9 and rows[0]["reorder_level"] == 10


def test_an_item_with_no_stock_at_all_is_low(client):
    i = item(client, "SAND-1", reorder_level=1)
    assert [r["item_id"] for r in client.get("/items/low-stock", headers=USER).json()] == [i["id"]]


def test_items_by_id_still_work(client):
    i = item(client, "CEM-50")
    assert client.get(f"/items/{i['id']}", headers=USER).json()["sku"] == "CEM-50"
