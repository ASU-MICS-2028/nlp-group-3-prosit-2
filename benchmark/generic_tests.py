"""Hidden tests that every scenario gets, worked out from its spec. No agent ever sees this file.

It is copied next to hidden_spec.json and hidden_examples.json and reads them: the same checks
run on every scenario, so scores can be compared between scenarios and between systems.
What it checks, for each entity that can be created through the API:
  create returns the record with an id; get and list find it; unknown ids are 404;
  a missing required field or a wrong type is 422; a duplicate unique field is 409;
  an unknown parent id is 404; PUT and PATCH change it; DELETE removes it.
Business rules are different for every scenario, so they are in the scenario's own rules.py.

All calls are made as an admin, so access rules never get in the way here (the contract tests
check access).
"""
import json
import re
from datetime import datetime
from pathlib import Path

import pytest

HERE = Path(__file__).parent
SPEC = json.loads((HERE / "hidden_spec.json").read_text())
EXAMPLES = json.loads((HERE / "hidden_examples.json").read_text())   # {entity: {"create": body, "update": body}}
ADMIN = {"X-Role": "admin", "X-User-Id": "1"}
ENTITIES = {e["name"]: e for e in SPEC["entities"]}
WRONG = {"int": "abc", "float": "abc", "bool": "abc", "date": "not-a-date", "datetime": "not-a-time", "email": "not-an-email"}
UNKNOWN_ID = 987654


def snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def fields(entity: str) -> dict:
    return {f["name"]: f for f in ENTITIES[entity]["fields"]}


def parents(entity: str) -> dict:
    """{foreign key field: parent entity}"""
    return {f"{snake(p)}_id": p for p in ENTITIES[entity].get("belongs_to", [])}


def endpoint(entity: str, method: str, kind: str):
    """The entity's endpoint of one kind: "collection" is /things, "item" is /things/{id}."""
    for ep in SPEC["endpoints"]:
        is_item = re.fullmatch(r"/[^/{}]+/\{[^/{}]+\}", ep["path"]) is not None
        is_collection = re.fullmatch(r"/[^/{}]+", ep["path"]) is not None
        if ep.get("entity") == entity and ep["method"] == method and (is_item if kind == "item" else is_collection):
            return ep
    return None


def url(ep: dict, id=None) -> str:
    return re.sub(r"\{[^}]*\}", str(id), ep["path"])


def creatable(entity: str, seen=()) -> bool:
    """Can a test make one? It needs a POST /things, an example body, and creatable parents."""
    post = endpoint(entity, "POST", "collection")
    if post is None or entity not in EXAMPLES or entity in seen:
        return False
    return all(creatable(parent, (*seen, entity)) for fk, parent in parents(entity).items()
               if fk in post.get("request_fields", []))


def body_for(client, entity: str) -> dict:
    """A valid body for POST /things. Parents are created first and their ids filled in."""
    post = endpoint(entity, "POST", "collection")
    body = dict(EXAMPLES[entity]["create"])
    for fk, parent in parents(entity).items():
        if fk in post.get("request_fields", []):
            body[fk] = make(client, parent)["id"]
    return body


def create(client, entity: str, body: dict):
    return client.post(endpoint(entity, "POST", "collection")["path"], json=body, headers=ADMIN)


def make(client, entity: str) -> dict:
    r = create(client, entity, body_for(client, entity))
    assert r.status_code in (200, 201), f"could not create a {entity}: {r.status_code} {r.text[:200]}"
    return r.json()


def same(kind: str, sent, got) -> bool:
    if kind == "datetime" and isinstance(got, str):   # 10:00:00 and 10:00:00Z are the same moment here
        return datetime.fromisoformat(sent.replace("Z", "")) == datetime.fromisoformat(got.replace("Z", "+00:00")).replace(tzinfo=None)
    if kind == "float" and isinstance(got, (int, float)):
        return abs(sent - got) < 1e-6
    return sent == got


def check_fields(entity: str, sent: dict, got: dict) -> None:
    for name, value in sent.items():
        assert name in got, f"{name} is missing from the response"
        assert same(fields(entity)[name]["type"], value, got[name]), f"{name}: sent {value!r}, got {got[name]!r}"


CAN_CREATE = [e for e in ENTITIES if creatable(e)]


def having(method: str, kind: str) -> list[str]:
    return [e for e in CAN_CREATE if endpoint(e, method, kind)]


def cases(make_cases) -> list:
    return [case for entity in CAN_CREATE for case in make_cases(entity, endpoint(entity, "POST", "collection"))]


# ---------- create, read ----------

@pytest.mark.parametrize("entity", CAN_CREATE)
def test_create_returns_the_record(client, entity):
    body = body_for(client, entity)
    r = create(client, entity, body)
    assert r.status_code == endpoint(entity, "POST", "collection")["status_code"], r.text[:200]
    got = r.json()
    assert isinstance(got.get("id"), int), "the server must assign an integer id"
    check_fields(entity, body, got)
    missing = [name for name in fields(entity) if name not in got]
    assert not missing, f"the response lacks these fields: {missing}"


