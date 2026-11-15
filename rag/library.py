"""RAG for the Coder (Role 4): find the pattern or doc section that answers a question.

RAG = Retrieval-Augmented Generation. Instead of hoping the model remembers how we build APIs,
the Coder calls search_patterns("unique email 409") and gets our own worked example back, then
writes code from it. How it works, step by step:

  1. Library. rag/patterns/*.md are patterns we wrote for our stack (FastAPI + sqlite3, our
     layout, our auth headers, our status codes). rag/docs/*.md are pages of the FastAPI docs.
  2. Chunk. Each file is cut into sections at its headings, so one chunk = one idea with its code.
  3. Embed. Each chunk becomes a vector with one number per word: TF-IDF. A word counts for more
     when it is frequent in this chunk (TF) and rare in the library (IDF).
  4. Retrieve. The query is embedded the same way; chunks are ranked by cosine similarity (the
     angle between the two vectors) and the top few go back to the model as the tool result.

Why TF-IDF and not a neural embedding model: the library is small and full of exact names
(HTTPException, lastrowid, 409), which word matching finds reliably; it needs no download, no
API key and no network; and the same query always gives the same answer, so it can be tested
(tests/test_rag.py). ponytail: swap embed() for a sentence-embedding model if the library
outgrows word matching (queries that share no words with the right chunk).
"""
import math
import os
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

HERE = Path(__file__).parent
TOP_K = 3              # chunks returned per search
MAX_CHARS = 1800       # a doc section longer than this is cut into smaller chunks
MIN_SCORE = 0.08       # below this nothing in the library is really about the query
PATTERN_BOOST = 1.3    # our own patterns follow our conventions; the FastAPI docs are general
TITLE_WEIGHT = 3       # a word in the heading says more about a chunk than a word in its body

STOPWORDS = set("a an and are as at be but by can do does for from has have how i if in into is it its my no not of "
                "on or so than that the then there this to up use used using was we what when which who why will "
                "with you your".split())


@dataclass(frozen=True)
class Chunk:
    source: str   # "patterns/crud.md" or "docs/tutorial-handling-errors.md"
    title: str    # "Endpoints > Delete a record: 204 with no body"
    text: str     # the section's Markdown, code included

    @property
    def is_pattern(self) -> bool:
        return self.source.startswith("patterns/")


# ---------- step 2: chunk ----------

def blocks(markdown: str) -> list[str]:
    """Cut Markdown into paragraphs and whole code blocks (a code block is never cut in two)."""
    out, current, in_code = [], [], False
    for line in markdown.splitlines():
        fence = line.startswith("```")
        if fence and not in_code and current:          # a code block starts: close the paragraph before it
            out.append("\n".join(current))
            current = []
        current.append(line)
        if fence:
            in_code = not in_code
        if (fence and not in_code) or (not in_code and not line.strip()):   # a code block or paragraph ended
            out.append("\n".join(current))
            current = []
    if current:
        out.append("\n".join(current))
    return [b for b in out if b.strip()]


def sections(markdown: str, levels: int) -> list[tuple[str, str]]:
    """Cut a file at its headings: [(title, body), ...]. `levels`=2 cuts at "## " only, 3 also at "### ".
    The title is the path of headings, e.g. "Lifespan Events > Use Case".
    A "#" inside a code block is a Python comment, not a heading, so code blocks are tracked."""
    path, body, out, in_code = ["", "", ""], [], [], False   # the current "# ", "## " and "### " headings
    for line in markdown.splitlines() + ["## end"]:          # the extra heading closes the last section
        if line.startswith("```"):
            in_code = not in_code
        found = None if in_code else re.match(r"(#{1,3}) (.+)", line)
        if found and len(found.group(1)) <= levels:
            out.append((" > ".join(t for t in path if t), "\n".join(body)))
            level, body = len(found.group(1)), []
            path[level - 1:] = [found.group(2).strip()] + [""] * (3 - level)
        elif not line.startswith("<!--"):
            body.append(line)
    return out


def chunk_file(source: str, markdown: str, levels: int, max_chars: Optional[int]) -> list[Chunk]:
    """One chunk per section; a section longer than max_chars becomes several chunks with the same title."""
    chunks = []
    for title, body in sections(markdown, levels):
        pieces, size = [[]], 0
        for block in blocks(body):                      # pack whole blocks into pieces of at most max_chars
            if max_chars and pieces[-1] and size + len(block) > max_chars:
                pieces.append([])
                size = 0
            pieces[-1].append(block.strip("\n"))
            size += len(block)
        for piece in pieces:
            text = "\n\n".join(piece)
            if len(text) > 80:                          # skip empty sections and one-line leftovers
                chunks.append(Chunk(source, title, text))
    return chunks


@lru_cache(maxsize=1)
def load_chunks() -> tuple[Chunk, ...]:
    chunks = []
    for path in sorted((HERE / "patterns").glob("*.md")):   # our patterns: one chunk per "## " section, never cut
        chunks += chunk_file(f"patterns/{path.name}", path.read_text(), levels=2, max_chars=None)
    for path in sorted((HERE / "docs").glob("*.md")):       # FastAPI docs: long pages, so smaller pieces
        chunks += chunk_file(f"docs/{path.name}", path.read_text(), levels=3, max_chars=MAX_CHARS)
    return tuple(c for c in chunks if "deprecated" not in c.title.lower())   # never teach the old way


# ---------- step 3: embed ----------

