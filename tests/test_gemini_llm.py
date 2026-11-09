import json

import httpx
import pytest
from google.genai import errors as genai_errors

from companion.errors import LLMError
from companion.engine import UserImage
from companion.gemini_llm import GeminiLLM

SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}, "facts": {"type": "array", "items": {"type": "string"}}},
    "required": ["summary", "facts"],
}


class _Response:
    def __init__(self, text):
        self.text = text


class _Chunk:
    def __init__(self, text):
        self.text = text


class _FakeStreamModels:
    """Stands in for client.models when only generate_content_stream is exercised (the image
    tests care about what `contents` was built with, not about summaries)."""

    def __init__(self, chunks):
        self.chunks = chunks
        self.calls = []

    def generate_content_stream(self, **kwargs):
        self.calls.append(kwargs)
        return (_Chunk(c) for c in self.chunks)


class _FakeStreamClient:
    def __init__(self, chunks):
        self.models = _FakeStreamModels(chunks)


class _FakeModels:
    """Stands in for client.models: returns (or raises) one scripted outcome per call."""

    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return _Response(self.outcome)


class _FakeClient:
    def __init__(self, outcome):
        self.models = _FakeModels(outcome)


def make_llm(monkeypatch, outcome):
    monkeypatch.setattr("companion.gemini_llm.genai.Client", lambda **kwargs: _FakeClient(outcome))
    return GeminiLLM(api_key="test-key")


MESSAGES = [{"role": "user", "content": "請整理"}]


def test_structured_output_comes_back_as_a_parsed_object(monkeypatch):
    llm = make_llm(monkeypatch, json.dumps({"summary": "聊過貓", "facts": ["喜歡貓"]}, ensure_ascii=False))
    assert llm.generate_structured("整理記憶", MESSAGES, SCHEMA) == {"summary": "聊過貓", "facts": ["喜歡貓"]}


def test_the_request_asks_the_model_for_json_that_matches_the_schema(monkeypatch):
    llm = make_llm(monkeypatch, "{}")
    llm.generate_structured("整理記憶", MESSAGES, SCHEMA)

    call = llm._client.models.calls[0]
    config = call["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == SCHEMA
    assert config.system_instruction == "整理記憶"
    assert [c.role for c in call["contents"]] == ["user"]
    assert call["contents"][0].parts[0].text == "請整理"


def test_assistant_messages_are_sent_as_the_models_own_turns(monkeypatch):
    llm = make_llm(monkeypatch, "{}")
    llm.generate_structured("s", [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}], SCHEMA)
    assert [c.role for c in llm._client.models.calls[0]["contents"]] == ["user", "model"]


@pytest.mark.parametrize("bad", [None, "", "not json at all", '{"summary": "cut off'])
def test_an_empty_or_broken_reply_is_an_error_not_a_made_up_object(monkeypatch, bad):
    llm = make_llm(monkeypatch, bad)
    with pytest.raises(ValueError):  # json.JSONDecodeError is a ValueError too
        llm.generate_structured("s", MESSAGES, SCHEMA)


def test_rate_limiting_is_translated_like_it_is_for_normal_chat(monkeypatch):
    llm = make_llm(monkeypatch, genai_errors.ClientError(429, {"error": {"message": "quota"}}))
    with pytest.raises(LLMError) as exc_info:
        llm.generate_structured("s", MESSAGES, SCHEMA)
    assert exc_info.value.kind == "rate_limit"


def test_a_timeout_is_translated_like_it_is_for_normal_chat(monkeypatch):
    request = httpx.Request("POST", "https://generativelanguage.googleapis.com/")
    llm = make_llm(monkeypatch, httpx.ReadTimeout("slow", request=request))
    with pytest.raises(LLMError) as exc_info:
        llm.generate_structured("s", MESSAGES, SCHEMA)
    assert exc_info.value.kind == "timeout"


def test_an_attached_image_becomes_an_extra_part_sent_before_the_text(monkeypatch):
    monkeypatch.setattr("companion.gemini_llm.genai.Client", lambda **kwargs: _FakeStreamClient(["嗨"]))
    llm = GeminiLLM(api_key="test-key")
    message = {"role": "user", "content": "你看我家貓", "image": UserImage(b"fake-png-bytes", "image/png")}
    list(llm.stream("s", [message]))

    parts = llm._client.models.calls[0]["contents"][0].parts
    assert len(parts) == 2
    assert parts[0].inline_data.data == b"fake-png-bytes"
    assert parts[0].inline_data.mime_type == "image/png"
    assert parts[1].text == "你看我家貓"


def test_a_message_without_an_image_still_sends_just_the_text_part(monkeypatch):
    monkeypatch.setattr("companion.gemini_llm.genai.Client", lambda **kwargs: _FakeStreamClient(["嗨"]))
    llm = GeminiLLM(api_key="test-key")
    list(llm.stream("s", [{"role": "user", "content": "嗨"}]))

    parts = llm._client.models.calls[0]["contents"][0].parts
    assert len(parts) == 1
    assert parts[0].text == "嗨"
