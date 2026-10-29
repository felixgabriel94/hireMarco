"""Marco as a Mac app: build it, start it at login, or take it away again.

``app/MarcoApp.swift`` is the menu-bar app that starts the booth when Logic
opens. ``build`` compiles it into ~/Applications/Marco.app, signs it for this
Mac only, and writes the repository and uv paths it runs the booth from.
``install`` adds the login item (a LaunchAgent) and opens the app;
``uninstall`` removes both. The login item is a setting on the Owner's Mac,
so install and uninstall are his to run.
"""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
from pathlib import Path

from hiremarco import config

REPO = Path(__file__).resolve().parents[3]
SOURCE = REPO / "app" / "MarcoApp.swift"
ICON = REPO / "app" / "icon.jpg"  # the tie, the Owner's avatar for Marco
APP = Path.home() / "Applications" / "Marco.app"
AGENT = Path.home() / "Library" / "LaunchAgents" / "com.hiremarco.marco.plist"
LABEL = "com.hiremarco.marco"

INFO = {
    "CFBundleIdentifier": LABEL,
    "CFBundleName": "Marco",
    "CFBundleDisplayName": "Marco",
    "CFBundleExecutable": "Marco",
    "CFBundleIconFile": "Marco",
    "CFBundlePackageType": "APPL",
    "CFBundleShortVersionString": "0.1",
    "CFBundleVersion": "1",
    "LSMinimumSystemVersion": "14.0",
    "LSUIElement": True,  # menu bar only, no Dock icon
    "NSMicrophoneUsageDescription": "Marco listens for his name and your commands while Logic is open.",
    "NSAppleEventsUsageDescription": "Marco runs Logic's key commands and reads its tracks for you.",
}


def build(app: Path = APP, source: Path = SOURCE) -> Path:
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uv is not on the PATH")
    macos = app / "Contents" / "MacOS"
    macos.mkdir(parents=True, exist_ok=True)
    (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps(INFO))
    done = subprocess.run(["swiftc", "-O", "-swift-version", "5", str(source), "-o", str(macos / "Marco")],
                          capture_output=True, text=True, timeout=300)
    if done.returncode != 0:
        raise RuntimeError(f"the app did not build: {done.stderr.strip()[-300:]}")
    make_icon(ICON, app / "Contents" / "Resources" / "Marco.icns")
    for name in ("menubar.png", "menubar@2x.png"):  # the menu bar's tie, cut from the Owner's logo
        shutil.copyfile(REPO / "app" / name, app / "Contents" / "Resources" / name)
    signed = subprocess.run(["codesign", "--force", "--sign", "-", str(app)], capture_output=True, text=True)
    if signed.returncode != 0:
        raise RuntimeError(f"the app did not sign: {signed.stderr.strip()[-200:]}")
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    (config.STATE_DIR / "app.json").write_text(json.dumps({"repo": str(REPO), "uv": uv}))
    return app


def make_icon(source: Path, target: Path) -> Path:
    """The app icon from one square picture: every size macOS asks for, packed into an .icns."""
    import tempfile

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "Marco.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                px = size * scale
                name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
                subprocess.run(["sips", "-s", "format", "png", "-z", str(px), str(px), str(source),
                                "--out", str(iconset / name)], check=True, capture_output=True)
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(target)], check=True, capture_output=True)
    return target


def agent_plist(app: Path = APP) -> bytes:
    return plistlib.dumps({"Label": LABEL, "ProgramArguments": ["/usr/bin/open", "-a", str(app)],
                           "RunAtLoad": True})


def install(app: Path = APP, agent: Path = AGENT) -> str:
    if not (app / "Contents" / "MacOS" / "Marco").exists():
        raise RuntimeError("build the app first: marco app build")
    agent.parent.mkdir(parents=True, exist_ok=True)
    agent.write_bytes(agent_plist(app))
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(agent)], capture_output=True)
    loaded = subprocess.run(["launchctl", "bootstrap", domain, str(agent)], capture_output=True, text=True)
    if loaded.returncode != 0:
        raise RuntimeError(f"the login item did not load: {loaded.stderr.strip()[-200:]}")
    subprocess.run(["open", "-a", str(app)], check=True)
    return f"Marco starts at login; the login item is {agent}"


def uninstall(agent: Path = AGENT) -> str:
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(agent)], capture_output=True)
    if agent.exists():
        agent.unlink()
    subprocess.run(["osascript", "-e", 'tell application "Marco" to quit'], capture_output=True)
    return "Marco no longer starts at login, and the app is closed; it stays in ~/Applications until you move it"
