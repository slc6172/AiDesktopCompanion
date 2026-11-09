"""Where the program finds its page and its user files: next to app.py, i.e. the project folder."""
from pathlib import Path

from companion import paths

PROJECT = Path(__file__).resolve().parent.parent


def test_the_project_folder_is_the_one_that_holds_app_py_and_the_page():
    assert paths.project_dir() == PROJECT
    assert (paths.project_dir() / "app.py").is_file()
    assert (paths.project_dir() / "static" / "index.html").is_file()


def test_user_files_live_in_the_project_folder():
    assert paths.user_dir() == PROJECT
