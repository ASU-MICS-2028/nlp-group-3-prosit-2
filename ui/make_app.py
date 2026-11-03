"""Build "Prosit Builder.app" (macOS) so the app has its own Dock / Launchpad / Spotlight icon.

    .venv/bin/python -m ui.make_app [target_dir]     # default ~/Applications

The bundle is a thin launcher: it runs this repo's .venv python with `-m ui.desktop`.
Re-run after moving the repo.
"""
import pathlib
import plistlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
ICON = ROOT / "ui" / "static" / "icon.png"
NAME = "Prosit Builder"


def make_icns(dest: pathlib.Path):
    with tempfile.TemporaryDirectory() as tmp:
        iconset = pathlib.Path(tmp) / "icon.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                px = size * scale
                out = iconset / f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
                subprocess.run(["sips", "-z", str(px), str(px), str(ICON), "--out", str(out)],
                               check=True, capture_output=True)
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(dest)], check=True)


def main():
    if sys.platform != "darwin":
        sys.exit("macOS only. On Windows/Linux run: python -m ui.desktop (the window uses ui/static/icon.png).")
    target = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "~/Applications").expanduser()
    app = target / f"{NAME}.app"
    if app.exists():
        shutil.rmtree(app)
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "Resources").mkdir()
    make_icns(app / "Contents" / "Resources" / "icon.icns")
    plistlib.dump({
        "CFBundleName": NAME, "CFBundleDisplayName": NAME, "CFBundleIdentifier": "edu.prosit.builder",
        "CFBundleExecutable": "launch", "CFBundleIconFile": "icon", "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "0.1", "NSHighResolutionCapable": True,
    }, (app / "Contents" / "Info.plist").open("wb"))
    launcher = app / "Contents" / "MacOS" / "launch"
    # Dock launches have no shell PATH; add the usual places for docker and claude
    launcher.write_text(f'''#!/bin/bash
export PATH="/usr/local/bin:/opt/homebrew/bin:$HOME/.local/bin:$PATH"
cd "{ROOT}"
exec "{ROOT}/.venv/bin/python" -m ui.desktop
''')
    launcher.chmod(0o755)
    subprocess.run(["touch", str(app)])  # nudge Finder / Dock to pick up the icon
    print(f"Built {app}\nOpen it from Launchpad or Spotlight, then right-click its Dock icon > Options > Keep in Dock.")


if __name__ == "__main__":
    main()
