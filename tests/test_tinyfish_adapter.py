"""Talking to TinyFish Search over plain HTTP (spec Part 12, section 4): GET, the key in X-API-Key, place and
language from the settings; anything that goes wrong becomes one kind of error the engine knows how to answer."""
import httpx
import pytest

from companion.apikey import MissingApiKey
from companion.tinyfish_adapter import SearchUnavailable, TinyFishSearch

GOOD = {"query": "q", "results": [{"position": 1, "site_name": "a.com", "title": "標題", "snippet": "摘要", "url": "https://a.com/x"}],
        "total_results": 1, "page": 0}


def adapter(handler, **kwargs):
    seen = []

    def wrapped(request):
        seen.append(request)
        return handler(request)

    client = httpx.Client(transport=httpx.MockTransport(wrapped))
    return TinyFishSearch(api_key="secret-key", client=client, **kwargs), seen


def test_it_sends_a_get_with_the_query_place_language_and_key():
    search, seen = adapter(lambda r: httpx.Response(200, json=GOOD), location="TW", language="zh")
    search.search("台北今天天氣")
    [request] = seen
    assert request.method == "GET" and request.url.host == "api.search.tinyfish.ai"
    assert request.url.params["query"] == "台北今天天氣"
    assert request.url.params["location"] == "TW" and request.url.params["language"] == "zh"
    assert request.headers["X-API-Key"] == "secret-key"


def test_it_returns_the_results_list_as_given():
    search, _ = adapter(lambda r: httpx.Response(200, json=GOOD))
    assert search.search("q") == GOOD["results"]


@pytest.mark.parametrize("response", [
    httpx.Response(429, json={"error": "slow down"}), httpx.Response(500, text="boom"), httpx.Response(401, json={}),
    httpx.Response(429, json=GOOD), httpx.Response(503, json=GOOD),   # an error status is an error whatever the body looks like
    httpx.Response(200, text="not json"), httpx.Response(200, json=["a", "list"]), httpx.Response(200, json={"results": "x"}),
])
def test_a_refusal_or_a_broken_answer_is_a_search_unavailable_error(response):
    search, _ = adapter(lambda r: response)
    with pytest.raises(SearchUnavailable):
        search.search("q")


@pytest.mark.parametrize("error", [httpx.ConnectTimeout("t"), httpx.ReadTimeout("t"), httpx.ConnectError("c"), httpx.RemoteProtocolError("p")])
def test_timeouts_and_network_failures_are_a_search_unavailable_error(error):
    def fail(request):
        raise error

    search, _ = adapter(fail)
    with pytest.raises(SearchUnavailable):
        search.search("q")


def test_it_never_retries_a_failed_request():
    search, seen = adapter(lambda r: httpx.Response(429, json={}))
    with pytest.raises(SearchUnavailable):
        search.search("q")
    assert len(seen) == 1


def test_the_error_does_not_leak_the_key():
    search, _ = adapter(lambda r: httpx.Response(500, text="boom"))
    with pytest.raises(SearchUnavailable) as caught:
        search.search("q")
    assert "secret-key" not in str(caught.value)


def test_without_a_key_it_says_so_instead_of_sending_anything(monkeypatch):
    monkeypatch.setattr("companion.tinyfish_adapter.get_api_key", lambda provider: None)
    with pytest.raises(MissingApiKey):
        TinyFishSearch()


# ---- testing against a local stand-in for the service ---------------------------------------------------------------

@pytest.mark.parametrize("url", ["http://127.0.0.1:8765", "http://localhost:8765/x", "http://[::1]:8765"])
def test_a_local_test_address_in_the_environment_redirects_the_calls_there(monkeypatch, url):
    monkeypatch.setenv("COMPANION_TINYFISH_TEST_URL", url)
    search, seen = adapter(lambda r: httpx.Response(200, json=GOOD))
    search.search("q")
    assert str(seen[0].url).startswith(url.rstrip("/"))


@pytest.mark.parametrize("url", ["https://evil.example.com", "http://192.168.1.5:8765", "http://example.com", "ftp://127.0.0.1", "junk"])
def test_an_address_that_is_not_this_machine_is_ignored_so_the_key_can_never_be_sent_elsewhere(monkeypatch, url):
    monkeypatch.setenv("COMPANION_TINYFISH_TEST_URL", url)
    search = TinyFishSearch(api_key="k", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=GOOD))))
    assert search._url == "https://api.search.tinyfish.ai"
    from companion.tinyfish_adapter import TinyFishFetch
    assert TinyFishFetch(api_key="k")._url == "https://api.fetch.tinyfish.ai"
