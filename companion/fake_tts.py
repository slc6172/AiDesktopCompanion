import io
import math
import struct
import time
import wave


class BeepTTS:
    """Offline stand-in: a soft beep whose length follows the text length."""

    mime_type = "audio/wav"

    def synthesize(self, text):
        time.sleep(0.15)  # pretend synthesis takes a moment
        rate = 16000
        seconds = min(0.12 * len(text), 3.0)
        frames = b"".join(
            struct.pack("<h", int(3000 * math.sin(2 * math.pi * 440 * i / rate)))
            for i in range(int(rate * seconds))
        )
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(frames)
        return buf.getvalue()
