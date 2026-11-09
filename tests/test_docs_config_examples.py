"""docs/configuration.md must say what the program really does (an example that quietly drifts from the defaults
misleads the person who copies it).

 * Every section of config.DEFAULT_CONFIG has a block under a marker comment  <!-- config-defaults: <section> -->
   that is read back and compared with the real defaults. A new section with no block fails here.
 * Every command-line flag and every environment variable the program reads is mentioned.
"""
import json
import re
from pathlib import Path

import pytest

from companion import launcher
from companion.config import DEFAULT_CONFIG
from tests.repo_scan import python_string_literals

ROOT = Path(__file__).resolve().parent.parent
DOC = (ROOT / "docs" / "configuration.md").read_text(encoding="utf-8")
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9]*_[A-Z0-9_]+$")


def environment_variables_read_by_the_program():
    names = set()
    for path in [*(ROOT / "companion").glob("*.py"), ROOT / "app.py"]:
        names |= {text for _, text in python_string_literals(path.read_text(encoding="utf-8")) if ENV_NAME.match(text)}
    return sorted(names)


@pytest.mark.parametrize("section", sorted(DEFAULT_CONFIG))
def test_the_documented_defaults_of_each_config_section_equal_the_real_defaults(section):
    found = re.search(r"<!-- config-defaults: " + section + r" -->\s*```json\n(.*?)\n```", DOC, re.S)
    assert found, f"docs/configuration.md has no 'config-defaults: {section}' block"
    assert json.loads(found.group(1)) == {section: DEFAULT_CONFIG[section]}


def test_every_command_line_flag_is_documented():
    flags = [o for action in launcher.build_parser()._actions for o in action.option_strings if o.startswith("--") and o != "--help"]
    missing = [flag for flag in flags if f"`{flag}`" not in DOC]
    assert missing == []


def test_every_environment_variable_the_program_reads_is_documented():
    missing = [name for name in environment_variables_read_by_the_program() if f"`{name}`" not in DOC]
    assert missing == []


def test_the_environment_variable_scan_really_finds_the_variables():
    names = environment_variables_read_by_the_program()
    assert {"GEMINI_API_KEY", "COMPANION_VOICE", "CF_ACCOUNT_ID", "COMPANION_DB"} <= set(names) and len(names) > 30
