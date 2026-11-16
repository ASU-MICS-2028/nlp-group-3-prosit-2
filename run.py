"""Run the whole pipeline in the terminal, with the same agents the web app uses.

    python run.py --golden clinic          the golden example, start to finish (real agents, costs money)
    python run.py --golden clinic --stub   the same run offline: stub agents replay the golden example
    python run.py "I run a small clinic"   your own idea: you answer the questions in the terminal

Steps: chat (Requirements) -> design (Architect) -> approve -> build (Coder <-> Tester) -> start the API.
In --golden mode the golden user turns answer the Requirements agent's questions, in order, and the
summary and the spec are approved automatically. At the end it prints a summary per agent (steps, tokens,
cost, time) and, for --golden, how the generated spec compares with the golden one (eval/spec_compare.py).

Everything lands in workspace/<name>-<time>/: app/, tests/, steps.jsonl (every step) and state.json.
The exit code is 0 only when the code passed the Coder's checks and every test passed.
"""
import argparse
import asyncio
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

from agents import orchestrator as O
from agents import requirements as req_agent
from core.events import Event
from core.sdk import MODEL
from core.spec import Spec
from core.state import Message, ProjectState
from eval import spec_compare
from core import sandbox
from server import stubs

ROOT = Path(__file__).resolve().parent
MAX_CHAT_TURNS = 12           # stop rule for the scripted chat
NUDGE = "That's everything I can tell you. Please summarise what you have."


# ---------- output ----------

async def show(event: Event) -> None:
    """Print each event on one line, as the web app shows it in the activity feed."""
    if event.type == "status" and event.detail != "idle":
        print(f"\n== {event.detail}")
    elif event.type in ("step", "error"):   # "test" repeats the tester's last step
        print(f"  [{event.agent or '-':12}] {event.detail[:160]}")


def say(role: str, text: str) -> None:
    print(f"\n{role}: {text}")


# ---------- who answers the questions ----------

def golden_answers(name: str):
    """The golden user turns, in order. The last turn ("Yes, that's exactly it") is the confirm button."""
    chat = json.loads((ROOT / "golden" / name / "chat.json").read_text())
    turns = [m["content"] for m in chat if m["role"] == "user"][:-1]

    def answer(question: str) -> str:
        return turns.pop(0) if turns else NUDGE
    return answer


def ask_terminal(question: str) -> str:
    return input("\nyou: ").strip() or "I'm not sure, you choose."


# ---------- the pipeline ----------

async def converse(state: ProjectState, first: str, answer, auto: bool) -> ProjectState:
    """Chat with the Requirements agent until the requirements are confirmed, then design."""
    text = first
    for _ in range(MAX_CHAT_TURNS):
        say("you", text)
        state.chat.append(Message(role="user", content=text))
        state = await O.chat(state, show)          # designs by itself if the agent confirmed the summary
        if state.requirements is not None:
            return state
        reply = state.chat[-1].content if state.chat and state.chat[-1].role == "assistant" else ""
        say("agent", reply)
        if req_agent.pending_summary(state) is not None:
            ok = True if auto else input("\nLooks right? [Y / type what to change] ").strip()
            if ok is True or ok.lower() in ("", "y", "yes"):
                state = await req_agent.confirm(state, show)          # the "Looks right" button
                return await O.design(state, show)
            text = ok
            continue
        text = answer(reply)
    raise RuntimeError(f"No confirmed requirements after {MAX_CHAT_TURNS} turns")


async def approve(state: ProjectState, auto: bool) -> ProjectState:
    """The approval screen: show the spec, then approve or send a change request to the Architect."""
    while True:
        spec = state.spec
        say("architect", f"{spec.project_name}: {len(spec.entities)} entities, {len(spec.endpoints)} endpoints")
        for e in spec.endpoints:
            print(f"    {e.method:6} {e.path:32} {e.access}")
        if auto:
            break
        change = input("\nApprove this spec? [Y / type a change] ").strip()
        if change.lower() in ("", "y", "yes"):
            break
        state.change_request, state.change_files = change, []
        state = await O.design(state, show)
    state.spec_approved = True
    return state


async def deliver(state: ProjectState, keep_serving: bool) -> None:
    """Start the API like the gateway does: it must answer GET /health, or it is refused."""
    try:
        handle = await sandbox.serve(state.workspace, "")
    except RuntimeError as e:
        print(f"\nThe API did not start: {e}")
        return
    url = f"http://127.0.0.1:{handle[1]}"
    state.result.base_url, state.result.docs_url = url, url + "/docs"
    print(f"\nThe API is running: {url}  (docs: {url}/docs)")
    try:
        if keep_serving:
            print("Ctrl+C to stop.")
            await asyncio.Event().wait()
    finally:
        sandbox.stop(handle)


