"""RAG, offline: no model and no network. Three things are checked:
  1. the library itself: every code sample is valid Python, and the example app the patterns
     describe really works when it is run with the Tester's own fixture;
  2. chunking and embedding;
  3. retrieval: for realistic Coder queries, the right pattern is in the top results."""
import ast
import asyncio
import inspect
import pathlib
import re

import pytest

import rag
from agents import tester as T
from rag import library as S

PATTERNS = pathlib.Path(S.HERE) / "patterns"
CODE_BLOCK = re.compile(r"```python\n(.*?)\n```", re.S)
ALL_CODE = [(path.name, code) for path in sorted(PATTERNS.glob("*.md")) for code in CODE_BLOCK.findall(path.read_text())]


# ---------- 1. the library ----------

@pytest.mark.parametrize("name,code", ALL_CODE, ids=[f"{n}:{i}" for i, (n, _) in enumerate(ALL_CODE)])
def test_every_code_sample_is_valid_python(name, code):
    ast.parse(code)


def test_no_sample_builds_sql_from_values():
    """Our own rule: parameterised queries only. No f-string or .format() inside execute()."""
    for name, code in ALL_CODE:
        live = "\n".join(line for line in code.splitlines() if not line.strip().startswith("#"))
        assert not re.search(r"execute\w*\(\s*f[\"']", live), f"{name} has an f-string query"
        assert ".format(" not in live, name


