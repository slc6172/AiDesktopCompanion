"""docs/install.md: the steps must match the pinned Electron, give the commands for both Windows shells, and name only
files that exist. It also keeps honest about which download routes someone has actually walked through."""
import json
import re
from pathlib import Path

import pytest

from tests.repo_scan import ROOT, mentioned_files_that_do_not_exist

GUIDE = (ROOT / "docs" / "install.md").read_text(encoding="utf-8")
PINNED = json.loads((ROOT / "electron" / "package.json").read_text(encoding="utf-8"))["devDependencies"]["electron"]
ZIP = f"electron-v{PINNED}-win32-x64.zip"
CHECKSUMS = ROOT / "electron" / "node_modules" / "electron" / "checksums.json"
GENERATED = {"config.json", "persona.md", "history.db", "app.log", "hello.mp3", "path.txt", "checksums.json", "SHASUMS256.txt"}


def section(title):
    start = GUIDE.index(title)
    following = re.search(r"\n#{2,3} ", GUIDE[start + len(title):])
    return GUIDE[start:start + len(title) + (following.start() if following else len(GUIDE))]


def test_it_names_the_pinned_electron_version_and_the_windows_zip_that_goes_with_it():
    assert PINNED in GUIDE and ZIP in GUIDE


@pytest.mark.skipif(not CHECKSUMS.exists(), reason="electron is not installed in this checkout")
def test_the_sha256_it_tells_you_to_compare_is_the_one_the_electron_package_itself_pins():
    assert json.loads(CHECKSUMS.read_text(encoding="utf-8"))[ZIP] in GUIDE


def test_the_mirror_variable_is_given_for_both_powershell_and_cmd():
    assert "$env:ELECTRON_MIRROR" in GUIDE and "set ELECTRON_MIRROR=" in GUIDE


def test_the_manual_route_skips_the_download_with_npms_own_flag_not_a_variable_electron_no_longer_reads():
    manual = section("### 路線 C")
    assert "npm install --ignore-scripts" in manual
    assert "ELECTRON_SKIP_BINARY_DOWNLOAD" not in GUIDE


def test_the_check_after_installing_looks_at_the_files_instead_of_asking_electron_which_would_start_a_download():
    check = section("### 確認 Electron 裝好了")
    assert "Test-Path" in check and r"node_modules\electron\dist\electron.exe" in check
    assert "require('./node_modules/electron')" not in check, "requiring the package downloads the program when it is missing"


def test_path_txt_is_written_without_a_trailing_newline():
    manual = section("### 路線 C")
    assert "-NoNewline" in manual and "path.txt" in manual


def test_the_manual_route_says_to_check_the_download_against_the_pinned_hash():
    assert "Get-FileHash" in section("### 路線 C")


def test_the_three_routes_say_honestly_which_ones_were_walked_through():
    assert "尚未實測" in section("### 路線 B")
    assert "尚未實測" not in section("### 路線 C") and "實測" in section("### 路線 C")


def test_it_covers_the_whole_way_from_nothing_to_a_first_conversation():
    for needle in ("python -m venv", "pip install -r requirements.txt", "npm install", "--set-key", "persona.example.md",
                   "smoke_gemini.py", "smoke_tts.py", "run.bat"):
        assert needle in GUIDE


def test_every_file_it_mentions_exists_or_is_one_the_reader_or_the_install_creates():
    assert mentioned_files_that_do_not_exist(GUIDE, GENERATED) == []
