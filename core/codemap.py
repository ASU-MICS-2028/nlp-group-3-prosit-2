"""Static map of a generated project: which module imports which, and the routes each router serves.

Read with ast, never imported, so it is safe on code that doesn't run. Feeds the UI's Map view.
"""
import ast
import pathlib

METHODS = {"get", "post", "put", "patch", "delete"}


def _layer(rel: pathlib.Path) -> str:
    if rel.parts == ("app", "main.py"):
        return "entry"
    if len(rel.parts) > 2 and rel.parts[1] in ("routers", "services", "schemas"):
        return rel.parts[1]
    return "core"


def _routes(tree: ast.Module) -> list[dict]:
    prefix = ""
    for n in ast.walk(tree):  # APIRouter(prefix="/x")
        if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == "APIRouter":
            for kw in n.keywords:
                if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                    prefix = kw.value.value
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in n.decorator_list:
            if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in METHODS
                    and d.args and isinstance(d.args[0], ast.Constant)):
                out.append({"method": d.func.attr.upper(), "path": (prefix + d.args[0].value) or "/",
                            "line": n.lineno})
    return out


def code_map(ws: pathlib.Path) -> dict:
    files = {p for p in (ws / "app").rglob("*.py") if "__pycache__" not in p.parts and p.name != "__init__.py"}
    mods = {".".join(p.relative_to(ws).with_suffix("").parts): p for p in files}
    nodes, edges = [], set()
    for mod, p in sorted(mods.items()):
        rel = p.relative_to(ws)
        try:
            tree = ast.parse(p.read_text(errors="replace"))
        except SyntaxError:
            tree = ast.Module(body=[], type_ignores=[])
        pkg = mod.rsplit(".", 1)[0]
        for n in ast.walk(tree):
            targets = []
            if isinstance(n, ast.Import):
                targets = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                base = n.module or ""
                if n.level:  # relative import
                    base = ".".join(pkg.split(".")[: len(pkg.split(".")) - n.level + 1] + ([base] if base else []))
                # `from app.routers import food_entries` imports a module; `from app.x import name` imports from one
                targets = [f"{base}.{a.name}" if f"{base}.{a.name}" in mods else base for a in n.names]
            edges.update((mod, t) for t in targets if t in mods and t != mod)
        doc = (ast.get_docstring(tree) or "").strip().splitlines()
        nodes.append({"id": mod, "file": str(rel), "name": p.stem, "layer": _layer(rel),
                      "doc": doc[0] if doc else "", "routes": _routes(tree)})
    return {"nodes": nodes, "edges": [{"from": a, "to": b} for a, b in sorted(edges)]}
