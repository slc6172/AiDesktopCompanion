"""README.en.md is a short English overview, not a translation of the documentation. It must say plainly what an English
reader needs to know first (Windows only, Traditional Chinese interface), give the same install commands as the Chinese
README (a copy that drifts is worse than none), and link only to documents that exist."""
import re
from pathlib import Path

import pytest

from tests.repo_scan import ROOT, mentioned_files_that_do_not_exist

EN = (ROOT / "README.en.md").read_text(encoding="utf-8")
ZH = (ROOT / "README.md").read_text(encoding="utf-8")
GENERATED = {"config.json", "persona.md", "history.db", "app.log", "idle.webm", "base.png", "outfit.txt"}


def commands(markdown):
    """The command part (before any `#` comment) of every line of the first powershell block."""
    block = re.search(r"```powershell\n(.*?)```", markdown, re.S).group(1)
    return [line.split("#")[0].strip() for line in block.splitlines() if line.split("#")[0].strip()]


def test_it_says_up_front_that_only_windows_10_and_11_are_supported():
    assert re.search(r"only supports? Windows 10", EN, re.I) and "11" in EN


def test_it_says_up_front_that_the_interface_and_documentation_are_in_traditional_chinese():
    assert "Traditional Chinese" in EN and "繁體中文" in EN


def test_the_quick_start_commands_are_exactly_the_chinese_readmes():
    assert commands(EN) == commands(ZH)
    assert len(commands(EN)) == 6


@pytest.mark.parametrize("feature", ["photo", "outfit", "selfie", "voice", "memory", "item", "affection", "emotion"])
def test_the_headline_features_are_named(feature):
    assert feature in EN.lower()


def test_it_covers_installing_starting_quitting_and_making_the_animation():
    for needle in ("run.bat", "run-debug.bat", "idle.webm", "animation-tools", "clips", "persona.example.md"):
        assert needle in EN


def test_it_tells_the_reader_about_the_manual_electron_download_when_the_default_is_slow():
    assert "manual" in EN.lower() and "install.md" in EN


def test_every_relative_link_points_at_a_file_that_exists():
    links = [target.split("#")[0] for target in re.findall(r"\]\(([^)]+)\)", EN) if not target.startswith(("http", "#"))]
    assert links and all((ROOT / target).exists() for target in links), links


def test_every_file_it_mentions_exists_or_is_created_by_the_reader():
    assert mentioned_files_that_do_not_exist(EN, GENERATED, search=("", "docs", "animation-tools")) == []


def test_the_chinese_readme_links_to_it_in_its_first_lines():
    assert "README.en.md" in "\n".join(ZH.splitlines()[:6])
