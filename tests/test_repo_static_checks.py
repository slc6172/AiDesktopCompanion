"""Static checks over the whole repository (spec "倉庫靜態檢查", ticket 02).

This file is the one new test seam of the release-prep work. Ticket 02 only builds and tests the shared
walking helpers (tests/repo_scan.py); the real rules arrive with their own tickets:

  scan                  scope                                                    false positives
  --------------------  -------------------------------------------------------  ---------------------------
  gender-neutrality     companion/, static/, electron/, root smoke_*.py, tools/, a reasoned allowlist entry
  (tickets 08, 09)      animation-tools/, config.example.json, the example       (every entry needs a reason)
                        persona, all Markdown outside the archive. NOT tests/,
                        tests_js/, tests_electron/ code.
  removed-feature       the same scope, documents included; CHANGELOG excluded   exact strings only; never the
  leftovers             (tickets 05, 06, 20)                                     words "edge" or "pet"
  doc links (ticket 20) every Markdown file; external links are not checked      none
"""
import re
from pathlib import Path

from tests.repo_scan import iter_files, python_string_literals, strip_front_end_comments, unreasoned, shipped_files, ALLOWLISTS, strip_front_end_comments, broken_markdown_links


def touch(root, *names):
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")


def names(root, found):
    return sorted(p.relative_to(root).as_posix() for p in found)


def test_walking_skips_ignored_and_archived_folders(tmp_path):
    touch(tmp_path, "companion/a.py", "static/page.html", "node_modules/pkg/x.js", ".venv/lib/y.py",
          "__pycache__/z.pyc", ".git/config", ".pytest_cache/n.py", "docs/design-archive/old.md",
          "docs/install.md")
    found = names(tmp_path, iter_files(tmp_path, (".py", ".html", ".js", ".md")))
    assert found == ["companion/a.py", "docs/install.md", "static/page.html"]


def test_walking_can_be_limited_to_some_suffixes(tmp_path):
    touch(tmp_path, "a.py", "b.md", "c.js")
    assert names(tmp_path, iter_files(tmp_path, (".md",))) == ["b.md"]


def texts(source):
    return [text for _, text in python_string_literals(source)]


def test_string_values_are_found_but_comments_are_not():
    source = 'x = "跟她說"  # 她在註解裡\ny = \'hello\'\n'
    assert texts(source) == ["跟她說", "hello"]


def test_docstrings_are_left_out_but_other_strings_in_the_same_function_are_kept():
    source = (
        '"""模組說明:她"""\n'
        'class A:\n    """類別說明:她"""\n'
        '    def f(self):\n        """函式說明:她"""\n        return "你好"\n'
    )
    assert texts(source) == ["你好"]


def test_the_literal_parts_of_an_f_string_are_scanned_and_each_has_its_line_number():
    source = 'a = 1\nb = f"前{a}後"\n'
    assert python_string_literals(source) == [(2, "前"), (2, "後")]


def test_line_and_block_comments_are_removed_from_scripts_and_styles():
    source = "let a = 1; // 她在這\n/* 她 */ let b = 2;\n"
    assert "她" not in strip_front_end_comments(source)
    assert "let a = 1;" in strip_front_end_comments(source) and "let b = 2;" in strip_front_end_comments(source)


def test_html_comments_are_removed_across_lines():
    assert "她" not in strip_front_end_comments("<p>好</p><!-- 她\n她 --><p>好</p>")


def test_a_double_slash_inside_a_string_is_not_a_comment():
    source = 'const url = "http://127.0.0.1/";  const hint = "跟她說";\n'
    assert "跟她說" in strip_front_end_comments(source)


def test_removing_comments_keeps_the_line_numbers():
    source = "a\n/* x\ny */\nb // c\nd\n"
    assert strip_front_end_comments(source).split("\n").index("d") == source.split("\n").index("d")


def test_an_allowlist_entry_without_a_reason_is_reported():
    allowlist = {"companion/a.py": "分詞用的資料,不送模型", "companion/b.py": "", "static/c.js": "   "}
    assert unreasoned(allowlist) == ["companion/b.py", "static/c.js"]


