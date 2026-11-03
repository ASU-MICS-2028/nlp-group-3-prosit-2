"""Architect agent: requirements -> validated Spec + build tasks for the coder."""
import json
import re
import time

from pydantic import ValidationError

from core.llm import LLM, extract_json
from core.spec import Spec
from core.state import LogEntry, ProjectState

MAX_ATTEMPTS = 3

SYSTEM = """You are a backend API architect. Turn the user's requirements into an API spec.

Rules:
- Entity names are PascalCase and singular. Field names are snake_case. Do not list "id".
- A reference to another entity is a field named <entity>_id (type int) plus the entity name in belongs_to.
- Fields the server sets (status, created_at) get "read_only": true and never appear in request_fields.
- Give each entity the CRUD endpoints the requirements need, using REST paths like /appointments and /appointments/{id}.
- access: "public" for anonymous reads, "user" for logged-in users, "admin" for staff-only actions. Writes are never public, except self-registration (e.g. POST /patients).
- request_fields only lists fields of the endpoint's entity.
- Put business rules (e.g. "no double booking") in rules.

Reply with ONE JSON object matching this JSON schema, and nothing else:
""" + json.dumps(Spec.model_json_schema())


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def check_spec(spec: Spec) -> list[str]:
    """Semantic checks pydantic can't do. Returns a list of problems (empty = ok)."""
    problems = []
    names = [e.name for e in spec.entities]
    entities = {e.name: e for e in spec.entities}
    for n in {n for n in names if names.count(n) > 1}:
        problems.append(f"entity name {n!r} is used more than once")
    for e in spec.entities:
        for b in e.belongs_to:
            if b not in entities:
                problems.append(f"entity {e.name!r} belongs_to unknown entity {b!r}")
            if f"{_snake(b)}_id" not in {f.name for f in e.fields}:
                problems.append(f"entity {e.name!r} belongs_to {b!r} but has no field {_snake(b)}_id")
    seen = set()
    for ep in spec.endpoints:
        key = (ep.method, ep.path)
        if key in seen:
            problems.append(f"duplicate endpoint {ep.method} {ep.path}")
        seen.add(key)
        if not ep.path.startswith("/"):
            problems.append(f"endpoint path {ep.path!r} must start with '/'")
        if ep.entity is None:
            if ep.request_fields:
                problems.append(f"{ep.method} {ep.path} has request_fields but no entity")
            continue
        ent = entities.get(ep.entity)
        if ent is None:
            problems.append(f"{ep.method} {ep.path} refers to unknown entity {ep.entity!r}")
            continue
        fields = {f.name: f for f in ent.fields}
        for rf in ep.request_fields:
            if rf not in fields:
                problems.append(f"{ep.method} {ep.path}: request field {rf!r} is not a field of {ent.name}")
            elif fields[rf].read_only:
                problems.append(f"{ep.method} {ep.path}: request field {rf!r} is read_only")
    return problems


def split_tasks(spec: Spec) -> list[str]:
    tasks = []
    for e in spec.entities:
        fields = ", ".join(f"{f.name}: {f.type}" for f in e.fields)
        tasks.append(f"Create model + storage for {e.name} with fields {fields}")
    for ep in spec.endpoints:
        tasks.append(f"Implement {ep.method} {ep.path}: {ep.summary} ({ep.access})")
    for r in spec.rules:
        tasks.append(f"Enforce rule: {r}")
    return tasks


def _prompt(state: ProjectState, revise: bool) -> str:
    req = state.requirements.model_dump_json(indent=2)
    if not revise:
        return f"Requirements:\n{req}"
    return (f"Requirements:\n{req}\n\nCurrent spec:\n{state.spec.model_dump_json(indent=2)}\n\n"
            f"The user asked for this change:\n{state.change_request}\n\n"
            "Return the full revised spec.")


def run(state: ProjectState, llm: LLM) -> ProjectState:
    if state.requirements is None:
        raise ValueError("architect needs state.requirements")
    revise = bool(state.change_request) and state.spec is not None
    start, tokens0 = time.time(), llm.tokens
    messages = [{"role": "user", "content": _prompt(state, revise)}]

    for attempt in range(1, MAX_ATTEMPTS + 1):
        reply = llm(SYSTEM, messages)
        try:
            spec = Spec.model_validate(extract_json(reply))
            problems = check_spec(spec)
        except (ValueError, ValidationError) as e:  # JSONDecodeError is a ValueError
            problems = [str(e)]
        if not problems:
            break
        messages += [
            {"role": "assistant", "content": reply},
            {"role": "user", "content": "Your spec has problems:\n- " + "\n- ".join(problems)
             + "\nReturn the corrected full spec as JSON."},
        ]
    else:
        raise RuntimeError(f"architect failed after {MAX_ATTEMPTS} attempts: {problems}")

    state.spec = spec
    state.tasks = split_tasks(spec)
    if revise:
        state.change_request = None
        state.spec_approved = False
    state.logs.append(LogEntry(
        agent="architect", action="revise" if revise else "generate",
        detail=f"valid spec after {attempt} attempt(s): {len(spec.entities)} entities, {len(spec.endpoints)} endpoints",
        tokens=llm.tokens - tokens0, seconds=round(time.time() - start, 3),
    ))
    return state
