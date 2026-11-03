"""Run the agents for real: chat -> requirements -> spec -> approve/change -> build.

    .venv/bin/python run.py                      # start from scratch
    .venv/bin/python run.py project_state.json   # skip to building a saved, approved spec
    .venv/bin/python run.py --serve <workspace>  # start an already built API
"""
import itertools
import json
import pathlib
import sys
import threading
import time
from contextlib import contextmanager

from agents import architect, orchestrator, requirements
from core.llm import get_llm
from core.state import Message, ProjectState


@contextmanager
def spinner(text: str):
    """Show an animated spinner with elapsed seconds while the block runs."""
    stop = threading.Event()

    def spin():
        start = time.time()
        for frame in itertools.cycle("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"):
            print(f"\r{frame} {text} {time.time() - start:.0f}s ", end="", flush=True)
            if stop.wait(0.1):
                break
        print("\r\033[K", end="", flush=True)  # clear the spinner line

    thread = threading.Thread(target=spin, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()


def ask(prompt: str) -> str:
    """input() that re-asks on blank answers."""
    while not (answer := input(prompt).strip()):
        pass
    return answer


STEP_LABELS = {"write_file": "Writing code", "write_files": "Writing the project files", "read_file": "Reading code",
               "list_files": "Looking at files", "run_checks": "Checking in the sandbox", "finish": "Wrapping up",
               "invalid": "Retrying (garbled reply)", "contract": "Tester", "write_test": "Writing tests",
               "read_test": "Reading tests", "run_tests": "Running tests", "verdict": "Test result",
               "restored": "Restored"}


def build(state: ProjectState, llm) -> ProjectState:
    print("Building your API. You'll see each step as it happens.\n")
    count = itertools.count(1)

    def show(entry):  # print above the spinner line
        if entry.action == "done":
            return
        who = "tester" if entry.agent == "tester" else "coder"
        print(f"\r\033[K  {next(count):2}. [{who}] {STEP_LABELS.get(entry.action, entry.action)}: {entry.detail[:80]}")

    with spinner("Working..."):
        state = orchestrator.build(state, llm, on_step=show)
    if state.build_ok:
        n = len(state.spec.endpoints)
        print(f"\nDone! Your API is built: {n} endpoints for {state.spec.project_name}.")
        if state.tests_ok:
            print(f"Tests: {state.test_summary}")
        else:
            print(f"Known problems the coder couldn't fix ({state.test_summary}):\n{state.test_report}")
        print(f"Code: {state.workspace}")
    else:
        print(f"\nI couldn't get it fully working. {state.logs[-1].detail}")
    return state


def free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def try_it(state: ProjectState):
    """Offer to start the built API in the sandbox and open its interactive docs."""
    import webbrowser
    from core import sandbox
    if input("\nStart it now so you can try it? (y/n): ").strip().lower() not in ("y", "yes"):
        print(f"OK. Run it later with: .venv/bin/python run.py --serve {state.workspace}")
        return
    port = free_port()
    proc = sandbox.serve(state.workspace, port)
    with spinner("Starting your API..."):
        ready = sandbox.wait_ready(proc, port)
    if not ready:
        err = proc.stderr.read()[-500:] if proc.poll() is not None else "timed out"
        print(f"It didn't start: {err}")
        sandbox.stop(proc, port)
        return
    url = f"http://127.0.0.1:{port}/docs"
    print(f"\nYour API is live at {url}")
    print("When trying endpoints, set the headers X-Role (user or admin) and X-User-Id (e.g. 1).")
    print("Press Ctrl+C to stop it.")
    webbrowser.open(url)
    try:
        proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        sandbox.stop(proc, port)
        print("\nStopped.")


def save(state: ProjectState):
    open("project_state.json", "w").write(state.model_dump_json(indent=2))
    if state.workspace:  # also where the web UI looks for projects
        data = {"state": state.model_dump(mode="json"), "revisions": []}
        (pathlib.Path(state.workspace) / "state.json").write_text(json.dumps(data, indent=1))


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--serve":
        try_it(ProjectState(workspace=sys.argv[2]))
        return
    llm = get_llm()
    if len(sys.argv) > 1:  # resume from a saved, approved spec
        state = ProjectState.model_validate_json(open(sys.argv[1]).read())
        state = build(state, llm)
        save(state)
        print(f"Model: {llm.model}. Tokens used: {llm.tokens}")
        if state.build_ok:
            try_it(state)
        return
    state = ProjectState()

    with spinner("Thinking..."):
        state = requirements.run(state, llm)
    while state.requirements is None:
        print(f"\nAssistant: {state.chat[-1].content}")
        state.chat.append(Message(role="user", content=ask("\nYou: ")))
        with spinner("Thinking..."):
            state = requirements.run(state, llm)
    print(f"\nAssistant: {state.chat[-1].content}\n")

    with spinner("Designing your API..."):
        state = architect.run(state, llm)
    while True:
        print("\nData:")
        for e in state.spec.entities:
            print(f"  {e.name}: {', '.join(f.name for f in e.fields)}")
        print("\nEndpoints:")
        for ep in state.spec.endpoints:
            print(f"  {ep.method:6} {ep.path:28} {ep.summary} [{ep.access}]")
        answer = ask("\nApprove? (y / or type a change): ")
        if answer.lower() in ("y", "yes"):
            state.spec_approved = True
            break
        state.change_request = answer
        with spinner("Updating the design..."):
            state = architect.run(state, llm)

    save(state)
    print(f"\nApproved. {len(state.tasks)} build tasks. Saved project_state.json.\n")
    state = build(state, llm)
    save(state)
    print(f"Model: {llm.model}. Tokens used: {llm.tokens}")
    if state.build_ok:
        try_it(state)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nBye.")
    except Exception as e:  # show a readable message instead of a traceback
        print(f"\nSomething went wrong: {type(e).__name__}: {str(e)[:300]}")
        sys.exit(1)