def test_the_allowlists_in_use_all_have_reasons():
    from tests.repo_scan import ALLOWLISTS

    for name, allowlist in ALLOWLISTS.items():
        assert unreasoned(allowlist) == [], f"allowlist {name!r} has entries without a reason"


def test_the_helpers_can_read_every_python_and_front_end_file_of_the_repository():
    from tests.repo_scan import ROOT

    for path in iter_files(ROOT, (".py",)):
        python_string_literals(path.read_text(encoding="utf-8"))
    for path in iter_files(ROOT, (".js", ".html")):
        source = path.read_text(encoding="utf-8")
        assert len(strip_front_end_comments(source)) == len(source), path


# ---- removed features must leave nothing behind (exact strings only: never the words "edge" or "pet") ----

# Strings of features that no longer exist. Ticket 05 adds the packaging ones; ticket 06 adds the browser-mode ones.
REMOVED = {
    "PyInstaller": "the packaging into an exe was removed (ticket 05)",
    "build.bat": "the packaging script was removed (ticket 05)",
    "sys.frozen": "there is no frozen build any more (ticket 05)",
    "_MEIPASS": "there is no frozen build any more (ticket 05)",
    'sys, "frozen"': 'the other way to ask "am I a packaged exe?" (ticket 05)',
    "--mode browser": "browser-tab mode was removed (ticket 06)",
    "--mode edge": "the old pywebview mode was removed long ago (ticket 06)",
    "REMOVED_MODES": "the launcher no longer has modes (ticket 06)",
    "pywebview": "the old window library, replaced by Electron (ticket 06)",
    "smoke_record": "the stand-alone microphone page was removed (ticket 06)",
    "load_memory": "the old summary-and-facts memory was removed; the store has load_fold_progress (ticket 11)",
    "save_memory": "the old summary-and-facts memory was removed; tests use apply_fold / save_facts (ticket 11)",
    "memory_block": "the old memory's prompt block was removed (ticket 11)",
    "EMPTY_MEMORY": "the old memory record was removed (ticket 11)",
    "legacy_imported": "the old memory is no longer imported (ticket 11)",
    "(聽不清楚)": "no server code ever sent this placeholder transcript; an unrecognised turn is `heard === null` (ticket 11)",
    "(語音訊息)": "no server code ever sent this placeholder transcript (ticket 11)",
    "HANDOFF": "the development hand-over notes were deleted (ticket 11)",
    "companion-tickets-part": "the old ticket batches were deleted (ticket 11)",
    "stt-field-data": "the field-data note was deleted (ticket 11)",
    "smoke_structured": "an unreferenced smoke script, deleted (ticket 11)",
    "smoke_tinyfish": "an unreferenced smoke script, deleted (ticket 11)",
    "docs/ai-companion-spec": "moved to docs/design-archive/ (ticket 11)",
    "docs/companion-ui-spec": "moved to docs/design-archive/ (ticket 11)",
    "docs/companion-redesign-spec": "moved to docs/design-archive/ (ticket 11)",
    "docs/companion-time-spec": "moved to docs/design-archive/ (ticket 11)",
    "docs/voice_companion": "moved to docs/design-archive/ (ticket 11)",
    "在網址列允許": "the pet window has no address bar; wording left over from browser mode (ticket 18). (File Explorer's address bar is fine.)",
    "這個瀏覽器": "the pet window is not a browser tab (ticket 18)",
    "Chrome／Edge": "nobody picks a browser for the pet window (ticket 18)",
    "Edge 或 Chrome": "nobody picks a browser for the pet window (ticket 18)",
    "詳情見 Console": "a user cannot open the renderer console (ticket 18)",
    "FAILED_NOTICE": "an unreferenced constant, deleted (ticket 18)",
    "32.3.3": "the Electron that was pinned before the upgrade; nothing public should mention it (ticket 21)",
    "ELECTRON_SKIP_BINARY_DOWNLOAD": "Electron no longer reads it; the manual route uses npm's --ignore-scripts (ticket 21)",
    "SETUP.md": "the old all-in-one guide was split into the new documents and deleted (ticket 20)",
    "從舊版升級": "there is one memory design and no earlier version to upgrade from; nothing is converted or kept for old files (ticket 18)",
    "舊版的 `--mode`": "the first public release has no earlier version to compare with (ticket 18)",
    "依舊版指南": "the old development guide is not a public document (ticket 18)",
}

