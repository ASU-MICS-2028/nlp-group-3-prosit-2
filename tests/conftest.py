import os

# The existing tests describe the multi-agent flow; tests of the single-agent flow set PIPELINE=solo themselves.
os.environ.setdefault("PIPELINE", "team")
