"""Photos at the HTTP edge (spec Part 12, section 5, ticket 89): the route that serves them, the shape of the
`photo` event the page receives, what the person is told at startup, and that a program with photos switched
off never loads the picture library."""
import json
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient

from companion.engine import Notice, Photo
from companion.history import InMemoryHistory
from companion.server import create_app, event_to_dict
from companion.state import InMemoryState

PNG = b"\x89PNG\r\n\x1a\n" + b"fake-picture"


class FakeCloudflare:
    def __init__(self):
        self.calls = []

    def generate(self, prompt, reference=None, width=576, height=1024):
        self.calls.append((prompt, reference))
        return PNG


class Llm:
    def __init__(self, reply="[照片:現在|by the window][happy]好啊。"):
        self.reply, self.systems = reply, []

    def stream(self, system, messages):
        self.systems.append(system)
        yield self.reply


class QuietTTS:
    mime_type = "audio/fake"

    def synthesize(self, text):
        return b"x"


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr("companion.server.user_dir", lambda: tmp_path)
    monkeypatch.setattr("companion.config.config_path", lambda: tmp_path / "config.json")
    for name in ("COMPANION_FAKE", "CF_API_TOKEN", "CF_ACCOUNT_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CF_API_TOKEN", "token")
    monkeypatch.setenv("CF_ACCOUNT_ID", "acct")
    (tmp_path / "clips" / "日常").mkdir(parents=True)
    (tmp_path / "clips" / "日常" / "idle.webm").write_bytes(b"v")

    def make(image=None, config=None, llm=None, store=None, **kwargs):
        settings = {"stt": {"enabled": False}, "image": {"enabled": True, "appearance": "a young woman"}, **(config or {})}
        (tmp_path / "config.json").write_text(json.dumps(settings), encoding="utf-8")
        return TestClient(create_app(llm=llm or Llm(), persona="p", tts=QuietTTS(), store=store or InMemoryHistory(),
                                     state_store=InMemoryState(), image=image, **kwargs))

    make.root = tmp_path
    return make


