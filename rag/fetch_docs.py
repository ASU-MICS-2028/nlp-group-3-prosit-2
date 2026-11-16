"""Download the FastAPI doc pages we index and save them as plain Markdown in rag/docs/.

Run it only to refresh the docs (it needs the internet; searching never does):

    python -m rag.fetch_docs            # the FastAPI version in REF below
    python -m rag.fetch_docs 0.162.4    # another version (a git tag) or "master"

The pages are FastAPI's own documentation (MIT License, see rag/docs/LICENSE). In the FastAPI
repository the code samples are separate files, pulled into a page by a line such as
    {* ../../docs_src/handling_errors/tutorial001_py310.py hl[1] *}
so we download each sample and put it in the page as a normal code block.
"""
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REF = "0.162.4"   # the FastAPI version the generated APIs run on
RAW = "https://raw.githubusercontent.com/fastapi/fastapi/{ref}/{path}"
OUT = Path(__file__).parent / "docs"

# Only what a generated API needs: routes, validation, errors, dependencies, routers, startup.
# Left out on purpose: SQLModel/SQLAlchemy, OAuth2, templates, websockets, deployment.
PAGES = [
    "tutorial/first-steps", "tutorial/path-params", "tutorial/query-params", "tutorial/body",
    "tutorial/query-params-str-validations", "tutorial/path-params-numeric-validations",
    "tutorial/body-fields", "tutorial/extra-data-types", "tutorial/header-params",
    "tutorial/response-model", "tutorial/extra-models", "tutorial/response-status-code",
    "tutorial/handling-errors", "tutorial/path-operation-configuration", "tutorial/body-updates",
    "tutorial/dependencies/index", "tutorial/dependencies/dependencies-in-path-operation-decorators",
    "tutorial/dependencies/dependencies-with-yield", "tutorial/bigger-applications",
    "advanced/events", "advanced/additional-status-codes",
]

INCLUDE = re.compile(r"^\{\*\s*(\S+)(.*?)\*\}\s*$", re.M)


def get(ref: str, path: str) -> str:
    for attempt in range(3):   # the network sometimes times out; try again before giving up
        try:
            with urllib.request.urlopen(RAW.format(ref=ref, path=path), timeout=30) as r:
                return r.read().decode()
        except urllib.error.HTTPError as e:
            sys.exit(f"{path} at {ref}: {e}")   # e.g. 404: the page or the version does not exist
        except OSError as e:
            if attempt == 2:
                sys.exit(f"{path} at {ref}: {e}. Nothing was changed; run it again.")
            time.sleep(2)


def lines_wanted(options: str, code: str) -> str:
    """`ln[1:8,20:24]` means: show only these lines of the sample."""
    found = re.search(r"ln\[([\d:,\s]+)\]", options)
    if not found:
        return code.strip("\n")
    lines, parts = code.splitlines(), []
    for span in found.group(1).split(","):
        first, _, last = span.strip().partition(":")
        parts.append("\n".join(lines[int(first) - 1:int(last or first)]))
    return "\n# ...\n".join(parts)


def clean(page: str, ref: str) -> str:
    """Turn FastAPI's doc source into plain Markdown: samples inlined, site-only markup removed."""
    def include(m: re.Match) -> str:
        path = re.sub(r"^(\.\./)+", "", m.group(1))            # ../../docs_src/x.py -> docs_src/x.py
        return "```python\n" + lines_wanted(m.group(2), get(ref, path)) + "\n```"

    page = INCLUDE.sub(include, page)
    page = re.sub(r"^(#+ .*?)[ \t]*\{ #[\w-]+ \}[ \t]*$", r"\1", page, flags=re.M)   # "## Title { #title }"
    page = re.sub(r"^///\s*(\w+).*$", lambda m: f"**{m.group(1).capitalize()}:**", page, flags=re.M)  # "/// tip"
    page = re.sub(r"^///\s*$\n?", "", page, flags=re.M)                          # the closing "///"
    page = re.sub(r"\{\.[^}]*\}", "", page)                                       # {.internal-link target=_blank}
    parts = re.split(r"(```python\n.*?\n```)", page, flags=re.S)                 # leave the code samples alone
    parts[::2] = [re.sub(r"</?[a-zA-Z][^>\n]*>", "", text) for text in parts[::2]]   # html the site needs, we do not
    page = "".join(parts)
    return re.sub(r"\n{3,}", "\n\n", page).strip() + "\n"


def main(ref: str = REF) -> None:
    # Download everything first, so a failure half-way leaves rag/docs/ as it was.
    files = {"LICENSE": get(ref, "LICENSE")}
    for name in PAGES:
        source = f"docs/en/docs/{name}.md"
        text = clean(get(ref, source), ref)
        url = f"https://github.com/fastapi/fastapi/blob/{ref}/{source}"
        files[name.replace("/", "-") + ".md"] = f"<!-- FastAPI {ref} docs (MIT License): {url} -->\n{text}"
        print(f"{name}: {len(text):,} characters")
    OUT.mkdir(exist_ok=True)
    for old in OUT.glob("*.md"):
        old.unlink()
    for name, text in files.items():
        (OUT / name).write_text(text)


if __name__ == "__main__":
    main(*sys.argv[1:2])