@pytest.mark.parametrize("entity", having("GET", "item"))
def test_get_returns_what_was_created(client, entity):
    made = make(client, entity)
    r = client.get(url(endpoint(entity, "GET", "item"), made["id"]), headers=ADMIN)
    assert r.status_code == 200 and r.json() == made, r.text[:200]


@pytest.mark.parametrize("entity", having("GET", "collection"))
def test_list_contains_what_was_created(client, entity):
    path = endpoint(entity, "GET", "collection")["path"]
    before = client.get(path, headers=ADMIN)
    assert before.status_code == 200 and isinstance(before.json(), list), before.text[:200]
    made = make(client, entity)
    assert made["id"] in [row["id"] for row in client.get(path, headers=ADMIN).json()]


@pytest.mark.parametrize("method,entity", [(m, e) for m in ("GET", "PUT", "PATCH", "DELETE") for e in having(m, "item")])
def test_unknown_id_is_404(client, method, entity):
    ep = endpoint(entity, method, "item")
    body = {k: v for k, v in body_for(client, entity).items() if k in ep.get("request_fields", [])}
    r = client.request(method, url(ep, UNKNOWN_ID), json=body or None, headers=ADMIN)
    assert r.status_code == 404, f"got {r.status_code} {r.text[:200]}"


# ---------- invalid input ----------

@pytest.mark.parametrize("entity,field", cases(lambda e, post: [
    (e, f) for f in post.get("request_fields", []) if fields(e)[f].get("required", True)]))
def test_missing_required_field_is_422(client, entity, field):
    body = body_for(client, entity)
    assert field in body, f"hidden_examples.json has no {field} for {entity}"
    del body[field]
    assert create(client, entity, body).status_code == 422


@pytest.mark.parametrize("entity,field", cases(lambda e, post: [
    (e, f) for f in post.get("request_fields", []) if fields(e)[f]["type"] in WRONG]))
def test_wrong_type_is_422(client, entity, field):
    body = body_for(client, entity)
    body[field] = WRONG[fields(entity)[field]["type"]]
    assert create(client, entity, body).status_code == 422


@pytest.mark.parametrize("entity,field", cases(lambda e, post: [
    (e, f) for f in post.get("request_fields", []) if fields(e)[f].get("unique")]))
def test_duplicate_unique_field_is_409(client, entity, field):
    body = body_for(client, entity)
    assert create(client, entity, body).status_code in (200, 201)
    assert create(client, entity, body).status_code == 409   # the same body again


@pytest.mark.parametrize("entity,fk", cases(lambda e, post: [
    (e, fk) for fk in parents(e) if fk in post.get("request_fields", [])]))
def test_unknown_parent_is_404(client, entity, fk):
    body = body_for(client, entity)
    body[fk] = UNKNOWN_ID
    r = create(client, entity, body)
    assert r.status_code == 404, f"got {r.status_code} {r.text[:200]}"


# ---------- update, delete ----------

def changes(entity: str, ep: dict) -> dict:
    return {k: v for k, v in EXAMPLES[entity].get("update", {}).items() if k in ep.get("request_fields", [])}


@pytest.mark.parametrize("entity", [e for e in having("PUT", "item") if changes(e, endpoint(e, "PUT", "item"))])
def test_put_replaces_the_record(client, entity):
    ep = endpoint(entity, "PUT", "item")
    body = body_for(client, entity)
    made = create(client, entity, body).json()
    new = {**{k: v for k, v in body.items() if k in ep["request_fields"]}, **changes(entity, ep)}
    r = client.put(url(ep, made["id"]), json=new, headers=ADMIN)
    assert r.status_code == 200, r.text[:200]
    check_fields(entity, new, r.json())
    assert r.json()["id"] == made["id"]
    get = endpoint(entity, "GET", "item")
    if get:
        check_fields(entity, new, client.get(url(get, made["id"]), headers=ADMIN).json())   # it was really saved


@pytest.mark.parametrize("entity", [e for e in having("PATCH", "item") if changes(e, endpoint(e, "PATCH", "item"))])
def test_patch_changes_only_what_is_sent(client, entity):
    ep = endpoint(entity, "PATCH", "item")
    made = make(client, entity)
    new = changes(entity, ep)
    r = client.patch(url(ep, made["id"]), json=new, headers=ADMIN)
    assert r.status_code == 200, r.text[:200]
    check_fields(entity, new, r.json())
    untouched = {k: v for k, v in made.items() if k not in new}
    assert {k: r.json().get(k) for k in untouched} == untouched, "PATCH changed fields that were not sent"


@pytest.mark.parametrize("entity", having("DELETE", "item"))
def test_delete_removes_the_record(client, entity):
    ep = endpoint(entity, "DELETE", "item")
    made = make(client, entity)
    r = client.delete(url(ep, made["id"]), headers=ADMIN)
    assert r.status_code == ep["status_code"], r.text[:200]
    if ep["status_code"] == 204:
        assert r.content == b""
    assert client.delete(url(ep, made["id"]), headers=ADMIN).status_code == 404   # it is gone
    get = endpoint(entity, "GET", "item")
    if get:
        assert client.get(url(get, made["id"]), headers=ADMIN).status_code == 404
