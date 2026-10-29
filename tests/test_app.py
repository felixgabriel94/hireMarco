import plistlib

import pytest

from hiremarco.studio import app


def test_the_build_writes_a_menu_bar_app_with_its_permissions_explained(tmp_path, monkeypatch):
    calls = []

    class Done:
        returncode = 0
        stderr = ""

    monkeypatch.setattr(app.shutil, "which", lambda name: "/opt/homebrew/bin/uv")
    monkeypatch.setattr(app.subprocess, "run", lambda args, **k: calls.append(args) or Done())
    built = app.build(tmp_path / "Marco.app")
    info = plistlib.loads((built / "Contents" / "Info.plist").read_bytes())
    assert info["LSUIElement"] is True and "listens" in info["NSMicrophoneUsageDescription"]
    assert calls[0][0] == "swiftc" and calls[-1][:3] == ["codesign", "--force", "--sign"]
    assert sum(c[0] == "sips" for c in calls) == 10 and any(c[0] == "iconutil" for c in calls)  # every icon size
    assert info["CFBundleIconFile"] == "Marco"
    assert '"uv": "/opt/homebrew/bin/uv"' in (app.config.STATE_DIR / "app.json").read_text()


def test_the_login_item_opens_the_app_at_login_and_install_needs_a_build(tmp_path):
    agent = plistlib.loads(app.agent_plist(tmp_path / "Marco.app"))
    assert agent["RunAtLoad"] is True and agent["ProgramArguments"][-1].endswith("Marco.app")
    with pytest.raises(RuntimeError, match="build the app first"):
        app.install(tmp_path / "Missing.app", tmp_path / "agent.plist")
