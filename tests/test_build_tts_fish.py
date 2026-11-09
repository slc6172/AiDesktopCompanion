import pytest

from companion.edge_tts_adapter import EdgeTTS
from companion.fish_adapter import FishTTS
from companion.server import build_tts


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.delenv("COMPANION_FAKE", raising=False)
    for name in ("COMPANION_TTS", "COMPANION_TTS_FALLBACK", "COMPANION_PRIMETTS_URL",
                 "COMPANION_FISH_MODEL", "COMPANION_FISH_REFERENCE_ID", "COMPANION_FISH_FORMAT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FISH_API_KEY", "fish-test-key")
    monkeypatch.setattr("companion.config.config_path", lambda: tmp_path / "config.json")


def test_engine_fish_uses_fish_as_primary_and_edge_as_the_fallback(monkeypatch):
    monkeypatch.setenv("COMPANION_TTS", "fish")
    primary, fallback = build_tts()
    assert isinstance(primary, FishTTS)
    assert isinstance(fallback, EdgeTTS)


def test_fallback_off_leaves_fish_on_its_own(monkeypatch):
    monkeypatch.setenv("COMPANION_TTS", "fish")
    monkeypatch.setenv("COMPANION_TTS_FALLBACK", "off")
    primary, fallback = build_tts()
    assert isinstance(primary, FishTTS)
    assert fallback is None


def test_the_fish_settings_reach_the_adapter(monkeypatch):
    monkeypatch.setenv("COMPANION_TTS", "fish")
    monkeypatch.setenv("COMPANION_FISH_FORMAT", "wav")
    primary, _ = build_tts()
    assert primary.mime_type == "audio/wav"


def test_without_choosing_fish_it_is_never_used_even_with_a_key_present():
    primary, fallback = build_tts()  # engine "auto", no PrimeTTS url
    assert isinstance(primary, EdgeTTS)
    assert fallback is None


def test_fake_mode_still_short_circuits_to_the_beep_double(monkeypatch):
    from companion.fake_tts import BeepTTS

    monkeypatch.setenv("COMPANION_FAKE", "1")
    monkeypatch.setenv("COMPANION_TTS", "fish")
    primary, fallback = build_tts()
    assert isinstance(primary, BeepTTS)
    assert fallback is None


@pytest.mark.parametrize("fish_section", [{"timeout_s": "fast"}, {"timeout_s": None}, {"format": "ogg"}, {"model": 5}, {"reference_id": 12345}, "oops"])
def test_a_typo_in_the_fish_settings_does_not_stop_the_app_from_building_its_voice(tmp_path, monkeypatch, fish_section):
    import json

    path = tmp_path / "config.json"
    path.write_text(json.dumps({"tts": {"fish": fish_section}}), encoding="utf-8")
    monkeypatch.setattr("companion.config.config_path", lambda: path)
    monkeypatch.setenv("COMPANION_TTS", "fish")
    primary, _ = build_tts()
    assert isinstance(primary, FishTTS)
    assert primary._tagged("嗨", "happy") == "[happy] 嗨"      # and the model name is usable for the tag decision


# ---- Fish falls back to its PAID default model when it does not recognise the model name: say so loudly ----

KNOWN_FISH_MODELS = ["s1", "s2-pro", "s2.1-pro", "s2.1-pro-free"]


@pytest.mark.parametrize("model", KNOWN_FISH_MODELS)
def test_a_known_fish_model_name_builds_quietly(monkeypatch, caplog, model):
    monkeypatch.setenv("COMPANION_TTS", "fish")
    monkeypatch.setenv("COMPANION_FISH_MODEL", model)
    with caplog.at_level("WARNING"):
        primary, _ = build_tts()
    assert primary._model == model
    assert [r for r in caplog.records if r.levelname == "WARNING"] == []


@pytest.mark.parametrize("typo", ["s2.1-pro-fre", "S2.1-pro-free", "s3-pro", "free"])
def test_an_unknown_fish_model_name_is_still_used_but_warns_that_fish_will_bill_the_paid_model(monkeypatch, caplog, typo):
    monkeypatch.setenv("COMPANION_TTS", "fish")
    monkeypatch.setenv("COMPANION_FISH_MODEL", typo)
    with caplog.at_level("WARNING"):
        primary, _ = build_tts()
    assert primary._model == typo                               # not silently replaced: a future real model must keep working
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert typo in warnings[0] and "付費" in warnings[0] and "s2.1-pro-free" in warnings[0]
