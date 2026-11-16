import os

# Generated code runs as a local process in the tests; the Docker sandbox has its own tests (test_sandbox.py).
os.environ.setdefault("SANDBOX", "local")
