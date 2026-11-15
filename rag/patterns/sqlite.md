# Using sqlite3

## Parameterised queries: never build SQL from user input (SQL injection)

Every value goes in as a `?` placeholder with the values in a tuple. Never use an f-string,
`+`, `%` or `.format()` to put a value into SQL: a name like `x'; DROP TABLE rooms; --` would
then run as SQL.

```python
import sqlite3


def examples(db: sqlite3.Connection, name: str, capacity: int, room_id: int) -> None:
    db.execute("SELECT * FROM rooms WHERE name = ?", (name,))             # one value: note the comma
    db.execute("INSERT INTO rooms (name, capacity) VALUES (?, ?)", (name, capacity))
    db.execute("UPDATE rooms SET capacity = ? WHERE id = ?", (capacity, room_id))
    db.execute("SELECT * FROM rooms WHERE name LIKE ?", (f"%{name}%",))   # the % signs go in the value

    # WRONG, never do this:
    # db.execute(f"SELECT * FROM rooms WHERE name = '{name}'")
```

`(name)` is not a tuple, `(name,)` is. Passing a bare string gives `sqlite3.ProgrammingError:
Incorrect number of bindings supplied`. Table and column names cannot be placeholders: write
them in the SQL yourself, never take them from the client.

## Insert a row and return it with its new id (lastrowid)

`cursor.lastrowid` is the id SQLite gave the new row. Commit, then read the row back and return
it, so the response shows exactly what is stored (defaults and server-set fields included).

```python
import sqlite3


def create_member(db: sqlite3.Connection, full_name: str, email: str) -> dict:
    cur = db.execute("INSERT INTO members (full_name, email) VALUES (?, ?)", (full_name, email))
    db.commit()
    row = db.execute("SELECT * FROM members WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)
```

## Reading rows: fetchone, fetchall, dict(row), count

With `conn.row_factory = sqlite3.Row` a row can be read by column name and turned into a dict.

```python
import sqlite3


def reading(db: sqlite3.Connection) -> None:
    row = db.execute("SELECT * FROM rooms WHERE id = ?", (1,)).fetchone()    # one row, or None
    if row is not None:
        name = row["name"]
        as_dict = dict(row)                                                  # {"id": 1, "name": ...}
    rows = db.execute("SELECT * FROM rooms ORDER BY name").fetchall()        # a list, [] when empty
    as_list = [dict(r) for r in rows]
    count = db.execute("SELECT COUNT(*) FROM rooms").fetchone()[0]           # a number
    exists = db.execute("SELECT 1 FROM rooms WHERE name = ?", ("A1",)).fetchone() is not None
```

Always return `dict(row)` or a list of dicts from an endpoint, never the `sqlite3.Row`.

## Commit and rollback: several changes that must happen together

Nothing is saved until `db.commit()`. Make all the changes of one request, then commit once:
if an exception is raised before the commit, the connection is closed and none of them is kept.

```python
import sqlite3

from fastapi import HTTPException


def transfer(db: sqlite3.Connection, from_id: int, to_id: int, amount: float) -> None:
    source = db.execute("SELECT balance FROM accounts WHERE id = ?", (from_id,)).fetchone()
    if source is None or db.execute("SELECT 1 FROM accounts WHERE id = ?", (to_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="Account not found")
    if source["balance"] < amount:
        raise HTTPException(status_code=409, detail="Not enough money in the account")
    db.execute("UPDATE accounts SET balance = balance - ? WHERE id = ?", (amount, from_id))
    db.execute("UPDATE accounts SET balance = balance + ? WHERE id = ?", (amount, to_id))
    db.commit()   # both updates are saved here, together
```

## Tables for related entities: foreign keys, join tables, defaults

`belongs_to` in the spec becomes a `REFERENCES` column. A many-to-many link (students enrol in
courses) is its own table with one row per pair and `UNIQUE` on the pair. Create parent tables
before the tables that point at them.

```python
SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    capacity INTEGER NOT NULL DEFAULT 30,
    fee REAL NOT NULL DEFAULT 0,
    starts_on TEXT
);
CREATE TABLE IF NOT EXISTS enrolments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id),
    course_id INTEGER NOT NULL REFERENCES courses(id),
    enrolled_at TEXT NOT NULL,
    UNIQUE (student_id, course_id)
);
"""
```

Table names are the plural snake_case of the entity (`OrderItem` -> `order_items`), and column
names are exactly the spec's field names.

## Totals, counts and reports: SUM, COUNT, GROUP BY, JOIN

Let SQL do the adding up. `COALESCE(SUM(x), 0)` gives 0 instead of NULL when there are no rows.

```python
import sqlite3

from fastapi import APIRouter, Depends

from app.database import get_db

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/summary")
def summary(db: sqlite3.Connection = Depends(get_db)):
    total = db.execute("SELECT COALESCE(SUM(amount), 0) FROM expenses").fetchone()[0]
    by_category = db.execute(
        "SELECT category, COUNT(*) AS count, SUM(amount) AS total FROM expenses GROUP BY category ORDER BY total DESC")
    return {"total": total, "by_category": [dict(r) for r in by_category]}


@router.get("/bookings-per-room")
def bookings_per_room(db: sqlite3.Connection = Depends(get_db)):
    rows = db.execute(
        "SELECT rooms.id, rooms.name, COUNT(bookings.id) AS bookings "
        "FROM rooms LEFT JOIN bookings ON bookings.room_id = rooms.id AND bookings.status = 'booked' "
        "GROUP BY rooms.id ORDER BY rooms.name")
    return [dict(r) for r in rows]
```

## Set a timestamp on the server: created_at, updated_at

A read-only time field is filled in by the server in UTC, as ISO text.

```python
import sqlite3
from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def create_note(db: sqlite3.Connection, user_id: int, text: str) -> dict:
    cur = db.execute("INSERT INTO notes (user_id, text, created_at) VALUES (?, ?, ?)", (user_id, text, utc_now()))
    db.commit()
    return dict(db.execute("SELECT * FROM notes WHERE id = ?", (cur.lastrowid,)).fetchone())
```
