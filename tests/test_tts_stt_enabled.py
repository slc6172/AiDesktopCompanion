"""`tts.enabled` and `stt.enabled` are the first question: do you want speech out / speech in at
all? Only when the answer is yes do the engine and model choices matter (spec Part 12, section 6;
the person's decision on top of it)."""
import json

import pytest

from companion import config as cfg


@pytest.fixture
def write(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr("companion.config.config_path", lambda: path)
    for name in ("COMPANION_TTS", "COMPANION_PRIMETTS_URL", "COMPANION_PRIMETTS_MODEL", "COMPANION_PRIMETTS_VOICE",
                 "COMPANION_PRIMETTS_FORMAT", "COMPANION_PRIMETTS_API_KEY", "COMPANION_PRIMETTS_TIMEOUT_S"):
        monkeypatch.delenv(name, raising=False)

    def put(data):
        path.write_text(json.dumps(data), encoding="utf-8")

    return put


# ---- the two switches -------------------------------------------------------------------------

def test_both_switches_default_to_on_so_an_upgrade_changes_nothing(write):
    assert cfg.resolve_tts_config()["enabled"] is True
    assert cfg.resolve_stt_config()["enabled"] is True


def test_the_switches_can_be_turned_off(write):
    write({"tts": {"enabled": False}, "stt": {"enabled": False}})
    assert cfg.resolve_tts_config()["enabled"] is False
    assert cfg.resolve_stt_config()["enabled"] is False


@pytest.mark.parametrize("junk", ["no", 0, None, [], "false"])
def test_a_junk_switch_value_counts_as_not_set_which_means_on(write, junk):
    write({"tts": {"enabled": junk}, "stt": {"enabled": junk}})
    assert cfg.resolve_tts_config()["enabled"] is True
    assert cfg.resolve_stt_config()["enabled"] is True


# ---- the OpenAI-compatible server's section is `tts.openai` (its engine value may still be spelt "primetts") ------------------------------------------------------------

def test_the_new_openai_section_configures_the_openai_compatible_server(write):
    write({"tts": {"openai": {"url": "http://127.0.0.1:8880/v1", "voice": "nova"}}})
    settings = cfg.resolve_tts_config()
    assert settings["primetts_url"] == "http://127.0.0.1:8880/v1"
    assert settings["primetts_voice"] == "nova"
    assert settings["primetts_model"] == "primetts"          # the sibling default is kept


def test_an_old_primetts_section_is_no_longer_read_the_section_is_called_openai(write):
    write({"tts": {"primetts": {"url": "http://old:1/v1", "voice": "old-voice"}}})
    settings = cfg.resolve_tts_config()
    assert settings["primetts_url"] is None and settings["primetts_voice"] == "default"


@pytest.mark.parametrize("name", ["openai", "primetts"])
def test_both_names_pick_the_same_engine_as_a_tts_engine_value(name):
    assert cfg.resolve_engine(name, None) == cfg.resolve_engine("primetts", None) == "primetts"


def test_auto_keeps_its_meaning_and_never_picks_fish():
    assert cfg.resolve_engine("auto", "http://x/v1") == "primetts"
    assert cfg.resolve_engine("auto", None) == "edge"


# ---- building the voice: the switch comes first --------------------------------------------------------

@pytest.fixture
def voice(tmp_path, monkeypatch):
    """build_tts() against a throw-away config file; no key anywhere unless a test adds one."""
    path = tmp_path / "config.json"
    monkeypatch.setattr("companion.config.config_path", lambda: path)
    monkeypatch.delenv("COMPANION_FAKE", raising=False)
    for name in ("COMPANION_TTS", "COMPANION_TTS_FALLBACK", "FISH_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setitem(__import__("sys").modules, "keyring", type("NoKeyring", (), {"get_password": staticmethod(lambda *a: None)})())

    def build(config):
        path.write_text(json.dumps(config), encoding="utf-8")
        from companion.server import build_tts
        return build_tts()

    return build


def test_with_speech_switched_off_there_is_no_voice_at_all_whatever_the_engine_says(voice):
    assert voice({"tts": {"enabled": False, "engine": "edge"}}) == (None, None)
    assert voice({"tts": {"enabled": False, "engine": "fish"}}) == (None, None)   # no key needed, none asked about


def test_switched_off_wins_even_in_the_offline_demo_mode(voice, monkeypatch):
    monkeypatch.setenv("COMPANION_FAKE", "1")
    assert voice({"tts": {"enabled": False}}) == (None, None)


def test_with_speech_switched_off_the_engine_settings_are_not_even_looked_at(voice, caplog):
    import logging

    with caplog.at_level(logging.WARNING):
        voice({"tts": {"enabled": False, "engine": "fish", "fish": {"model": "s2-typo"}}})
    assert caplog.records == []    # the unknown-Fish-model warning belongs to a person who is using Fish


def test_with_speech_on_the_engine_choice_applies(voice):
    from companion.edge_tts_adapter import EdgeTTS
    from companion.primetts_adapter import PrimeTTS

    primary, _ = voice({"tts": {"enabled": True, "engine": "edge"}})
    assert isinstance(primary, EdgeTTS)
    primary, fallback = voice({"tts": {"enabled": True, "engine": "openai", "openai": {"url": "http://x/v1"}}})
    assert isinstance(primary, PrimeTTS) and isinstance(fallback, EdgeTTS)


def test_the_engine_value_primetts_builds_the_openai_compatible_voice(voice):
    from companion.primetts_adapter import PrimeTTS

    primary, _ = voice({"tts": {"engine": "primetts", "openai": {"url": "http://old/v1"}}})
    assert isinstance(primary, PrimeTTS)


def test_fish_chosen_with_a_key_is_the_real_fish_engine(voice, monkeypatch):
    from companion.fish_adapter import FishTTS

    monkeypatch.setenv("FISH_API_KEY", "k")
    primary, _ = voice({"tts": {"engine": "fish"}})
    assert isinstance(primary, FishTTS)


def test_fish_chosen_without_a_key_falls_back_to_edge_instead_of_stopping_the_app(voice):
    from companion.edge_tts_adapter import EdgeTTS

    primary, fallback = voice({"tts": {"engine": "fish"}})
    assert isinstance(primary, EdgeTTS) and fallback is None


# ---- the page and the server: listening switched off ------------------------------------------------------

@pytest.fixture
def app(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from companion.server import create_app

    path = tmp_path / "config.json"
    monkeypatch.setattr("companion.config.config_path", lambda: path)
    monkeypatch.setenv("COMPANION_FAKE", "1")

    def make(config):
        path.write_text(json.dumps(config), encoding="utf-8")
        return TestClient(create_app(persona="p"))

    return make


def events(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_the_page_is_told_listening_is_available_by_default(app):
    assert app({}).get("/config").json()["stt"] == {"enabled": True}


def test_the_page_is_told_when_listening_is_switched_off(app):
    assert app({"stt": {"enabled": False}}).get("/config").json()["stt"] == {"enabled": False}


def test_a_recording_sent_while_listening_is_off_gets_a_plain_explanation_not_a_crash(app):
    client = app({"stt": {"enabled": False}})
    reply = client.post("/chat/audio", content=b"fake-bytes", headers={"content-type": "audio/webm"})
    assert [(e["type"], e.get("kind")) for e in events(reply)] == [("error", "stt_disabled")]


def test_with_listening_on_a_recording_still_goes_through_as_before(app):
    client = app({})
    reply = client.post("/chat/audio", content=b"fake-bytes", headers={"content-type": "audio/webm"})
    assert events(reply)[0]["type"] != "error"


def test_a_missing_groq_key_also_hides_the_microphone(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from companion.server import create_app

    path = tmp_path / "config.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("companion.config.config_path", lambda: path)
    monkeypatch.delenv("COMPANION_FAKE", raising=False)
    monkeypatch.setattr("companion.features.get_api_key", lambda provider="gemini": None)
    monkeypatch.setattr("companion.server.user_dir", lambda: tmp_path)   # an isolated folder with one healthy outfit
    (tmp_path / "clips" / "日常").mkdir(parents=True)
    (tmp_path / "clips" / "日常" / "idle.webm").write_bytes(b"v")

    from companion.history import InMemoryHistory

    class Llm:
        def stream(self, system, messages):
            yield "好。"

    class QuietTTS:
        mime_type = "audio/fake"

        def synthesize(self, text):
            return b"x"

    client = TestClient(create_app(llm=Llm(), persona="p", tts=QuietTTS(), store=InMemoryHistory()))
    assert client.get("/config").json()["stt"] == {"enabled": False}
    notices = [e for e in events(client.post("/chat", json={"message": "嗨"})) if e["type"] == "notice"]
    assert len(notices) == 1 and "Groq" in notices[0]["message"]


def test_a_recogniser_handed_to_the_app_is_still_not_used_when_listening_is_switched_off(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from companion.history import InMemoryHistory
    from companion.server import create_app

    path = tmp_path / "config.json"
    path.write_text(json.dumps({"stt": {"enabled": False}}), encoding="utf-8")
    monkeypatch.setattr("companion.config.config_path", lambda: path)
    monkeypatch.delenv("COMPANION_FAKE", raising=False)

    class Llm:
        def stream(self, system, messages):
            yield "好。"

    class Quiet:
        mime_type = "audio/fake"

        def synthesize(self, text):
            return b"x"

    client = TestClient(create_app(llm=Llm(), persona="p", tts=Quiet(), store=InMemoryHistory(), stt=object()))
    assert client.get("/config").json()["stt"] == {"enabled": False}
