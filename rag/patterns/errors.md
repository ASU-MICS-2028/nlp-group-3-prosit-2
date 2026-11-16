# Errors and fixes

## Which status code for which problem: 401, 403, 404, 409, 422

| Code | When | Who answers |
| --- | --- | --- |
| 200 | read, update or action worked | default |
| 201 | a record was created | `status_code=201` in the decorator |
| 204 | a record was deleted; no body | `status_code=204` and `return Response(status_code=204)` |
| 401 | no `X-Role` header, or not `user`/`admin` | the `current_user` dependency |
| 403 | signed in, but not allowed (user on an admin endpoint, someone else's record) | `admin_only` or an owner check |
| 404 | the id in the path or in the body does not exist | `raise HTTPException(status_code=404, ...)` |
| 409 | conflicts with stored data: duplicate, double booking, full, already cancelled | `raise HTTPException(status_code=409, ...)` |
| 422 | invalid input: missing field, wrong type, value out of range, date in the past | pydantic by itself, or `raise HTTPException(status_code=422, ...)` |

Use the success code the spec gives for the endpoint. `detail` is a short sentence a person can
read. Raise the exception; do not return it.

```python
from fastapi import HTTPException


def refuse_examples(found: bool, duplicate: bool, quantity: int) -> None:
    if not found:
        raise HTTPException(status_code=404, detail="Item 7 not found")
    if duplicate:
        raise HTTPException(status_code=409, detail="This phone number is already registered")
    if quantity <= 0:
        raise HTTPException(status_code=422, detail="quantity must be more than 0")
```

## Test failure: expected 401 or 403 but got 422, 404 or 200

The access check ran too late or not at all.

- Got 200/201 instead of 401: the endpoint has no auth dependency. Add
  `dependencies=[Depends(current_user)]` (access "user") or `Depends(admin_only)` (access "admin").
- Got 422 instead of 401/403: the check is inside the function body, so the body was validated
  first. Move it into a dependency: dependencies run before body validation.
- Got 404 instead of 401/403: the record was looked up before the access check. Same fix.
- Got 401 instead of 403: `admin_only` must depend on `current_user` and raise 403 when the role
  is `user`.
- Got 401 on a public endpoint: the router was created with `dependencies=[...]` for all its
  endpoints. Put the dependency on each endpoint instead.

```python
from fastapi import APIRouter, Depends

from app.dependencies import admin_only

router = APIRouter(prefix="/products", tags=["products"])


@router.delete("/{id}", status_code=204, dependencies=[Depends(admin_only)])   # 401/403 before anything else
def delete_product(id: int):
    ...
```

## Test failure: expected 409 or 404 but got 500 (sqlite3.IntegrityError)

A 500 means an exception nobody caught. `sqlite3.IntegrityError: UNIQUE constraint failed` is a
duplicate: check for it before the INSERT and raise 409. `FOREIGN KEY constraint failed` is an id
that does not exist (check it first, raise 404) or a delete of a record others still point at
(raise 409, or delete the children first). `NOT NULL constraint failed` means the INSERT left
out a column: list every column the table requires.

```python
import sqlite3

from fastapi import HTTPException


def create_customer(db: sqlite3.Connection, full_name: str, phone: str) -> int:
    if db.execute("SELECT 1 FROM customers WHERE phone = ?", (phone,)).fetchone():
        raise HTTPException(status_code=409, detail="This phone number is already registered")
    cur = db.execute("INSERT INTO customers (full_name, phone) VALUES (?, ?)", (full_name, phone))
    db.commit()
    return cur.lastrowid
```

## Error: sqlite3.OperationalError no such table / no such column / unable to open database file

- `no such table`: the tables were never created. `init_db()` must run in the app's `lifespan`
  in `app/main.py`, and the table must be in `SCHEMA`. Check the table name is spelled the same
  in `SCHEMA` and in the query.
- `no such column` or `table has no column named`: the query uses a name that is not in the
  CREATE TABLE statement. Column names are exactly the spec's field names.
- `unable to open database file`: the folder of `DATABASE_PATH` does not exist or cannot be
  written. Read the path from the environment (`os.getenv("DATABASE_PATH", "data/app.db")`),
  never a path inside `app/`: the code folder is read-only when the API runs.
- Data from one test shows up in another, or the tests see an empty database after a create:
  the app opened the database at a fixed path. Read `DATABASE_PATH` once, at the top of
  `app/database.py`, and open a new connection per request with `get_db`.

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="My API", lifespan=lifespan)
```

## Error: sqlite3.ProgrammingError SQLite objects created in a thread can only be used in that same thread

FastAPI runs normal `def` endpoints and dependencies in a pool of worker threads, so the
connection made by `get_db` can be used by a different thread. Open it with
`check_same_thread=False`, and keep one connection per request (never one global connection
shared by all requests).

```python
import os
import sqlite3

