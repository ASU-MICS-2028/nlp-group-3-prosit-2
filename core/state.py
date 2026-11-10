"""Project state passed between agents (shared contract).

Agent format: async def run(state: ProjectState, emit: Emit) -> ProjectState
Each agent appends at least one LogEntry to state.logs.
"""
from typing import Literal, Optional

from pydantic import BaseModel

from core.spec import Failure, Requirements, Spec


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class LogEntry(BaseModel):
    agent: str
    action: str
    detail: str = ""
    tokens: int = 0
    seconds: float = 0.0


class BuildResult(BaseModel):
    """What the user gets at the end of a build. Filled in by the orchestrator."""
    base_url: str = ""                  # set by the gateway when the API is started
    docs_url: str = ""                  # Swagger page, base_url + "/docs"
    endpoints: list[str] = []           # e.g. "POST /appointments"
    test_summary: str = ""              # e.g. "31 passed in 0.9s"
    known_failures: list[Failure] = []  # tests the Coder could not fix


class ProjectState(BaseModel):
    chat: list[Message] = []
    requirements: Optional[Requirements] = None
    spec: Optional[Spec] = None
    spec_approved: bool = False
    change_request: Optional[str] = None   # set by the approval screen
    tasks: list[str] = []                  # build tasks for the coder
    workspace: Optional[str] = None        # folder holding the generated API (app/main.py)
    build_ok: bool = False                 # coder's sandbox checks passed
    test_report: Optional[str] = None      # failure report as text, shown in the UI; sends the coder back in
    failures: list[Failure] = []           # the same failures, one per test, for the coder
    tests_ok: Optional[bool] = None        # tester's verdict on the current code (None = not tested)
    test_summary: str = ""                 # e.g. "31 passed in 0.9s"
    test_results: list[dict] = []          # one {"file", "name", "outcome"} per test, for the Tests view
    result: Optional[BuildResult] = None   # set by the orchestrator when a build finishes
    logs: list[LogEntry] = []
