"""Project state passed between agents.

Agent format: run(state: ProjectState, llm: LLM) -> ProjectState
Each agent appends at least one LogEntry to state.logs.
"""
from typing import Literal, Optional

from pydantic import BaseModel

from core.spec import Requirements, Spec


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class LogEntry(BaseModel):
    agent: str
    action: str
    detail: str = ""
    tokens: int = 0
    seconds: float = 0.0


class ProjectState(BaseModel):
    chat: list[Message] = []
    requirements: Optional[Requirements] = None
    spec: Optional[Spec] = None
    spec_approved: bool = False
    change_request: Optional[str] = None   # set by the approval screen
    tasks: list[str] = []                  # build tasks for the coder
    workspace: Optional[str] = None        # folder holding the generated API (app/main.py)
    build_ok: bool = False                 # coder's sandbox checks passed
    test_report: Optional[str] = None      # failure report from the tester; sends the coder back in
    tests_ok: Optional[bool] = None        # tester's verdict on the current code (None = not tested)
    test_summary: str = ""                 # e.g. "31 passed in 0.9s"
    test_results: list[dict] = []          # one {"file", "name", "outcome"} per test, for the Tests view
    logs: list[LogEntry] = []
