# Project setup

## Project layout: the files to write and what each one holds

Every generated API has the same files; these are the files you need to write. The examples in this library are one small app (meeting
rooms and bookings) written in this layout.

```
app/__init__.py           empty; also one in schemas/, routers/ and services/
app/main.py               creates `app = FastAPI(...)`, creates the tables on startup, includes the routers, GET /health
app/database.py           the SQLite connection, the CREATE TABLE statements, the get_db dependency
app/dependencies.py       header auth: current_user, admin_only
app/schemas/<entity>.py   pydantic models: <Entity>Create, <Entity>Update, <Entity>
app/routers/<entity>.py   one APIRouter per resource; thin handlers
app/services/<entity>.py  business rules, only when the spec has rules for that entity
```

Use only `fastapi`, `pydantic` and the Python standard library. No SQLAlchemy, no SQLModel, no
`email-validator`, no other package: the sandbox has no network and nothing else is installed.
Import with the full name (`from app.database import get_db`), never a relative or bare import.

## app/database.py: SQLite connection, tables and the get_db dependency

The database path comes from the `DATABASE_PATH` environment variable (the tests set it to a
temporary file). One table per entity, created with `CREATE TABLE IF NOT EXISTS` so startup can
run many times. `id INTEGER PRIMARY KEY AUTOINCREMENT` makes the server assign ids.

```python
# app/database.py
import os
import sqlite3

DB_PATH = os.getenv("DATABASE_PATH", "data/app.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS rooms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    capacity INTEGER NOT NULL,
    has_projector INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id INTEGER NOT NULL REFERENCES rooms(id),
    user_id INTEGER NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    purpose TEXT,
    status TEXT NOT NULL DEFAULT 'booked'
);
"""


def get_conn() -> sqlite3.Connection:
    # check_same_thread=False: FastAPI may open the connection in one worker thread and run the
    # endpoint in another. Each request still has its own connection, so this is safe.
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row            # rows behave like dicts: row["name"], dict(row)
    conn.execute("PRAGMA foreign_keys = ON")  # off by default in SQLite, and it is per connection
    return conn


def init_db() -> None:
    """Create the tables. Called once on startup."""
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.close()


def get_db():
    """FastAPI dependency: one connection per request, always closed afterwards."""
    conn = get_conn()
    try:
        yield conn
    finally:
        conn.close()   # anything not committed is thrown away
```

Endpoints take it as `db: sqlite3.Connection = Depends(get_db)` and call `db.commit()` after
every INSERT, UPDATE or DELETE. Without the commit the change is lost when the request ends.

## app/main.py: create the app, create tables on startup (lifespan), include routers, GET /health

`lifespan` runs once when the app starts: that is where the tables are created. Do not create
tables at import time and do not use the old `@app.on_event("startup")`.

`GET /health` is required in every API: no auth, returns exactly `{"status": "ok"}` with 200. It
runs `SELECT 1` first and answers 503 `{"status": "error"}` when the database cannot be reached.

```python
# app/main.py
import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.database import get_conn, init_db
from app.routers import booking, room


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()   # before the first request
    yield


app = FastAPI(title="Room Bookings", lifespan=lifespan)
app.include_router(room.router)
app.include_router(booking.router)


@app.get("/health", tags=["health"])
def health():
    try:
        conn = get_conn()
        conn.execute("SELECT 1")
        conn.close()
    except sqlite3.Error:
        return JSONResponse(status_code=503, content={"status": "error"})
    return {"status": "ok"}
```

Every router file must be imported and passed to `app.include_router(...)` here. A router that
is not included gives 404 on all of its endpoints.
