"""Evaluation (Role 4): build every benchmark scenario, judge it with the hidden tests, save a CSV.

    python -m eval.run --label team                      # the full team on all scenarios
    python -m eval.run --label no-tester --system coder  # the Coder alone: no Tester, no fix rounds
    RAG=off python -m eval.run --label no-rag            # same team, search_patterns switched off
    LLM_MODEL=claude-sonnet-5-5 python -m eval.run --label sonnet
    python -m eval.run --label team --scenarios 05-shop 16-hotel --repeat 3
    python -m eval.run --label single --system single    # one agent, same spec, same tools and budget
    python -m eval.run --label team --fuzz               # also fuzz each build with Schemathesis (crashes)
    python -m eval.run --summary                         # print the table from the CSV, run nothing

One row is written per build, as soon as it finishes, so a run that stops half-way loses nothing
and running the same label again skips what is already there.

What is measured, per build:
  hidden_score   hidden tests passed / hidden tests run: the quality of what was built. No agent
                 sees these tests (see benchmark/). all_passed = every hidden test passed.
  build_ok       the Coder's own checks passed (the app starts and serves every endpoint)
  tests_ok       the Tester's verdict on the final code (empty when there was no Tester)
  fix_rounds     how many times the Tester sent the Coder back
  tokens, cost_usd, seconds   what the build cost, summed over every agent step
  hidden_contract / hidden_generic / hidden_rules   the score per kind of hidden test: the spec's
                 contract (routes, auth), generic behaviour (CRUD, 404/409/422), business rules
  false_ok       the system said its own tests pass (tests_ok) but the hidden tests found bugs:
                 how far to trust the system's own "done"
  searches       search_patterns calls (RAG use); crashes: endpoints Schemathesis crashed (--fuzz)

Each build starts from the scenario's reference spec, already approved: this measures the Coder
and Tester, not the Requirements agent or the Architect. THIS MAKES REAL MODEL CALLS.
"""
import argparse
import asyncio
import csv
import os
import shutil
import time
from pathlib import Path

import benchmark
from agents import orchestrator
from core import sdk
from core.state import ProjectState

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "eval" / "results" / "results.csv"
WORKSPACES = ROOT / "workspace" / "_eval"     # workspace/ is gitignored
COLUMNS = ["label", "system", "model", "rag", "scenario", "run", "build_ok", "tests_ok", "tester_tests", "fix_rounds",
           "hidden_passed", "hidden_total", "hidden_score", "all_passed", "hidden_contract", "hidden_generic",
           "hidden_rules", "false_ok", "searches", "crashes", "tokens", "cost_usd", "seconds",
           "coder_tokens", "tester_tokens", "single_tokens", "failed", "error"]
FUZZ = False   # --fuzz: also run Schemathesis on every build (no model calls, but slower)


async def no_events(event) -> None:
    pass


# ---------- the systems that can be compared ----------

async def team(state: ProjectState) -> ProjectState:
    """The full pipeline after approval: Coder -> Tester -> fix rounds."""
    return await orchestrator.build(state, no_events)


async def coder_only(state: ProjectState) -> ProjectState:
    """No Tester and no fix rounds: what the Coder builds on its own."""
    state.tasks = orchestrator.plan_tasks(state.spec)
    state = await orchestrator.AGENTS["coder"](state, no_events)
    orchestrator.write_log(state)
    return state


async def single_agent(state: ProjectState) -> ProjectState:
    """One agent, the same approved spec, the team's tools and total budget (agents/single.run_spec)."""
    state = await orchestrator.AGENTS["single"](state, no_events)
    orchestrator.write_log(state)
    return state


SYSTEMS = {"team": team, "coder": coder_only, "single": single_agent}


def category_score(results: list[dict], file: str) -> str:
    """Score of one hidden test file, e.g. 0.875; empty when the file had no tests."""
    mine = [r for r in results if r["file"] == f"tests/{file}" and r["outcome"] in ("passed", "failed", "error")]
    return round(sum(r["outcome"] == "passed" for r in mine) / len(mine), 4) if mine else ""


# ---------- one build ----------

async def run_one(scenario: benchmark.Scenario, system: str, label: str, run: int) -> dict:
    """Build one scenario in its own folder and judge it. Never raises: an error becomes a row."""
    ws = WORKSPACES / label / f"{scenario.name}-{run}"
    shutil.rmtree(ws, ignore_errors=True)
    ws.mkdir(parents=True)
    row = dict.fromkeys(COLUMNS, "")
    row.update(label=label, system=system, model=sdk.MODEL, rag=os.getenv("RAG", "on"), scenario=scenario.name, run=run)
    state = ProjectState(spec=scenario.spec, spec_approved=True, workspace=str(ws))
    start = time.time()
    try:
        state = await SYSTEMS[system](state)
        verdict = await benchmark.judge(scenario, ws / "app")
    except Exception as e:                     # e.g. the model could not be reached
        row.update(error=f"{type(e).__name__}: {e}"[:300], seconds=round(time.time() - start, 1))
        return row

    def total(field: str, agent: str | None = None) -> float:
        return sum(getattr(log, field) for log in state.logs if agent in (None, log.agent))

    not_passed = [r["name"] for r in verdict["results"] if r["outcome"] in ("failed", "error")]
    all_passed = verdict["total"] > 0 and verdict["passed"] == verdict["total"]
    crashes = ""
    if FUZZ and state.build_ok:
        from agents import schema_check
        crashes = len((await schema_check.check(ws / "app"))["crashes"])
    row.update(
        hidden_contract=category_score(verdict["results"], "test_contract.py"),
        hidden_generic=category_score(verdict["results"], "test_hidden_generic.py"),
        hidden_rules=category_score(verdict["results"], "test_hidden_rules.py"),
        false_ok=bool(state.tests_ok) and not all_passed,
        searches=sum(log.action == "search_patterns" for log in state.logs), crashes=crashes,
        single_tokens=int(total("tokens", "single")),
        build_ok=state.build_ok, tests_ok="" if state.tests_ok is None else state.tests_ok,
        tester_tests=len(state.test_results), fix_rounds=sum(log.action == "fix_round" for log in state.logs),
        hidden_passed=verdict["passed"], hidden_total=verdict["total"], hidden_score=round(verdict["score"], 4),
        all_passed=all_passed,
        tokens=int(total("tokens")), cost_usd=round(total("cost_usd"), 4), seconds=round(time.time() - start, 1),
        coder_tokens=int(total("tokens", "coder")), tester_tokens=int(total("tokens", "tester")),
        # No test ran at all (e.g. the app cannot even be imported): a score of 0, not an error to retry.
        failed="; ".join(not_passed)[:1000] if verdict["total"] else "no hidden test could run: " + verdict["summary"][:200])
    return row


