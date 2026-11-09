import json

import httpx
import pytest

from companion.apikey import MissingApiKey, get_api_key
from companion.errors import TTSUnavailable
from companion.fish_adapter import FishTTS


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("FISH_API_KEY", "COMPANION_FISH_MODEL", "COMPANION_FISH_REFERENCE_ID",
                 "COMPANION_FISH_FORMAT", "COMPANION_FISH_TIMEOUT_S"):
        monkeypatch.delenv(name, raising=False)
    # never reach the real Windows Credential Manager from a test
    monkeypatch.setattr("keyring.get_password", lambda *args, **kwargs: None)


def make_tts(handler, **kwargs):
    """A FishTTS whose HTTP client is an in-memory fake: `handler(request)` plays Fish Audio."""
    seen = []

    def recording_handler(request):
        seen.append(request)
        return handler(request)

    client = httpx.Client(transport=httpx.MockTransport(recording_handler))
    kwargs.setdefault("api_key", "fish-test-key")
    return FishTTS(client=client, **kwargs), seen


def ok(body=b"ID3....mp3data"):
    return lambda request: httpx.Response(200, content=body)


def test_text_is_posted_to_fish_with_the_model_in_a_header_and_the_audio_comes_back():
    tts, seen = make_tts(ok(b"audio-bytes"))
    assert tts.synthesize("你好呀") == b"audio-bytes"

    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == "https://api.fish.audio/v1/tts"
    assert request.headers["authorization"] == "Bearer fish-test-key"
    # Fish wants the model as a *header*, not a body field, and rejects the request without it.
    assert request.headers["model"] == "s2.1-pro-free"
    assert json.loads(request.content) == {"text": "你好呀", "format": "mp3"}


def test_a_voice_model_id_is_sent_as_reference_id_only_when_configured():
    with_voice, seen_with = make_tts(ok(), reference_id="abc123")
    with_voice.synthesize("嗨")
    assert json.loads(seen_with[0].content)["reference_id"] == "abc123"

    without, seen_without = make_tts(ok())
    without.synthesize("嗨")
    assert "reference_id" not in json.loads(seen_without[0].content)


def test_the_model_is_configurable():
    tts, seen = make_tts(ok(), model="s2.1-pro")
    tts.synthesize("嗨")
    assert seen[0].headers["model"] == "s2.1-pro"


def test_mime_type_follows_the_requested_audio_format():
    assert make_tts(ok(), response_format="mp3")[0].mime_type == "audio/mpeg"
    assert make_tts(ok(), response_format="wav")[0].mime_type == "audio/wav"


def test_an_unsupported_audio_format_is_rejected_up_front():
    with pytest.raises(ValueError):
        make_tts(ok(), response_format="pcm")  # raw PCM has no container the browser can play


def test_nothing_to_say_is_an_empty_result_and_never_reaches_fish():
    tts, seen = make_tts(ok())
    assert tts.synthesize("   ") == b""
    assert tts.synthesize("") == b""
    assert seen == []  # no point spending free-tier quota on blank input


def test_a_successful_response_with_no_audio_is_an_empty_result_not_an_error():
    tts, _ = make_tts(ok(b""))
    assert tts.synthesize("嗯") == b""


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_a_fish_side_error_means_the_engine_is_unavailable(status):
    tts, _ = make_tts(lambda request: httpx.Response(status, json={"message": "boom"}))
    with pytest.raises(TTSUnavailable):
        tts.synthesize("你好")


def test_being_rate_limited_means_the_engine_is_unavailable_right_now():
    # Free access is "fair use": a 429 is a "not now", so this sentence should go to the
    # fallback voice instead of the whole turn falling silent.
    tts, _ = make_tts(lambda request: httpx.Response(429, json={"message": "slow down"}))
    with pytest.raises(TTSUnavailable):
        tts.synthesize("你好")


def test_the_network_being_down_means_the_engine_is_unavailable():
    def refuse(request):
        raise httpx.ConnectError("no route", request=request)

    tts, _ = make_tts(refuse)
    with pytest.raises(TTSUnavailable):
        tts.synthesize("你好")


def test_a_timeout_means_the_engine_is_unavailable():
    def hang(request):
        raise httpx.ReadTimeout("too slow", request=request)

    tts, _ = make_tts(hang)
    with pytest.raises(TTSUnavailable):
        tts.synthesize("你好")


@pytest.mark.parametrize("status", [400, 401, 402, 403, 422])
def test_a_rejected_request_is_a_configuration_problem_and_is_not_disguised_as_unavailable(status):
    # A bad key, no credit, or a wrong voice id must stay visible instead of quietly sending
    # every sentence to the fallback forever.
    tts, _ = make_tts(lambda request: httpx.Response(status, json={"message": "no"}))
    with pytest.raises(httpx.HTTPStatusError):
        tts.synthesize("你好")


def test_the_api_key_never_appears_in_the_unavailable_error():
    def refuse(request):
        raise httpx.ConnectError("no route", request=request)

    tts, _ = make_tts(refuse, api_key="super-secret-key")
    with pytest.raises(TTSUnavailable) as caught:
        tts.synthesize("你好")
    assert "super-secret-key" not in str(caught.value)


def test_the_api_key_comes_from_the_environment_when_not_passed_in(monkeypatch):
    monkeypatch.setenv("FISH_API_KEY", "from-env")
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=b"x")

    FishTTS(client=httpx.Client(transport=httpx.MockTransport(handler))).synthesize("嗨")
    assert seen[0].headers["authorization"] == "Bearer from-env"


def test_a_missing_key_fails_at_construction_with_a_clear_error():
    with pytest.raises(MissingApiKey) as caught:
        FishTTS()
    assert "FISH_API_KEY" in str(caught.value)


def test_settings_come_from_the_environment_when_not_passed_in(monkeypatch):
    monkeypatch.setenv("COMPANION_FISH_MODEL", "s2.1-pro")
    monkeypatch.setenv("COMPANION_FISH_REFERENCE_ID", "voice-9")
    monkeypatch.setenv("COMPANION_FISH_FORMAT", "wav")
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=b"x")

    tts = FishTTS(api_key="k", client=httpx.Client(transport=httpx.MockTransport(handler)))
    tts.synthesize("嗨")

    assert seen[0].headers["model"] == "s2.1-pro"
    assert json.loads(seen[0].content) == {"text": "嗨", "format": "wav", "reference_id": "voice-9"}
    assert tts.mime_type == "audio/wav"


def test_fish_is_a_known_provider_for_the_key_store(monkeypatch):
    monkeypatch.setenv("FISH_API_KEY", "abc")
    assert get_api_key("fish") == "abc"
