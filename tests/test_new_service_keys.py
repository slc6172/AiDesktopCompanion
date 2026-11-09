"""API keys for the two services added in Part 12 (TinyFish, Cloudflare Workers AI): environment
variable first, then the Windows Credential Manager — and never config.json."""
import pytest

from companion import apikey, launcher


class FakeKeyring:
    def __init__(self, stored=None):
        self.stored = dict(stored or {})

    def get_password(self, service, name):
        return self.stored.get((service, name))

    def set_password(self, service, name, value):
        self.stored[(service, name)] = value


@pytest.fixture
def keyring(monkeypatch):
    fake = FakeKeyring()
    monkeypatch.setitem(__import__("sys").modules, "keyring", fake)
    for name in ("TINYFISH_API_KEY", "CF_API_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    return fake


@pytest.mark.parametrize("provider, env_var, stored_name", [
    ("tinyfish", "TINYFISH_API_KEY", "TINYFISH_API_KEY"),
    ("cloudflare", "CF_API_TOKEN", "CF_API_TOKEN"),
])
def test_the_environment_variable_wins_over_the_credential_manager(keyring, monkeypatch, provider, env_var, stored_name):
    keyring.stored[(apikey.SERVICE, stored_name)] = "from-manager"
    assert apikey.get_api_key(provider) == "from-manager"
    monkeypatch.setenv(env_var, "from-env")
    assert apikey.get_api_key(provider) == "from-env"


@pytest.mark.parametrize("provider", ["tinyfish", "cloudflare"])
def test_a_missing_key_is_none_not_an_error(keyring, provider):
    assert apikey.get_api_key(provider) is None


@pytest.mark.parametrize("flag, provider", [("--set-key-tinyfish", "tinyfish"), ("--set-key-cloudflare", "cloudflare")])
def test_the_set_key_commands_store_the_key_for_their_service_and_exit(monkeypatch, flag, provider):
    saved = []
    monkeypatch.setattr(launcher, "set_key_dialog", lambda provider="gemini", label="": saved.append(provider))
    monkeypatch.setattr(launcher, "start_server", lambda *a, **k: pytest.fail("must not start the app"))
    launcher.main([flag])
    assert saved == [provider]


def test_the_key_dialog_saves_under_the_chosen_provider(keyring, monkeypatch):
    import getpass
    import sys

    monkeypatch.setitem(sys.modules, "tkinter", None)  # no window: the dialog falls back to the console prompt
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "  secret-token  ")
    assert launcher.set_key_dialog(provider="cloudflare", label="Cloudflare API Token") is True
    assert keyring.stored == {(apikey.SERVICE, "CF_API_TOKEN"): "secret-token"}
