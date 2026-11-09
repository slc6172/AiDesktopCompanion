"""Windows batch files are fussy: cmd.exe reads them with the machine's own code page (not UTF-8)
and expects CRLF line endings. A stray long dash in a comment, or Unix line endings, are the
classic causes of garbled "'X' is not recognized as an internal or external command" errors.
These files are written and zipped on other systems, so check the bytes that actually ship."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BATCH_FILES = sorted(ROOT.glob("*.bat"))


def test_the_batch_files_are_found():
    assert {p.name for p in BATCH_FILES} >= {"run.bat", "run-debug.bat"}


@pytest.mark.parametrize("path", BATCH_FILES, ids=lambda p: p.name)
def test_a_batch_file_is_plain_ascii(path):
    data = path.read_bytes()
    bad = [(i, hex(b)) for i, b in enumerate(data) if b > 127][:3]
    assert not bad, f"{path.name} has non-ASCII bytes at {bad}; cmd.exe would misread them under a Chinese code page"


@pytest.mark.parametrize("path", BATCH_FILES, ids=lambda p: p.name)
def test_a_batch_file_uses_windows_line_endings_only(path):
    data = path.read_bytes()
    lone_lf = data.count(b"\n") - data.count(b"\r\n")
    lone_cr = data.count(b"\r") - data.count(b"\r\n")
    assert lone_lf == 0 and lone_cr == 0, f"{path.name}: {lone_lf} bare LF and {lone_cr} bare CR line endings"


# ---- the two launchers: run.bat is silent (one window: the pet), run-debug.bat keeps the console ----

def lines_of(name):
    return [l.strip() for l in (ROOT / name).read_text(encoding="ascii").splitlines()]


def first_line_with(lines, needle):
    return next(i for i, l in enumerate(lines) if needle in l.lower() and not l.lower().startswith("rem"))


def test_run_bat_starts_the_program_without_a_console_window_and_then_ends_itself():
    lines = lines_of("run.bat")
    start = first_line_with(lines, "pythonw.exe\" app.py")
    assert lines[start].lower().startswith('start ""'), "the first quoted argument of start is the window title"
    assert lines[start + 1:start + 2] == ["exit /b 0"], "the batch file must end right after starting the program"


def test_run_bat_checks_the_environment_before_it_starts_anything():
    lines = lines_of("run.bat")
    start = first_line_with(lines, "pythonw.exe\" app.py")
    for needle in ("scripts\\pythonw.exe", "path.txt", "import uvicorn"):
        assert first_line_with(lines, needle) < start, f"{needle!r} must be checked before the start line"


def test_every_failed_check_leaves_the_window_open_with_a_message_instead_of_vanishing():
    lines = lines_of("run.bat")
    after_start = lines[first_line_with(lines, "pythonw.exe\" app.py"):]
    assert sum(l.lower() == "pause" for l in after_start) >= 3  # no venv / no packages / no Electron


def test_run_debug_bat_runs_the_same_program_with_a_console_and_waits_before_closing():
    lines = lines_of("run-debug.bat")
    run = first_line_with(lines, "python.exe\" app.py")
    assert "pythonw" not in " ".join(lines).lower()
    assert "pause" in [l.lower() for l in lines[run + 1:]]


# ---- animation-tools/: tools for making the character's clips (they may carry Chinese, e.g. the default outfit) ----
# The launchers above must stay pure ASCII. These are different: they name the outfit folder "日常", so they are
# UTF-8 (no BOM) with CRLF line ends, and they switch the console to UTF-8 (`chcp 65001`) before reading any of it.

TOOLS = ROOT / "animation-tools"
TOOL_FILES = sorted(TOOLS.glob("*.bat"))


def test_the_animation_tools_folder_has_exactly_one_keying_script_and_one_cropping_script():
    assert [p.name for p in TOOL_FILES] == ["crop-916.bat", "make-clip.bat"]


@pytest.mark.parametrize("path", TOOL_FILES, ids=lambda p: p.name)
def test_an_animation_tool_is_utf8_without_bom_with_crlf_and_switches_the_console_to_utf8_first(path):
    data = path.read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf"), "a BOM would be read by cmd as part of the first command"
    text = data.decode("utf-8")  # raises if it is not UTF-8
    assert "\r\n" in text and "\n" not in text.replace("\r\n", "")
    assert text.index("chcp 65001") < min((i for i, c in enumerate(text) if ord(c) > 127), default=len(text))


def test_make_clip_writes_into_the_outfit_folder_and_its_default_outfit_is_the_projects_default():
    from companion.config import DEFAULT_CONFIG

    text = (TOOLS / "make-clip.bat").read_bytes().decode("utf-8")  # read_text would turn CRLF into LF
    assert f"set OUTFIT={DEFAULT_CONFIG['outfit']['default']}\r\n" in text
    assert "set OUT=%~dp0..\\clips\\%OUTFIT%" in text, "the outfit folder lives next to animation-tools, in the project's clips"
    assert 'mkdir "%OUT%"' in text and '"%OUT%\\%~n1.webm"' in text


def test_make_clip_keeps_the_tuned_keying_settings():
    text = (TOOLS / "make-clip.bat").read_bytes().decode("utf-8")  # read_text would turn CRLF into LF
    assert "set SIM=0.14" in text and "lut=a=" in text
