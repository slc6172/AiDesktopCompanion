import json

import pytest

from companion.config import DEFAULT_CONFIG, load_config, resolve_engine, resolve_fish_config

ENV_VARS = ("COMPANION_FISH_MODEL", "COMPANION_FISH_REFERENCE_ID", "COMPANION_FISH_FORMAT",
            "COMPANION_FISH_TIMEOUT_S")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def write_config(tmp_path, monkeypatch, data):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr("companion.config.config_path", lambda: path)


def test_the_defaults_use_the_free_model_mp3_and_no_voice_id(tmp_path, monkeypatch):
    monkeypatch.setattr("companion.config.config_path", lambda: tmp_path / "config.json")
    settings = resolve_fish_config()
    emotion_tags = settings.pop("emotion_tags")
    assert settings == {
        "model": "s2.1-pro-free", "reference_id": None, "format": "mp3", "timeout_s": 20.0,
    }
    assert emotion_tags == {"neutral": "", "happy": "[happy]", "sad": "[sad]",
                            "angry": "[angry]", "surprised": "[surprised]"}


def test_the_config_file_overrides_the_defaults_one_field_at_a_time(tmp_path, monkeypatch):
    write_config(tmp_path, monkeypatch, {"tts": {"fish": {"reference_id": "my-voice"}}})
    settings = resolve_fish_config()
    assert settings["reference_id"] == "my-voice"
    assert settings["model"] == "s2.1-pro-free"  # untouched sibling kept


def test_an_env_var_overrides_the_config_file(tmp_path, monkeypatch):
    write_config(tmp_path, monkeypatch, {"tts": {"fish": {"model": "from-file", "format": "wav"}}})
    monkeypatch.setenv("COMPANION_FISH_MODEL", "from-env")
    monkeypatch.setenv("COMPANION_FISH_REFERENCE_ID", "env-voice")
    monkeypatch.setenv("COMPANION_FISH_FORMAT", "mp3")
    monkeypatch.setenv("COMPANION_FISH_TIMEOUT_S", "7")
    settings = resolve_fish_config()
    settings.pop("emotion_tags")
    assert settings == {
        "model": "from-env", "reference_id": "env-voice", "format": "mp3", "timeout_s": 7.0,
    }


def test_adding_the_fish_section_does_not_disturb_the_other_tts_sections():
    assert DEFAULT_CONFIG["tts"]["engine"] == "auto"
    assert set(DEFAULT_CONFIG["tts"]["edge"]) == {"voice", "rate", "volume", "pitch"}


def test_auto_never_picks_fish_because_it_is_a_cloud_service_you_opt_into():
    assert resolve_engine("auto", None) == "edge"
    assert resolve_engine("auto", "http://x/v1") == "primetts"
    assert resolve_engine("fish", "http://x/v1") == "fish"  # explicit choice is never overridden


def test_the_example_file_documents_the_fish_defaults(monkeypatch):
    from pathlib import Path

    example = Path(__file__).resolve().parent.parent / "config.example.json"
    assert json.loads(example.read_text(encoding="utf-8"))["tts"]["fish"] == DEFAULT_CONFIG["tts"]["fish"]


def test_one_emotion_tag_can_be_changed_without_losing_the_others(tmp_path, monkeypatch):
    write_config(tmp_path, monkeypatch, {"tts": {"fish": {"emotion_tags": {"happy": "[excited]"}}}})
    tags = resolve_fish_config()["emotion_tags"]
    assert tags["happy"] == "[excited]"
    assert tags["sad"] == "[sad]"  # untouched sibling kept


def test_a_malformed_emotion_tags_section_is_ignored_instead_of_breaking_startup(tmp_path, monkeypatch):
    write_config(tmp_path, monkeypatch, {"tts": {"fish": {"emotion_tags": "oops"}}})
    assert resolve_fish_config()["emotion_tags"] == {}
    write_config(tmp_path, monkeypatch, {"tts": {"fish": {"emotion_tags": {"sad": 5, "happy": "[h]"}}}})
    tags = resolve_fish_config()["emotion_tags"]
    assert tags["happy"] == "[h]"
    assert "sad" not in tags  # the non-text value is dropped: that emotion is sent as plain text


# ---- a typo in the hand-edited file must never stop the app from starting (same rule as every other section) ----

DEFAULTS = {"model": "s2.1-pro-free", "reference_id": None, "format": "mp3", "timeout_s": 20.0}


