"""Files the page loads must be re-checked on every load, never served from Electron's disk cache.

Why: you re-encode a clip, restart the app, and the OLD clip keeps playing because the browser
engine decided it was still fresh. The same would happen to the app's own scripts after an upgrade.
`Cache-Control: no-cache` does not mean "don't store" — it means "ask the server (cheaply, with the
ETag) before using your copy", so an unchanged file still costs only a 304."""
import os

import pytest
from fastapi.testclient import TestClient

from companion.server import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPANION_FAKE", "1")  # offline doubles, in-memory history
    monkeypatch.setattr("companion.config.config_path", lambda: tmp_path / "config.json")
    monkeypatch.setattr("companion.server.user_dir", lambda: tmp_path)
    (tmp_path / "clips").mkdir()
    (tmp_path / "fillers").mkdir()
    (tmp_path / "clips" / "idle.webm").write_bytes(b"OLD-CLIP-BYTES-0123456789")
    (tmp_path / "fillers" / "hmm.mp3").write_bytes(b"FILLER-BYTES")
    c = TestClient(create_app(persona="test persona"))
    c.root = tmp_path
    return c


@pytest.mark.parametrize("url", ["/clips/idle.webm", "/fillers/hmm.mp3"])
def test_user_content_must_be_rechecked_on_every_load(client, url):
    response = client.get(url)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers.get("etag")  # the thing it is re-checked against


def test_an_unchanged_clip_is_confirmed_cheaply_with_a_304_that_still_says_no_cache(client):
    first = client.get("/clips/idle.webm")
    again = client.get("/clips/idle.webm", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304
    assert again.headers["cache-control"] == "no-cache"


def test_a_clip_that_was_re_encoded_is_picked_up_instead_of_the_old_copy(client):
    first = client.get("/clips/idle.webm")
    path = client.root / "clips" / "idle.webm"
    path.write_bytes(b"NEW-CLIP-BYTES-THAT-ARE-LONGER")
    os.utime(path, (first_mtime := path.stat().st_mtime + 10, first_mtime))
    again = client.get("/clips/idle.webm", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 200 and again.content == b"NEW-CLIP-BYTES-THAT-ARE-LONGER"
    assert again.headers["etag"] != first.headers["etag"]


def test_seeking_inside_a_video_still_works_because_range_requests_are_untouched(client):
    response = client.get("/clips/idle.webm", headers={"Range": "bytes=0-2"})
    assert response.status_code == 206 and response.content == b"OLD"
    assert response.headers["cache-control"] == "no-cache"


def test_the_apps_own_scripts_and_page_are_rechecked_too_so_an_upgrade_is_not_masked_by_old_copies(client):
    for url in ("/static/shell.js", "/static/vad.js", "/"):
        response = client.get(url)
        assert response.status_code == 200, url
        assert response.headers["cache-control"] == "no-cache", url
