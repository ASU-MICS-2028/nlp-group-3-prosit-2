from core.codemap import code_map


def test_imports_layers_and_routes(tmp_path):
    files = {
        "app/main.py": "from app.routers import items\n",
        "app/database.py": '"""Storage."""\n',
        "app/routers/items.py": (
            "from fastapi import APIRouter\nfrom app import database as db\nfrom ..services.items import f\n"
            "router = APIRouter(prefix='/items')\n@router.get('')\ndef ls(): ...\n@router.delete('/{id}')\ndef rm(): ...\n"),
        "app/services/items.py": "def f(): ...\n",
        "app/schemas/broken.py": "def (:\n",  # syntax error must not crash the map
    }
    for rel, src in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(src)
    m = code_map(tmp_path)
    nodes = {n["id"]: n for n in m["nodes"]}
    assert nodes["app.main"]["layer"] == "entry" and nodes["app.database"]["layer"] == "core"
    assert nodes["app.database"]["doc"] == "Storage."
    assert [(r["method"], r["path"]) for r in nodes["app.routers.items"]["routes"]] == [("GET", "/items"), ("DELETE", "/items/{id}")]
    assert {(e["from"], e["to"]) for e in m["edges"]} == {
        ("app.main", "app.routers.items"), ("app.routers.items", "app.database"), ("app.routers.items", "app.services.items")}
