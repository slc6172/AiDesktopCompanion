import os

import httpx

from .apikey import MissingApiKey, get_api_key
from .errors import TTSUnavailable

_MIME_TYPES = {"mp3": "audio/mpeg", "wav": "audio/wav"}
_DEFAULT_URL = "https://api.fish.audio/v1/tts"


class FishTTS:
    """Speech-synthesis boundary for Fish Audio's hosted `POST /v1/tts` (default model
    `s2.1-pro-free`, the free fair-use tier).

    Same shape as EdgeTTS / PrimeTTS (`synthesize(text) -> bytes`, `mime_type`), so it is
    interchangeable wherever TurnEngine takes a TTS. It speaks Fish's own protocol, not the
    OpenAI one: the model goes in a `model` *header*, the voice is a `reference_id` in the body.

    Three outcomes, kept apart on purpose (see TurnEngine._synthesize):
    - nothing to say (blank text, or an answer with no audio) -> b"" ("no clip for this line");
    - Fish cannot be reached, times out, is rate limited (429) or fails on its side (5xx) ->
      TTSUnavailable, which TurnEngine routes to the fallback engine. Free access is "fair
      use" with no SLA, so a 429 is a "not right now", not a broken setup;
    - Fish rejects the request (any other 4xx: bad key, no credit, unknown voice id) -> the
      ordinary httpx.HTTPStatusError, a configuration problem that must stay visible instead
      of quietly sending every sentence to the fallback forever.

    The API key is looked up like the Gemini and Groq ones (FISH_API_KEY, then the Windows
    Credential Manager) and is never written to config.json.

    Verified against the HTTP contract with an in-memory fake server only; run
    smoke_fish.py on your machine for the live check.
    """

    # Tells TurnEngine to pass each sentence's emotion to synthesize(); see TurnEngine._say.
    supports_emotion = True

    def __init__(self, api_key=None, model=None, reference_id=None, response_format=None,
                 timeout=None, url=None, client=None, emotion_tags=None):
        api_key = api_key or get_api_key("fish")
        if not api_key:
            raise MissingApiKey(
                "找不到 Fish Audio API 金鑰。請設定環境變數 FISH_API_KEY,"
                "或執行 app.py --set-key-fish 把金鑰存進 Windows 憑證管理員"
                "(金鑰在 https://fish.audio/app/api-keys 申請)。"
            )
        response_format = response_format or os.environ.get("COMPANION_FISH_FORMAT", "mp3")
        if response_format not in _MIME_TYPES:
            raise ValueError(f"不支援的音訊格式 {response_format!r};可用:{', '.join(_MIME_TYPES)}")
        self._url = url or _DEFAULT_URL
        self._model = model or os.environ.get("COMPANION_FISH_MODEL", "s2.1-pro-free")
        self._emotion_tags = dict(emotion_tags or {})
        self._reference_id = reference_id or os.environ.get("COMPANION_FISH_REFERENCE_ID") or None
        self._format = response_format
        self.mime_type = _MIME_TYPES[response_format]
        self._headers = {"Authorization": f"Bearer {api_key}", "model": self._model}
        # A cloud service: connecting should be quick, but the free tier promises no latency,
        # so the read timeout is more generous than the local PrimeTTS one.
        read_timeout = timeout or float(os.environ.get("COMPANION_FISH_TIMEOUT_S", "20"))
        self._client = client or httpx.Client(timeout=httpx.Timeout(read_timeout, connect=5.0))

    def _tagged(self, text, emotion):
        """`text` with the emotion's tag in front, e.g. "[sad] 我好難過". S2-family models
        (s2-pro, s2.1-pro, s2.1-pro-free) read a leading `[bracket]` cue as a tone instruction;
        the legacy S1 uses a different syntax, so other models get no tag rather than a wrong one.
        An emotion with no tag configured (neutral by default) is sent as plain text."""
        tag = (self._emotion_tags.get(emotion) or "").strip() if emotion else ""
        if not tag or not self._model.startswith("s2"):
            return text
        return f"{tag} {text}"

    def synthesize(self, text, emotion=None):
        if not text.strip():
            return b""
        body = {"text": self._tagged(text, emotion), "format": self._format}
        if self._reference_id:
            body["reference_id"] = self._reference_id
        try:
            response = self._client.post(self._url, headers=self._headers, json=body)
            response.raise_for_status()
        except httpx.TransportError as exc:  # refused, DNS, timeouts, dropped connection...
            raise TTSUnavailable(f"Fish Audio unreachable: {type(exc).__name__}") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 429 or status >= 500:
                raise TTSUnavailable(f"Fish Audio unavailable (HTTP {status})") from exc
            raise
        return response.content
