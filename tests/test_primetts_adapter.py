import json

import httpx
import pytest

from companion.errors import TTSUnavailable
from companion.primetts_adapter import PrimeTTS, PrimeTTSNotConfigured


def make_tts(handler, **kwargs):
    """Build a PrimeTTS whose HTTP client is an in-memory fake: `handler(request)` plays the
    part of the local OpenAI-compatible server. Returns (tts, requests_seen)."""
    seen = []

    def recording_handler(request):
        seen.append(request)
        return handler(request)

    client = httpx.Client(transport=httpx.MockTransport(recording_handler))
    kwargs.setdefault("base_url", "http://127.0.0.1:8880/v1")
    return PrimeTTS(client=client, **kwargs), seen


def ok(body=b"RIFF....WAVEdata"):
    return lambda request: httpx.Response(200, content=body)


def test_text_is_posted_to_the_speech_endpoint_and_the_audio_bytes_come_back():
    tts, seen = make_tts(ok(b"audio-bytes"), model="primetts", voice="xinran")
    assert tts.synthesize("你好呀") == b"audio-bytes"

    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == "http://127.0.0.1:8880/v1/audio/speech"
    assert json.loads(request.content) == {
        "model": "primetts", "voice": "xinran", "input": "你好呀", "response_format": "wav",
    }


def test_a_trailing_slash_on_the_base_url_is_tolerated():
    tts, seen = make_tts(ok(), base_url="http://127.0.0.1:8880/v1/")
    tts.synthesize("嗨")
    assert str(seen[0].url) == "http://127.0.0.1:8880/v1/audio/speech"


def test_mime_type_follows_the_requested_audio_format():
    assert make_tts(ok(), response_format="wav")[0].mime_type == "audio/wav"
    assert make_tts(ok(), response_format="mp3")[0].mime_type == "audio/mpeg"


def test_an_unsupported_audio_format_is_rejected_up_front():
    with pytest.raises(ValueError):
        make_tts(ok(), response_format="pcm")  # raw PCM has no container the browser can play


def test_nothing_to_say_is_an_empty_result_and_never_reaches_the_server():
    tts, seen = make_tts(ok())
    assert tts.synthesize("   ") == b""
    assert tts.synthesize("") == b""
    assert seen == []  # OpenAI-style servers reject empty input; asking would only produce an error


def test_a_successful_response_with_no_audio_is_an_empty_result_not_an_error():
    tts, _ = make_tts(ok(b""))
    assert tts.synthesize("嗯") == b""


def test_a_server_side_error_means_the_engine_is_unavailable():
    tts, _ = make_tts(lambda request: httpx.Response(500, json={"error": "model crashed"}))
    with pytest.raises(TTSUnavailable):
        tts.synthesize("你好")


def test_the_local_server_being_down_means_the_engine_is_unavailable():
    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)

    tts, _ = make_tts(refuse)
    with pytest.raises(TTSUnavailable):
        tts.synthesize("你好")


def test_a_timeout_means_the_engine_is_unavailable():
    def hang(request):
        raise httpx.ReadTimeout("too slow", request=request)

    tts, _ = make_tts(hang)
    with pytest.raises(TTSUnavailable):
        tts.synthesize("你好")


def test_a_client_error_is_a_configuration_problem_and_is_not_disguised_as_unavailable():
    # A wrong model or voice name (400/404) must not quietly send every sentence to the
    # fallback forever; it stays an ordinary failure so the user sees the voice notice.
    tts, _ = make_tts(lambda request: httpx.Response(404, json={"error": "no such voice"}))
    with pytest.raises(httpx.HTTPStatusError):
        tts.synthesize("你好")


def test_an_api_key_is_sent_as_a_bearer_token_only_when_configured():
    with_key, seen_with = make_tts(ok(), api_key="sk-local")
    with_key.synthesize("嗨")
    assert seen_with[0].headers["authorization"] == "Bearer sk-local"

    without_key, seen_without = make_tts(ok())
    without_key.synthesize("嗨")
    assert "authorization" not in seen_without[0].headers


def test_settings_come_from_the_environment_when_not_passed_in(monkeypatch):
    monkeypatch.setenv("COMPANION_PRIMETTS_URL", "http://10.0.0.5:9000/v1")
    monkeypatch.setenv("COMPANION_PRIMETTS_MODEL", "prime-v21")
    monkeypatch.setenv("COMPANION_PRIMETTS_VOICE", "anchen")
    monkeypatch.setenv("COMPANION_PRIMETTS_FORMAT", "mp3")
    monkeypatch.setenv("COMPANION_PRIMETTS_API_KEY", "sk-env")
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=b"x")

    tts = PrimeTTS(client=httpx.Client(transport=httpx.MockTransport(handler)))
    tts.synthesize("嗨")

    assert str(seen[0].url) == "http://10.0.0.5:9000/v1/audio/speech"
    assert json.loads(seen[0].content) == {
        "model": "prime-v21", "voice": "anchen", "input": "嗨", "response_format": "mp3",
    }
    assert seen[0].headers["authorization"] == "Bearer sk-env"
    assert tts.mime_type == "audio/mpeg"


def test_a_missing_server_address_fails_at_construction_with_a_clear_error(monkeypatch):
    monkeypatch.delenv("COMPANION_PRIMETTS_URL", raising=False)
    with pytest.raises(PrimeTTSNotConfigured):
        PrimeTTS()
