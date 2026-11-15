"""Try a search from the terminal:  python -m rag "unique email 409" """
import sys

from rag.library import as_text, load_chunks, search

query = " ".join(sys.argv[1:])
if not query:
    chunks = load_chunks()
    print(f"{len(chunks)} chunks: {sum(c.is_pattern for c in chunks)} from our patterns, "
          f"{sum(not c.is_pattern for c in chunks)} from the FastAPI docs.")
    sys.exit('Usage: python -m rag "unique email 409"')
results = search(query)
print("\n".join(f"{score:.2f}  {chunk.title}  ({chunk.source})" for score, chunk in results), end="\n\n")
print(as_text(query, results))
