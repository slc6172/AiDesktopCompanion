"""persona.md is the user's own file (it is git-ignored); the repository ships persona.example.md to copy."""
import shutil
import subprocess
from pathlib import Path

import pytest

from companion.server import create_app

PROJECT = Path(__file__).resolve().parent.parent


def test_the_example_persona_exists_and_says_how_to_write_one():
    text = (PROJECT / "persona.example.md").read_text(encoding="utf-8")
    assert text.strip()
    assert "人稱" in text or "代名詞" in text, "the guidance must tell the user to state the character's pronoun themselves"


def test_the_users_own_persona_file_is_not_part_of_the_repository():
    if not (PROJECT / ".git").exists() or shutil.which("git") is None:
        pytest.skip("not a git checkout")
    tracked = subprocess.run(["git", "ls-files"], cwd=PROJECT, capture_output=True, text=True, encoding="utf-8").stdout.splitlines()
    assert "persona.md" not in tracked and "persona.example.md" in tracked


def test_a_missing_persona_file_tells_the_user_to_copy_the_example(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPANION_FAKE", "1")
    monkeypatch.setattr("companion.server.user_dir", lambda: tmp_path)
    monkeypatch.delenv("COMPANION_PERSONA", raising=False)
    with pytest.raises(FileNotFoundError) as error:
        create_app()
    message = str(error.value)
    assert "persona.md" in message and "persona.example.md" in message and "複製" in message
