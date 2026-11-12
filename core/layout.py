"""The standard layout of a generated project (README: "Generated APIs and SQLite").

LAYOUT        the rules, as the coding agent reads them in its prompt
check(ws, spec)   what is missing or misplaced; an empty list means the layout is right
tidy(ws)          removes files the agent emptied (it has no delete tool)
scaffold(ws, spec)  the files our code writes (spec.json, README.md, requirements.txt, Dockerfile, .gitignore)
"""
import re
from pathlib import Path

from core.spec import Spec

LAYOUT = """Project layout (required; the build is checked against it):
app/__init__.py            empty
app/main.py                creates `app = FastAPI(...)`, includes the routers, creates the tables on startup,
                           and has GET /health. No endpoint logic here.
app/database.py            DB_PATH = os.getenv("DATABASE_PATH", "/data/app.db"), get_conn() (sqlite3.Row,
                           PRAGMA foreign_keys = ON), and init_db() creating every table
app/dependencies.py        header auth: X-Role / X-User-Id -> 401 / 403
app/schemas/__init__.py    empty
app/schemas/<entity>.py    pydantic models <Entity>Create, <Entity>Update, <Entity>
app/routers/__init__.py    empty
app/routers/<entity>.py    one APIRouter per resource, thin handlers
app/services/<entity>.py   business rules, when the spec has rules for that entity
<entity> is the snake_case entity name, e.g. medical_record for MedicalRecord."""

REQUIREMENTS = "fastapi>=0.110\nuvicorn>=0.29\npydantic>=2\n"
GITIGNORE = "data/\n__pycache__/\n.pytest_cache/\n"
DOCKERFILE = """FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
ENV DATABASE_PATH=/data/app.db
VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
"""


def snake(name: str) -> str:
    """'MedicalRecord' -> 'medical_record'"""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def check(ws: Path, spec: Spec) -> list[str]:
    """Layout problems, e.g. 'app/routers/book.py is missing'. Empty means the layout is right."""
    app = ws / "app"
    need = ["__init__.py", "main.py", "database.py", "dependencies.py", "schemas/__init__.py", "routers/__init__.py"]
    for entity in sorted({e.entity for e in spec.endpoints if e.entity}):
        need += [f"schemas/{snake(entity)}.py", f"routers/{snake(entity)}.py"]
    problems = [f"app/{f} is missing" for f in need if not (app / f).is_file()]
    names = {snake(e.name) for e in spec.entities}
    for folder in ("schemas", "routers", "services"):
        for f in sorted((app / folder).glob("*.py")):
            if f.name != "__init__.py" and f.stem not in names and f.read_text().strip():
                problems.append(f"app/{folder}/{f.name}: name it after its entity ({', '.join(sorted(names))}), "
                                "then make the old file empty (empty files are removed)")
    main = (app / "main.py").read_text() if (app / "main.py").is_file() else ""
    if re.search(r"@app\.(post|put|patch|delete)\(", main):
        problems.append("app/main.py has endpoint handlers: move them to app/routers/<entity>.py "
                        "(main.py only creates the app, includes the routers and has GET /health)")
    return problems


def tidy(ws: Path) -> list[str]:
    """Remove empty .py files in app/ (an agent can't delete a file, so it empties it). Keeps __init__.py."""
    gone = [f for f in (ws / "app").rglob("*.py") if f.name != "__init__.py" and not f.read_text().strip()]
    for f in gone:
        f.unlink()
    return [str(f.relative_to(ws)) for f in gone]


def readme(spec: Spec) -> str:
    rows = "\n".join(f"| `{e.method}` | `{e.path}` | {e.summary} | {e.access} |" for e in spec.endpoints)
    rules = "\n".join(f"- {r}" for r in spec.rules) or "- None"
    return f"""# {spec.project_name}

{spec.description}

Built with [Mesora Blocks](https://mesorablocks.online): FastAPI and SQLite.

## Run it

```bash
pip install -r requirements.txt
DATABASE_PATH=./data/app.db uvicorn app.main:app --reload
```

Then open http://localhost:8000/docs. With Docker: `docker build -t api . && docker run -p 8000:8000 -v $PWD/data:/data api`.

Sign in with headers: `X-Role: user` or `X-Role: admin`, and `X-User-Id: <number>`.

## Endpoints

| Method | Path | What it does | Who |
| --- | --- | --- | --- |
{rows}

`GET /health` answers `{{"status": "ok"}}` with no sign-in.

## Rules

{rules}

## Tests

```bash
pip install pytest httpx
pytest
```
"""


def scaffold(ws: Path, spec: Spec) -> None:
    """Write the files our code owns. Rewritten after every build, so they always match the spec."""
    (ws / "spec.json").write_text(spec.model_dump_json(indent=2))
    (ws / "README.md").write_text(readme(spec))
    (ws / "requirements.txt").write_text(REQUIREMENTS)
    (ws / "Dockerfile").write_text(DOCKERFILE)
    (ws / ".gitignore").write_text(GITIGNORE)
