"""CONTRIBUTING.md, CHANGELOG.md, SECURITY.md and .github/dependabot.yml (ticket 18).

The commands in CONTRIBUTING.md were each run before they were written down; the tests keep the written form exactly that
(a wildcard without quotes, or a folder alone, does not work on Windows PowerShell / on current Node). SECURITY.md must name
the pinned Electron version, so that raising the pin cannot leave a stale sentence behind."""
import json
import re
from pathlib import Path

import pytest

from tests.repo_scan import ROOT, mentioned_files_that_do_not_exist

CONTRIBUTING = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
CHANGELOG = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
SECURITY = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
DEPENDABOT = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
PINNED = json.loads((ROOT / "electron" / "package.json").read_text(encoding="utf-8"))["devDependencies"]["electron"]
GENERATED = {"config.json", "persona.md", "history.db", "app.log", "checksums.json", "SHASUMS256.txt"}


# ---- CONTRIBUTING.md ----

@pytest.mark.parametrize("command", [
    r".venv\Scripts\python -m pytest tests",
    'node --test "tests_js/*.test.js"',
    r".venv\Scripts\pip-audit -r requirements.txt",
    "npm audit",
    "smoke_state.py",
])
def test_contributing_gives_the_command_exactly_as_it_was_run(command):
    assert command in CONTRIBUTING


def test_contributing_warns_that_a_folder_alone_does_not_work_for_the_node_tests_and_names_the_node_version():
    assert "Cannot find module" in CONTRIBUTING and "Node 22" in CONTRIBUTING


def test_contributing_says_the_electron_scenarios_are_not_automatic_and_where_they_are_described():
    assert "非自動測試" in CONTRIBUTING and "tests_electron/README.md" in CONTRIBUTING


def test_contributing_explains_the_electron_upgrade_policy_and_what_an_upgrade_must_change():
    assert "最新三個" in CONTRIBUTING and "8 週" in CONTRIBUTING
    for needle in ("tests/test_electron_pin.py", "package-lock.json", "docs/install.md", "SHA-256", "SECURITY.md"):
        assert needle in CONTRIBUTING


def test_contributing_explains_the_prompt_regression_check():
    assert "改動前" in CONTRIBUTING and "改動後" in CONTRIBUTING and "90%" in CONTRIBUTING


def test_contributing_mentions_only_files_that_exist():
    assert mentioned_files_that_do_not_exist(CONTRIBUTING, GENERATED) == []


# ---- CHANGELOG.md ----

def test_the_changelog_has_one_entry_the_first_public_release():
    versions = re.findall(r"^## \[?(\d+\.\d+\.\d+)", CHANGELOG, re.M)
    assert versions == ["0.1.0"] and "首次公開" in CHANGELOG


# ---- SECURITY.md ----

def test_security_names_the_pinned_electron_version_and_the_date_its_official_support_ends():
    assert PINNED in SECURITY and "2027-04-27" in SECURITY and "終止支援" in SECURITY


def test_contributing_states_which_electron_is_pinned_now():
    assert PINNED in CONTRIBUTING and "2027-04-27" in CONTRIBUTING


@pytest.mark.parametrize("fact", ["127.0.0.1", "未加密", "Gemini", "憑證管理員", "回報"])
def test_security_states_what_the_reader_needs_to_judge_the_risk(fact):
    assert fact in SECURITY


# ---- .github/dependabot.yml ----

def update_blocks():
    """[(ecosystem, directory, interval)] read line by line (no YAML library in this project)."""
    blocks = []
    for chunk in re.split(r"\n  - ", DEPENDABOT)[1:]:
        ecosystem = re.search(r'package-ecosystem:\s*"?([\w-]+)"?', chunk).group(1)
        directory = re.search(r'directory:\s*"([^"]+)"', chunk).group(1)
        interval = re.search(r'interval:\s*"?(\w+)"?', chunk).group(1)
        blocks.append((ecosystem, directory, interval))
    return blocks


def test_dependabot_watches_the_python_packages_and_the_electron_folder():
    assert re.search(r"^version:\s*2\s*$", DEPENDABOT, re.M)
    assert update_blocks() == [("pip", "/", "weekly"), ("npm", "/electron", "weekly")]


# ---- things only the owner can fill in: this one stays "expected to fail" until it is filled in ----

def test_the_license_is_mit_and_names_its_copyright_holder():
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert text.startswith("MIT License") and "Copyright (c) 2026 slc6172" in text and "<<" not in text


@pytest.mark.xfail(reason="the security contact is still a placeholder (owner to provide)", strict=False)
def test_the_security_contact_is_filled_in():
    assert "<<" not in SECURITY
