"""The exit button lives in the page (static/index.html). The two-step logic is unit-tested in tests_js; this
only guards that the page really has the button, at the top of the toolbar, and that the click-through
hit-test knows about it (otherwise it would be unclickable while click-through is on)."""
import re

import pytest
from fastapi.testclient import TestClient

from companion.server import create_app


@pytest.fixture
def page(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPANION_FAKE", "1")
    monkeypatch.setattr("companion.config.config_path", lambda: tmp_path / "config.json")
    monkeypatch.setattr("companion.server.user_dir", lambda: tmp_path)
    return TestClient(create_app(persona="test persona")).get("/").text


def test_the_toolbar_has_an_exit_button_above_all_other_buttons(page):
    tools = page[page.index('id="tools"'):page.index('id="gear"')]
    assert 'id="exitBtn"' in tools
    assert tools.index('id="exitBtn"') < tools.index('id="handle"')


def test_the_exit_button_is_among_the_regions_that_take_the_mouse_when_the_toolbar_is_open(page):
    regions = re.search(r"function hitRegions\(\).*?\n}\n", page, re.S).group()
    assert '"exitBtn"' in regions
