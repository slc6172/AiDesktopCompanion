"""smoke_stt.py sends any audio file to the real speech-to-text service; it must tell the service
the right audio type from the file name (the standard library calls .webm a *video*)."""
import pytest

import smoke_stt


@pytest.mark.parametrize("name, expected", [
    ("a.webm", "audio/webm"), ("a.wav", "audio/wav"), ("a.mp3", "audio/mpeg"),
    ("a.m4a", "audio/mp4"), ("a.ogg", "audio/ogg"), ("a.flac", "audio/flac"),
])
def test_the_audio_type_comes_from_the_file_extension(name, expected):
    assert smoke_stt.mime_type_for(name) == expected


def test_the_extension_is_matched_ignoring_case_and_folders():
    assert smoke_stt.mime_type_for(r"C:\錄音\我的 聲音.WAV") == "audio/wav"


def test_an_unknown_extension_is_refused_with_the_list_of_supported_ones():
    with pytest.raises(ValueError) as error:
        smoke_stt.mime_type_for("notes.txt")
    assert ".webm" in str(error.value) and ".wav" in str(error.value)
