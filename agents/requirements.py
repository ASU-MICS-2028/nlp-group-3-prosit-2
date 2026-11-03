"""Requirements agent: chats with a non-developer, one question per turn,
until it can write a Requirements summary.

Agent format: run(state, llm) -> state. One call = one assistant turn.
"""
import json
import time

from pydantic import ValidationError

from core.llm import LLM, extract_json
from core.spec import Requirements
from core.state import LogEntry, Message, ProjectState

SYSTEM = """You help a non-developer describe a backend (an app's data and actions) they want built.

How to talk:
- Plain, friendly language. No technical jargon (no "API", "endpoint", "schema", "database").
- Ask exactly ONE short question per turn.
- Cover: who uses it, what information it keeps, what each kind of user can do, and any rules (limits, who can see what, things that must never happen).
- After about 10 questions, or sooner once you know enough, stop asking and finish with your best guess.

Guardrails:
- Stay on topic. If the user goes off topic, gently steer back to describing their app.
- If the request is clearly unsafe or illegal (e.g. stalking people, stealing data, fraud), say kindly that you can't help build that and ask what else they'd like to build.

Reply with ONLY one JSON object, nothing else. Either:
{"type": "question", "text": "<your one question>"}
or, when finished:
{"type": "done",
 "summary": "<short plain-English recap for the user>",
 "requirements": {
   "project_name": "<short name>",
   "description": "<one or two sentences>",
   "users": ["<who uses it>", ...],
   "data": ["<thing to store, with its details>", ...],
   "actions": ["<who can do what>", ...],
   "rules": ["<business rule>", ...]
 }}"""

START = "(The user just opened the chat. Greet them briefly and ask your first question.)"
FALLBACK = "Sorry, I didn't quite follow. Could you tell me a bit more about what you want your app to do?"
MAX_CHAT = 30
KEEP_LAST = 20


def _messages(chat: list[Message]) -> list[dict]:
    # blank messages make Gemini drop the turn ("Requests ending with a model turn")
    msgs = [{"role": m.role, "content": m.content} for m in chat if m.content.strip()]
    # ponytail: crude short-term memory (first msg + last 20); summarise dropped turns if context gets lost
    if len(msgs) > MAX_CHAT:
        note = {"role": "user", "content": f"({len(msgs) - 1 - KEEP_LAST} earlier messages omitted.)"}
        msgs = msgs[:1] + [note] + msgs[-KEEP_LAST:]
    if not msgs or msgs[0]["role"] != "user":
        msgs.insert(0, {"role": "user", "content": START})
    # the API wants alternating roles: merge neighbours with the same role
    merged = [msgs[0]]
    for m in msgs[1:]:
        if m["role"] == merged[-1]["role"]:
            merged[-1] = {"role": m["role"], "content": merged[-1]["content"] + "\n\n" + m["content"]}
        else:
            merged.append(m)
    return merged


def _parse(reply: str) -> dict:
    data = extract_json(reply)
    if data.get("type") == "question" and isinstance(data.get("text"), str) and data["text"].strip():
        return data
    if data.get("type") == "done":
        data["requirements"] = Requirements.model_validate(data.get("requirements"))
        data.setdefault("summary", "Here's what I understood.")
        return data
    raise ValueError('reply must be {"type":"question","text":...} or {"type":"done",...}')


def run(state: ProjectState, llm: LLM) -> ProjectState:
    if state.chat and state.chat[-1].role == "user" and not state.chat[-1].content.strip():
        state.chat.pop()  # ignore a blank answer; keep waiting for a real one
    if state.chat and state.chat[-1].role != "user":
        return state  # waiting for the user
    t0, tok0 = time.time(), llm.tokens
    msgs = _messages(state.chat)

    data, err = None, None
    for _ in range(2):  # one try + one retry with the error fed back
        reply = llm(SYSTEM, msgs)
        try:
            data = _parse(reply)
            break
        except (ValueError, ValidationError) as e:
            err = str(e)
            msgs = msgs + [
                {"role": "assistant", "content": reply},
                {"role": "user", "content": f"Your reply was invalid: {err}\nReply with ONLY the JSON object."},
            ]

    if data is None:
        action, detail, text = "error", err, FALLBACK
    elif data["type"] == "question":
        action, detail, text = "ask", data["text"], data["text"]
    else:
        state.requirements = data["requirements"]
        action, detail, text = "done", state.requirements.project_name, data["summary"]

    state.chat.append(Message(role="assistant", content=text))
    state.logs.append(LogEntry(agent="requirements", action=action, detail=detail,
                               tokens=llm.tokens - tok0, seconds=round(time.time() - t0, 3)))
    return state


def main():
    from core.llm import get_llm
    llm, state = get_llm(), ProjectState()
    run(state, llm)
    while state.requirements is None:
        print(f"\nAssistant: {state.chat[-1].content}")
        state.chat.append(Message(role="user", content=input("\nYou: ")))
        run(state, llm)
    print(f"\nAssistant: {state.chat[-1].content}\n")
    print(json.dumps(state.requirements.model_dump(), indent=2))


if __name__ == "__main__":
    main()
