# Access rules (who may call an endpoint)

## app/dependencies.py: header auth with X-Role and X-User-Id (401 and 403)

Callers identify themselves with two headers: `X-Role` is `user` or `admin`, `X-User-Id` is
their id. A missing or unknown `X-Role` is 401. A user calling an admin endpoint is 403.

```python
# app/dependencies.py
from typing import Optional

from fastapi import Depends, Header, HTTPException


def current_user(x_role: Optional[str] = Header(default=None),
                 x_user_id: Optional[str] = Header(default=None)) -> dict:
    """Any signed-in caller (user or admin). 401 when the X-Role header is missing or invalid."""
    if x_role not in ("user", "admin"):
        raise HTTPException(status_code=401, detail="Missing or invalid X-Role header")
    user_id = int(x_user_id) if x_user_id and x_user_id.isdigit() else None
    return {"role": x_role, "id": user_id}


def admin_only(user: dict = Depends(current_user)) -> dict:
    """Admins only. 401 when not signed in, 403 when signed in as a user."""
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user
```

`Header()` turns the parameter name `x_role` into the header `X-Role` by itself.

## Protect an endpoint by its access level: public, user or admin

The spec gives every endpoint an access level. Put the check in a dependency, never in the
function body: dependencies run before the body is validated and before any database lookup, so
a caller with no header gets 401 (not 422 or 404) and a user on an admin endpoint gets 403.

```python
import sqlite3

from fastapi import APIRouter, Depends

from app.database import get_db
from app.dependencies import admin_only, current_user

router = APIRouter(prefix="/rooms", tags=["rooms"])


@router.get("")                                           # access "public": no dependency at all
def list_rooms(db: sqlite3.Connection = Depends(get_db)):
    return [dict(r) for r in db.execute("SELECT * FROM rooms")]


@router.get("/{id}/bookings", dependencies=[Depends(current_user)])   # access "user": users and admins
def room_bookings(id: int, db: sqlite3.Connection = Depends(get_db)):
    return [dict(r) for r in db.execute("SELECT * FROM bookings WHERE room_id = ?", (id,))]


@router.delete("/{id}", status_code=204, dependencies=[Depends(admin_only)])   # access "admin"
def delete_room(id: int, db: sqlite3.Connection = Depends(get_db)):
    db.execute("DELETE FROM rooms WHERE id = ?", (id,))
    db.commit()
```

Use `dependencies=[Depends(...)]` when the function does not need to know who is calling, and a
parameter `user: dict = Depends(current_user)` when it does (see the owner pattern).

## Owner only: a user sees and changes only their own records, an admin sees all

Store who created the record (`user_id`, taken from the `X-User-Id` header, never from the
request body). On read, update or cancel: 404 when the record does not exist, then 403 when it
belongs to someone else and the caller is not an admin.

```python
import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.database import get_db
from app.dependencies import current_user

router = APIRouter(prefix="/bookings", tags=["bookings"])


def get_own_booking(id: int, user: dict, db: sqlite3.Connection) -> sqlite3.Row:
    row = db.execute("SELECT * FROM bookings WHERE id = ?", (id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Booking {id} not found")
    if user["role"] != "admin" and row["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="This booking belongs to someone else")
    return row


@router.get("/mine")   # "my bookings": declared BEFORE /{id}, or "mine" is read as an id (422)
def my_bookings(user: dict = Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    return [dict(r) for r in db.execute("SELECT * FROM bookings WHERE user_id = ?", (user["id"],))]


@router.get("/{id}")
def get_booking(id: int, user: dict = Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    return dict(get_own_booking(id, user, db))
```

Only add the owner check when the spec's rules ask for it ("users can only see their own ...").
Without such a rule, access "user" means any signed-in user.
