# Business rules

## Where rules go: app/services/<entity>.py, called by the router before it writes

A rule from the spec ("no double booking", "cannot be in the past") becomes one small function
that raises `HTTPException` with the status code the rule names. The router calls the checks,
then writes. Order of checks: does the referenced record exist (404), is the input sensible
(422), does it clash with what is stored (409).

```python
# app/services/booking.py
import sqlite3
from datetime import datetime, timezone

from fastapi import HTTPException


def to_utc(t: datetime) -> datetime:
    """Clients may send a time with or without a timezone. Keep every time as plain UTC, so
    times can be compared with each other and with now."""
    return t.astimezone(timezone.utc).replace(tzinfo=None) if t.tzinfo else t


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def check_room_exists(db: sqlite3.Connection, room_id: int) -> None:
    if db.execute("SELECT 1 FROM rooms WHERE id = ?", (room_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail=f"Room {room_id} not found")


def check_times(start: datetime, end: datetime) -> None:
    if end <= start:
        raise HTTPException(status_code=422, detail="end_time must be after start_time")
    if start < now():
        raise HTTPException(status_code=422, detail="A booking cannot start in the past")


def check_room_is_free(db: sqlite3.Connection, room_id: int, start: datetime, end: datetime) -> None:
    """Two bookings overlap when each one starts before the other ends. Cancelled ones do not count."""
    clash = db.execute(
        "SELECT 1 FROM bookings WHERE room_id = ? AND status = 'booked' AND start_time < ? AND end_time > ?",
        (room_id, end.isoformat(), start.isoformat())).fetchone()
    if clash:
        raise HTTPException(status_code=409, detail="The room is already booked at that time")
```

## A router that applies the rules: create a booking, cancel it (action endpoint)

The router stays thin: checks from the service, then one INSERT or UPDATE and `db.commit()`.
`user_id` and `status` are set by the server. An action that is not plain CRUD (cancel, approve,
return, mark as paid) is a `POST /<things>/{id}/<action>` that changes one column and returns
the updated record with 200.

```python
# app/routers/booking.py
import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.database import get_db
from app.dependencies import admin_only, current_user
from app.schemas.booking import Booking, BookingCreate
from app.services.booking import check_room_exists, check_room_is_free, check_times, to_utc

router = APIRouter(prefix="/bookings", tags=["bookings"])


def get_booking_or_404(db: sqlite3.Connection, id: int) -> dict:
    row = db.execute("SELECT * FROM bookings WHERE id = ?", (id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Booking {id} not found")
    return dict(row)


@router.post("", response_model=Booking, status_code=201)
def create_booking(body: BookingCreate, user: dict = Depends(current_user),
                   db: sqlite3.Connection = Depends(get_db)):
    start, end = to_utc(body.start_time), to_utc(body.end_time)
    check_room_exists(db, body.room_id)        # 404
    check_times(start, end)                    # 422
    check_room_is_free(db, body.room_id, start, end)   # 409
    cur = db.execute(
        "INSERT INTO bookings (room_id, user_id, start_time, end_time, purpose, status) VALUES (?, ?, ?, ?, ?, 'booked')",
        (body.room_id, user["id"], start.isoformat(), end.isoformat(), body.purpose))
    db.commit()
    return get_booking_or_404(db, cur.lastrowid)


@router.get("", response_model=list[Booking], dependencies=[Depends(admin_only)])
def list_bookings(db: sqlite3.Connection = Depends(get_db)):
    return [dict(r) for r in db.execute("SELECT * FROM bookings ORDER BY start_time")]


@router.get("/{id}", response_model=Booking, dependencies=[Depends(current_user)])
def get_booking(id: int, db: sqlite3.Connection = Depends(get_db)):
    return get_booking_or_404(db, id)


@router.post("/{id}/cancel", response_model=Booking, dependencies=[Depends(current_user)])
def cancel_booking(id: int, db: sqlite3.Connection = Depends(get_db)):
    booking = get_booking_or_404(db, id)
    if booking["status"] == "cancelled":
        raise HTTPException(status_code=409, detail="This booking is already cancelled")
    db.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (id,))   # kept, never deleted
    db.commit()
    return get_booking_or_404(db, id)
```

