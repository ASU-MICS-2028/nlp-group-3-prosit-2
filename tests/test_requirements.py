"""Requirements agent with a scripted runner (no model calls): each fake runner plays the model's tool calls."""
import asyncio
import json
import pathlib

from agents import requirements as R
from core.spec import Requirements
from core.state import Message, ProjectState

GOLDEN = json.loads(pathlib.Path("golden/clinic/requirements.json").read_text())
EVENTS = []


async def emit(e):
    EVENTS.append(e)


def turn(state, *calls, seen=None):
    """Run one agent turn where the 'model' makes these tool calls in order."""
    async def runner(system, prompt, tools, schemas):
        if seen is not None:
            seen.update(prompt=prompt, tools=set(tools))
        for name, args in calls:
            seen_reply = await tools[name](args)
            if seen is not None:
                seen.setdefault("replies", []).append(seen_reply)
        return {"tokens": 42}
    return asyncio.run(R.run(state, emit, runner=runner))


def chat(*texts):
    return ProjectState(chat=[Message(role="user", content=t) for t in texts])


def test_asks_one_question_with_quick_replies():
    seen = {}
    st = turn(chat("I run a bakery"), ("ask_user", {"question": "Who uses it?", "options": ["Customers", " ", "Staff"]}), seen=seen)
    assert st.chat[-1] == Message(role="assistant", content="Who uses it?")
    assert json.loads(st.logs[-1].detail) == {"question": "Who uses it?", "options": ["Customers", "Staff"]}
    assert st.logs[-1].tokens == 42 and st.requirements is None
    assert "<conversation>" in seen["prompt"] and "Person: I run a bakery" in seen["prompt"]


def test_bad_summary_is_sent_back_then_fixed_and_waits_for_ok():
    seen = {}
    st = turn(chat("bakery", "customers and staff"),
              ("propose_summary", {"project_name": "Bakery"}),          # missing fields: refused
              ("propose_summary", GOLDEN), seen=seen)
    assert "incomplete" in seen["replies"][0]
    assert st.requirements is None and R.pending_summary(st) == Requirements(**GOLDEN)
    assert "Does that look right?" in st.chat[-1].content and "**Who uses it:**" in st.chat[-1].content


def test_confirm_locks_in_the_stored_draft_not_a_new_one():
    st = turn(chat("bakery"), ("propose_summary", GOLDEN))
    st.chat.append(Message(role="user", content="yes that's it"))
    st = turn(st, ("confirm_summary", {}))
    assert st.requirements == Requirements(**GOLDEN) and st.logs[-1].action == "confirmed"
    assert R.pending_summary(st) is None


def test_confirm_without_a_summary_is_refused():
    seen = {}
    st = turn(chat("yes"), ("confirm_summary", {}), ("ask_user", {"question": "What is the app for?"}), seen=seen)
    assert "no summary" in seen["replies"][0].lower() and st.requirements is None
    assert st.chat[-1].content == "What is the app for?"


def test_only_the_first_reply_counts():
    seen = {}
    st = turn(chat("hi"), ("ask_user", {"question": "A?"}), ("ask_user", {"question": "B?"}), seen=seen)
    assert st.chat[-1].content == "A?" and len(st.chat) == 2 and "already replied" in seen["replies"][1]


def test_off_topic_is_declined():
    st = turn(chat("write my essay"), ("decline", {"message": "I can only help you describe an app."}))
    assert st.logs[-1].action == "decline" and st.chat[-1].content.startswith("I can only")


def test_model_failure_keeps_the_chat_and_says_sorry():
    async def broken(*a):
        raise RuntimeError("no credentials")
    st = asyncio.run(R.run(chat("hello"), emit, runner=broken))
    assert st.logs[-1].action == "gave_up" and "no credentials" in st.logs[-1].detail
    assert st.chat[0].content == "hello" and "Sorry" in st.chat[-1].content


def test_no_more_questions_after_the_limit():
    st = chat("hi")
    st.logs = [R.LogEntry(agent="requirements", action="ask", detail="{}")] * R.MAX_QUESTIONS
    seen = {}
    turn(st, ("propose_summary", GOLDEN), seen=seen)
    assert "ask_user" not in seen["tools"] and "propose_summary" in seen["tools"]
