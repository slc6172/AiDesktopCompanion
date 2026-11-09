"""Cloudflare Workers AI image generation over plain HTTP (spec Part 12, section 5).

One POST, multipart/form-data (this model family does not take JSON), a Bearer token; the answer is JSON with
the picture as Base64 in `result.image`. Success is `success: true` AND a good HTTP status. Whatever goes wrong
becomes an ImageError that carries the HTTP status and Cloudflare's error code — never the token.
"""
import base64
import binascii

import httpx

BASE = "https://api.cloudflare.com/client/v4/accounts"
MODEL_PREFIX = "@cf/black-forest-labs/"


class ImageError(Exception):
    """The picture could not be made. `status` is the HTTP status (None when nothing came back), `code`
    Cloudflare's own error code when it sent one, `timed_out` whether we gave up waiting."""

    def __init__(self, message, status=None, code=None, timed_out=False):
        super().__init__(message)
        self.status, self.code, self.timed_out = status, code, timed_out


def _error_code(body):
    try:
        return int(body["errors"][0]["code"])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _error_text(body):
    """Cloudflare's own explanation, short (it never contains our token: we only ever send that in a header)."""
    try:
        return str(body["errors"][0]["message"])[:200]
    except (KeyError, IndexError, TypeError):
        return ""


class CloudflareImage:
    def __init__(self, api_token, account_id, model="flux-2-klein-9b", timeout=120.0, client=None):
        self._token, self._account = api_token, account_id
        self._model = model if model.startswith("@cf/") else MODEL_PREFIX + model
        self._client = client or httpx.Client(timeout=timeout)

    def generate(self, prompt, reference=None, width=576, height=1024):
        """The picture's bytes. `reference` (JPEG bytes, already shrunk) goes up as input_image_0."""
        # (name, (filename, content, type)): giving every field a tuple makes httpx send multipart even without a file.
        fields = [("prompt", (None, prompt)), ("width", (None, str(width))), ("height", (None, str(height)))]
        if reference is not None:
            fields.append(("input_image_0", ("reference.jpg", reference, "image/jpeg")))
        try:
            response = self._client.post(f"{BASE}/{self._account}/ai/run/{self._model}", files=fields,
                                         headers={"Authorization": f"Bearer {self._token}"})
        except httpx.TimeoutException:
            raise ImageError("timeout", timed_out=True) from None
        except httpx.HTTPError as error:
            raise ImageError(f"network: {type(error).__name__}") from None
        try:
            body = response.json()
        except ValueError:
            body = None
        if response.status_code >= 400 or not isinstance(body, dict) or body.get("success") is not True:
            code = _error_code(body) if isinstance(body, dict) else None
            said = _error_text(body) if isinstance(body, dict) else ""
            raise ImageError(f"http {response.status_code}" + (f" code {code}" if code else "") + (f": {said}" if said else ""),
                             status=response.status_code, code=code)
        try:
            return base64.b64decode(body["result"]["image"], validate=True)
        except (KeyError, TypeError, binascii.Error):
            raise ImageError("no picture in the answer", status=response.status_code) from None
