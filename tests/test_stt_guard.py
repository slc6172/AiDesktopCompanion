from companion.server import is_likely_non_speech_transcript


def test_generic_music_caption_is_rejected_only_for_short_continuous_turns():
    assert is_likely_non_speech_transcript("Music", "continuous", 1200)
    assert not is_likely_non_speech_transcript("Music", "hold", 1200)
    assert not is_likely_non_speech_transcript("Music", "continuous", 4000)


def test_generic_video_caption_is_rejected_in_continuous_mode():
    assert is_likely_non_speech_transcript("Thanks for watching!", "continuous", 9000)
    assert is_likely_non_speech_transcript("字幕由 Amara.org 社群提供", "continuous", 9000)


def test_realistic_chinese_and_english_speech_are_not_filtered():
    assert not is_likely_non_speech_transcript("我想聽音樂", "continuous", 1500)
    assert not is_likely_non_speech_transcript("Stop", "continuous", 500)
    assert not is_likely_non_speech_transcript("Music helps me focus", "continuous", 1800)


# ---- through the real endpoint: the same "didn't catch that" path an empty transcript takes ----

import json

import pytest
from fastapi.testclient import TestClient

from companion.server import create_app


class Heard:
    def __init__(self, text):
        self.text = text

    def transcribe(self, data, mime):
        return self.text


class CountingLLM:
    def __init__(self):
        self.calls = 0

    def stream(self, system, messages):
        self.calls += 1
        yield "[happy]好。"


def post(text, voice_mode=None, duration=None, monkeypatch=None):
    llm = CountingLLM()
    client = TestClient(create_app(llm=llm, stt=Heard(text), persona="test persona"))
    headers = {"Content-Type": "audio/webm"}
    if voice_mode is not None:
        headers["X-Voice-Mode"] = voice_mode
    if duration is not None:
        headers["X-Voice-Duration-Ms"] = duration.encode("latin-1")   # bytes: HTTP headers are latin-1, and "²" is not ASCII
    res = client.post("/chat/audio", content=b"\x00" * 100, headers=headers)
    events = [json.loads(line[len("data: "):]) for line in res.text.splitlines() if line.startswith("data: ")]
    return res, events, llm


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setenv("COMPANION_FAKE", "1")


def test_a_short_continuous_music_caption_is_answered_like_an_empty_transcript_and_never_reaches_the_character():
    res, events, llm = post("Music", "continuous", "1200")
    _, empty_events, _ = post("", "continuous", "1200")
    assert res.status_code == 200
    assert events == empty_events                                  # exactly the same error event as "heard nothing"
    assert events[0]["type"] == "error" and "沒聽清楚" in events[0]["message"]
    assert llm.calls == 0


def test_the_same_words_in_hold_to_talk_mode_are_answered_normally():
    _, events, llm = post("Music", "hold", "1200")
    assert [e["type"] for e in events][0] == "transcript" and events[0]["text"] == "Music"
    assert llm.calls == 1


def test_a_long_continuous_clip_with_the_same_word_is_answered_normally():
    _, events, llm = post("Music", "continuous", "4000")
    assert events[0]["type"] == "transcript" and llm.calls == 1


def test_without_the_voice_headers_nothing_is_filtered():
    _, events, llm = post("Music")
    assert events[0]["type"] == "transcript" and llm.calls == 1


@pytest.mark.parametrize("bad", [b"abc", b"-5", b"12.5", b"", b"99999999999999999999", b"\xb2", b"\xbd"])
def test_a_garbage_duration_header_never_breaks_the_request(bad):
    """Raw ASGI call: the test client would re-encode a non-ASCII header value, so it would never arrive as sent.
    (b"\xb2" is "²": str.isdigit() is True for it, but int("²") raises.)"""
    import asyncio

    app = create_app(llm=CountingLLM(), stt=Heard("Music"), persona="test persona")
    headers = [(b"host", b"127.0.0.1"), (b"content-type", b"audio/webm"), (b"x-voice-mode", b"continuous"), (b"x-voice-duration-ms", bad)]
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "http",
             "path": "/chat/audio", "raw_path": b"/chat/audio", "query_string": b"", "headers": headers,
             "server": ("test", 80), "client": ("test", 1)}
    sent = []

    body_sent = False

    async def receive():
        nonlocal body_sent
        if not body_sent:
            body_sent = True
            return {"type": "http.request", "body": b"\x00" * 100, "more_body": False}
        await asyncio.Event().wait()   # a streaming response listens for a disconnect; it is cancelled once the stream ends

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    assert sent[0]["type"] == "http.response.start" and sent[0]["status"] == 200
