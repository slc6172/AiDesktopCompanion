import asyncio
import os

import edge_tts
from edge_tts.exceptions import NoAudioReceived


class EdgeTTS:
    """Real speech-synthesis boundary. edge-tts calls Microsoft's online service
    (unofficial), so it needs internet. Verified against the library API only;
    run smoke_tts.py on your machine for the live check."""

    mime_type = "audio/mpeg"

    def __init__(self, voice=None, rate=None, volume=None, pitch=None):
        self._voice = voice or os.environ.get("COMPANION_VOICE", "zh-TW-HsiaoChenNeural")
        self._rate = rate or os.environ.get("COMPANION_RATE", "+0%")
        self._volume = volume or os.environ.get("COMPANION_VOLUME", "+0%")
        self._pitch = pitch or os.environ.get("COMPANION_PITCH", "+0Hz")

    def synthesize(self, text):
        async def run():
            data = bytearray()
            communicate = edge_tts.Communicate(
                text, self._voice, rate=self._rate, volume=self._volume, pitch=self._pitch
            )
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    data += chunk["data"]
            return bytes(data)

        try:
            return asyncio.run(run())
        except NoAudioReceived:
            # edge-tts raises this itself rather than just yielding no chunks. A handful of
            # very short or punctuation-only fragments (a lone "…" left over from a stutter,
            # for instance) legitimately have nothing for the service to say. That is not a
            # broken TTS service — it is "no clip for this one line" — so it is reported to
            # TurnEngine the same way as any other empty result, not as an exception. Letting
            # this escape as an exception previously made TurnEngine treat it as if the whole
            # TTS service had died, silencing every sentence after it for the rest of the turn.
            return b""
