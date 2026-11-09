"""M1: the server refuses DNS rebinding (a foreign Host) and other web pages (a foreign Origin).
L1: a push stream that is gone gives its thread back; request sizes are capped before work is done."""
import time

import pytest
from fastapi.testclient import TestClient

from companion import server
from companion.history import InMemoryHistory
from companion.state import InMemoryState


class _Llm:
    def stream(self, system, messages):
        yield "[心情:neutral]好"

    def generate(self, *a, **k):
        return ""


def _client(**kw):
    return TestClient(server.create_app(llm=_Llm(), persona="p", tts=None, store=InMemoryHistory(),
                                        state_store=InMemoryState(), **kw))


@pytest.fixture
def client():
    return _client()


@pytest.mark.parametrize("host", ["evil.example.com", "evil.example.com:8000", "127.0.0.1.evil.com", "localhost.evil.com:1", ""])
def test_a_foreign_host_is_refused_on_every_route(client, host):
    for path in ("/history", "/config", "/avatar", "/"):
        assert client.get(path, headers={"Host": host}).status_code == 403


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.1:8000", "localhost", "localhost:51234", "LOCALHOST"])
def test_this_machines_own_names_are_accepted(client, host):
    assert client.get("/config", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize("origin", ["https://evil.example.com", "http://evil.com:8000", "null", "http://127.0.0.1.evil.com"])
def test_a_foreign_origin_is_refused(client, origin):
    assert client.get("/history", headers={"Origin": origin}).status_code == 403
    assert client.post("/chat", json={"message": "hi"}, headers={"Origin": origin}).status_code == 403


def test_the_pets_own_origin_is_accepted(client):
    assert client.get("/history", headers={"Origin": "http://127.0.0.1:8000"}).status_code == 200
    assert client.get("/history", headers={"Origin": "http://localhost:8000"}).status_code == 200


def test_no_origin_header_is_accepted(client):
    assert client.get("/history").status_code == 200


# ---- L1: sizes ----

def test_an_overlong_message_is_refused_before_it_reaches_the_model(client):
    assert client.post("/chat", json={"message": "字" * (server.MAX_MESSAGE_CHARS + 1)}).status_code == 422
    assert client.post("/chat", json={"message": "字" * server.MAX_MESSAGE_CHARS}).status_code == 200


def test_an_oversized_image_text_is_refused_before_it_is_decoded(client):
    huge = "A" * (server.MAX_IMAGE_BASE64_CHARS + 1)
    assert client.post("/chat", json={"message": "x", "image_data": huge, "image_mime": "image/png"}).status_code == 422


def _audio_client():
    class Stt:
        def transcribe(self, data, mime):
            return "你好"

    return _client(stt=Stt())


def test_an_oversized_recording_is_refused_by_its_declared_length():
    c = _audio_client()
    r = c.post("/chat/audio", content=b"x" * (server.MAX_AUDIO_BYTES + 1), headers={"Content-Type": "audio/webm"})
    assert r.status_code == 413


def test_an_oversized_recording_without_a_length_is_refused_while_it_streams():
    c = _audio_client()

    def body():
        for _ in range(server.MAX_AUDIO_BYTES // (1024 * 1024) + 2):
            yield b"x" * (1024 * 1024)

    r = c.post("/chat/audio", content=body(), headers={"Content-Type": "audio/webm"})  # generator body: chunked, no Content-Length
    assert r.status_code == 413


def test_a_normal_recording_still_works():
    c = _audio_client()
    r = c.post("/chat/audio", content=b"abc", headers={"Content-Type": "audio/webm"})
    assert r.status_code == 200 and '"transcript"' in r.text


# ---- L1: push stream (needs a real server: the in-process TestClient cannot read an endless stream) ----

@pytest.fixture
def live(monkeypatch):
    import socket
    import threading

    import httpx
    import uvicorn

    monkeypatch.setattr(server, "PROACTIVE_KEEPALIVE_S", 0.05)
    monkeypatch.setattr(server, "MAX_PROACTIVE_LISTENERS", 1)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    app = server.create_app(llm=_Llm(), persona="p", tts=None, store=InMemoryHistory(), state_store=InMemoryState())
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5)
    srv.should_exit = True
    thread.join(5)


def test_the_push_stream_sends_a_keepalive_comment_when_idle(live):
    with live.stream("GET", "/chat/proactive") as r:
        assert r.status_code == 200
        assert next(r.iter_lines()).startswith(":")


def test_too_many_push_streams_are_refused_and_a_closed_one_frees_its_slot(live):
    with live.stream("GET", "/chat/proactive") as first:
        assert first.status_code == 200
        next(first.iter_lines())
        assert live.get("/chat/proactive").status_code == 429
    deadline = time.time() + 5
    while time.time() < deadline:
        with live.stream("GET", "/chat/proactive") as again:
            if again.status_code == 200:
                return
        time.sleep(0.1)
    pytest.fail("the slot was never freed after the stream closed")