# Files that still mention them, each until the ticket that deletes or rewrites it. Remove an entry when that happens.
ALLOWLISTS["leftovers"] = {}


def test_nothing_of_the_removed_features_is_left_in_what_ships():
    from tests.repo_scan import ROOT

    allowed = ALLOWLISTS["leftovers"]
    hits = []
    for path in shipped_files():
        relative = path.relative_to(ROOT).as_posix()
        if relative in allowed or relative == "CHANGELOG.md":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        hits += [f"{relative}: {needle}" for needle in REMOVED if needle in text]
    assert hits == []


# ---- no gendered wording in anything the program says or sends (ticket 08: Python strings) ----
# Allowed: 他 / 你 / 等. Forbidden: 她, 妳, she, her, hers. Comments and docstrings are not scanned.

GENDERED_WORDS = re.compile(r"[她妳]|\b(she|her|hers|herself)\b", re.IGNORECASE)

ALLOWLISTS["gender"] = {
    "companion/retrieval.py": "_FUNCTION_CHARS is a set of function characters the memory search skips; it is neither sent to a "
                              "model nor shown, and dropping 她 from it would change what the search finds",
}


def test_no_python_string_in_what_ships_assumes_a_gender():
    from tests.repo_scan import ROOT

    allowed = ALLOWLISTS["gender"]
    hits = []
    for path in shipped_files():
        relative = path.relative_to(ROOT).as_posix()
        if path.suffix != ".py" or relative in allowed:
            continue
        for line, text in python_string_literals(path.read_text(encoding="utf-8")):
            hits += [f"{relative}:{line}: {m.group()}" for m in GENDERED_WORDS.finditer(text)]
    assert hits == []


def test_no_page_script_document_or_example_file_assumes_a_gender():
    """Ticket 09: what is drawn on screen, the example files and every Markdown document. Python is covered above."""
    from tests.repo_scan import ROOT

    allowed = ALLOWLISTS["gender"]
    hits = []
    for path in shipped_files():
        relative = path.relative_to(ROOT).as_posix()
        if path.suffix == ".py" or relative in allowed:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix in (".js", ".html"):
            text = strip_front_end_comments(text)
        for number, line in enumerate(text.splitlines(), 1):
            hits += [f"{relative}:{number}: {m.group()}" for m in GENDERED_WORDS.finditer(line)]
    assert hits == []


def test_a_document_that_names_a_file_which_does_not_exist_is_caught(tmp_path):
    from tests.repo_scan import mentioned_files_that_do_not_exist

    touch(tmp_path, "run.bat", "docs/install.md")
    text = "執行 `run.bat`,看 `docs/install.md`,別忘了 `gone.py`、`docs/nowhere.md`,以及你自己的 `persona.md`。"
    assert mentioned_files_that_do_not_exist(text, {"persona.md"}, root=tmp_path) == ["gone.py", "docs/nowhere.md"]


# ---- links between documents (ticket 20) ----

def test_the_link_checker_finds_a_broken_relative_link_and_ignores_examples_and_web_links(tmp_path):
    touch(tmp_path, "docs/there.md")
    page = tmp_path / "docs" / "page.md"
    page.write_text(
        "[ok](there.md) [broken](gone.md) [web](https://example.com/x.md) [same page](#top) [with place](there.md#part)\n"
        "`[inline](nope.md)`\n```\n[fenced](nope2.md)\n```\n<!-- ![commented](nope3.png) -->\n", encoding="utf-8")
    assert broken_markdown_links(page) == ["gone.md"]


def test_every_relative_link_in_every_markdown_document_points_at_something_that_exists():
    from tests.repo_scan import ROOT

    problems = {path.relative_to(ROOT).as_posix(): broken_markdown_links(path)
                for path in iter_files(ROOT, (".md",)) if broken_markdown_links(path)}
    assert problems == {}


def test_the_start_up_notice_points_at_a_tutorial_that_exists():
    from companion.outfits import ANIMATION_TUTORIAL
    from tests.repo_scan import ROOT

    assert (ROOT / ANIMATION_TUTORIAL).is_file()