## Unique field: reject a duplicate with 409 (email, phone, name, code)

Two layers. The column is `UNIQUE` in the table, so the database can never hold a duplicate.
The endpoint checks first so the client gets a clear 409 instead of a 500. On update, do not
count the record itself as a duplicate.

```python
import sqlite3
from typing import Optional

from fastapi import HTTPException


def check_email_is_free(db: sqlite3.Connection, email: str, except_id: Optional[int] = None) -> None:
    row = db.execute("SELECT id FROM members WHERE email = ?", (email,)).fetchone()
    if row is not None and row["id"] != except_id:
        raise HTTPException(status_code=409, detail="This email is already registered")


def insert_member(db: sqlite3.Connection, full_name: str, email: str) -> int:
    """The other way: let the UNIQUE column refuse it and turn that error into a 409."""
    try:
        cur = db.execute("INSERT INTO members (full_name, email) VALUES (?, ?)", (full_name, email))
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="This email is already registered")
    db.commit()
    return cur.lastrowid
```

A pair that must be unique together (one enrolment per student per course) is a table
constraint: `UNIQUE (student_id, course_id)`, checked with `WHERE student_id = ? AND course_id = ?`.

## A referenced record must exist: 404 for an unknown customer_id, room_id, product_id

When the body holds the id of another record (`belongs_to` in the spec), look it up before
inserting and answer 404 when it is not there. Do not rely on the foreign key alone: that
raises `sqlite3.IntegrityError`, which the client would see as a 500.

```python
import sqlite3

from fastapi import HTTPException


def check_student_exists(db: sqlite3.Connection, student_id: int) -> None:
    if db.execute("SELECT 1 FROM students WHERE id = ?", (student_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail=f"Student {student_id} not found")


def check_course_exists(db: sqlite3.Connection, course_id: int) -> None:
    if db.execute("SELECT 1 FROM courses WHERE id = ?", (course_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail=f"Course {course_id} not found")
```

Call both at the top of the create endpoint, before the other rules and before the INSERT.

## Dates and times: not in the past, end after start, fixed-length slots

Store every datetime as UTC text made with `.isoformat()`: ISO text sorts in time order, so SQL
can compare it with `<` and `>`. A client may send `2030-01-01T10:00:00` (no timezone) or
`2030-01-01T10:00:00Z` (with one); comparing the two kinds in Python raises `TypeError: can't
compare offset-naive and offset-aware datetimes`, so convert first.

```python
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException

SLOT = timedelta(minutes=30)   # "each lesson lasts 30 minutes"


def to_utc(t: datetime) -> datetime:
    return t.astimezone(timezone.utc).replace(tzinfo=None) if t.tzinfo else t


def check_not_in_past(start: datetime) -> None:
    if to_utc(start) < datetime.now(timezone.utc).replace(tzinfo=None):
        raise HTTPException(status_code=422, detail="The start time cannot be in the past")


def check_due_date(due: date) -> None:
    if due < date.today():
        raise HTTPException(status_code=422, detail="The due date cannot be in the past")


def slot_end(start: datetime) -> str:
    """When the spec gives a fixed length, the client sends only the start; store the end too."""
    return (to_utc(start) + SLOT).isoformat()
```

## No double booking: reject overlapping times with 409

Two time ranges overlap when each starts before the other ends: `existing.start < new.end AND
existing.end > new.start`. Limit the check to the same person / room / resource, and leave out
cancelled records. When changing an existing booking, leave out the booking itself.

```python
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException

SLOT = timedelta(minutes=30)


def check_tutor_is_free(db: sqlite3.Connection, tutor_id: int, start: datetime,
                        except_id: Optional[int] = None) -> None:
    """Lessons store only start_time and all last SLOT, so two overlap when their starts
    are less than one SLOT apart."""
    clash = db.execute(
        "SELECT id FROM lessons WHERE tutor_id = ? AND status = 'booked' AND start_time > ? AND start_time < ?",
        (tutor_id, (start - SLOT).isoformat(), (start + SLOT).isoformat())).fetchone()
    if clash is not None and clash["id"] != except_id:
        raise HTTPException(status_code=409, detail="The tutor already has a lesson at that time")
```

Pass `start` already converted to plain UTC, the same form the stored values have.

