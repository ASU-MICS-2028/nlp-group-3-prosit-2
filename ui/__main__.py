"""Start the web UI: .venv/bin/python -m ui [--port 7860] [--no-browser]"""
import sys
import threading
import webbrowser

import uvicorn

port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 7860
if "--no-browser" not in sys.argv:
    threading.Timer(1.0, webbrowser.open, args=[f"http://127.0.0.1:{port}"]).start()
uvicorn.run("ui.server:app", host="127.0.0.1", port=port, log_level="warning")
