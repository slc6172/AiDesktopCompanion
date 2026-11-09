"""Emotion -> Fish tag. Only Fish gets a tag; edge-tts / PrimeTTS never do; animations unaffected."""
import json

import httpx
import pytest

from companion.engine import Audio, Sentence, TurnEngine
from companion.errors import TTSUnavailable
from companion.fish_adapter import FishTTS

TAGS = {"neutral": "", "happy": "[happy]", "sad": "[sad]", "angry": "[angry]", "surprised": "[surprised]"}


class FakeLLM:
    """Streams the given chunks, like the LLM boundary does."""

    def __init__(self, chunks):
        self.chunks = chunks

    def stream(self, system, messages):
        yield from self.chunks


@pytest.fixture(autouse=True)
def no_keyring(monkeypatch):
    monkeypatch.setattr("keyring.get_password", lambda *a, **k: None)


def fish(model="s2.1-pro-free", tags=TAGS):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content)["text"])
        return httpx.Response(200, content=b"mp3")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return FishTTS(api_key="k", model=model, client=client, emotion_tags=tags), sent


@pytest.mark.parametrize("emotion,expected", [
    ("happy", "[happy] 你好"), ("sad", "[sad] 你好"), ("angry", "[angry] 你好"),
    ("surprised", "[surprised] 你好"), ("neutral", "你好"), (None, "你好"),
])
def test_each_emotion_becomes_its_tag_in_front_of_the_sentence(emotion, expected):
    tts, sent = fish()
    tts.synthesize("你好", emotion=emotion)
    assert sent == [expected]


@pytest.mark.parametrize("model", ["s2.1-pro-free", "s2.1-pro", "s2-pro"])
def test_the_s2_models_all_use_the_same_tag_syntax(model):
    tts, sent = fish(model=model)
    tts.synthesize("好難過", emotion="sad")
    assert sent == ["[sad] 好難過"]


def test_a_legacy_model_gets_no_tag_rather_than_a_wrong_one():
    tts, sent = fish(model="s1")
    tts.synthesize("好難過", emotion="sad")
    assert sent == ["好難過"]


def test_the_tag_text_is_whatever_the_config_says():
    tts, sent = fish(tags={"happy": "[溫柔地說]"})
    tts.synthesize("嗨", emotion="happy")
    tts.synthesize("嗨", emotion="sad")  # no tag configured for it -> plain
    assert sent == ["[溫柔地說] 嗨", "嗨"]


def test_blank_text_is_still_not_sent_just_because_a_tag_exists():
    tts, sent = fish()
    assert tts.synthesize("  ", emotion="happy") == b""
    assert sent == []


class PlainTTS:  # shaped like EdgeTTS / PrimeTTS: synthesize(text) only, no emotion parameter
    mime_type = "audio/plain"

    def __init__(self):
        self.calls = []

    def synthesize(self, text):
        self.calls.append(text)
        return b"plain:" + text.encode()


class DownTTS:
    mime_type = "audio/down"
    supports_emotion = True

    def synthesize(self, text, emotion=None):
        raise TTSUnavailable("down")


def test_engines_without_emotion_support_are_called_exactly_as_before():
    plain = PlainTTS()  # would raise TypeError if the engine passed it an emotion
    events = list(TurnEngine(FakeLLM(["[sad]好難過"]), persona="p", tts=plain).send("嗨"))
    assert plain.calls == ["好難過"]
    assert Sentence("好難過", "sad") in events


def test_the_animation_emotion_is_unchanged_when_fish_is_the_voice():
    tts, sent = fish()
    events = list(TurnEngine(FakeLLM(["[happy]太好了![sad]可是好難過。"]), persona="p", tts=tts).send("嗨"))
    assert sent == ["[happy] 太好了!", "[sad] 可是好難過。"]
    assert [(e.text, e.emotion) for e in events if isinstance(e, Audio)] == [
        ("太好了!", "happy"), ("可是好難過。", "sad")]  # Audio keeps the clean sentence + emotion


def test_when_fish_is_down_the_fallback_never_receives_a_tag():
    plain = PlainTTS()
    events = list(TurnEngine(FakeLLM(["[angry]別這樣!"]), persona="p", tts=DownTTS(),
                             tts_fallback=plain).send("嗨"))
    assert plain.calls == ["別這樣!"]
    assert any(isinstance(e, Audio) and e.emotion == "angry" for e in events)


def test_the_one_same_engine_retry_after_an_empty_answer_carries_the_tag_too():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content)["text"])
        return httpx.Response(200, content=b"" if len(sent) == 1 else b"mp3")   # first answer has no audio

    tts = FishTTS(api_key="k", client=httpx.Client(transport=httpx.MockTransport(handler)), emotion_tags=TAGS)
    events = list(TurnEngine(FakeLLM(["[sad]好難過"]), persona="p", tts=tts).send("嗨"))
    assert sent == ["[sad] 好難過", "[sad] 好難過"]          # tried twice, both with the tag
    assert any(isinstance(e, Audio) for e in events)
