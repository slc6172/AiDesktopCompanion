"""README.md is the first page a visitor reads: it must state the platform limit plainly, name the features, and
every file or script it tells the reader to run must really exist (a README that names a file which is gone
is the commonest way for a project's front page to rot)."""
import re
from pathlib import Path

import pytest

from tests.repo_scan import mentioned_files_that_do_not_exist

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")

# The reader's own files: created by them, not shipped, so they are not expected to exist in a fresh checkout.
USER_FILES = {"config.json", "persona.md", "history.db", "window-state.json", "app.log", "idle.webm", "base.png",
              "outfit.txt", "hello.mp3"}


def test_it_says_in_plain_words_that_only_windows_10_and_11_are_supported():
    assert "僅支援 Windows 10" in README and "11" in README


@pytest.mark.parametrize("feature", ["真人照片", "換裝", "自拍", "語音", "記憶", "物品", "好感度", "情緒"])
def test_every_headline_feature_is_mentioned(feature):
    assert feature in README


def test_it_leaves_room_for_one_or_two_screenshots_not_more():
    placeholders = re.findall(r"<!-- 截圖", README)
    assert 1 <= len(placeholders) <= 2


def test_it_names_no_nickname_or_personal_handle():
    assert "@" not in README.replace("@echo", "")


def test_every_file_it_mentions_exists_or_is_one_of_the_readers_own_files():
    assert mentioned_files_that_do_not_exist(README, USER_FILES) == []
