"""The Cloudflare Workers AI image adapter (spec Part 12, section 5): what it puts on the wire and how it reads
the answer. The network is a fake transport; no real service is touched."""
import base64
from email import message_from_bytes

import httpx
import pytest

from companion.cloudflare_adapter import CloudflareImage, ImageError

PICTURE = b"\x89PNG\r\n\x1a\nfake"
TOKEN = "cf-secret-token-123"


def parse_multipart(request):
    raw = b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + request.content
    parts = {}
    for part in message_from_bytes(raw).get_payload():
        parts[part.get_param("name", header="content-disposition")] = (
            part.get_filename(), part.get_content_type(), part.get_payload(decode=True))
    return parts


def adapter_over(handler, **kwargs):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return CloudflareImage(api_token=TOKEN, account_id="ACC123", client=client, **kwargs)


def success(request):
    return httpx.Response(200, json={"success": True, "errors": [], "messages": [],
                                     "result": {"image": base64.b64encode(PICTURE).decode()}})


def test_a_text_only_request_is_multipart_with_a_bearer_token_and_the_picture_comes_back_decoded():
    seen = []

    def handler(request):
        seen.append(request)
        return success(request)

    picture = adapter_over(handler).generate("a cat", None, 576, 1024)
    assert picture == PICTURE
    request = seen[0]
    assert request.method == "POST"
    assert request.url.path == "/client/v4/accounts/ACC123/ai/run/@cf/black-forest-labs/flux-2-klein-9b"
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert request.headers["content-type"].startswith("multipart/form-data")
    fields = {name: data for name, (_file, _kind, data) in parse_multipart(request).items()}
    assert fields == {"prompt": b"a cat", "width": b"576", "height": b"1024"}     # no input_image_0 at all


def test_a_reference_picture_goes_up_as_input_image_0_and_the_model_name_can_be_changed():
    seen = []

    def handler(request):
        seen.append(request)
        return success(request)

    adapter_over(handler, model="flux-2-klein-4b").generate("a cat", b"\xff\xd8\xffjpegbytes", 576, 1024)
    assert seen[0].url.path.endswith("/ai/run/@cf/black-forest-labs/flux-2-klein-4b")
    parts = parse_multipart(seen[0])
    assert set(parts) == {"prompt", "width", "height", "input_image_0"}
    assert parts["input_image_0"] == ("reference.jpg", "image/jpeg", b"\xff\xd8\xffjpegbytes")


@pytest.mark.parametrize("response, status, code", [
    (httpx.Response(429, json={"success": False, "errors": [{"code": 3036, "message": "daily"}]}), 429, 3036),
    (httpx.Response(403, json={"success": False, "errors": [{"code": 5035, "message": "paid"}]}), 403, 5035),
    (httpx.Response(200, json={"success": False, "errors": [{"code": 5004, "message": "bad"}]}), 200, 5004),
    (httpx.Response(500, text="<html>oops</html>"), 500, None),
    (httpx.Response(200, json={"success": True, "result": {}}), 200, None),                     # no image in it
    (httpx.Response(200, json={"success": True, "result": {"image": "***not base64***"}}), 200, None),
    (httpx.Response(200, json={"success": True, "result": {"image": "QUJD!REVG"}}), 200, None),   # stray characters inside
])
def test_anything_but_a_clean_success_is_an_error_that_carries_the_status_and_code(response, status, code):
    with pytest.raises(ImageError) as caught:
        adapter_over(lambda request: response).generate("a cat", None, 576, 1024)
    assert (caught.value.status, caught.value.code) == (status, code)


def test_a_timeout_is_an_error_marked_as_a_timeout():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ImageError) as caught:
        adapter_over(handler).generate("a cat", None, 576, 1024)
    assert caught.value.timed_out and caught.value.status is None


def test_the_token_never_appears_in_an_error_message():
    def handler(request):
        raise httpx.ConnectError(f"cannot reach {request.headers['authorization']}", request=request)

    with pytest.raises(ImageError) as caught:
        adapter_over(handler).generate("a cat", None, 576, 1024)
    assert TOKEN not in str(caught.value) and TOKEN not in repr(caught.value)


def test_cloudflares_own_explanation_is_kept_in_the_error_so_the_log_can_say_what_went_wrong():
    response = httpx.Response(400, json={"success": False, "errors": [{"code": 9999, "message": "prompt was refused"}]})
    with pytest.raises(ImageError) as caught:
        adapter_over(lambda request: response).generate("a cat", None, 576, 1024)
    assert "prompt was refused" in str(caught.value) and TOKEN not in str(caught.value)