## Status changes: only allowed moves, 409 for the rest

A record with a status (order: pending, paid, shipped, cancelled) may only move along fixed
steps. Keep the allowed moves in one dict; an action that is not allowed from the current
status is a 409 conflict. New records always start in the first status, set by the server.

```python
import sqlite3

from fastapi import HTTPException

ALLOWED = {
    "pending": {"paid", "cancelled"},
    "paid": {"shipped", "cancelled"},
    "shipped": set(),        # final
    "cancelled": set(),      # final
}


def change_status(db: sqlite3.Connection, order_id: int, new_status: str) -> dict:
    row = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
    if new_status not in ALLOWED[row["status"]]:
        raise HTTPException(status_code=409, detail=f"An order that is {row['status']} cannot become {new_status}")
    db.execute("UPDATE orders SET status = ? WHERE id = ?", (new_status, order_id))
    db.commit()
    return dict(db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone())
```

## Limits and capacity: at most N per course, per user, per day (409 when full)

Count what is already stored, compare with the limit, then insert.

```python
import sqlite3

from fastapi import HTTPException

MAX_LOANS = 3   # "a member can borrow at most 3 books at a time"


def check_course_has_space(db: sqlite3.Connection, course_id: int) -> None:
    course = db.execute("SELECT capacity FROM courses WHERE id = ?", (course_id,)).fetchone()
    if course is None:
        raise HTTPException(status_code=404, detail=f"Course {course_id} not found")
    taken = db.execute("SELECT COUNT(*) FROM enrolments WHERE course_id = ?", (course_id,)).fetchone()[0]
    if taken >= course["capacity"]:
        raise HTTPException(status_code=409, detail="This course is full")


def check_loan_limit(db: sqlite3.Connection, member_id: int) -> None:
    open_loans = db.execute("SELECT COUNT(*) FROM loans WHERE member_id = ? AND returned = 0",
                            (member_id,)).fetchone()[0]
    if open_loans >= MAX_LOANS:
        raise HTTPException(status_code=409, detail=f"A member can have at most {MAX_LOANS} books at a time")
```

## Stock and quantities: take from stock when ordering, never below zero

Check there is enough (409 when not), then change the stock and insert the order with the same
connection and ONE `db.commit()` at the end. If anything raises in between, nothing is saved,
so stock and orders can never disagree. Compute totals on the server, not from the client.

```python
import sqlite3

from fastapi import HTTPException


def place_order(db: sqlite3.Connection, user_id: int, product_id: int, quantity: int) -> dict:
    product = db.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if product is None:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")
    if quantity > product["stock"]:
        raise HTTPException(status_code=409, detail=f"Only {product['stock']} left in stock")
    total = round(product["price"] * quantity, 2)     # read-only field: the server works it out
    db.execute("UPDATE products SET stock = stock - ? WHERE id = ?", (quantity, product_id))
    cur = db.execute("INSERT INTO orders (user_id, product_id, quantity, total, status) VALUES (?, ?, ?, ?, 'pending')",
                     (user_id, product_id, quantity, total))
    db.commit()                                       # both changes, or neither
    return dict(db.execute("SELECT * FROM orders WHERE id = ?", (cur.lastrowid,)).fetchone())
```

In the request model use `quantity: int = Field(gt=0)` so zero and negative amounts are 422.

## Soft delete: records are kept, only marked (cancelled, archived, inactive)

When a rule says records are "never deleted", there is no DELETE statement: an action sets a
status or flag, and the lists leave marked records out unless asked.

```python
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.database import get_db

router = APIRouter(prefix="/products", tags=["products"])


@router.post("/{id}/archive")
def archive_product(id: int, db: sqlite3.Connection = Depends(get_db)):
    cur = db.execute("UPDATE products SET active = 0 WHERE id = ?", (id,))
    db.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail=f"Product {id} not found")
    return dict(db.execute("SELECT * FROM products WHERE id = ?", (id,)).fetchone())


@router.get("")
def list_products(include_archived: Optional[bool] = False, db: sqlite3.Connection = Depends(get_db)):
    sql = "SELECT * FROM products" + ("" if include_archived else " WHERE active = 1")
    return [dict(r) for r in db.execute(sql)]
```
