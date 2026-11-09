"""The server answers only to a Host naming this machine (see server.only_this_machine); Starlette's TestClient
defaults to "testserver", so every test client here talks to 127.0.0.1 instead, as the real window does."""
import inspect

from starlette.testclient import TestClient

_original_init = TestClient.__init__
_BASE_URL_DEFAULT = "http://127.0.0.1"


def _init(self, *args, **kwargs):
    params = list(inspect.signature(_original_init).parameters)  # self, app, base_url, ...
    if "base_url" not in kwargs and len(args) < params.index("base_url"):
        kwargs["base_url"] = _BASE_URL_DEFAULT
    _original_init(self, *args, **kwargs)


TestClient.__init__ = _init
