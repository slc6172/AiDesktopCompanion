"""Which optional features work this run (spec Part 12, section 6).

A feature is available when it is switched on AND has what it needs. One that is on but cannot
work is turned off and explained once; the program still starts. (Gemini stays mandatory — that
check lives where it always did.)
"""
import os
from dataclasses import dataclass

from .apikey import get_api_key
from .config import (load_config, resolve_engine, resolve_image_config, resolve_memory_config, resolve_stt_config,
                     resolve_tinyfish_config, resolve_tts_config)

# Keys that must never be read from config.json for the new services (the environment and the
# Credential Manager only). If one is found there we say so — without ever repeating its value.
_SECRET_FIELDS = ("api_key", "api_token", "token")


@dataclass(frozen=True)
class Features:
    image: bool
    tinyfish: bool
    memory: bool
    stt: bool = True
    notices: tuple = ()  # plain-language messages to show the person once per run


def _secrets_in_the_file(raw_config):
    found = []
    for block in ("tinyfish", "image"):
        section = raw_config.get(block)
        if isinstance(section, dict):
            found += [f"{block}.{field}" for field in _SECRET_FIELDS if section.get(field)]
    return found


def resolve_features(get_key=None):
    get_key = get_key or get_api_key  # looked up now, not when this file was loaded
    notices = []
    for field in _secrets_in_the_file(load_config()):
        notices.append(f"config.json 裡的 {field} 不會被使用(金鑰只接受環境變數或 Windows 憑證管理員),請把它從檔案中移除。")

    tinyfish = resolve_tinyfish_config()
    tinyfish_on = False
    if tinyfish["enabled"]:
        tinyfish_on = bool(get_key("tinyfish"))
        if not tinyfish_on:
            notices.append("上網查資料已啟用,但找不到 TinyFish API 金鑰,所以先關閉。"
                           "請執行 app.py --set-key-tinyfish(或設定環境變數 TINYFISH_API_KEY)。")

    image = resolve_image_config()
    image_on = False
    if image["enabled"]:
        missing = []
        if not get_key("cloudflare"):
            missing.append("Cloudflare API Token(執行 app.py --set-key-cloudflare,或設定環境變數 CF_API_TOKEN)")
        if not image["account_id"]:
            missing.append("Cloudflare 帳號 ID(config.json 的 image.account_id,或環境變數 CF_ACCOUNT_ID)")
        image_on = not missing
        if missing:
            notices.append("拍照功能已啟用,但缺少:" + "、".join(missing) + ",所以先關閉。")

    # Speech. The switch comes first: when it is off nothing about that direction is examined.
    tts = resolve_tts_config()
    if tts["enabled"] and resolve_engine(tts["engine"], tts["primetts_url"]) == "fish" and not get_key("fish"):
        notices.append("語音引擎設為 Fish Audio,但找不到 Fish API 金鑰,先改用 edge-tts。"
                       "請執行 app.py --set-key-fish(或設定環境變數 FISH_API_KEY)。")
    stt_on = False
    if resolve_stt_config()["enabled"]:
        stt_on = os.environ.get("COMPANION_FAKE") == "1" or bool(get_key("groq"))  # the offline demo brings its own listener
        if not stt_on:
            notices.append("語音輸入已啟用,但找不到 Groq API 金鑰,所以先關閉麥克風(仍可打字)。"
                           "請執行 app.py --set-key-groq(或設定環境變數 GROQ_API_KEY)。")

    return Features(image=image_on, stt=stt_on, tinyfish=tinyfish_on,
                    memory=resolve_memory_config()["enabled"],
                    notices=tuple(notices))
