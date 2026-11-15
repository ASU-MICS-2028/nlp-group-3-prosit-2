"""Collect every run's step log into two CSV files for the evaluation (handover to Role 4).

    python -m eval.export_logs                        reads workspace/, writes results/runs.csv and results/steps.csv
    python -m eval.export_logs --workspace DIR --out DIR --reference golden/clinic/spec.json

A run is any folder with a steps.jsonl or state.json:
  - run.py runs        workspace/<name>-<time>/          (state.json, steps.jsonl, summary.json)
  - web app projects   workspace/<session>/<project>/    (state.json holds {"state", "revisions"})

runs.csv has one row per run, steps.csv one row per agent step. eval/README.md explains every column.
"""
import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from core.spec import Spec
from core.state import LogEntry, ProjectState
from eval import spec_compare

ROOT = Path(__file__).resolve().parent.parent
AGENTS = ("requirements", "architect", "coder", "tester", "single")
DETAIL_CHARS = 300


def find_runs(workspace: Path) -> list[Path]:
    found = {p.parent for name in ("steps.jsonl", "state.json") for p in workspace.rglob(name)}
    return sorted(d for d in found if "_published" not in d.parts and not {"app", "tests"} & set(d.parts[-1:]))


def load_run(d: Path) -> tuple[ProjectState | None, list[LogEntry], dict]:
    """The run's state (if saved), its steps, and run.py's summary.json (if any)."""
    state = None
    if (d / "state.json").exists():
        data = json.loads((d / "state.json").read_text())
        state = ProjectState.model_validate(data.get("state", data))   # web app wraps it in {"state": ...}
    steps = []
    if (d / "steps.jsonl").exists():
        steps = [LogEntry.model_validate_json(line) for line in (d / "steps.jsonl").read_text().splitlines() if line]
    elif state:
        steps = state.logs
    summary = json.loads((d / "summary.json").read_text()) if (d / "summary.json").exists() else {}
    return state, steps, summary


def count_tests(summary: str) -> tuple[int, int]:
    """'1 failed, 87 passed in 1.28s' -> (87, 1). Errors count as failures."""
    n = {k: int(v) for v, k in re.findall(r"(\d+) (passed|failed|error)", summary or "")}
    return n.get("passed", 0), n.get("failed", 0) + n.get("error", 0)


def reference_for(d: Path, default: Path | None) -> Path | None:
    """--reference if given; otherwise golden/<name>/spec.json for a run.py run named golden-<name>-<time>."""
    if default:
        return default
    m = re.match(r"golden-(.+)-\d{8}-\d{6}$", d.name)
    ref = ROOT / "golden" / m.group(1) / "spec.json" if m else None
    return ref if ref and ref.exists() else None


def run_row(d: Path, workspace: Path, reference: Path | None) -> tuple[dict, list[dict]]:
    state, steps, summary = load_run(d)
    run = d.relative_to(workspace).as_posix()
    per = defaultdict(lambda: [0, 0.0, 0.0])
    for s in steps:
        per[s.agent][0] += s.tokens
        per[s.agent][1] += s.cost_usd
        per[s.agent][2] += s.seconds
    tokens = sum(v[0] for v in per.values())
    test_summary = state.test_summary if state else summary.get("test_summary", "")
    passed, failed = count_tests(test_summary)
    row = {
        "run": run,
        "source": "cli" if (d / "summary.json").exists() else "web",
        "mode": "single" if any(s.agent == "single" for s in steps) else "multi",
        "model": summary.get("model", ""),
        "stub": tokens == 0,   # no tokens at all: the stub agents replayed the golden example
        "project": state.spec.project_name if state and state.spec else (state.requirements.project_name
                                                                        if state and state.requirements else ""),
        "build_ok": state.build_ok if state else summary.get("build_ok", ""),
        "tests_ok": state.tests_ok if state else summary.get("tests_ok", ""),
        "tests_passed": passed,
        "tests_failed": failed,
        "known_failures": len(state.failures) if state else len(summary.get("known_failures", [])),
        "fix_rounds": sum(s.action == "fix_round" for s in steps),
        "restored": sum(s.action == "restored" for s in steps),
        "chat_turns": sum(m.role == "user" for m in state.chat) if state else summary.get("chat_turns", ""),
        "questions": sum(s.agent == "requirements" and s.action == "ask" for s in steps),
        "change_requests": sum(s.agent == "architect" and s.action == "change" for s in steps),
        "mid_build_stops": sum(s.agent == "orchestrator" and s.action == "change" for s in steps),
        "entities": len(state.spec.entities) if state and state.spec else "",
        "endpoints": len(state.spec.endpoints) if state and state.spec else "",
        "steps": len(steps),
        "tokens": tokens,
        "cost_usd": round(sum(v[1] for v in per.values()), 4),
        "agent_seconds": round(sum(v[2] for v in per.values()), 1),
        "wall_seconds": summary.get("seconds", ""),
    }
    for agent in AGENTS:
        t, c, sec = per.get(agent, (0, 0.0, 0.0))
        row.update({f"{agent}_tokens": t, f"{agent}_cost_usd": round(c, 4), f"{agent}_seconds": round(sec, 1)})
    ref = reference_for(d, reference)
    if ref and state and state.spec:
        result = spec_compare.compare(state.spec, Spec.model_validate_json(ref.read_text()))
        row.update({"spec_reference": ref.relative_to(ROOT).as_posix() if ref.is_relative_to(ROOT) else str(ref),
                    **{f"spec_{k}": v for k, v in spec_compare.flat(result).items()}})
    step_rows = [{"run": run, "n": i, "agent": s.agent, "action": s.action,
                  "detail": s.detail.replace("\n", " ")[:DETAIL_CHARS],
                  "tokens": s.tokens, "cost_usd": s.cost_usd, "seconds": s.seconds}
                 for i, s in enumerate(steps, 1)]
    return row, step_rows


def write_csv(path: Path, rows: list[dict]) -> None:
    columns = list(dict.fromkeys(k for r in rows for k in r))   # runs without a reference leave spec_* empty
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


def export(workspace: Path, out: Path, reference: Path | None = None) -> tuple[int, int]:
    runs, steps = [], []
    for d in find_runs(workspace):
        try:
            row, step_rows = run_row(d, workspace, reference)
        except (ValueError, OSError) as e:   # a half-written or old-format run: skip it, say so
            print(f"skipped {d}: {type(e).__name__}: {str(e)[:120]}", file=sys.stderr)
            continue
        runs.append(row)
        steps += step_rows
    write_csv(out / "runs.csv", runs)
    write_csv(out / "steps.csv", steps)
    return len(runs), len(steps)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Export every run's logs to CSV for the evaluation.")
    p.add_argument("--workspace", default=str(ROOT / "workspace"), help="where the runs are (default: workspace/)")
    p.add_argument("--out", default=str(ROOT / "results"), help="where to write runs.csv and steps.csv")
    p.add_argument("--reference", help="compare every run's spec with this spec.json (default: golden runs only)")
    args = p.parse_args(argv)
    n_runs, n_steps = export(Path(args.workspace), Path(args.out), Path(args.reference) if args.reference else None)
    print(f"{n_runs} runs, {n_steps} steps -> {args.out}/runs.csv, {args.out}/steps.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
