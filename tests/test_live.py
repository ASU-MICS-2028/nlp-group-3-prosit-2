"""Real LLM calls on the golden clinic chat. Skipped without an API key for LLM_PROVIDER."""
import json
import os
import pathlib

import pytest

from agents import architect, requirements
from agents.architect import check_spec
from core.llm import get_llm, load_env
from core.state import Message, ProjectState

load_env()
_KEY = {"gemini": "GEMINI_API_KEY", "claude": "ANTHROPIC_API_KEY", "claude-code": None}[os.getenv("LLM_PROVIDER", "gemini")]
pytestmark = pytest.mark.skipif(_KEY is not None and not os.getenv(_KEY), reason=f"needs {_KEY}")


def test_golden_chat_to_spec():
    llm = get_llm()
    chat = json.loads(pathlib.Path("golden/clinic/chat.json").read_text())
    state = ProjectState(chat=[Message(**m) for m in chat])

    state = requirements.run(state, llm)
    if state.requirements is None:  # model asked one more question; tell it to wrap up
        state.chat.append(Message(role="user", content="That's everything, please finish."))
        state = requirements.run(state, llm)
    assert state.requirements is not None
    assert any("appointment" in d.lower() for d in state.requirements.data)

    state = architect.run(state, llm)
    names = {e.name for e in state.spec.entities}
    assert {"Patient", "Doctor", "Appointment"} <= names
    assert check_spec(state.spec) == []
    assert state.tasks

    state.change_request = "Add a way for admins to list all appointments for one doctor."
    state = architect.run(state, llm)
    assert state.change_request is None and check_spec(state.spec) == []
    print(f"\nmodel={llm.model} tokens={llm.tokens} entities={sorted(names)} endpoints={len(state.spec.endpoints)} tasks={len(state.tasks)}")