async def run(first: str, answer, auto: bool, workspace: Path, serve: str = "check") -> ProjectState:
    """The whole pipeline. serve: "check" starts the API, checks /health, stops it; "keep" leaves it
    running; "no" skips it."""
    workspace.mkdir(parents=True, exist_ok=True)
    state = ProjectState(workspace=str(workspace))
    state = await converse(state, first, answer, auto)
    state = await approve(state, auto)
    state = await O.build(state, show)
    if serve != "no" and state.build_ok:
        await deliver(state, serve == "keep")
    (workspace / "state.json").write_text(state.model_dump_json(indent=1))
    return state


# ---------- the summary ----------

def report(state: ProjectState, seconds: float, golden: str | None) -> dict:
    per_agent = defaultdict(lambda: {"steps": 0, "tokens": 0, "cost_usd": 0.0, "seconds": 0.0})
    for entry in state.logs:
        a = per_agent[entry.agent]
        a["steps"] += 1
        a["tokens"] += entry.tokens
        a["cost_usd"] += entry.cost_usd
        a["seconds"] += entry.seconds
    stub = all(e.tokens == 0 for e in state.logs)
    summary = {"model": "stub" if stub else MODEL, "build_ok": state.build_ok, "tests_ok": state.tests_ok, "test_summary": state.test_summary,
               "known_failures": [f"{f.endpoint}: {f.test}" for f in state.failures],
               "fix_rounds": sum(l.action == "fix_round" for l in state.logs),
               "chat_turns": sum(m.role == "user" for m in state.chat),
               "seconds": round(seconds, 1), "agents": dict(per_agent),
               "tokens": sum(a["tokens"] for a in per_agent.values()),
               "cost_usd": round(sum(a["cost_usd"] for a in per_agent.values()), 4)}
    if golden and state.spec:
        ref = Spec.model_validate_json((ROOT / "golden" / golden / "spec.json").read_text())
        summary["spec_vs_golden"] = spec_compare.compare(state.spec, ref)

    print("\n" + "=" * 64)
    print(f"Build {'OK' if state.build_ok else 'FAILED'} | tests: {state.test_summary or 'not run'}"
          f" | fix rounds: {summary['fix_rounds']} | chat turns: {summary['chat_turns']}")
    print(f"{'agent':14}{'steps':>7}{'tokens':>10}{'cost $':>10}{'seconds':>10}")
    for name, a in summary["agents"].items():
        print(f"{name:14}{a['steps']:>7}{a['tokens']:>10}{a['cost_usd']:>10.4f}{a['seconds']:>10.1f}")
    print(f"{'total':14}{'':>7}{summary['tokens']:>10}{summary['cost_usd']:>10.4f}{summary['seconds']:>10.1f} (wall)")
    for f in summary["known_failures"]:
        print(f"  known failure: {f}")
    if "spec_vs_golden" in summary:
        print("\nSpec vs golden (eval/spec_compare.py)\n" + spec_compare.show(summary["spec_vs_golden"]))
    print(f"Files: {state.workspace}")
    return summary


# ---------- command line ----------

def use_stubs() -> None:
    """Offline: every agent replays the golden clinic (no model calls)."""
    O.AGENTS.update(requirements=stubs.requirements, architect=stubs.architect,
                    coder=stubs.coder, tester=stubs.tester)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Run the whole pipeline in the terminal.")
    p.add_argument("prompt", nargs="?", help="what you want built (you answer the questions here)")
    p.add_argument("--golden", metavar="NAME", help="run a golden example, e.g. clinic (no questions asked)")
    p.add_argument("--stub", action="store_true", help="stub agents: offline, no model calls")
    p.add_argument("--serve", action="store_true", help="keep the API running at the end (Ctrl+C stops it)")
    p.add_argument("--no-serve", action="store_true", help="don't start the API at the end")
    args = p.parse_args(argv)
    if bool(args.prompt) == bool(args.golden):
        p.error("give either a prompt or --golden NAME")
    if args.golden and not (ROOT / "golden" / args.golden / "chat.json").exists():
        p.error(f"no golden example called {args.golden}")
    if args.stub:
        use_stubs()

    if args.golden:
        answer = golden_answers(args.golden)
        first, auto, name = answer(""), True, f"golden-{args.golden}"
    else:
        first, answer, auto, name = args.prompt, ask_terminal, False, "cli"
    workspace = ROOT / "workspace" / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}"
    serve = "no" if args.no_serve else "keep" if args.serve else "check"

    start = time.time()
    try:
        state = asyncio.run(run(first, answer, auto, workspace, serve))
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130
    summary = report(state, time.time() - start, args.golden)
    (workspace / "summary.json").write_text(json.dumps(summary, indent=1))
    return 0 if state.build_ok and state.tests_ok else 1


if __name__ == "__main__":
    sys.exit(main())
