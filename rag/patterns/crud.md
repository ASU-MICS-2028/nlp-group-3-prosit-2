# Endpoints (create, read, update, delete)

## app/routers/<entity>.py: a complete CRUD router with sqlite3

One `APIRouter` per resource. Status codes: create 201, read and update 200, delete 204, unknown
id 404, duplicate 409. Every query uses `?` placeholders. Every write ends with `db.commit()`.

```python
# app/routers/room.py
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response

from app.database import get_db
from app.dependencies import admin_only
from app.schemas.room import Room, RoomCreate, RoomUpdate

router = APIRouter(prefix="/rooms", tags=["rooms"])


def get_room_or_404(db: sqlite3.Connection, id: int) -> dict:
    row = db.execute("SELECT * FROM rooms WHERE id = ?", (id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Room {id} not found")
    return dict(row)   # a plain dict: FastAPI can turn it into the response model


def check_name_is_free(db: sqlite3.Connection, name: str, except_id: Optional[int] = None) -> None:
    row = db.execute("SELECT id FROM rooms WHERE name = ?", (name,)).fetchone()
    if row is not None and row["id"] != except_id:
        raise HTTPException(status_code=409, detail="A room with this name already exists")


@router.post("", response_model=Room, status_code=201, dependencies=[Depends(admin_only)])
def create_room(body: RoomCreate, db: sqlite3.Connection = Depends(get_db)):
    check_name_is_free(db, body.name)
    cur = db.execute("INSERT INTO rooms (name, capacity, has_projector, notes) VALUES (?, ?, ?, ?)",
                     (body.name, body.capacity, body.has_projector, body.notes))
    db.commit()
    return get_room_or_404(db, cur.lastrowid)   # cur.lastrowid is the id SQLite assigned


@router.get("", response_model=list[Room])
def list_rooms(min_capacity: Optional[int] = None, db: sqlite3.Connection = Depends(get_db)):
    if min_capacity is None:
        rows = db.execute("SELECT * FROM rooms ORDER BY id")
    else:
        rows = db.execute("SELECT * FROM rooms WHERE capacity >= ? ORDER BY id", (min_capacity,))
    return [dict(r) for r in rows]


@router.get("/{id}", response_model=Room)
def get_room(id: int, db: sqlite3.Connection = Depends(get_db)):
    return get_room_or_404(db, id)


@router.put("/{id}", response_model=Room, dependencies=[Depends(admin_only)])
def replace_room(id: int, body: RoomCreate, db: sqlite3.Connection = Depends(get_db)):
    get_room_or_404(db, id)
    check_name_is_free(db, body.name, except_id=id)
    db.execute("UPDATE rooms SET name = ?, capacity = ?, has_projector = ?, notes = ? WHERE id = ?",
               (body.name, body.capacity, body.has_projector, body.notes, id))
    db.commit()
    return get_room_or_404(db, id)


@router.patch("/{id}", response_model=Room, dependencies=[Depends(admin_only)])
def update_room(id: int, body: RoomUpdate, db: sqlite3.Connection = Depends(get_db)):
    room = get_room_or_404(db, id)
    room.update(body.model_dump(exclude_unset=True))   # only the fields the client sent replace the old values
    check_name_is_free(db, room["name"], except_id=id)
    db.execute("UPDATE rooms SET name = ?, capacity = ?, has_projector = ?, notes = ? WHERE id = ?",
               (room["name"], room["capacity"], room["has_projector"], room["notes"], id))
    db.commit()
    return get_room_or_404(db, id)


@router.delete("/{id}", status_code=204, dependencies=[Depends(admin_only)])
def delete_room(id: int, db: sqlite3.Connection = Depends(get_db)):
    get_room_or_404(db, id)
    if db.execute("SELECT 1 FROM bookings WHERE room_id = ? AND status = 'booked'", (id,)).fetchone():
        raise HTTPException(status_code=409, detail="This room still has bookings")
    db.execute("DELETE FROM bookings WHERE room_id = ?", (id,))   # old cancelled bookings go with it
    db.execute("DELETE FROM rooms WHERE id = ?", (id,))
    db.commit()
    return Response(status_code=204)
```

With `prefix="/rooms"`, the path `""` is `/rooms` and `"/{id}"` is `/rooms/{id}`. Use `""`, not
`"/"`, for the collection: `"/"` makes `/rooms` answer with a 307 redirect.

## Get one record by id, or 404 when it does not exist

Declare the path parameter as `id: int`: FastAPI then answers 422 for `/rooms/abc`. Look the
record up with a `?` placeholder and raise 404 when `fetchone()` returns `None`. Write this
helper once per entity and call it from get, update, delete and every action endpoint. Return
`dict(row)`, not the `sqlite3.Row` itself: FastAPI cannot turn a Row into a response model.

```python
import sqlite3

from fastapi import HTTPException


def get_room_or_404(db: sqlite3.Connection, id: int) -> dict:
    row = db.execute("SELECT * FROM rooms WHERE id = ?", (id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Room {id} not found")
    return dict(row)   # a plain dict: FastAPI can turn it into the response model
```

