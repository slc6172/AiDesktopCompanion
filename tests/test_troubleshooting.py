"""docs/troubleshooting.md is organised by what the person sees. Every on-screen message it quotes must really be said by
the program (or by the named third-party tool), and the three messages run.bat prints when the installation is
incomplete must each have an entry — otherwise the page sends people looking for a text that no longer exists."""
import re
from pathlib import Path

import pytest

from companion.engine import FRIENDLY
from tests.repo_scan import ROOT, mentioned_files_that_do_not_exist

DOC = (ROOT / "docs" / "troubleshooting.md").read_text(encoding="utf-8")
GENERATED = {"config.json", "persona.md", "history.db", "app.log", "window-state.json", "path.txt", "hello.mp3"}


def program_text():
    parts = [p.read_text(encoding="utf-8") for pattern in ("companion/*.py", "static/*.js", "static/index.html", "*.bat")
             for p in ROOT.glob(pattern)]
    return "\n".join(parts)


# what the person sees, quoted in the document (the first group) -> must exist in the program
PROGRAM_MESSAGES = [
    "語音暫時不能用,先用文字陪你聊。",
    "語音辨識暫時不能用,可以再說一次或用打字嗎?",
    "語音輸入已啟用,但找不到 Groq API 金鑰,所以先關閉麥克風(仍可打字)。",
    "找不到 Gemini API 金鑰",
    "麥克風沒有授權",
    "持續聆聽初始化失敗",
    "沒聽清楚,可以再說一次嗎?",
    "程式無法啟動",
]


@pytest.mark.parametrize("message", PROGRAM_MESSAGES)
def test_a_message_the_document_quotes_is_really_in_the_program(message):
    assert message in DOC, "the document must quote it"
    assert message in program_text(), "and the program must still say it"


@pytest.mark.parametrize("kind", sorted(FRIENDLY))
def test_the_characters_apology_for_each_kind_of_model_failure_is_quoted_as_the_program_words_it(kind):
    assert FRIENDLY[kind] in DOC


def run_bat_messages():
    """The first sentence after each failure label of run.bat."""
    text = (ROOT / "run.bat").read_text(encoding="ascii")
    return [re.search(r":" + label + r"\r?\necho\.?\r?\necho (.+?)\r?\n", text).group(1)
            for label in ("no_venv", "no_packages", "no_electron")]


@pytest.mark.parametrize("sentence", run_bat_messages())
def test_every_message_run_bat_prints_when_the_installation_is_incomplete_has_an_entry(sentence):
    assert sentence in DOC


def test_a_third_party_error_it_quotes_is_the_one_the_installed_tool_really_has():
    electron = ROOT / "electron" / "node_modules"
    if not electron.exists():
        pytest.skip("electron is not installed in this checkout")
    assert 'npx install-electron --no' in (electron / "electron" / "index.js").read_text(encoding="utf-8")
    assert "did not match expected checksum" in (electron / "sumchecker" / "index.js").read_text(encoding="utf-8")
    assert "Electron failed to install correctly" in DOC and "npx install-electron --no" in DOC and "did not match expected checksum" in DOC
    assert "try installing again" not in DOC, "that is the older package's wording"


def test_the_electron_download_problem_is_marked_as_walked_through_and_points_at_the_manual_route():
    start = DOC.index("## 安裝桌寵視窗(Electron)時的問題")
    section = DOC[start:start + 1500]
    assert "實測" in section and "install.md" in section and "手動下載" in section


def test_it_says_which_entries_are_not_walked_through():
    assert "依程式行為推導" in DOC


def test_it_tells_where_the_log_is_and_how_to_see_the_output_live():
    assert "data\\app.log" in DOC and "run-debug.bat" in DOC


def test_every_file_it_mentions_exists_or_is_created_by_the_reader_or_the_program():
    assert mentioned_files_that_do_not_exist(DOC, GENERATED) == []
