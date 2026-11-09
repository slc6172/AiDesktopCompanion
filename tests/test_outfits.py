"""Outfits: every sub-folder of clips/ is one set of clothes with its own animations (spec Part 12,
ticket 73). Observed the way the page sees it — /avatar, /clips/..., and what the person is told
when the folders are not as expected."""
import json
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from companion.history import InMemoryHistory
from companion.server import create_app
from companion.state import InMemoryState


class Llm:
    def stream(self, system, messages):
        yield "好。"


class QuietTTS:
    mime_type = "audio/fake"

    def synthesize(self, text):
        return b"x"


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A throw-away user folder. `make(config=..., stored_outfit=...)` builds the app over it."""
    monkeypatch.setattr("companion.server.user_dir", lambda: tmp_path)
    monkeypatch.setattr("companion.config.config_path", lambda: tmp_path / "config.json")
    monkeypatch.delenv("COMPANION_FAKE", raising=False)
    (tmp_path / "clips").mkdir()

    def clip(*parts, content=b"v"):
        path = tmp_path.joinpath("clips", *parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def make(config=None, stored_outfit=None):
        (tmp_path / "config.json").write_text(json.dumps(config or {"stt": {"enabled": False}}), encoding="utf-8")
        state = InMemoryState()
        if stored_outfit is not None:
            state.set_outfit(stored_outfit)
        app = create_app(llm=Llm(), persona="p", tts=QuietTTS(), store=InMemoryHistory(), state_store=state)
        return TestClient(app)

    make.clip = clip
    make.root = tmp_path
    return make


def avatar(client):
    return client.get("/avatar").json()


def two_outfits(world):
    for outfit in ("日常", "睡衣"):
        world.clip(outfit, "idle.webm", content=f"{outfit}-idle".encode())
        world.clip(outfit, "talking-happy.webm", content=f"{outfit}-happy".encode())


# ---- which outfit is worn ------------------------------------------------------------------------------

def test_the_avatar_shows_the_default_outfit_and_only_its_clips(world):
    two_outfits(world)
    body = avatar(world({"outfit": {"default": "睡衣"}}))
    assert body["outfit"] == "睡衣"
    assert body["outfits"] == ["日常", "睡衣"]
    assert body["clips"] == {"idle": "/clips/" + quote("睡衣") + "/idle.webm",
                             "talking:happy": "/clips/" + quote("睡衣") + "/talking-happy.webm"}


def test_the_remembered_outfit_beats_the_configured_default(world):
    two_outfits(world)
    assert avatar(world({"outfit": {"default": "日常"}}, stored_outfit="睡衣"))["outfit"] == "睡衣"


def test_a_remembered_outfit_whose_folder_is_gone_falls_back_to_the_default(world):
    two_outfits(world)
    assert avatar(world({"outfit": {"default": "睡衣"}}, stored_outfit="已刪除"))["outfit"] == "睡衣"


def test_a_default_that_does_not_exist_falls_back_to_the_first_by_name(world):
    for outfit in ("b套", "a套"):
        world.clip(outfit, "idle.webm")
    assert avatar(world({"outfit": {"default": "不存在"}}))["outfit"] == "a套"


# ---- what counts as an outfit ------------------------------------------------------------------------------

def test_a_folder_starting_with_an_underscore_is_ignored(world):
    world.clip("日常", "idle.webm")
    world.clip("_草稿", "idle.webm")
    assert avatar(world())["outfits"] == ["日常"]


def test_a_folder_without_an_idle_clip_is_not_an_outfit_and_the_person_is_told(world, caplog):
    world.clip("日常", "idle.webm")
    world.clip("半成品", "talking-happy.webm")
    client = world()
    assert avatar(client)["outfits"] == ["日常"]
    assert any("半成品" in m and "idle" in m for m in caplog.messages)


def test_a_missing_clip_is_never_borrowed_from_another_outfit(world):
    world.clip("日常", "idle.webm")
    world.clip("日常", "talking-sad.webm")
    world.clip("睡衣", "idle.webm")                      # this one has no talking-sad of its own
    body = avatar(world({"outfit": {"default": "睡衣"}}))
    assert "talking:sad" not in body["clips"]            # the page then falls back to talking:neutral / idle, inside 睡衣


def test_webm_beats_mp4_when_an_outfit_has_both(world):
    world.clip("日常", "idle.mp4")
    world.clip("日常", "idle.webm")
    assert avatar(world())["clips"]["idle"].endswith("/idle.webm")


# ---- serving the files (Chinese folder names) -------------------------------------------------------------------

def test_the_clips_of_an_outfit_with_a_chinese_name_can_be_fetched_through_the_url_the_page_is_given(world):
    two_outfits(world)
    client = world({"outfit": {"default": "睡衣"}})
    url = avatar(client)["clips"]["idle"]
    assert "%" in url                                    # the page receives it percent-encoded
    response = client.get(url)
    assert response.status_code == 200 and response.content == "睡衣-idle".encode()


# ---- a clip lying directly in the clips folder ------------------------------------------------------------------------

def test_a_clip_lying_directly_in_the_clips_folder_is_not_used_and_not_moved(world):
    old = world.clip("idle.webm", content=b"old")
    world.clip("日常", "idle.webm")
    client = world()
    assert avatar(client)["clips"]["idle"].startswith("/clips/" + quote("日常"))   # the loose file is not used
    assert old.exists() and old.read_bytes() == b"old"                              # and not moved


def test_with_no_usable_outfit_at_all_the_character_is_the_emoji_stand_in_and_the_person_is_told(world, caplog):
    world.clip("idle.webm")                                  # only a clip outside any outfit folder
    client = world()
    body = avatar(client)
    assert (body["outfit"], body["outfits"], body["clips"]) == (None, [], {})
    messages = [e["message"] for e in sse(client.post("/chat", json={"message": "嗨"})) if e["type"] == "notice"]
    assert len(messages) == 1 and "找不到任何可用的服裝資料夾" in messages[0]


def sse(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_the_folder_warnings_reach_the_chat_only_once(world):
    world.clip("睡衣", "thinking.webm")   # an outfit folder without idle: skipped, and then nothing is usable: two warnings
    client = world()
    first = [e for e in sse(client.post("/chat", json={"message": "嗨"})) if e["type"] == "notice"]
    second = [e for e in sse(client.post("/chat", json={"message": "再來"})) if e["type"] == "notice"]
    assert len(first) == 2 and second == []


def test_a_healthy_clips_folder_says_nothing(world):
    two_outfits(world)
    client = world()
    assert [e for e in sse(client.post("/chat", json={"message": "嗨"})) if e["type"] == "notice"] == []


def test_a_clip_file_with_a_space_in_its_name_is_still_reachable_through_its_url(world):
    world.clip("日常", "idle.webm")
    world.clip("日常", "talking-happy copy.webm", content=b"spaced")
    client = world()
    url = avatar(client)["clips"]["talking:happy copy"]
    assert " " not in url
    assert client.get(url).content == b"spaced"


def test_building_the_app_with_its_own_history_store_never_creates_the_real_database(world, monkeypatch):
    monkeypatch.delenv("COMPANION_DB", raising=False)
    world.clip("日常", "idle.webm")
    (world.root / "config.json").write_text(json.dumps({"stt": {"enabled": False}}), encoding="utf-8")
    create_app(llm=Llm(), persona="p", tts=QuietTTS(), store=InMemoryHistory())   # no state_store given
    assert not (world.root / "data").exists()


# ---- asking her to change, as the page experiences it ------------------------------------------------------------

def test_asking_in_the_chat_sends_the_page_an_outfit_event_and_the_avatar_follows(world):
    two_outfits(world)
    client = world({"outfit": {"default": "日常"}, "stt": {"enabled": False}})
    events = sse(client.post("/chat", json={"message": "換成睡衣"}))
    outfit = [e for e in events if e["type"] == "outfit"]
    assert outfit == [{"type": "outfit", "name": "睡衣",
                       "clips": {"idle": "/clips/" + quote("睡衣") + "/idle.webm",
                                 "talking:happy": "/clips/" + quote("睡衣") + "/talking-happy.webm"}}]
    assert events.index(outfit[0]) < next(i for i, e in enumerate(events) if e["type"] == "sentence")
    assert avatar(client)["outfit"] == "睡衣"      # a page reload now shows her in the pajamas


def test_an_ordinary_message_sends_no_outfit_event(world):
    two_outfits(world)
    client = world()
    assert [e for e in sse(client.post("/chat", json={"message": "你好"})) if e["type"] == "outfit"] == []