The parameter name in the function must be the same as in the path: `/rooms/{id}` needs
`id: int`, `/rooms/{room_id}` needs `room_id: int`. Use the exact path from the spec.

## List with optional filters, search, sorting and pagination (query parameters, limit, offset)

Query parameters are function parameters with a default. Build the WHERE clause from fixed
pieces of SQL and pass the values separately: user input never goes into the SQL string.

```python
import sqlite3
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query

from app.database import get_db

router = APIRouter(prefix="/rooms", tags=["rooms"])
ORDER_BY = {"name": "name", "capacity": "capacity DESC, name"}


@router.get("")
def list_rooms(min_capacity: Optional[int] = None,
               has_projector: Optional[bool] = None,
               search: Optional[str] = None,
               sort: Literal["name", "capacity"] = "name",          # any other value is 422
               limit: int = Query(default=50, ge=1, le=200),
               offset: int = Query(default=0, ge=0),
               db: sqlite3.Connection = Depends(get_db)):
    where, values = [], []
    if min_capacity is not None:
        where.append("capacity >= ?")
        values.append(min_capacity)
    if has_projector is not None:
        where.append("has_projector = ?")
        values.append(has_projector)
    if search:
        where.append("name LIKE ?")
        values.append(f"%{search}%")                                 # the % signs go in the value
    sql = "SELECT * FROM rooms"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY " + ORDER_BY[sort] + " LIMIT ? OFFSET ?"       # a fixed piece of SQL picked by the client's choice
    return [dict(r) for r in db.execute(sql, (*values, limit, offset))]
```

A list endpoint returns a plain JSON array (`[]` when there is nothing), not an object.

## Update a record: PUT replaces every field, PATCH is a partial update (only the fields sent)

PUT takes the Create model: the client sends the whole record. PATCH takes the Update model
(every field optional): read the stored record, lay the sent fields over it with
`model_dump(exclude_unset=True)`, and write every column back. Both answer 404 for an unknown id
and return the updated record with 200.

```python
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.database import get_db

router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskCreate(BaseModel):
    title: str = Field(min_length=1)
    done: bool = False
    notes: Optional[str] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1)
    done: Optional[bool] = None
    notes: Optional[str] = None


def get_task_or_404(db: sqlite3.Connection, id: int) -> dict:
    row = db.execute("SELECT * FROM tasks WHERE id = ?", (id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Task {id} not found")
    return dict(row)


def save(db: sqlite3.Connection, id: int, task: dict) -> dict:
    db.execute("UPDATE tasks SET title = ?, done = ?, notes = ? WHERE id = ?",
               (task["title"], task["done"], task["notes"], id))
    db.commit()
    return get_task_or_404(db, id)


@router.put("/{id}")
def replace_task(id: int, body: TaskCreate, db: sqlite3.Connection = Depends(get_db)):
    get_task_or_404(db, id)
    return save(db, id, body.model_dump())


@router.patch("/{id}")
def update_task(id: int, body: TaskUpdate, db: sqlite3.Connection = Depends(get_db)):
    task = get_task_or_404(db, id)
    task.update(body.model_dump(exclude_unset=True))   # fields that were not sent keep their old value
    return save(db, id, task)
```

Re-check the rules that the changed fields touch (a unique name, a time clash) before saving.

## Delete a record: 204 with no body, 404 when it does not exist

```python
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response

from app.database import get_db

router = APIRouter(prefix="/notes", tags=["notes"])


@router.delete("/{id}", status_code=204)
def delete_note(id: int, db: sqlite3.Connection = Depends(get_db)):
    cur = db.execute("DELETE FROM notes WHERE id = ?", (id,))
    db.commit()
    if cur.rowcount == 0:                 # nothing was deleted: there was no such id
        raise HTTPException(status_code=404, detail=f"Note {id} not found")
    return Response(status_code=204)      # 204 means no body at all
```

When other records point at this one (bookings of a room), decide from the spec's rules: refuse
with 409 while they exist, or delete them first. With `PRAGMA foreign_keys = ON`, deleting a
parent that still has children raises `sqlite3.IntegrityError`.

## Nested resource: list the records that belong to a parent (/rooms/{id}/bookings)

For example the bookings of a room, the lessons of a tutor (`/tutors/{id}/lessons`),
the orders of a customer, the tasks of a project. Return 404 when the parent does not exist,
and an empty list when it exists but has no children.

```python
import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.database import get_db

router = APIRouter(prefix="/rooms", tags=["rooms"])


@router.get("/{id}/bookings")
def bookings_of_room(id: int, db: sqlite3.Connection = Depends(get_db)):
    if db.execute("SELECT 1 FROM rooms WHERE id = ?", (id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail=f"Room {id} not found")
    rows = db.execute("SELECT * FROM bookings WHERE room_id = ? ORDER BY start_time", (id,))
    return [dict(r) for r in rows]
```
