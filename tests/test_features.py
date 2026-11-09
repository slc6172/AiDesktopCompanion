"""Which optional features are actually usable this run: switched on AND (where needed) holding
the credentials they need. A feature that is on but cannot work is turned off with ONE plain
explanation — the app itself still starts (spec Part 12, section 6)."""
import json

import pytest

from companion.features import resolve_features


@pytest.fixture
def setup(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr("companion.config.config_path", lambda: path)
    for name in ("CF_ACCOUNT_ID", "COMPANION_MEMORY"):
        monkeypatch.delenv(name, raising=False)
    keys = {}

    def configure(config=None, **provided):
        path.write_text(json.dumps(config or {}), encoding="utf-8")
        keys.clear()
        keys.update(provided)
        return resolve_features(get_key=lambda provider: keys.get(provider))

    return configure


def test_with_nothing_but_the_speech_key_set_up_only_the_local_features_are_on_and_nobody_is_told_anything(setup):
    features = setup(groq="g")
    assert (features.image, features.tinyfish) == (False, False)
    assert features.memory is True
    assert features.notices == ()


def test_a_feature_that_is_on_with_its_key_is_available(setup):
    features = setup({"tinyfish": {"enabled": True}, "image": {"enabled": True, "account_id": "acc"}},
                     tinyfish="tf-key", cloudflare="cf-token", groq="g")
    assert (features.tinyfish, features.image) == (True, True)
    assert features.notices == ()


def test_search_is_turned_off_with_one_notice_when_its_key_is_missing(setup):
    features = setup({"tinyfish": {"enabled": True}}, groq="g")
    assert features.tinyfish is False
    assert len(features.notices) == 1 and "TinyFish" in features.notices[0]
    assert "--set-key-tinyfish" in features.notices[0]


def test_photos_need_both_the_token_and_the_account_id_and_say_what_is_missing(setup):
    only_token = setup({"image": {"enabled": True}}, cloudflare="cf-token", groq="g")
    assert only_token.image is False and len(only_token.notices) == 1 and "CF_ACCOUNT_ID" in only_token.notices[0]

    only_account = setup({"image": {"enabled": True, "account_id": "acc"}}, groq="g")
    assert only_account.image is False and len(only_account.notices) == 1 and "--set-key-cloudflare" in only_account.notices[0]

    neither = setup({"image": {"enabled": True}}, groq="g")
    assert len(neither.notices) == 1   # still one message per feature, not one per missing thing
    assert "CF_ACCOUNT_ID" in neither.notices[0] and "--set-key-cloudflare" in neither.notices[0]


def test_a_feature_that_is_off_needs_no_key_and_says_nothing(setup):
    features = setup({"tinyfish": {"enabled": False}, "image": {"enabled": False}}, groq="g")
    assert features.notices == ()


def test_a_token_written_into_config_json_is_not_used_and_the_person_is_told(setup):
    features = setup({"tinyfish": {"enabled": True, "api_key": "leaked-in-file"},
                      "image": {"enabled": True, "account_id": "acc", "api_token": "also-in-file"}}, groq="g")
    assert (features.tinyfish, features.image) == (False, False)   # the file's value never counts
    text = "\n".join(features.notices)
    assert "tinyfish.api_key" in text and "image.api_token" in text
    assert "leaked-in-file" not in text and "also-in-file" not in text   # never echo a secret


def test_the_memory_switch_in_the_environment_beats_the_file(setup, monkeypatch):
    assert setup({"memory": {"enabled": True}}).memory is True
    monkeypatch.setenv("COMPANION_MEMORY", "off")
    assert setup({"memory": {"enabled": True}}).memory is False


# ---- the whole path: config.json -> app -> the chat stream -------------------------------------

def sse(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from companion.server import create_app

    monkeypatch.setenv("COMPANION_FAKE", "1")
    path = tmp_path / "config.json"
    monkeypatch.setattr("companion.config.config_path", lambda: path)
    monkeypatch.setattr("companion.features.get_api_key", lambda provider="gemini": None)
    # an isolated user folder with one healthy outfit, so these tests hear only about the features
    monkeypatch.setattr("companion.server.user_dir", lambda: tmp_path)
    (tmp_path / "clips" / "日常").mkdir(parents=True)
    (tmp_path / "clips" / "日常" / "idle.webm").write_bytes(b"v")
    for name in ("CF_ACCOUNT_ID", "COMPANION_MEMORY"):
        monkeypatch.delenv(name, raising=False)

    def make(config):
        path.write_text(json.dumps(config), encoding="utf-8")
        return TestClient(create_app(persona="test persona"))

    return make


def test_a_feature_turned_on_without_its_key_starts_fine_and_says_so_once_in_the_chat(app_client):
    client = app_client({"image": {"enabled": True}, "tinyfish": {"enabled": True}})
    first = [e for e in sse(client.post("/chat", json={"message": "嗨"})) if e["type"] == "notice"]
    assert len(first) == 2
    assert any("拍照" in e["message"] for e in first) and any("TinyFish" in e["message"] for e in first)
    second = [e for e in sse(client.post("/chat", json={"message": "再來"})) if e["type"] == "notice"]
    assert second == []


def test_nothing_is_said_when_every_optional_feature_is_off(app_client):
    client = app_client({})
    assert [e for e in sse(client.post("/chat", json={"message": "嗨"})) if e["type"] == "notice"] == []


def test_memory_enabled_false_in_the_file_keeps_what_she_remembers_out_of_the_prompt(tmp_path, monkeypatch):
    """Outside offline-demo mode: the real wiring from config.json to the engine."""
    from fastapi.testclient import TestClient

    from companion.history import InMemoryHistory
    from companion.server import create_app

    class RecordingLLM:
        systems = []

        def stream(self, system, messages):
            RecordingLLM.systems.append(system)
            yield "好啊。"

    class SilentTTS:
        mime_type = "audio/fake"

        def synthesize(self, text):
            return b"x"

    path = tmp_path / "config.json"
    monkeypatch.setattr("companion.config.config_path", lambda: path)
    monkeypatch.delenv("COMPANION_FAKE", raising=False)
    monkeypatch.delenv("COMPANION_MEMORY", raising=False)

    def ask(memory_enabled):
        path.write_text(json.dumps({"memory": {"enabled": memory_enabled}}), encoding="utf-8")
        store = InMemoryHistory()
        store.save_facts({"使用者": "- 喜歡黑咖啡"})
        client = TestClient(create_app(llm=RecordingLLM(), persona="p", tts=SilentTTS(), store=store, stt=object()))
        client.post("/chat", json={"message": "嗨"})
        return RecordingLLM.systems[-1]

    assert "喜歡黑咖啡" in ask(True)
    assert "喜歡黑咖啡" not in ask(False)


# ---- speech: the engine's key, and the microphone's -----------------------------------------------------

def test_fish_chosen_without_its_key_is_explained_once_and_with_the_fix(setup):
    features = setup({"tts": {"engine": "fish"}}, groq="g")
    assert len(features.notices) == 1
    assert "Fish" in features.notices[0] and "--set-key-fish" in features.notices[0] and "edge" in features.notices[0]


def test_fish_with_its_key_needs_no_explanation(setup):
    assert setup({"tts": {"engine": "fish"}}, groq="g", fish="f").notices == ()


def test_the_voice_engine_is_not_examined_when_speech_is_switched_off(setup):
    assert setup({"tts": {"enabled": False, "engine": "fish"}}, groq="g").notices == ()


def test_other_engines_need_no_key_and_say_nothing(setup):
    assert setup({"tts": {"engine": "edge"}}, groq="g").notices == ()
    assert setup({"tts": {"engine": "openai"}}, groq="g").notices == ()


def test_listening_is_off_with_one_explanation_when_the_groq_key_is_missing(setup):
    features = setup({})
    assert features.stt is False
    assert len(features.notices) == 1 and "Groq" in features.notices[0] and "--set-key-groq" in features.notices[0]


def test_listening_is_available_with_the_key(setup):
    assert setup({}, groq="g").stt is True


def test_listening_switched_off_needs_no_key_and_says_nothing(setup):
    features = setup({"stt": {"enabled": False}})
    assert features.stt is False and features.notices == ()


def test_the_offline_demo_has_its_own_listener_so_it_needs_no_key(setup, monkeypatch):
    monkeypatch.setenv("COMPANION_FAKE", "1")
    features = setup({})
    assert features.stt is True and features.notices == ()
