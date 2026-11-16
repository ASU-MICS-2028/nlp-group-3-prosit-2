# Evaluation data: run logs and spec comparison

Handover from Role 2 (orchestrator) to Role 4 (evaluation). Everything here reads the logs the pipeline already writes, so it makes no model calls and costs nothing.

## Where the logs come from

Every build writes one line per agent step to `steps.jsonl` in its project folder (`orchestrator.write_log`). There are two kinds of folder, both under `workspace/` (gitignored, so each person's runs stay on their own machine):

| Made by | Folder | Files |
| --- | --- | --- |
| `python run.py ...` | `workspace/<name>-<time>/` | `steps.jsonl`, `state.json`, `summary.json` (with the model) |
| the web app | `workspace/<session>/<project>/` | `steps.jsonl` after a build, `state.json` |

## Export to CSV

```bash
python -m eval.export_logs                                   # workspace/ -> results/runs.csv, results/steps.csv
python -m eval.export_logs --reference golden/clinic/spec.json   # compare every run's spec with this one
```

To combine runs from several machines, copy the run folders into one `workspace/` (or pass `--workspace DIR`) and export once.

### `runs.csv`: one row per run

| Column | Meaning |
| --- | --- |
| `run` | folder, relative to the workspace |
| `source` | `cli` (run.py) or `web` |
| `mode` | `multi` (the agent team) or `single` (one agent, `build_single`) |
| `model` | e.g. `claude-haiku-5-5`; `stub` for offline replays; empty for web runs (not recorded there) |
| `stub` | `True` when no tokens were used: the stub agents replayed the golden example. **Filter these out** |
| `project` | the spec's project name |
| `build_ok` | the code passed the Coder's checks (our code's verdict, not the model's) |
| `tests_ok` | every test passed |
| `tests_passed`, `tests_failed` | from the final test run (errors count as failed) |
| `known_failures` | failures still open at the end |
| `fix_rounds` | Coder ⇄ Tester rounds used (stop rule: `MAX_FIX_ROUNDS`) |
| `restored` | fix rounds that broke the build, so the last working code was put back |
| `chat_turns`, `questions` | user messages, and questions the Requirements agent asked |
| `change_requests` | specs the Architect revised on request |
| `mid_build_stops` | builds stopped by a message typed during the build |
| `entities`, `endpoints` | size of the final spec |
| `steps`, `tokens`, `cost_usd` | totals over all agents |
| `agent_seconds` | time spent inside agents; `wall_seconds` (cli only) is the whole run, including waiting |
| `<agent>_tokens`, `<agent>_cost_usd`, `<agent>_seconds` | per agent: requirements, architect, coder, tester, single |
| `spec_*` | spec vs reference, from `eval/spec_compare.py`; empty when there is no reference (see below) |

A run gets a `spec_*` comparison when it is a `run.py --golden <name>` run (compared with `golden/<name>/spec.json`), or for every run when you pass `--reference`. For benchmark scenarios, export each scenario's runs with its own `--reference`.

### `steps.csv`: one row per agent step

`run, n, agent, action, detail, tokens, cost_usd, seconds`. `detail` is cut to 300 characters on one line. Useful actions:

| Agent | Actions |
| --- | --- |
| requirements | `ask`, `summary`, `confirm` (the user said yes in the chat), `confirmed` (the "Looks right" button), `decline` |
| architect | `spec`, `change` |
| orchestrator | `build`, `plan`, `fix_round`, `restored`, `change` (mid-build stop) |
| coder | `run_checks`, `write_files`, `finish`, `gave_up` |
| tester | `write_tests`, `run_tests`, `retest` |

## Spec comparison

```bash
python -m eval.spec_compare workspace/<run>/state.json golden/clinic/spec.json [--csv results/specs.csv] [--json]
```

It compares by meaning: entities match by name or shared fields (`Booking` = `Appointment`), paths are renamed through that match, and PUT and PATCH both count as an update. The `spec_*` columns:

| Column | Meaning |
| --- | --- |
| `spec_score` | mean of the entity, field and endpoint F1 and the access agreement. A guide, not a grade |
| `spec_entities_*`, `spec_fields_*`, `spec_endpoints_*` | precision, recall, F1 per layer |
| `spec_fields_same_type`, `spec_fields_same_flags` | matched fields with the same type / same required and unique |
| `spec_access_agreement` | matched endpoints with the same access level. **The security number**: the Tester tests against the generated spec, so a wrong access level passes every test |
| `spec_request_fields` | overlap of request body fields on matched endpoints |
| `spec_rules_generated`, `spec_rules_reference` | counted only: whether two rules mean the same needs a person or a model |

Run it without `--csv` to see the list of differences (missing endpoints, access mismatches, renames).

## First result: golden clinic, Haiku, 15 Nov 2026

| Build | Tests | Fix rounds | Cost | Spec score | Access agreement |
| --- | --- | --- | --- | --- | --- |
| OK | 88 / 88 | 1 | $0.048 | 0.88 | 0.70 |

The access mismatches: `GET /appointments` open to any user (reference: admin only), and `GET /doctors` behind a login (reference: public). `GET /patients` and `GET /patients/{id}` are missing.