def effective(tmp_path, monkeypatch, fish_section):
    write_config(tmp_path, monkeypatch, {"tts": {"fish": fish_section}})
    settings = resolve_fish_config()
    settings.pop("emotion_tags")
    return settings


@pytest.mark.parametrize("bad", ["fast", None, 0, -5, True, [20], {"a": 1}, float("nan"), float("inf"), 1e9])
def test_a_timeout_that_is_not_a_sensible_number_means_the_default(tmp_path, monkeypatch, bad):
    assert effective(tmp_path, monkeypatch, {"timeout_s": bad})["timeout_s"] == 20.0


@pytest.mark.parametrize("good,expected", [(5, 5.0), (7.5, 7.5), (60, 60.0), (300, 300.0)])
def test_a_sensible_timeout_is_used(tmp_path, monkeypatch, good, expected):
    assert effective(tmp_path, monkeypatch, {"timeout_s": good})["timeout_s"] == expected


@pytest.mark.parametrize("bad", ["ogg", "flac", 5, None, "", "  ", True, ["mp3"]])
def test_an_audio_format_the_browser_cannot_play_means_the_default(tmp_path, monkeypatch, bad):
    assert effective(tmp_path, monkeypatch, {"format": bad})["format"] == "mp3"


def test_the_audio_format_may_be_written_in_any_case(tmp_path, monkeypatch):
    assert effective(tmp_path, monkeypatch, {"format": " WAV "})["format"] == "wav"


@pytest.mark.parametrize("bad", [5, None, "", "   ", True, ["s2"], {"a": 1}])
def test_a_model_that_is_not_text_means_the_default(tmp_path, monkeypatch, bad):
    assert effective(tmp_path, monkeypatch, {"model": bad})["model"] == "s2.1-pro-free"


def test_a_model_name_is_trimmed(tmp_path, monkeypatch):
    assert effective(tmp_path, monkeypatch, {"model": " s2.1-pro "})["model"] == "s2.1-pro"


@pytest.mark.parametrize("bad", [12345, None, "", "   ", True, ["abc"]])
def test_a_voice_id_that_is_not_text_means_no_voice_id(tmp_path, monkeypatch, bad):
    assert effective(tmp_path, monkeypatch, {"reference_id": bad})["reference_id"] is None


def test_a_voice_id_is_trimmed(tmp_path, monkeypatch):
    assert effective(tmp_path, monkeypatch, {"reference_id": " abc123 "})["reference_id"] == "abc123"


def test_a_bad_environment_value_falls_back_to_the_config_file_not_to_a_crash(tmp_path, monkeypatch):
    write_config(tmp_path, monkeypatch, {"tts": {"fish": {"timeout_s": 9, "format": "wav", "model": "from-file"}}})
    monkeypatch.setenv("COMPANION_FISH_TIMEOUT_S", "abc")
    monkeypatch.setenv("COMPANION_FISH_FORMAT", "ogg")
    monkeypatch.setenv("COMPANION_FISH_MODEL", "")
    settings = resolve_fish_config()
    assert (settings["timeout_s"], settings["format"], settings["model"]) == (9.0, "wav", "from-file")


@pytest.mark.parametrize("env", ["0", "-1", "nan", "inf", "9999"])
def test_an_environment_timeout_out_of_range_is_ignored(tmp_path, monkeypatch, env):
    write_config(tmp_path, monkeypatch, {"tts": {"fish": {"timeout_s": 9}}})
    monkeypatch.setenv("COMPANION_FISH_TIMEOUT_S", env)
    assert resolve_fish_config()["timeout_s"] == 9.0


@pytest.mark.parametrize("data", [{"tts": {"fish": "oops"}}, {"tts": {"fish": None}}, {"tts": {"fish": [1]}}, {"tts": "oops"}])
def test_a_fish_section_that_is_not_an_object_means_all_defaults(tmp_path, monkeypatch, data):
    write_config(tmp_path, monkeypatch, data)
    settings = resolve_fish_config()
    settings.pop("emotion_tags")
    assert settings == DEFAULTS


def test_a_number_written_as_text_in_the_config_file_is_not_a_number(tmp_path, monkeypatch):
    # same rule as every other numeric setting: in config.json a number must BE a number ("7" is text)
    assert effective(tmp_path, monkeypatch, {"timeout_s": "7"})["timeout_s"] == 20.0


def test_every_emotion_the_character_can_have_has_an_entry_in_the_default_fish_tags():
    from companion.engine import EMOTIONS

    assert set(DEFAULT_CONFIG["tts"]["fish"]["emotion_tags"]) == set(EMOTIONS)   # a new emotion must not silently go untagged