# The patterns marked with a first line "# app/<file>.py" are the files of one small app
# (rooms and bookings). These tests are run against that app, built from the library as it is.
APP_TESTS = '''
USER = {"X-Role": "user", "X-User-Id": "7"}
OTHER = {"X-Role": "user", "X-User-Id": "8"}
ADMIN = {"X-Role": "admin", "X-User-Id": "1"}
ROOM = {"name": "Baobab", "capacity": 8}


def room(client, **changes):
    r = client.post("/rooms", json={**ROOM, **changes}, headers=ADMIN)
    assert r.status_code == 201, r.text
    return r.json()


def book(client, room_id, start="2030-01-01T10:00:00", end="2030-01-01T11:00:00", headers=USER):
    return client.post("/bookings", json={"room_id": room_id, "start_time": start, "end_time": end}, headers=headers)


def test_health_is_public(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_create_room_returns_what_is_stored(client):
    created = room(client, has_projector=True)
    assert created == {"id": created["id"], "name": "Baobab", "capacity": 8, "has_projector": True, "notes": None}
    assert client.get(f"/rooms/{created['id']}").json() == created
    assert client.get("/rooms").json() == [created]


def test_each_test_starts_with_an_empty_database(client):
    assert client.get("/rooms").json() == []


def test_access_is_checked_before_the_body_and_the_id(client):
    assert client.post("/rooms", json={}).status_code == 401                 # not 422
    assert client.post("/rooms", json={}, headers=USER).status_code == 403   # not 422
    assert client.delete("/rooms/99").status_code == 401                     # not 404
    assert client.delete("/rooms/99", headers=USER).status_code == 403
    assert client.post("/rooms", json={}, headers={"X-Role": "boss"}).status_code == 401


def test_invalid_input_is_422(client):
    assert client.post("/rooms", json={"name": "A"}, headers=ADMIN).status_code == 422                  # capacity missing
    assert client.post("/rooms", json={"name": "A", "capacity": 0}, headers=ADMIN).status_code == 422
    assert client.post("/rooms", json={"name": "", "capacity": 2}, headers=ADMIN).status_code == 422
    assert client.get("/rooms/abc").status_code == 422


def test_unknown_id_is_404(client):
    assert client.get("/rooms/99").status_code == 404
    assert client.put("/rooms/99", json=ROOM, headers=ADMIN).status_code == 404
    assert client.patch("/rooms/99", json={}, headers=ADMIN).status_code == 404
    assert client.delete("/rooms/99", headers=ADMIN).status_code == 404


def test_duplicate_name_is_409_but_a_room_may_keep_its_own_name(client):
    first, second = room(client), room(client, name="Odum")
    assert client.post("/rooms", json=ROOM, headers=ADMIN).status_code == 409
    assert client.patch(f"/rooms/{second['id']}", json={"name": "Baobab"}, headers=ADMIN).status_code == 409
    assert client.put(f"/rooms/{first['id']}", json={**ROOM, "capacity": 9}, headers=ADMIN).json()["capacity"] == 9


def test_patch_changes_only_the_fields_sent(client):
    created = room(client, notes="ground floor")
    r = client.patch(f"/rooms/{created['id']}", json={"capacity": 12}, headers=ADMIN)
    assert r.status_code == 200 and r.json() == {**created, "capacity": 12}
    r = client.patch(f"/rooms/{created['id']}", json={"notes": None}, headers=ADMIN)   # null is a value too
    assert r.json()["notes"] is None and r.json()["capacity"] == 12


def test_list_filter(client):
    room(client), room(client, name="Odum", capacity=20)
    assert [r["name"] for r in client.get("/rooms", params={"min_capacity": 10}).json()] == ["Odum"]


def test_delete(client):
    created = room(client)
    r = client.delete(f"/rooms/{created['id']}", headers=ADMIN)
    assert r.status_code == 204 and r.content == b""
    assert client.get(f"/rooms/{created['id']}").status_code == 404


def test_booking_gets_its_owner_and_status_from_the_server(client):
    r = book(client, room(client)["id"])
    assert r.status_code == 201, r.text
    assert r.json()["user_id"] == 7 and r.json()["status"] == "booked"
    assert r.json()["start_time"] == "2030-01-01T10:00:00"
    assert client.get(f"/bookings/{r.json()['id']}", headers=USER).json() == r.json()


def test_booking_rules(client):
    room_id = room(client)["id"]
    assert book(client, 99).status_code == 404                                                      # no such room
    assert book(client, room_id, "2020-01-01T10:00:00", "2020-01-01T11:00:00").status_code == 422   # in the past
    assert book(client, room_id, "2030-01-01T11:00:00", "2030-01-01T10:00:00").status_code == 422   # ends before it starts
    assert book(client, room_id).status_code == 201
    assert book(client, room_id, "2030-01-01T10:30:00", "2030-01-01T11:30:00", OTHER).status_code == 409   # overlaps
    assert book(client, room_id, "2030-01-01T11:00:00", "2030-01-01T12:00:00", OTHER).status_code == 201   # starts as the other ends
    assert book(client, room(client, name="Odum")["id"]).status_code == 201                         # another room is free


def test_times_with_a_timezone_are_compared_correctly(client):
    room_id = room(client)["id"]
    assert book(client, room_id).status_code == 201                                                 # 10:00-11:00, no timezone
    assert book(client, room_id, "2030-01-01T12:30:00+02:00", "2030-01-01T13:30:00+02:00").status_code == 409   # = 10:30 UTC
    assert book(client, room_id, "2030-01-01T11:00:00Z", "2030-01-01T12:00:00Z").status_code == 201
    assert book(client, room_id, "2020-01-01T10:00:00Z", "2020-01-01T11:00:00Z").status_code == 422


def test_cancel_keeps_the_booking_and_frees_the_room(client):
    room_id = room(client)["id"]
    booking = book(client, room_id).json()
    r = client.post(f"/bookings/{booking['id']}/cancel", headers=USER)
    assert r.status_code == 200 and r.json() == {**booking, "status": "cancelled"}
    assert client.post(f"/bookings/{booking['id']}/cancel", headers=USER).status_code == 409     # already cancelled
    assert client.post("/bookings/99/cancel", headers=USER).status_code == 404
    assert book(client, room_id).status_code == 201                                              # the time is free again
    assert len(client.get("/bookings", headers=ADMIN).json()) == 2                               # nothing was deleted


def test_a_room_with_bookings_cannot_be_deleted(client):
    room_id = room(client)["id"]
    booking = book(client, room_id).json()
    assert client.delete(f"/rooms/{room_id}", headers=ADMIN).status_code == 409
    client.post(f"/bookings/{booking['id']}/cancel", headers=USER)
    assert client.delete(f"/rooms/{room_id}", headers=ADMIN).status_code == 204


def test_listing_all_bookings_is_admin_only(client):
    assert client.get("/bookings").status_code == 401
    assert client.get("/bookings", headers=USER).status_code == 403
    assert client.get("/bookings", headers=ADMIN).json() == []
'''


def test_the_example_app_in_the_patterns_works(tmp_path):
    """Write the files the patterns show, add the Tester's fixture, and run APP_TESTS on them for real."""
    files = {code.splitlines()[0][2:]: code for _, code in ALL_CODE if re.match(r"# app/\S+\.py$", code.splitlines()[0])}
    assert set(files) == {"app/database.py", "app/main.py", "app/dependencies.py", "app/schemas/room.py",
                          "app/schemas/booking.py", "app/routers/room.py", "app/routers/booking.py",
                          "app/services/booking.py"}
    for name, code in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        (path.parent / "__init__.py").touch()
        path.write_text(code + "\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n")
    (tmp_path / "tests" / "conftest.py").write_text(T.CONFTEST)   # the same `client` fixture generated APIs get
    (tmp_path / "tests" / "test_api.py").write_text(APP_TESTS)

    run = asyncio.run(T.run_pytest(tmp_path))
    assert run["ok"], run["output"][-3000:]
    assert len(run["results"]) == APP_TESTS.count("\ndef test_")


