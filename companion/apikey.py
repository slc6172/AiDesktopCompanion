import os

SERVICE = "ai-companion"
_PROVIDERS = {
    "gemini": {"keyring_name": "GEMINI_API_KEY", "env_vars": ("GEMINI_API_KEY", "GOOGLE_API_KEY")},
    "groq": {"keyring_name": "GROQ_API_KEY", "env_vars": ("GROQ_API_KEY",)},
    "fish": {"keyring_name": "FISH_API_KEY", "env_vars": ("FISH_API_KEY",)},
    # Part 12. These two are accepted from the environment and the Credential Manager ONLY —
    # never from config.json (see features.py, which also warns when one is found there).
    "tinyfish": {"keyring_name": "TINYFISH_API_KEY", "env_vars": ("TINYFISH_API_KEY",)},
    "cloudflare": {"keyring_name": "CF_API_TOKEN", "env_vars": ("CF_API_TOKEN",)},
}


class MissingApiKey(RuntimeError):
    pass


def get_api_key(provider="gemini"):
    """Environment variable first, then the Windows Credential Manager (via keyring).

    `provider` selects which service's key to look up; existing callers that don't pass one
    keep getting the Gemini key exactly as before.
    """
    spec = _PROVIDERS[provider]
    for env_var in spec["env_vars"]:
        key = os.environ.get(env_var)
        if key:
            return key
    try:
        import keyring

        return keyring.get_password(SERVICE, spec["keyring_name"])
    except Exception:
        return None


def save_api_key(key, provider="gemini"):
    import keyring

    keyring.set_password(SERVICE, _PROVIDERS[provider]["keyring_name"], key)
