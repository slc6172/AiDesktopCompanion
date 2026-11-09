"""Finding the Electron program to start (spec Part 9, ticket 39 and the follow-up to the first
real-world run). Checked at the outer edge: a throw-away folder laid out like `electron/`."""
import sys

import pytest

from companion import launcher


@pytest.fixture
def electron_tree(tmp_path, monkeypatch):
    """An `electron/` folder in a path with a space and Chinese characters, as real ones have."""
    root = tmp_path / "我的 專案" / "electron"
    (root / "node_modules" / "electron" / "dist").mkdir(parents=True)
    (root / "node_modules" / ".bin").mkdir(parents=True)
    monkeypatch.setattr(launcher, "electron_dir", lambda: root)
    return root


def install(root, binary_name, *, path_txt=True, binary=True, shim=None):
    pkg = root / "node_modules" / "electron"
    if path_txt:
        (pkg / "path.txt").write_text(binary_name)
    if binary:
        (pkg / "dist" / binary_name).write_bytes(b"binary")
    if shim:
        (root / "node_modules" / ".bin" / shim).write_text("shim")


def test_the_real_program_is_started_directly_not_through_npms_batch_shim(electron_tree):
    install(electron_tree, "electron.exe", shim="electron.cmd")
    found = launcher.find_electron_binary()
    assert found == electron_tree / "node_modules" / "electron" / "dist" / "electron.exe"
    assert found.suffix != ".cmd"      # going through cmd.exe and Node at launch is what we avoid


def test_the_programs_name_comes_from_electrons_own_path_txt(electron_tree):
    (electron_tree / "node_modules" / "electron" / "dist" / "bin").mkdir()
    install(electron_tree, "bin/custom-electron")
    assert launcher.find_electron_binary().name == "custom-electron"


def test_an_install_that_never_finished_downloading_the_program_is_reported_as_not_installed(electron_tree):
    install(electron_tree, "electron.exe", binary=False, shim="electron.cmd")   # path.txt but no program
    assert launcher.find_electron_binary() is None


def test_npms_batch_shim_alone_is_not_an_installed_electron(electron_tree):
    install(electron_tree, "x", path_txt=False, binary=False, shim="electron.cmd")
    assert launcher.find_electron_binary() is None


def test_nothing_installed_means_none(electron_tree):
    assert launcher.find_electron_binary() is None


# ---- starting without a console (run.bat starts pythonw.exe: stdout and stderr do not exist) ----

import time
import urllib.request


@pytest.fixture
def headless(tmp_path, monkeypatch):
    """A project folder with a persona, the offline doubles, and NO standard output or error (as under
    pythonw.exe). Yields what the test needs to look at; the real uvicorn server is used."""
    (tmp_path / "persona.md").write_text("測試人設", encoding="utf-8")
    (tmp_path / "clips").mkdir()
    monkeypatch.setenv("COMPANION_FAKE", "1")
    monkeypatch.setattr("companion.config.config_path", lambda: tmp_path / "config.json")
    monkeypatch.setattr("companion.server.user_dir", lambda: tmp_path)
    monkeypatch.setattr(launcher, "user_dir", lambda: tmp_path)
    started = {}
    real_start = launcher.start_server

    def start(port):
        started["server"], started["port"] = real_start(port), port
        return started["server"]

    monkeypatch.setattr(launcher, "start_server", start)
    started["log"] = tmp_path / "data" / "app.log"

    def silence():  # inside the test body: pytest's capture would put its own stdout back after a fixture
        monkeypatch.setattr(sys, "stdout", None)
        monkeypatch.setattr(sys, "stderr", None)

    started["silence"] = silence
    return started


def port_is_open(port):
    import socket

    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def test_the_whole_start_up_works_without_a_console_and_what_would_be_printed_goes_to_the_log(headless, monkeypatch):
    seen = {}

    def window(url):  # stands in for the Electron window: the page is reachable, and something is "printed"
        seen["config"] = urllib.request.urlopen(url + "config", timeout=5).status
        print("寫給主控台的字")

    monkeypatch.setattr(launcher, "open_electron_window", window)
    headless["silence"]()
    launcher.main(["--port", "0"])
    sys.stdout.flush()
    log_text = headless["log"].read_text(encoding="utf-8")
    sys.stdout.close()
    assert seen["config"] == 200
    assert "寫給主控台的字" in log_text