# ---------- the CSV ----------

def read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def append(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        if new:
            writer.writeheader()
        writer.writerow(row)


async def run_all(label: str, system: str, names: list[str], repeat: int, parallel: int, path: Path) -> list[dict]:
    """Run every (scenario, run) for this label that the CSV does not have yet, `parallel` at a time."""
    done = {(r["scenario"], int(r["run"])) for r in read(path) if r["label"] == label and not r["error"]}
    todo = [(s, n) for s in benchmark.scenarios() if not names or s.name in names
            for n in range(1, repeat + 1) if (s.name, n) not in done]
    limit, rows = asyncio.Semaphore(parallel), []

    async def one(scenario: benchmark.Scenario, n: int) -> None:
        async with limit:
            row = await run_one(scenario, system, label, n)
        append(path, row)
        rows.append(row)
        print(f"{scenario.name} #{n}: " + (row["error"] or f"hidden {row['hidden_passed']}/{row['hidden_total']}, "
              f"{row['fix_rounds']} fix rounds, {row['tokens']:,} tokens, {row['seconds']}s"), flush=True)

    print(f"{label}: {len(todo)} builds to run ({len(done)} already in {path.name}), model {sdk.MODEL}", flush=True)
    await asyncio.gather(*(one(s, n) for s, n in todo))
    return rows


# ---------- the summary table ----------

def summary(rows: list[dict]) -> list[dict]:
    """One line per label: how many builds, how good, how expensive."""
    table = []
    for label in dict.fromkeys(r["label"] for r in rows):
        mine = [r for r in rows if r["label"] == label and not r["error"]]
        if not mine:
            continue
        n = len(mine)
        table.append({
            "label": label, "model": mine[0]["model"], "builds": n,
            "all_passed": sum(r["all_passed"] in (True, "True") for r in mine),
            "hidden_score": round(sum(float(r["hidden_score"]) for r in mine) / n, 3),
            **{k: avg(mine, k) for k in ("hidden_contract", "hidden_generic", "hidden_rules")},
            "false_ok": sum(r.get("false_ok") in (True, "True") for r in mine),
            "searches": round(sum(int(r.get("searches") or 0) for r in mine) / n, 1),
            "crashes": avg(mine, "crashes"),
            "fix_rounds": sum(int(r["fix_rounds"]) for r in mine),
            "tokens_per_build": round(sum(int(r["tokens"]) for r in mine) / n),
            "cost_usd": round(sum(float(r["cost_usd"]) for r in mine), 2),
            "seconds_per_build": round(sum(float(r["seconds"]) for r in mine) / n),
        })
    return table


def avg(rows: list[dict], key: str):
    values = [float(r[key]) for r in rows if r.get(key) not in (None, "")]
    return round(sum(values) / len(values), 3) if values else ""


def as_text(table: list[dict]) -> str:
    if not table:
        return "No results yet."
    widths = {k: max(len(k), *(len(str(row[k])) for row in table)) for k in table[0]}
    lines = ["  ".join(k.ljust(widths[k]) for k in table[0])]
    lines += ["  ".join(str(row[k]).ljust(widths[k]) for k in row) for row in table]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the benchmark and save the results to a CSV.")
    parser.add_argument("--label", help="a name for this configuration, e.g. team, no-tester, no-rag, sonnet")
    parser.add_argument("--system", choices=list(SYSTEMS), default="team")
    parser.add_argument("--scenarios", nargs="*", default=[], help="scenario folder names; default: all")
    parser.add_argument("--repeat", type=int, default=1, help="builds per scenario (models are not deterministic)")
    parser.add_argument("--parallel", type=int, default=3)
    parser.add_argument("--out", type=Path, default=RESULTS)
    parser.add_argument("--summary", action="store_true", help="only print the table from the CSV")
    parser.add_argument("--fuzz", action="store_true", help="also fuzz each build with Schemathesis (count crashes)")
    args = parser.parse_args()
    global FUZZ
    FUZZ = args.fuzz
    if not args.summary:
        if not args.label:
            parser.error("--label is required to run builds")
        asyncio.run(run_all(args.label, args.system, args.scenarios, args.repeat, args.parallel, args.out))
    print("\n" + as_text(summary(read(args.out))))


if __name__ == "__main__":
    main()
