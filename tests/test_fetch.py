"""Reading one page in full (spec Part 12, section 4, ticket 86): which address may be fetched, and how."""
import httpx
import pytest

from companion.tinyfish_adapter import FetchUnavailable, TinyFishFetch
from companion.websafety import pick_fetch_url

GOOD = {"results": [{"url": "https://a.com/x", "title": "標題", "format": "markdown", "text": "# 標題\n\n內文"}], "errors": []}


def adapter(handler, **kwargs):
    seen = []

    def wrapped(request):
        seen.append(request)
        return handler(request)

    return TinyFishFetch(api_key="secret-key", client=httpx.Client(transport=httpx.MockTransport(wrapped)), **kwargs), seen


def test_it_posts_one_address_as_markdown_with_the_key():
    fetcher, seen = adapter(lambda r: httpx.Response(200, json=GOOD))
    assert fetcher.fetch("https://a.com/x") == {"title": "標題", "text": "# 標題\n\n內文"}
    [request] = seen
    assert request.method == "POST" and request.url.host == "api.fetch.tinyfish.ai"
    import json

    assert json.loads(request.content) == {"urls": ["https://a.com/x"], "format": "markdown"}
    assert request.headers["X-API-Key"] == "secret-key"


@pytest.mark.parametrize("response", [
    httpx.Response(429, json=GOOD), httpx.Response(500, text="x"), httpx.Response(200, text="not json"),
    httpx.Response(200, json={"results": [], "errors": []}), httpx.Response(200, json={"results": [], "errors": [{"url": "u", "error": "blocked"}]}),
    httpx.Response(200, json={"results": [{"url": "u", "title": "t"}], "errors": []}),     # no text
    httpx.Response(200, json=["x"]),
])
def test_anything_but_a_page_with_text_is_a_fetch_unavailable_error(response):
    fetcher, _ = adapter(lambda r: response)
    with pytest.raises(FetchUnavailable):
        fetcher.fetch("https://a.com/x")


@pytest.mark.parametrize("error", [httpx.ReadTimeout("t"), httpx.ConnectError("c")])
def test_network_trouble_is_a_fetch_unavailable_error_and_is_never_retried(error):
    calls = []

    def fail(request):
        calls.append(1)
        raise error

    fetcher, _ = adapter(fail)
    with pytest.raises(FetchUnavailable):
        fetcher.fetch("https://a.com/x")
    assert len(calls) == 1


def item(url):
    return {"title": "t", "snippet": "s", "url": url}


def test_the_first_address_that_passes_is_chosen_from_the_search_results():
    raw = [item("https://one.com/a"), item("https://two.com/b")]
    assert pick_fetch_url(raw, blocked=[]) == "https://one.com/a"


@pytest.mark.parametrize("bad", [
    "http://plain.com/a", "ftp://files.com/a", "https://127.0.0.1/a", "https://192.168.1.5/a", "https://[::1]/a", "https://10.0.0.1:8443/a",
    "https://localhost/a", "https://app.localhost/a", "https://printer.local/a", "https://db.internal/a", "https://user:pw@evil.com/a",
    "https://evil.com:8080/a", "https:///nohost", "javascript:alert(1)", "//evil.com/a", "", "not a url", None, 5,
])
def test_an_address_that_is_not_a_plain_public_https_page_is_never_chosen(bad):
    assert pick_fetch_url([item(bad), item("https://fine.com/ok")], blocked=[]) == "https://fine.com/ok"


def test_blocked_sites_and_their_sub_domains_are_skipped():
    raw = [item("https://bad.com/a"), item("https://m.bad.com/a"), item("https://fine.com/a")]
    assert pick_fetch_url(raw, blocked=["bad.com"]) == "https://fine.com/a"


def test_when_nothing_passes_nothing_is_chosen():
    assert pick_fetch_url([item("http://a.com"), item("https://127.0.0.1/")], blocked=[]) is None
    assert pick_fetch_url([], blocked=[]) is None
    assert pick_fetch_url("junk", blocked=[]) is None
