"""First start with no character animation at all (the repository ships none): the program must still
start and chat (the face falls back to an emoji), and the first reply must say where to learn how to
make animation. No guided set-up screen: just the notice."""
import json
import types

import pytest
from fastapi.testclient import TestClient

from companion.server import create_app

TUTORIAL = "docs/animation-tutorial.md"


def sse(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def make_client(tmp_path, monkeypatch, layout):
    monkeypatch.setenv("COMPANION_FAKE", "1")
    monkeypatch.setattr("companion.fake_tts.time", types.SimpleNamespace(sleep=lambda seconds: None))  # no pretend delay
    monkeypatch.setattr("companion.config.config_path", lambda: tmp_path / "config.json")
    monkeypatch.setattr("companion.features.get_api_key", lambda provider="gemini": None)  # never ask the real key store
    monkeypatch.setattr("companion.server.user_dir", lambda: tmp_path)
    if layout == "empty clips folder":
        (tmp_path / "clips").mkdir()
    elif layout == "only a draft folder":
        (tmp_path / "clips" / "_草稿").mkdir(parents=True)
        (tmp_path / "clips" / "_草稿" / "idle.webm").write_bytes(b"v")
    elif layout == "an outfit folder without idle":
        (tmp_path / "clips" / "日常").mkdir(parents=True)
    return TestClient(create_app(persona="test persona"))


LAYOUTS = ["no clips folder", "empty clips folder", "only a draft folder", "an outfit folder without idle"]


@pytest.fixture(params=LAYOUTS)
def client(request, tmp_path, monkeypatch):
    return make_client(tmp_path, monkeypatch, request.param)


def test_the_avatar_has_no_outfits_and_no_clips_instead_of_failing(client):
    reply = client.get("/avatar")
    assert reply.status_code == 200
    body = reply.json()
    assert body["outfits"] == [] and body["clips"] == {}


def test_a_text_chat_works_and_ends_normally(client):
    events = sse(client.post("/chat", json={"message": "嗨"}))
    kinds = [e["type"] for e in events]
    assert "sentence" in kinds and kinds[-1] == "done" and "error" not in kinds


def test_the_first_reply_says_where_to_learn_to_make_animation(client):
    notices = [e["message"] for e in sse(client.post("/chat", json={"message": "嗨"})) if e["type"] == "notice"]
    assert any(TUTORIAL in message for message in notices), notices


def test_the_notice_is_said_once_not_on_every_turn(client):
    sse(client.post("/chat", json={"message": "嗨"}))
    second = [e for e in sse(client.post("/chat", json={"message": "再來"})) if e["type"] == "notice"]
    assert second == []
