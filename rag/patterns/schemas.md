# Schemas (pydantic models) and field types

## Field types: spec type to pydantic type to SQLite column

| Spec type | Pydantic | SQLite column | Notes |
| --- | --- | --- | --- |
| `str` | `str` | `TEXT` | |
| `int` | `int` | `INTEGER` | |
| `float` | `float` | `REAL` | money, prices, amounts |
| `bool` | `bool` | `INTEGER` | stored as 0 or 1; pydantic turns it back into true/false |
| `date` | `datetime.date` | `TEXT` | stored as `2030-01-31` with `.isoformat()` |
| `datetime` | `datetime.datetime` | `TEXT` | stored as `2030-01-31T10:00:00` with `.isoformat()` |
| `email` | `str` with a pattern | `TEXT` | `EmailStr` needs a package we do not have |

A required field has no default; pydantic answers 422 by itself when it is missing or has the
wrong type. An optional field (`required: false`) is `Optional[...] = None` and a nullable column.
A `unique` field gets `UNIQUE` on its column. A field in `belongs_to` is an `INTEGER NOT NULL
REFERENCES <table>(id)` column.

```python
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class MemberCreate(BaseModel):
    full_name: str = Field(min_length=1)                 # required, and "" is rejected with 422
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")   # type "email"
    age: Optional[int] = Field(default=None, ge=0)       # optional, never negative
    balance: float = Field(default=0, ge=0)
    joined_on: Optional[date] = None
    last_seen: Optional[datetime] = None
    active: bool = True
```

## app/schemas/<entity>.py: Create, Update and response models for one entity

Three models per entity. `<Entity>Create` has exactly the endpoint's `request_fields`.
`<Entity>Update` is for PATCH: the same fields, all optional. `<Entity>` is what the API returns:
every field plus `id`. PUT takes the Create model (it replaces every field).

```python
# app/schemas/room.py
from typing import Optional

from pydantic import BaseModel, Field


class RoomCreate(BaseModel):
    name: str = Field(min_length=1)
    capacity: int = Field(gt=0)          # 0 or less is 422
    has_projector: bool = False
    notes: Optional[str] = None


class RoomUpdate(BaseModel):
    """PATCH body: only the fields that are sent are changed."""
    name: Optional[str] = Field(default=None, min_length=1)
    capacity: Optional[int] = Field(default=None, gt=0)
    has_projector: Optional[bool] = None
    notes: Optional[str] = None


class Room(RoomCreate):
    id: int
```

Use the response model in the decorator (`response_model=Room`, or `list[Room]` for a list) and
return `dict(row)`: FastAPI converts the dict into the model (0/1 back to a bool, text back to
a date). Returning the `sqlite3.Row` itself fails.

## Read-only fields: set by the server, never accepted from the client

A field with `read_only: true` in the spec (a status, a created time, a total, the owner's id) is
NOT in the Create or Update model, so a client cannot set it. It IS in the response model. The
server fills it in when the record is created. Fields that are not in the endpoint's
`request_fields` are left out of the request model the same way.

```python
# app/schemas/booking.py
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class BookingCreate(BaseModel):
    room_id: int
    start_time: datetime
    end_time: datetime
    purpose: Optional[str] = None


class Booking(BookingCreate):
    id: int
    user_id: int    # read-only: taken from the X-User-Id header
    status: str     # read-only: "booked" or "cancelled", set by the server
```

## Limit a field to fixed choices (status, category, priority)

When a field may hold only a few values, use `Literal`: any other value is rejected with 422 and
the choices show up in the Swagger page.

```python
from typing import Literal, Optional

from pydantic import BaseModel, Field

Priority = Literal["low", "medium", "high"]


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    priority: Priority = "medium"
    estimate_hours: Optional[float] = Field(default=None, gt=0)
```

The same works for a query parameter: `def list_tasks(priority: Optional[Priority] = None)`.
