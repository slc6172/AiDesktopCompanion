import os

import httpx

from .errors import TTSUnavailable

_MIME_TYPES = {"wav": "audio/wav", "mp3": "audio/mpeg", "opus": "audio/ogg", "flac": "audio/flac"}


class PrimeTTSNotConfigured(RuntimeError):
    pass


class PrimeTTS:
    """Speech-synthesis boundary for a locally hosted PrimeTTS (or any server that speaks the
    OpenAI `POST /audio/speech` protocol). The model itself runs in that separate server, so
    this project carries no onnxruntime / g2pw / model files — only a small HTTP client.

    Same shape as EdgeTTS (`synthesize(text) -> bytes`, `mime_type`), so the two are
    interchangeable wherever TurnEngine takes a TTS.

    Three outcomes, kept apart on purpose (see TurnEngine._synthesize):
    - nothing to say (blank text, or a server that answers with no audio) -> b"" ("no clip for
      this line");
    - the server cannot be reached, times out, or fails on its side (5xx) -> TTSUnavailable, which
      TurnEngine routes to the fallback engine;
    - the server rejects the request (4xx, e.g. a wrong model or voice name) -> the ordinary
      httpx.HTTPStatusError, a configuration problem that must stay visible instead of quietly
      sending every sentence to the fallback forever.

    Verified against the HTTP contract with an in-memory fake server only; run
    smoke_primetts.py on your machine for the live check.
    """

    def __init__(self, base_url=None, model=None, voice=None, response_format=None, api_key=None,
                 timeout=None, client=None):
        base_url = base_url or os.environ.get("COMPANION_PRIMETTS_URL")
        if not base_url:
            raise PrimeTTSNotConfigured(
                "找不到本機語音伺服器位址。請設定環境變數 COMPANION_PRIMETTS_URL,"
                "例如 http://127.0.0.1:8880/v1(要包含 /v1,不含 /audio/speech)。"
            )
        response_format = response_format or os.environ.get("COMPANION_PRIMETTS_FORMAT", "wav")
        if response_format not in _MIME_TYPES:
            raise ValueError(f"不支援的音訊格式 {response_format!r};可用:{', '.join(_MIME_TYPES)}")
        self._url = base_url.rstrip("/") + "/audio/speech"
        self._model = model or os.environ.get("COMPANION_PRIMETTS_MODEL", "primetts")
        self._voice = voice or os.environ.get("COMPANION_PRIMETTS_VOICE", "default")
        self._format = response_format
        self.mime_type = _MIME_TYPES[response_format]
        api_key = api_key or os.environ.get("COMPANION_PRIMETTS_API_KEY")
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        # Connecting to a local server either works at once or not at all, so a short connect
        # timeout keeps "the server isn't running" from costing the user a long silent wait
        # before the fallback voice starts; the read timeout covers actual synthesis time.
        read_timeout = timeout or float(os.environ.get("COMPANION_PRIMETTS_TIMEOUT_S", "15"))
        self._client = client or httpx.Client(timeout=httpx.Timeout(read_timeout, connect=3.0))

    def synthesize(self, text):
        if not text.strip():
            # OpenAI-style servers reject empty input with a 400; there is nothing to say anyway.
            return b""
        try:
            response = self._client.post(
                self._url,
                headers=self._headers,
                json={"model": self._model, "voice": self._voice, "input": text,
                      "response_format": self._format},
            )
            response.raise_for_status()
        except httpx.TransportError as exc:  # refused, DNS, timeouts, dropped connection...
            raise TTSUnavailable(f"PrimeTTS server unreachable: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code >= 500:
                raise TTSUnavailable(f"PrimeTTS server error {exc.response.status_code}") from exc
            raise
        return response.content
