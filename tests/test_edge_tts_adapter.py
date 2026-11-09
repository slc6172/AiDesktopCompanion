from edge_tts.exceptions import NoAudioReceived

from companion.edge_tts_adapter import EdgeTTS


class _NoAudioCommunicate:
    """Stands in for edge_tts.Communicate: raises NoAudioReceived, the way the real library
    does for a fragment with no speakable content (see edge_tts.communicate.Communicate.stream,
    which raises this itself rather than just yielding zero chunks)."""

    def __init__(self, text, voice, **kwargs):
        pass

    def stream(self):
        async def gen():
            raise NoAudioReceived("No audio was received.")
            yield  # pragma: no cover - makes this an async generator function

        return gen()


def test_no_audio_received_comes_back_as_an_empty_clip_not_a_crash(monkeypatch):
    monkeypatch.setattr("companion.edge_tts_adapter.edge_tts.Communicate", _NoAudioCommunicate)
    tts = EdgeTTS()
    assert tts.synthesize("…") == b""


class _RecordingCommunicate:
    """Stands in for edge_tts.Communicate, recording exactly how it was constructed."""

    calls = []

    def __init__(self, text, voice, **kwargs):
        _RecordingCommunicate.calls.append({"text": text, "voice": voice, **kwargs})

    def stream(self):
        async def gen():
            yield {"type": "audio", "data": b"x"}

        return gen()


def test_rate_volume_and_pitch_are_passed_through_to_edge_tts(monkeypatch):
    monkeypatch.setattr("companion.edge_tts_adapter.edge_tts.Communicate", _RecordingCommunicate)
    _RecordingCommunicate.calls.clear()
    tts = EdgeTTS(voice="v", rate="+10%", volume="-5%", pitch="+3Hz")
    tts.synthesize("嗨")
    assert _RecordingCommunicate.calls == [{"text": "嗨", "voice": "v", "rate": "+10%", "volume": "-5%", "pitch": "+3Hz"}]


def test_rate_volume_and_pitch_default_to_their_own_environment_variables(monkeypatch):
    monkeypatch.setenv("COMPANION_RATE", "+20%")
    monkeypatch.setenv("COMPANION_VOLUME", "+0%")
    monkeypatch.setenv("COMPANION_PITCH", "-2Hz")
    monkeypatch.setattr("companion.edge_tts_adapter.edge_tts.Communicate", _RecordingCommunicate)
    _RecordingCommunicate.calls.clear()
    EdgeTTS().synthesize("嗨")
    call = _RecordingCommunicate.calls[0]
    assert (call["rate"], call["volume"], call["pitch"]) == ("+20%", "+0%", "-2Hz")
