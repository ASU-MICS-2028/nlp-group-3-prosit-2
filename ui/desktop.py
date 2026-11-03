"""Desktop app: the same UI in a native window (pywebview), no browser.

    .venv/bin/python -m ui.desktop
    .venv/bin/python -m ui.make_app      # macOS: build "Prosit Builder.app" for the Dock / Launchpad
"""
import pathlib
import socket
import sys
import threading
import time

import uvicorn
import webview

from ui import server

ICON = pathlib.Path(__file__).resolve().parent / "static" / "icon.png"


def _mac_branding():
    """Dock icon and menu-bar name when run straight from Python (the .app bundle sets these too)."""
    try:
        from AppKit import NSApplication, NSImage
        from Foundation import NSBundle
    except ImportError:
        return
    info = NSBundle.mainBundle().localizedInfoDictionary() or NSBundle.mainBundle().infoDictionary()
    if info is not None:
        info["CFBundleName"] = "Prosit Builder"
    NSApplication.sharedApplication().setApplicationIconImage_(NSImage.alloc().initWithContentsOfFile_(str(ICON)))


def main():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    while not srv.started:
        time.sleep(0.05)

    webview.settings["ALLOW_DOWNLOADS"] = True  # "Download code" saves the zip via a native dialog
    webview.create_window("Prosit Builder", f"http://127.0.0.1:{port}/?desktop=1",
                          width=1480, height=920, min_size=(1000, 640))
    if sys.platform == "darwin":
        _mac_branding()
    webview.start(icon=str(ICON))  # icon= is used on Linux (GTK/Qt); blocks until the window closes

    server._stop_server()  # don't leave the generated API's container running
    srv.should_exit = True
    thread.join(timeout=5)


if __name__ == "__main__":
    main()
