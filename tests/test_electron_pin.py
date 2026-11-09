"""The Electron version is pinned: Electron ships a whole browser, so an unnoticed upgrade changes
what the pet window is made of. Upgrading is a deliberate act (see CONTRIBUTING.md) that changes
EXPECTED here, package.json and the lock file together."""
import json
from pathlib import Path

ELECTRON = Path(__file__).resolve().parent.parent / "electron"
EXPECTED = "45.2.2"


def test_package_json_names_one_exact_electron_version():
    package = json.loads((ELECTRON / "package.json").read_text(encoding="utf-8"))
    assert package["devDependencies"]["electron"] == EXPECTED


def test_the_lock_file_agrees_with_package_json_and_resolves_the_same_version():
    lock = json.loads((ELECTRON / "package-lock.json").read_text(encoding="utf-8"))
    assert lock["packages"][""]["devDependencies"]["electron"] == EXPECTED
    assert lock["packages"]["node_modules/electron"]["version"] == EXPECTED


def test_npm_install_in_the_electron_folder_also_fetches_the_program():
    """Electron 42 and later no longer download their executable during npm install; the project asks for it explicitly, so
    the install stays one command. Manual downloaders skip it with `npm install --ignore-scripts`."""
    package = json.loads((ELECTRON / "package.json").read_text(encoding="utf-8"))
    assert package["scripts"]["postinstall"] == "install-electron"


def test_the_node_version_the_docs_ask_for_is_the_one_the_electron_package_requires():
    package = json.loads((ELECTRON / "package.json").read_text(encoding="utf-8"))
    assert package["engines"]["node"] == ">=22.12.0"
    needed = package["engines"]["node"].removeprefix(">=").rsplit(".", 1)[0]  # "22.12"
    root = ELECTRON.parent
    for name in ("README.md", "README.en.md", "docs/install.md"):
        text = (root / name).read_text(encoding="utf-8")
        assert needed in text, f"{name} must ask for Node {needed} or newer"
        assert "Node.js 18" not in text and "18 或更新" not in text and "18 or newer" not in text
