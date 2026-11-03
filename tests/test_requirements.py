import json
from pathlib import Path

from agents.requirements import FALLBACK, run
from core.llm import FakeLLM
from core.state import Message, ProjectState

GOLDEN = Path(__file__).resolve().parent.parent / "golden" / "clinic" / "requirements.json"
REQS = json.loads(GOLDEN.read_text()) if GOLDEN.exists() else {
    "project_name": "Clinic Appointments",
    "description": "Patients book appointments with doctors.",
    "users": ["patients", "clinic staff"],
    "data": ["patients with name and phone", "appointments with date and doctor"],
    "actions": ["patients book appointments", "staff cancel appointments"],
    "rules": ["no double booking"],
}
QUESTION = json.dumps({"type": "question", "text": "Who will use your app?"})
DONE = json.dumps({"type": "done", "summary": "Got it!", "requirements": REQS})


def user_state(text="I want a clinic booking app"):
    return ProjectState(chat=[Message(role="user", content=text)])


def test_empty_chat_greets():
    llm = FakeLLM([QUESTION])
    s = run(ProjectState(), llm)
    assert s.chat[-1].content == "Who will use your app?"
    assert llm.calls[0][1][0]["role"] == "user"  # synthetic opener so API gets a user msg first


def test_question_turn():
    s = run(user_state(), FakeLLM([QUESTION]))
    assert s.chat[-1].role == "assistant" and s.requirements is None
    assert s.logs[-1].agent == "requirements" and s.logs[-1].action == "ask"


def test_done_sets_requirements():
    s = run(user_state(), FakeLLM([f"```json\n{DONE}\n```"]))
    assert s.requirements.project_name == REQS["project_name"]
    assert s.chat[-1].content == "Got it!"
    assert s.logs[-1].action == "done"


def test_retry_after_malformed():
    llm = FakeLLM(["not json at all", QUESTION])
    s = run(user_state(), llm)
    assert s.chat[-1].content == "Who will use your app?"
    assert "invalid" in llm.calls[1][1][-1]["content"]


def test_double_failure_falls_back():
    bad_done = json.dumps({"type": "done", "requirements": {"project_name": "x"}})
    s = run(user_state(), FakeLLM(["oops", bad_done]))
    assert s.chat[-1].content == FALLBACK and s.requirements is None
    assert s.logs[-1].action == "error"


def test_waits_for_user():
    s = user_state()
    s.chat.append(Message(role="assistant", content="hi"))
    llm = FakeLLM([])
    run(s, llm)
    assert not llm.calls and not s.logs


def test_long_chat_truncated():
    chat = [Message(role="user" if i % 2 == 0 else "assistant", content=f"m{i}") for i in range(41)]
    llm = FakeLLM([QUESTION])
    run(ProjectState(chat=chat), llm)
    sent = llm.calls[0][1]
    text = " ".join(m["content"] for m in sent)
    assert "m0" in text and "m40" in text and "m5\n" not in text and "omitted" in text
    assert all(a["role"] != b["role"] for a, b in zip(sent, sent[1:]))


def test_blank_user_message_is_ignored():
    from core.llm import FakeLLM
    from core.state import Message, ProjectState
    from agents import requirements
    state = ProjectState(chat=[Message(role="user", content="a diet app"),
                               Message(role="assistant", content="Just for you?"),
                               Message(role="user", content="   ")])
    llm = FakeLLM([])
    state = requirements.run(state, llm)
    assert llm.calls == [] and state.chat[-1].role == "assistant"
