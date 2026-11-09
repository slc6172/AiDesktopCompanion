"""The /config endpoint is how the page learns settings it cannot read from the environment."""
import json

import pytest
from fastapi.testclient import TestClient

from companion.server import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPANION_FAKE", "1")  # offline doubles, in-memory history
    path = tmp_path / "config.json"
    monkeypatch.setattr("companion.config.config_path", lambda: path)
    for name in ("COMPANION_AUTO_LISTEN", "COMPANION_ON_TOP_LEVEL", "COMPANION_HIT_WIDTH_RATIO",
                 "COMPANION_VAD_SILENCE_MS", "COMPANION_VAD_MIN_MS"):
        monkeypatch.delenv(name, raising=False)
    client = TestClient(create_app(persona="test persona"))
    client.config_file = path
    return client


def test_config_keeps_the_existing_voice_activity_fields(client):
    body = client.get("/config").json()
    assert body["vadSilenceMs"] == 700
    assert body["vadMinMs"] == 500


def test_config_tells_the_page_the_ui_settings_it_needs(client):
    ui = client.get("/config").json()["ui"]
    assert ui == {"autoListen": False, "hitWidthRatio": 0.6, "speakingBoost": 1.0, "duckLevel": 0.4}


def test_config_reflects_what_the_user_set_in_config_json(client):
    client.config_file.write_text(json.dumps({"ui": {"auto_listen": True, "hit_width_ratio": 0.45}}), encoding="utf-8")
    ui = client.get("/config").json()["ui"]
    assert ui == {"autoListen": True, "hitWidthRatio": 0.45, "speakingBoost": 1.0, "duckLevel": 0.4}


def test_config_does_not_hand_the_page_settings_only_the_window_shell_needs(client):
    # on_top_level is for Electron's main process (it reaches it through the launcher), not the page
    assert "onTopLevel" not in client.get("/config").json()["ui"]


# ---- the time settings reach the engine (spec Part 11, ticket 47) ----

class RecordingLLM:
    def __init__(self):
        self.systems = []

    def stream(self, system, messages):
        self.systems.append(system)
        yield "[happy]好。"


def test_by_default_the_model_is_told_the_time(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPANION_FAKE", "1")  # offline speech double and in-memory history
    monkeypatch.setattr("companion.config.config_path", lambda: tmp_path / "config.json")
    llm = RecordingLLM()
    client = TestClient(create_app(llm=llm, persona="test persona"))
    client.post("/chat", json={"message": "嗨"})
    assert "【時間資訊" in llm.systems[0]


def test_turning_time_awareness_off_in_config_json_removes_it_from_the_prompt(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPANION_FAKE", "1")
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"time": {"enabled": False}}), encoding="utf-8")
    monkeypatch.setattr("companion.config.config_path", lambda: path)
    llm = RecordingLLM()
    TestClient(create_app(llm=llm, persona="test persona")).post("/chat", json={"message": "嗨"})
    assert "【時間資訊" not in llm.systems[0]


def test_the_configured_time_zone_is_what_the_model_is_shown(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPANION_FAKE", "1")
    shown = {}
    for zone in ("Etc/GMT-14", "Etc/GMT+12"):  # UTC+14 and UTC-12: 26 hours apart, so never the same wall clock
        path = tmp_path / f"{zone.replace('/', '_')}.json"
        path.write_text(json.dumps({"time": {"timezone": zone}}), encoding="utf-8")
        monkeypatch.setattr("companion.config.config_path", lambda p=path: p)
        llm = RecordingLLM()
        TestClient(create_app(llm=llm, persona="test persona")).post("/chat", json={"message": "嗨"})
        shown[zone] = llm.systems[0].split("現在是 ")[1][:19]
    assert shown["Etc/GMT-14"] != shown["Etc/GMT+12"]


# ---- the speech-recognition settings reach the adapter, and a thrown-away recording ends the turn ----

def test_the_stt_settings_in_config_json_are_handed_to_the_speech_adapter(tmp_path, monkeypatch):
    from companion.server import build_stt

    monkeypatch.delenv("COMPANION_FAKE", raising=False)
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"stt": {"language": "zh", "debug_log": True, "no_speech_prob_max": 0.5}}), encoding="utf-8")
    monkeypatch.setattr("companion.config.config_path", lambda: path)
    received = {}

    class Recorder:
        def __init__(self, **kwargs):
            received.update(kwargs)

    monkeypatch.setattr("companion.groq_stt.GroqSTT", Recorder)
    build_stt()
    assert received["settings"]["language"] == "zh" and received["settings"]["debug_log"] is True
    assert received["settings"]["no_speech_prob_max"] == 0.5 and received["settings"]["allowed_languages"] == ["zh", "en", "ja"]


def test_a_recording_the_recogniser_invented_text_for_ends_as_didnt_catch_that_and_the_model_is_never_asked(tmp_path, monkeypatch):
    from companion.groq_stt import GroqSTT

    monkeypatch.setenv("COMPANION_FAKE", "1")
    monkeypatch.setattr("companion.config.config_path", lambda: tmp_path / "config.json")

    class Answer:  # what Groq sends back for a recording of speaker echo / room noise
        text = "Доброе утро!"
        language = "russian"
        segments = [{"text": "Доброе утро!", "no_speech_prob": 0.7, "avg_logprob": -1.3}]

    class Client:
        class audio:
            class transcriptions:
                @staticmethod
                def create(**kwargs):
                    return Answer()

    monkeypatch.setattr("companion.groq_stt.Groq", lambda **kw: Client())
    llm = RecordingLLM()
    client = TestClient(create_app(llm=llm, stt=GroqSTT(api_key="k"), persona="test persona"))
    response = client.post("/chat/audio", content=b"\x00noise", headers={"Content-Type": "audio/webm"})
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert [(e["type"], e.get("kind")) for e in events] == [("error", "stt_empty")]
    assert llm.systems == []                         # nothing was said to the character
    assert client.get("/history").json() == []       # and nothing was written to the conversation


def test_the_page_is_told_the_speaking_boost(client):
    assert client.get("/config").json()["ui"]["speakingBoost"] == 1.0


def test_a_boost_set_in_config_json_reaches_the_page(client):
    client.config_file.write_text(json.dumps({"ui": {"speaking_boost": 2.5}}), encoding="utf-8")
    assert client.get("/config").json()["ui"]["speakingBoost"] == 2.5


def test_config_tells_the_page_how_far_to_turn_her_down(tmp_path, monkeypatch):
    import json
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"ui": {"duck_level": 0.55}}), encoding="utf-8")
    monkeypatch.setattr("companion.config.config_path", lambda: path)
    monkeypatch.delenv("COMPANION_DUCK_LEVEL", raising=False)
    monkeypatch.setenv("COMPANION_FAKE", "1")
    from fastapi.testclient import TestClient
    from companion.server import create_app
    assert TestClient(create_app(persona="p")).get("/config").json()["ui"]["duckLevel"] == 0.55