# ---------- 2. chunking and embedding ----------

MARKDOWN = '''# Page

Intro under the page title.

## First idea

Some words about the first idea, long enough to be kept as a chunk of its own.

```python
# app/thing.py
## not a heading either
x = 1

y = 2
```

### A detail

More words about the detail, also long enough to be kept as a chunk of its own, yes.

## Second idea

Words about the second idea, again long enough to be kept as a chunk of its own, yes.
'''


def test_chunks_are_cut_at_headings_and_never_inside_code():
    chunks = S.chunk_file("patterns/x.md", MARKDOWN, levels=2, max_chars=None)
    assert [c.title for c in chunks] == ["Page > First idea", "Page > Second idea"]
    assert "x = 1\n\ny = 2" in chunks[0].text and "A detail" in chunks[0].text   # the "#" lines in the code are not headings

    deeper = S.chunk_file("docs/x.md", MARKDOWN, levels=3, max_chars=None)
    assert [c.title for c in deeper] == ["Page > First idea", "Page > First idea > A detail", "Page > Second idea"]


def test_a_long_section_is_cut_between_blocks():
    long = "## Long\n\n" + "\n\n".join(f"Paragraph {i} " + "word " * 60 for i in range(6)) + "\n\n```python\n" + "a = 1\n\n" * 200 + "```\n"
    chunks = S.chunk_file("docs/x.md", long, levels=3, max_chars=800)
    assert len(chunks) > 2 and all(c.title == "Long" for c in chunks)
    assert chunks[-1].text.startswith("```python") and chunks[-1].text.endswith("```")   # the code block stayed whole
    assert all(len(c.text) <= 800 for c in chunks[:-1])


def test_the_library_is_loaded():
    chunks = S.load_chunks()
    patterns = [c for c in chunks if c.is_pattern]
    assert len(patterns) >= 40 and len(chunks) - len(patterns) >= 150
    assert len({(c.source, c.title) for c in patterns}) == len(patterns)   # one chunk per pattern
    assert all(c.text.count("```") % 2 == 0 for c in chunks)               # no chunk ends inside a code block
    assert all(" > " in c.title for c in patterns)
    assert not any("deprecated" in c.title.lower() for c in chunks)
    assert (pathlib.Path(S.HERE) / "docs" / "LICENSE").exists()            # the FastAPI docs are MIT: keep the notice


def test_tokens():
    assert S.tokens("HTTPException") == ["httpexception", "http", "exception"]
    assert S.tokens("check_same_thread") == ["check_same_thread", "check", "sam", "thread"]
    assert S.tokens("the bookings are cancelled") == S.tokens("booking cancel") == ["book", "cancel"]   # stop words dropped
    assert S.tokens("deleted duplicates categories") == S.tokens("delete duplicate category")
    assert S.tokens("409") == ["409"]


def test_embedding_is_unit_length_and_ignores_unknown_words():
    _, idf, vectors = S.index()
    assert all(abs(sum(x * x for x in v.values()) - 1) < 1e-9 for v in vectors)
    assert S.embed(["zzzunknown"], idf) == {}
    rare, common = S.embed(["lastrowid", "fastapi"], idf)["lastrowid"], S.embed(["lastrowid", "fastapi"], idf)["fastapi"]
    assert rare > common   # IDF: a rare word weighs more than one found everywhere


# ---------- 3. retrieval ----------