def test_when_the_window_closes_the_server_is_shut_down_and_the_program_ends(headless, monkeypatch):
    monkeypatch.setattr(launcher, "open_electron_window", lambda url: None)  # the window was closed at once
    headless["silence"]()
    launcher.main(["--port", "0"])
    sys.stdout.close()
    deadline = time.monotonic() + 10
    while port_is_open(headless["port"]) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not port_is_open(headless["port"])


def test_a_failure_after_the_server_started_is_shown_in_a_dialog_and_the_program_exits_with_an_error(headless, monkeypatch):
    shown = []
    monkeypatch.setattr(launcher, "show_error", shown.append)

    def broken_window(url):
        raise RuntimeError("找不到 Electron")

    monkeypatch.setattr(launcher, "open_electron_window", broken_window)
    headless["silence"]()
    with pytest.raises(SystemExit) as stopped:
        launcher.main(["--port", "0"])
    sys.stdout.close()
    assert stopped.value.code == 1
    assert len(shown) == 1 and "找不到 Electron" in shown[0] and "app.log" in shown[0]


def test_without_electron_the_error_says_how_to_install_it(electron_tree):
    with pytest.raises(RuntimeError) as error:
        launcher.open_electron_window("http://127.0.0.1:1/")
    assert "npm install" in str(error.value)


# ---- there is one way to show the program: the Electron window (no --mode) ----

def test_a_mode_argument_is_no_longer_accepted(capsys):
    with pytest.raises(SystemExit) as stopped:
        launcher.main(["--mode", "browser"])
    assert stopped.value.code == 2  # argparse: unrecognized arguments
    assert "--mode" in capsys.readouterr().err


def test_a_normal_start_opens_the_electron_window_and_never_a_browser_tab(headless, monkeypatch):
    import webbrowser

    opened = []
    monkeypatch.setattr(launcher, "open_electron_window", opened.append)
    monkeypatch.setattr(webbrowser, "open", lambda *a, **k: pytest.fail("a browser tab must not be opened"))
    headless["silence"]()
    launcher.main(["--port", "0"])
    sys.stdout.close()
    assert len(opened) == 1 and opened[0].startswith("http://127.0.0.1:")


# ---- a hand-placed Electron (the manual-download route in docs/install.md) ----

def test_a_manually_placed_electron_is_found_with_nothing_but_dist_and_path_txt(tmp_path, monkeypatch):
    """What you get from: npm install with the download skipped, then unzipping the official zip
    into node_modules/electron/dist and writing the name of the program into path.txt."""
    package = tmp_path / "電子 資料夾" / "node_modules" / "electron"
    (package / "dist").mkdir(parents=True)
    (package / "dist" / "electron.exe").write_bytes(b"binary")
    (package / "path.txt").write_text("electron.exe")  # no trailing newline, as npm writes it
    monkeypatch.setattr(launcher, "electron_dir", lambda: tmp_path / "電子 資料夾")
    assert launcher.find_electron_binary() == package / "dist" / "electron.exe"


def test_a_path_txt_that_points_at_a_missing_program_means_not_installed(tmp_path, monkeypatch):
    package = tmp_path / "electron" / "node_modules" / "electron"
    (package / "dist").mkdir(parents=True)
    (package / "path.txt").write_text("electron.exe")
    monkeypatch.setattr(launcher, "electron_dir", lambda: tmp_path / "electron")
    assert launcher.find_electron_binary() is None


# ---- the command line (docs/configuration.md lists every flag, and a test holds it to this list) ----

def test_the_command_line_flags_are_exactly_these():
    flags = sorted(option for action in launcher.build_parser()._actions for option in action.option_strings if option.startswith("--") and option != "--help")
    assert flags == ["--port", "--reset-state", "--set-key", "--set-key-cloudflare", "--set-key-fish",
                     "--set-key-groq", "--set-key-tinyfish"]


def test_the_port_defaults_to_8000_and_the_other_flags_are_off_by_default():
    args = launcher.build_parser().parse_args([])
    assert args.port == 8000 and not any(vars(args)[name] for name in vars(args) if name != "port")