def events_of(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def wait_for_a_photo(root, seconds=5):
    folder = root / "data" / "photos"
    deadline = time.time() + seconds
    while time.time() < deadline:
        found = sorted(folder.glob("*")) if folder.exists() else []
        if found:
            return found[0]
        time.sleep(0.02)
    raise AssertionError("no photo was saved")


def test_a_photo_she_takes_is_saved_and_served_from_the_local_photo_route(world):
    cloudflare = FakeCloudflare()
    client = world(image=cloudflare)
    reply = client.post("/chat", json={"message": "拍一張給我看"})
    assert [e["type"] for e in events_of(reply)][-1] == "done"           # the reply is over; the picture is not part of it
    saved = wait_for_a_photo(world.root)
    served = client.get(f"/photos/{saved.name}")
    assert served.status_code == 200 and served.content == PNG
    assert len(cloudflare.calls) == 1


def test_the_photo_route_serves_nothing_outside_the_photo_folder(world):
    client = world(image=FakeCloudflare())
    (world.root / "data").mkdir(exist_ok=True)
    (world.root / "data" / "secret.txt").write_text("private", encoding="utf-8")
    for path in ("/photos/../secret.txt", "/photos/..%2fsecret.txt", "/photos/%2e%2e/secret.txt", "/photos/nothing.png"):
        response = client.get(path)
        assert response.status_code == 404 and b"private" not in response.content


def test_the_page_is_sent_a_local_path_and_never_a_remote_address():
    assert event_to_dict(Photo("20270115-080000.png", "/photos/20270115-080000.png")) == {
        "type": "photo", "file": "20270115-080000.png", "url": "/photos/20270115-080000.png"}
    assert event_to_dict(Notice("photo", "📷 這張照片沒拍成。")) == {
        "type": "notice", "kind": "photo", "message": "📷 這張照片沒拍成。"}


def test_without_a_base_photo_or_an_appearance_she_is_warned_at_startup_but_still_tries(world):
    cloudflare = FakeCloudflare()
    client = world(image=cloudflare, config={"image": {"enabled": True}})
    first = events_of(client.post("/chat", json={"message": "拍一張"}))
    warnings = [e["message"] for e in first if e["type"] == "notice"]
    assert any("日常" in message and "基底" in message for message in warnings)
    wait_for_a_photo(world.root)
    assert len(cloudflare.calls) == 1                                      # a warning, not a refusal


def test_no_warning_when_there_is_an_appearance_or_the_base_photo(world):
    client = world(image=FakeCloudflare())                                  # the fixture's config has an appearance
    assert not [e for e in events_of(client.post("/chat", json={"message": "嗨"})) if e["type"] == "notice"]
    from PIL import Image

    Image.new("RGB", (100, 100)).save(world.root / "clips" / "日常" / "base.png")
    client = world(image=FakeCloudflare(), config={"image": {"enabled": True}})
    assert not [e for e in events_of(client.post("/chat", json={"message": "嗨"})) if e["type"] == "notice"]


def test_photos_switched_off_means_no_mention_to_her_and_no_call(world):
    cloudflare, llm = FakeCloudflare(), Llm()
    client = world(image=cloudflare, llm=llm, config={"image": {"enabled": False}})
    events = events_of(client.post("/chat", json={"message": "拍一張"}))
    assert "照片" not in llm.systems[0]
    assert [e["type"] for e in events] == ["sentence", "audio", "done"]     # the tag was only cut out
    time.sleep(0.1)
    assert cloudflare.calls == []


def test_without_the_cloudflare_key_photos_are_off_and_she_is_not_told_about_them(world, monkeypatch):
    monkeypatch.delenv("CF_API_TOKEN")
    monkeypatch.setattr("companion.apikey.get_api_key", lambda provider="gemini": None)
    monkeypatch.setattr("companion.features.get_api_key", lambda provider="gemini": None)
    llm = Llm()
    client = world(llm=llm)
    first = events_of(client.post("/chat", json={"message": "嗨"}))
    assert "照片" not in llm.systems[0]
    assert any(e["type"] == "notice" and "Cloudflare" in e["message"] for e in first)


def test_a_program_with_photos_off_never_loads_the_picture_library(tmp_path):
    script = f"""
import json, sys
from pathlib import Path
root = Path({str(tmp_path)!r})
(root / "clips" / "日常").mkdir(parents=True)
(root / "clips" / "日常" / "idle.webm").write_bytes(b"v")
(root / "config.json").write_text(json.dumps({{"stt": {{"enabled": False}}, "image": {{"enabled": False}}}}))
import companion.server as server
server.user_dir = lambda: root
import companion.config as config
config.config_path = lambda: root / "config.json"
from fastapi.testclient import TestClient
from companion.history import InMemoryHistory
from companion.state import InMemoryState
class Llm:
    def stream(self, system, messages):
        yield "[照片:現在|x][happy]好啊。"
class Tts:
    mime_type = "audio/fake"
    def synthesize(self, text):
        return b"x"
client = TestClient(server.create_app(llm=Llm(), persona="p", tts=Tts(), store=InMemoryHistory(), state_store=InMemoryState()))
client.post("/chat", json={{"message": "拍一張"}})
client.get("/avatar")
print("PIL" in sys.modules)
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, cwd=".",
                            env={**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "False"


def test_after_a_restart_the_history_still_shows_the_photo_and_the_route_still_serves_it(world):
    history = InMemoryHistory()                     # stands in for the same database file across the restart
    first = world(image=FakeCloudflare(), store=history)
    first.post("/chat", json={"message": "拍一張給我看"})
    saved = wait_for_a_photo(world.root)
    second = world(image=FakeCloudflare(), store=history)           # a fresh app over the same history and photo folder
    items = second.get("/history").json()
    her = items[-1]
    assert her["photo"] == {"file": saved.name, "url": f"/photos/{saved.name}", "exists": True}
    assert second.get(her["photo"]["url"]).content == PNG
    assert her["role"] == "assistant" and her["text"] == "好啊。" and her["emotions"] == ["happy"]
    assert items[0] == {"role": "user", "text": "拍一張給我看"}      # the user's side is exactly as before


def test_a_photo_the_person_deleted_is_listed_as_missing_and_nothing_breaks(world):
    history = InMemoryHistory()
    client = world(image=FakeCloudflare(), store=history)
    client.post("/chat", json={"message": "拍一張"})
    saved = wait_for_a_photo(world.root)
    saved.unlink()
    response = client.get("/history")
    assert response.status_code == 200
    photo = response.json()[-1]["photo"]
    assert photo["exists"] is False and photo["file"] is None and photo["url"] is None
    assert client.get(f"/photos/{saved.name}").status_code == 404


def test_a_photo_that_never_got_made_is_also_just_missing(world):
    class Down(FakeCloudflare):
        def generate(self, *a, **k):
            raise RuntimeError("service down")

    history = InMemoryHistory()
    client = world(image=Down(), store=history)
    client.post("/chat", json={"message": "拍一張"})
    time.sleep(0.2)
    assert client.get("/history").json()[-1]["photo"]["exists"] is False
