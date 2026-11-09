"""main.js must keep the guards that stop the pet window from being taken to another site (the behaviour of the
decision itself is tested in tests_js/navguard.test.js; this keeps the wiring from being deleted unnoticed)."""
from pathlib import Path

MAIN = (Path(__file__).resolve().parent.parent / "electron" / "main.js").read_text(encoding="utf-8")


def test_navigation_redirects_and_new_windows_are_guarded():
    assert 'webContents.on("will-navigate"' in MAIN
    assert 'webContents.on("will-redirect"' in MAIN
    assert "setWindowOpenHandler" in MAIN and '"deny"' in MAIN


def test_permissions_are_decided_by_origin_in_both_the_request_and_the_check_handler():
    assert "setPermissionRequestHandler" in MAIN and "setPermissionCheckHandler" in MAIN
    assert MAIN.count("navguard.permissionAllowed(") == 2
    assert 'callback(permission === "media")' not in MAIN  # the old handler let any page have the microphone
