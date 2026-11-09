import json
import os

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from .apikey import MissingApiKey, get_api_key
from .errors import LLMError


def to_llm_error(exc):
    """Translate SDK/network exceptions into LLMError; None if we do not recognise it."""
    if isinstance(exc, genai_errors.APIError):
        code = getattr(exc, "code", None)
        if code == 429:
            return LLMError("rate_limit", str(exc))
        if code in (408, 504):
            return LLMError("timeout", str(exc))
        return LLMError("unavailable", str(exc))
    if isinstance(exc, httpx.TimeoutException):
        return LLMError("timeout", str(exc))
    if isinstance(exc, httpx.HTTPError):
        return LLMError("unavailable", str(exc))
    return None


class GeminiLLM:
    """Real LLM boundary: streams text chunks from the Gemini API.

    Verified only against SDK types in the sandbox (no network to Google here);
    run smoke_gemini.py on your machine to verify end to end.
    """

    def __init__(self, api_key=None, model=None, thinking_level="low"):
        api_key = api_key or get_api_key()
        if not api_key:
            raise MissingApiKey(
                "找不到 Gemini API 金鑰。請設定環境變數 GEMINI_API_KEY,"
                "或執行 app.py --set-key 把金鑰存進 Windows 憑證管理員。"
            )
        timeout_ms = int(os.environ.get("COMPANION_LLM_TIMEOUT_MS", "20000"))
        self._client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=timeout_ms))
        self._model = model or os.environ.get("COMPANION_MODEL", "gemini-3.5-flash-lite")
        self._thinking_level = thinking_level

    @staticmethod
    def _parts(message):
        parts = []
        image = message.get("image")
        if image is not None:  # an attached image goes to the model as it was uploaded
            parts.append(types.Part.from_bytes(data=image.data, mime_type=image.mime_type))
        parts.append(types.Part(text=message["content"]))
        return parts

    def _contents(self, messages):
        return [
            types.Content(
                role="model" if m["role"] == "assistant" else "user",
                parts=self._parts(m),
            )
            for m in messages
        ]

    def stream(self, system, messages):
        config = types.GenerateContentConfig(
            system_instruction=system,
            thinking_config=types.ThinkingConfig(thinking_level=self._thinking_level),
        )
        try:
            for chunk in self._client.models.generate_content_stream(
                model=self._model, contents=self._contents(messages), config=config
            ):
                if chunk.text:
                    yield chunk.text
        except Exception as exc:
            translated = to_llm_error(exc)
            if translated is None:
                raise
            raise translated from exc

    def generate_structured(self, system, messages, schema):
        """One non-streaming call whose reply the API itself constrains to JSON matching
        `schema` (a JSON Schema dict); returns the parsed object.

        Service failures are translated to LLMError exactly as in stream(). A reply that is
        empty (e.g. blocked) or is not valid JSON (e.g. cut off) raises ValueError instead of
        being papered over — the caller decides what an unusable answer means.
        """
        config = types.GenerateContentConfig(
            system_instruction=system,
            thinking_config=types.ThinkingConfig(thinking_level=self._thinking_level),
            response_mime_type="application/json",
            response_json_schema=schema,
        )
        try:
            response = self._client.models.generate_content(
                model=self._model, contents=self._contents(messages), config=config
            )
        except Exception as exc:
            translated = to_llm_error(exc)
            if translated is None:
                raise
            raise translated from exc
        if not response.text:
            raise ValueError("the model returned no structured output")
        return json.loads(response.text)
