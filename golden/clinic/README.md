# Golden example: Clinic Appointments

Hand-written reference everyone builds against.

- `chat.json`: user ↔ requirements agent conversation (`list[core.state.Message]`)
- `requirements.json`: requirements summary (`core.spec.Requirements`)
- `spec.json`: API spec (`core.spec.Spec`)
- `app/main.py`: FastAPI implementation of the spec (auth via `X-Role: user|admin` header)
- `tests/test_api.py`: tests for the app and the contracts

Run from repo root: `.venv/bin/python -m pytest golden/clinic -q`