def stem(word: str) -> str:
    """Crude stemming so "bookings", "booked" and "booking" all match "book"."""
    if word.isdigit() or len(word) < 4:
        return word
    if word.endswith("ies"):
        word = word[:-3] + "y"
    elif word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    for suffix in ("ing", "ed"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[:-len(suffix)]
            if word[-1] == word[-2]:                    # cancell -> cancel
                word = word[:-1]
            break
    return word[:-1] if word.endswith("e") and len(word) > 3 else word   # delete -> delet, like deleted


def tokens(text: str) -> list[str]:
    """Words of a text, lower-cased and stemmed. Code names are kept whole AND split into parts:
    check_same_thread -> check_same_thread, check, same, thread; HTTPException -> httpexception, http, exception."""
    out = []
    for word in re.findall(r"[A-Za-z0-9_]+", text):
        parts = [p for p in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", word)]
        if len(parts) > 1:
            out.append(word.lower())
        out += [stem(p.lower()) for p in parts]
    return [t for t in out if t not in STOPWORDS]


def embed(words: list[str], idf: dict[str, float]) -> dict[str, float]:
    """A TF-IDF vector as {word: weight}, scaled to length 1 so a dot product is the cosine.
    Kept sparse (only the words present) because most of the vocabulary is absent from any one text."""
    counts = Counter(w for w in words if w in idf)
    vector = {w: (1 + math.log(n)) * idf[w] for w, n in counts.items()}
    length = math.sqrt(sum(x * x for x in vector.values()))
    return {w: x / length for w, x in vector.items()} if length else {}


@lru_cache(maxsize=1)
def index() -> tuple[tuple[Chunk, ...], dict[str, float], list[dict[str, float]]]:
    """Embed every chunk once (a few milliseconds). Returns (chunks, idf, one vector per chunk)."""
    chunks = load_chunks()
    words = [tokens(c.title) * TITLE_WEIGHT + tokens(c.text) for c in chunks]
    in_chunks = Counter(w for ws in words for w in set(ws))            # in how many chunks each word appears
    idf = {w: math.log((1 + len(chunks)) / (1 + n)) + 1 for w, n in in_chunks.items()}
    return chunks, idf, [embed(ws, idf) for ws in words]


# ---------- step 4: retrieve ----------

def search(query: str, k: int = TOP_K) -> list[tuple[float, Chunk]]:
    """The k chunks most similar to the query, best first, as (score, chunk). Score is 0..1 (times the boost)."""
    chunks, idf, vectors = index()
    q = embed(tokens(query), idf)
    scored = []
    for chunk, vector in zip(chunks, vectors):
        cosine = sum(weight * vector.get(word, 0.0) for word, weight in q.items())
        score = cosine * (PATTERN_BOOST if chunk.is_pattern else 1.0)
        if score >= MIN_SCORE:
            scored.append((score, chunk))
    scored.sort(key=lambda pair: -pair[0])
    best, pages = [], set()
    for score, chunk in scored:
        if chunk.source in pages:      # at most one result per docs page, so one long page
            continue                   # cannot fill every place and push our patterns out
        if not chunk.is_pattern:
            pages.add(chunk.source)
        best.append((score, chunk))
    return best[:k]


# ---------- the tool ----------

DESCRIPTION = ("Search the pattern library: worked FastAPI + sqlite3 examples written for this project "
               "(layout, database, auth headers, CRUD, business rules, fixes for common errors) and the FastAPI docs. "
               "Returns the best matching sections with code. Search before writing a kind of code for the first "
               "time, and search the error message or the failing status code when a check or test fails.")
SCHEMA = {"type": "object", "required": ["query"], "properties": {"query": {
    "type": "string",
    "description": "A few key words, e.g. 'unique email duplicate 409', 'admin only endpoint 403', "
                   "'overlapping bookings', 'sqlite3 no such table'"}}}
# A line for the Coder's system prompt. Empty when RAG is off, so the prompt never names a tool that is not there.
ENABLED = os.getenv("RAG", "on").lower() != "off"
PROMPT = ("Before you write a kind of code for the first time (database setup, auth, a CRUD router, a business "
          "rule), call search_patterns and follow the pattern it returns. When a check or test fails, search "
          "the error message or the status code before changing the code.") if ENABLED else ""


def as_text(query: str, results: list[tuple[float, Chunk]]) -> str:
    """What the model reads: the chunks, each with where it came from."""
    if not results:
        return (f"Nothing in the library matches {query!r}. Try other words: the thing you are building "
                "(e.g. 'delete endpoint 204') or the exact error message.")
    parts = []
    for n, (_, chunk) in enumerate(results, 1):
        origin = "project pattern" if chunk.is_pattern else "FastAPI docs"
        parts.append(f"=== Result {n}: {chunk.title} [{origin}: {chunk.source}] ===\n{chunk.text}")
    return "\n\n".join(parts)


def tools(on_search: Optional[Callable[[str, list], None]] = None) -> dict:
    """The search_patterns tool in the shared tool format, ready to add to an agent's tools:

        usage = await run_agent(SYSTEM, prompt, {**rag.tools(), "run_checks": ...}, workspace=ws)

    Returns {} when RAG=off (the "no RAG" comparison in the evaluation).
    `on_search(query, results)` is called on every search, e.g. to write a LogEntry."""
    if not ENABLED:
        return {}

    async def search_patterns(args: dict) -> str:
        query = str(args.get("query", "")).strip()
        if not query:
            return "Give a query: a few key words about what you need."
        results = search(query)
        if on_search:
            on_search(query, results)
        return as_text(query, results)

    return {"search_patterns": (DESCRIPTION, SCHEMA, search_patterns)}