DB_PATH = os.getenv("DATABASE_PATH", "data/app.db")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
```

`sqlite3.OperationalError: database is locked` has the same cure: one short-lived connection
per request, `db.commit()` straight after the writes, and the connection closed in `get_db`.

## Error: data is not saved, the new record is gone on the next request

The write was never committed. Call `db.commit()` after every INSERT, UPDATE and DELETE, before
returning. A GET straight after a POST then finds the record.

```python
import sqlite3


def rename_room(db: sqlite3.Connection, room_id: int, name: str) -> None:
    db.execute("UPDATE rooms SET name = ? WHERE id = ?", (name, room_id))
    db.commit()   # without this line the change disappears when the connection closes
```

## Error: 500 ResponseValidationError, or a field is missing or null in the response

The value returned does not fit the `response_model`.

- Returned a `sqlite3.Row`: return `dict(row)`.
- Returned `None`: the endpoint forgot to `return`, or read the row back before `db.commit()`
  with another connection.
- A field is missing: the SELECT did not include that column (`SELECT *` after the insert), or
  the response model has a field the table lacks.
- A required response field is NULL in the database: make it `Optional[...] = None` in the
  response model, or give the column a default.
- The id is missing from the response: the response model must have `id: int`, and the endpoint
  must read the row back using `cur.lastrowid`.

## Error: 404 or 405 on an endpoint that exists, or 307 redirect

- 404 on every endpoint of one resource: its router is not included. Add
  `app.include_router(<module>.router)` in `app/main.py`.
- 404 on one endpoint: the path differs from the spec. With `APIRouter(prefix="/rooms")` the
  decorator path is `""` for `/rooms` and `"/{id}"` for `/rooms/{id}`; do not repeat the prefix.
- 405 Method Not Allowed: the path exists with another method. Use the spec's method (PUT is not
  PATCH).
- 307 Temporary Redirect: the route was declared as `"/"` under a prefix, so `/rooms` redirects
  to `/rooms/`. Declare it as `""`.
- 422 on a fixed path such as `/bookings/mine` or `/items/search`: it is declared after
  `/{id}`, so `mine` is read as an id. Declare fixed paths before `/{id}`.

```python
from fastapi import APIRouter

router = APIRouter(prefix="/bookings", tags=["bookings"])


@router.get("")            # GET /bookings
def list_bookings(): ...


@router.get("/mine")       # GET /bookings/mine: before /{id}
def my_bookings(): ...


@router.get("/{id}")       # GET /bookings/{id}
def get_booking(id: int): ...
```

## Error: ModuleNotFoundError, ImportError or circular import when the app starts

- `No module named 'app.routers.room'`: the file is missing or named differently from the import.
- `No module named 'database'`: import with the full name, `from app.database import get_db`.
- `No module named 'sqlalchemy'` / `'email_validator'` / any other package: only `fastapi`,
  `pydantic` and the standard library are installed. Use `sqlite3`, and a `pattern` for emails.
- `cannot import name ... (most likely due to a circular import)`: `app/main.py` imports the
  routers, so routers and services must never import from `app.main`. Shared things live in
  `app/database.py` and `app/dependencies.py`.

## Error: TypeError can't compare offset-naive and offset-aware datetimes

One datetime has a timezone (`2030-01-01T10:00:00Z`) and the other does not. Convert every
incoming time to plain UTC before comparing or storing it.

```python
from datetime import datetime, timezone


def to_utc(t: datetime) -> datetime:
    return t.astimezone(timezone.utc).replace(tzinfo=None) if t.tzinfo else t


def is_in_past(t: datetime) -> bool:
    return to_utc(t) < datetime.now(timezone.utc).replace(tzinfo=None)
```