# (what the Coder might ask, words that must be in the title of a top-3 result)
QUERIES = [
    ("set up sqlite database connection", "app/database.py"),
    ("create tables on startup", "app/main.py"),
    ("health endpoint", "GET /health"),
    ("which files do I need to write", "Project layout"),
    ("X-Role header authentication", "app/dependencies.py"),
    ("admin only endpoint", "access level"),
    ("user can only see their own orders", "Owner only"),
    ("pydantic models for create and update", "app/schemas"),
    ("how to store a bool or datetime in sqlite", "Field types"),
    ("email field validation", "Field types"),
    ("status is read only set by server", "Read-only fields"),
    ("CRUD router example", "complete CRUD router"),
    ("return 404 when id not found", "or 404"),
    ("filter list by query parameter", "optional filters"),
    ("partial update PATCH", "PATCH"),
    ("delete returns 204", "Delete a record"),
    ("list appointments of a doctor /doctors/{id}/appointments", "Nested resource"),
    ("where do business rules go", "Where rules go"),
    ("cancel appointment endpoint", "action endpoint"),
    ("patient phone must be unique reject duplicates with 409", "Unique field"),
    ("patient_id and doctor_id must refer to existing records", "referenced record must exist"),
    ("appointments cannot start in the past", "Dates and times"),
    ("a doctor cannot have two appointments that overlap", "No double booking"),
    ("order status pending to shipped transitions", "Status changes"),
    ("course is full capacity limit", "Limits and capacity"),
    ("reduce product stock when order is placed", "Stock and quantities"),
    ("never deleted, mark as archived", "Soft delete"),
    ("sql injection placeholders", "Parameterised queries"),
    ("get id of inserted row", "lastrowid"),
    ("many to many table students courses", "related entities"),
    ("total amount per category report", "Totals, counts"),
    ("created_at timestamp", "timestamp"),
    ("update two rows together transaction", "Commit and rollback"),
    # the way failures arrive from the Tester and from tracebacks
    ("test_contract_401_post_rooms: expected 401 without an X-Role header, got 422", "expected 401 or 403"),
    ("expected 409, got 500 sqlite3.IntegrityError: UNIQUE constraint failed: patients.phone", "got 500"),
    ("sqlite3.OperationalError: no such table: rooms", "no such table"),
    ("sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread", "same thread"),
    ("POST then GET returns 404, record was not saved", "data is not saved"),
    ("fastapi.exceptions.ResponseValidationError", "ResponseValidationError"),
    ("got 307 redirect on POST /rooms", "307 redirect"),
    ("ModuleNotFoundError: No module named 'sqlalchemy'", "ModuleNotFoundError"),
    ("TypeError: can't compare offset-naive and offset-aware datetimes", "offset-naive"),
    ("should a duplicate be 400 or 409", "Which status code"),
    # answered by the FastAPI docs
    ("query parameter optional default value", "Query Parameters"),
    ("declare a header parameter", "Header Parameters"),
    ("APIRouter prefix and tags", "Bigger Applications"),
    ("dependency with yield", "Dependencies with yield"),
    ("Field validation gt le", "Number validations"),
]


def titles(query: str, k: int = 3) -> list[str]:
    return [chunk.title for _, chunk in rag.search(query, k)]


@pytest.mark.parametrize("query,expected", QUERIES, ids=[q[:45] for q, _ in QUERIES])
def test_the_right_section_is_in_the_top_3(query, expected):
    found = titles(query)
    assert any(expected in title for title in found), found


def test_most_queries_have_the_right_section_first():
    """Hit rate at 1, the number to quote in the evaluation: how often the best result is the right one."""
    hits = sum(expected in titles(query, 1)[0] for query, expected in QUERIES)
    assert hits / len(QUERIES) >= 0.8, f"{hits}/{len(QUERIES)}"


def test_results_are_sorted_and_scored():
    results = rag.search("unique email duplicate 409", 5)
    scores = [score for score, _ in results]
    assert len(results) == 5 and scores == sorted(scores, reverse=True) and scores[0] > 2 * scores[-1]


def test_one_docs_page_cannot_fill_every_place():
    sources = [c.source for _, c in rag.search("lifespan startup shutdown events", 5) if not c.is_pattern]
    assert len(sources) == len(set(sources))


def test_nonsense_finds_nothing():
    assert rag.search("xyzzy frobnicate") == [] and rag.search("") == [] and rag.search("the and of") == []


# ---------- the tool ----------

def call(tool: dict, **args) -> str:
    return asyncio.run(tool["search_patterns"][2](args))


def test_the_tool_has_the_shared_format_and_returns_the_code():
    seen = []
    tool = rag.tools(on_search=lambda query, results: seen.append((query, len(results))))
    description, schema, handler = tool["search_patterns"]
    assert schema["required"] == ["query"] and inspect.iscoroutinefunction(handler) and "sqlite3" in description

    answer = call(tool, query="unique email duplicate 409")
    assert answer.startswith("=== Result 1: Business rules > Unique field")
    assert "[project pattern: patterns/rules.md]" in answer and "sqlite3.IntegrityError" in answer
    assert answer.count("=== Result") == S.TOP_K and len(answer) < 12000
    assert seen == [("unique email duplicate 409", S.TOP_K)]


def test_the_tool_explains_an_empty_or_hopeless_query():
    tool = rag.tools()
    assert "Give a query" in call(tool) and "Give a query" in call(tool, query="  ")
    assert "Nothing in the library matches" in call(tool, query="xyzzy frobnicate")


def test_rag_can_be_switched_off_for_the_comparison(monkeypatch):
    monkeypatch.setattr(S, "ENABLED", False)
    assert rag.tools() == {}
