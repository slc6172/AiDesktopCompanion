"""TinyFish Search over plain HTTP (spec Part 12, section 4): no SDK, one GET.

Whatever goes wrong — a refusal, a limit, a timeout, a broken answer — is raised as the one error the engine
knows how to turn into "I can't reach the internet right now". A request is never retried here.
"""
import logging
import os
from urllib.parse import urlsplit

import httpx

from .apikey import MissingApiKey, get_api_key

log = logging.getLogger(__name__)

SEARCH_URL = "https://api.search.tinyfish.ai"


def _service_url(default):
    """The service address — or, for trying the program against a local stand-in (tools/fake_tinyfish.py),
    the address in COMPANION_TINYFISH_TEST_URL. Only an address on THIS machine is ever accepted, so the key
    can never be sent anywhere else by way of this setting."""
    test_url = os.environ.get("COMPANION_TINYFISH_TEST_URL")
    if test_url:
        try:
            parts = urlsplit(test_url)
            if parts.scheme in ("http", "https") and parts.hostname in ("127.0.0.1", "localhost", "::1"):
                return test_url.rstrip("/")
        except ValueError:
            pass
        log.warning("COMPANION_TINYFISH_TEST_URL is not an address on this machine; ignored")
    return default


class SearchUnavailable(Exception):
    """The search could not be done (limit reached, network, bad answer). Never carries the key."""


class TinyFishSearch:
    def __init__(self, api_key=None, location="TW", language="zh", timeout=15.0, client=None, url=None):
        self._key = api_key or get_api_key("tinyfish")
        if not self._key:
            raise MissingApiKey("tinyfish")
        self._location, self._language, self._url = location, language, url or _service_url(SEARCH_URL)
        self._client = client or httpx.Client(timeout=timeout)

    def search(self, query):
        """The raw results list: [{"position", "site_name", "title", "snippet", "url"}, ...]."""
        try:
            response = self._client.get(
                self._url, params={"query": query, "location": self._location, "language": self._language},
                headers={"X-API-Key": self._key})
        except httpx.HTTPError as error:
            raise SearchUnavailable(f"network: {type(error).__name__}") from None
        if response.status_code == 429:
            raise SearchUnavailable("rate limited")
        if response.status_code >= 400:
            raise SearchUnavailable(f"http {response.status_code}")
        try:
            results = response.json()["results"]
        except (ValueError, KeyError, TypeError):
            raise SearchUnavailable("unreadable answer") from None
        if not isinstance(results, list):
            raise SearchUnavailable("unreadable answer")
        return results


FETCH_URL = "https://api.fetch.tinyfish.ai"


class FetchUnavailable(Exception):
    """The page could not be read. Never carries the key."""


class TinyFishFetch:
    """TinyFish Fetch: one address in, the page as Markdown text out. Only the fields the documentation lists
    for the REST call are sent (`urls`, `format`); links and image addresses are taken out afterwards by the
    cleaning in websafety.py, whatever the service keeps."""

    def __init__(self, api_key=None, timeout=60.0, client=None, url=None):
        self._key = api_key or get_api_key("tinyfish")
        if not self._key:
            raise MissingApiKey("tinyfish")
        self._url = url or _service_url(FETCH_URL)
        self._client = client or httpx.Client(timeout=timeout)

    def fetch(self, page_url):
        """{"title", "text"} of the page."""
        try:
            response = self._client.post(self._url, json={"urls": [page_url], "format": "markdown"},
                                         headers={"X-API-Key": self._key, "Content-Type": "application/json"})
        except httpx.HTTPError as error:
            raise FetchUnavailable(f"network: {type(error).__name__}") from None
        if response.status_code >= 400:
            raise FetchUnavailable(f"http {response.status_code}")
        try:
            page = response.json()["results"][0]
            text = page["text"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise FetchUnavailable("no page came back") from None
        if not isinstance(text, str) or not text.strip():
            raise FetchUnavailable("the page had no text")
        title = page.get("title") if isinstance(page.get("title"), str) else ""
        return {"title": title, "text": text}
