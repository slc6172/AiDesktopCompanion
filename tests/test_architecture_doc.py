"""docs/architecture.md is a map of the code, written from the code. These tests keep the map from going stale: every module
is on it, the event types and the tags are the real ones, the routes are the real ones, and every file it names exists."""
import dataclasses
import re
from pathlib import Path

import pytest

from companion import engine
from companion.tags import REGISTRY
from tests.repo_scan import ROOT, mentioned_files_that_do_not_exist

DOC = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
MODULES = sorted(p.name for p in (ROOT / "companion").glob("*.py") if p.name != "__init__.py")
EVENTS = [name for name, obj in vars(engine).items()
          if isinstance(obj, type) and dataclasses.is_dataclass(obj) and not name.startswith("_") and name != "UserImage"]
ROUTES = ["/chat", "/chat/audio", "/chat/proactive", "/avatar", "/config", "/history", "/photos/"]
GENERATED = {"config.json", "persona.md", "history.db", "app.log", "window-state.json"}


@pytest.mark.parametrize("module", MODULES)
def test_every_module_of_the_companion_package_is_on_the_map(module):
    assert f"`{module}`" in DOC


@pytest.mark.parametrize("event", EVENTS)
def test_every_event_the_engine_can_emit_is_named(event):
    assert f"`{event}`" in DOC


def test_the_event_list_it_checks_is_the_real_one():
    assert {"Sentence", "Audio", "Notice", "Failure", "Done", "OutfitChange", "Photo", "Transcript"} <= set(EVENTS)


@pytest.mark.parametrize("tag", sorted(REGISTRY))
def test_every_tag_the_model_may_write_is_named_with_its_family(tag):
    assert f"[{tag}" in DOC
    assert REGISTRY[tag].family in ("meta", "action")


def test_it_states_which_tags_are_taken_anywhere_and_which_only_at_the_start_of_a_reply():
    assert "回覆開頭" in DOC and "polluted" in DOC


@pytest.mark.parametrize("route", ROUTES)
def test_every_route_of_the_server_is_listed(route):
    assert f"`{route}" in DOC


def test_every_file_it_names_exists_or_is_created_by_the_reader_or_the_program():
    assert mentioned_files_that_do_not_exist(DOC, GENERATED, search=("", "docs", "companion", "static", "electron")) == []


def test_it_stays_short_enough_to_read_in_one_sitting():
    assert len(DOC.splitlines()) <= 200


def test_the_archive_folder_says_what_it_is():
    archive = (ROOT / "docs" / "design-archive" / "README.md").read_text(encoding="utf-8")
    assert "歷史" in archive and "以程式碼為準" in archive and "architecture.md" in archive
