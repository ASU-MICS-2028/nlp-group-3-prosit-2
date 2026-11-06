"""Event format streamed from the orchestrator to the UI (shared contract).

Agents call `await emit(Event(...))` as they work; the gateway forwards each event
to the browser over Server-Sent Events.
"""
from typing import Awaitable, Callable, Literal

from pydantic import BaseModel

EventType = Literal["status", "step", "spec", "test", "result", "error"]


class Event(BaseModel):
    type: EventType
    agent: str = ""
    detail: str = ""
    data: dict = {}


Emit = Callable[[Event], Awaitable[None]]
