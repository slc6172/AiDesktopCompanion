"""The pet window is not a browser tab: it has no address bar, nobody picks a browser for it, and the DevTools console
is not something a user can open. What the page tells the person must not send them looking for those."""
import pytest
from fastapi.testclient import TestClient

from companion.server import create_app


@pytest.fixture
def page(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPANION_FAKE", "1")
    monkeypatch.setattr("companion.config.config_path", lambda: tmp_path / "config.json")
    monkeypatch.setattr("companion.server.user_dir", lambda: tmp_path)
    return TestClient(create_app(persona="test persona")).get("/").text


@pytest.mark.parametrize("phrase", ["網址列", "這個瀏覽器", "Chrome／Edge", "Edge 或 Chrome", "更新 Chrome", "詳情見 Console"])
def test_the_page_never_tells_the_person_to_use_a_browser_feature_the_window_does_not_have(page, phrase):
    assert phrase not in page


def test_a_failed_recording_points_at_what_can_really_be_checked_on_windows(page):
    note = next(line for line in page.splitlines() if "麥克風沒有授權或無法使用" in line)
    for needle in ("隱私設定", "輸入裝置", "別的程式"):
        assert needle in note


def test_a_failed_start_of_continuous_listening_says_that_pressing_to_talk_still_works(page):
    note = next(line for line in page.splitlines() if "持續聆聽初始化失敗" in line)
    assert "回音消除" in note and "按住說話" in note


def test_the_note_about_an_unconfirmed_echo_cancellation_suggests_headphones_not_a_browser_update(page):
    note = next(line for line in page.splitlines() if "無法確認回音消除狀態" in line)
    assert "耳機" in note
