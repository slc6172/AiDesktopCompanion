"""Does the user's own sentence order her to look something up? (spec Part 12, section 4)

The user's words are trusted, so a clear command can skip the model's first pass and search at once. Only a
short, unmistakable command counts: before the trigger phrase there may only be politeness, and there must
be something left to look up. A question about whether she could ("你可以上網查嗎"), a refusal ("不要上網查"),
or talk that merely mentions searching is left alone — the model can still choose to search itself.
"""
import re
from dataclasses import dataclass

_TRIGGERS = sorted([
    "上網幫我查一下", "上網幫我查", "上網幫我搜尋一下", "上網幫我搜尋", "上網查一下", "上網搜尋一下", "上網查", "上網搜尋",
    "網路上查", "幫我上網查一下", "幫我上網查", "幫我上網搜尋", "幫我查一下", "幫我查", "幫我搜尋一下", "幫我搜尋",
    "幫忙查一下", "幫忙查", "查一下", "搜尋一下", "搜尋",
], key=len, reverse=True)
_HEAD = frozenset("請麻煩可以你先就快點再好嗯那對,\uff0c ")
_DEEP = re.compile(r"(?:仔細|詳細|完整)地?(?=查|搜)")
_TRAILING = " \t吧啦喔哦啊呀嘛~\uff5e!\uff01\u3002.\u2026,\uff0c?\uff1f"
_LEADING = " \t:\uff1a,\uff0c"
_BRACKETS = re.compile(r"[\[\]【】]")
MAX_QUERY_CHARS = 100
MIN_QUERY_CHARS = 2


@dataclass(frozen=True)
class SearchRequest:
    query: str
    deep: bool  # she was asked to look carefully ("仔細查"): read a page, not just the search snippets


def split_depth(payload):
    """(words, deep) from what she wrote inside [搜尋:…]: "台北天氣|深入" asks for a page to be read as well."""
    for bar in ("|", "\uff5c"):
        head, found, tail = payload.rpartition(bar)
        if found and tail.strip() == "深入":
            return head, True
    return payload, False


def clean_query(text):
    """What to look up from words that may come from anywhere (the user, or the model's tag): brackets
    removed, tidied, cut to 100 characters; None when too little is left to look anything up."""
    query = re.sub(r"\s+", " ", _BRACKETS.sub(" ", text)).strip()[:MAX_QUERY_CHARS].strip()
    return query if len(query) >= MIN_QUERY_CHARS else None


def match_search_request(text):
    """A SearchRequest if `text` is a clear order to look something up, else None."""
    text = text.strip()
    deep = _DEEP.search(text) is not None
    text = _DEEP.sub("", text)
    triggers = _TRIGGERS + (["查"] if deep else [])
    triggers.sort(key=len, reverse=True)
    for trigger in triggers:
        at = text.find(trigger)
        if at < 0 or not all(c in _HEAD for c in text[:at]):
            continue
        rest = text[at + len(trigger):]
        if trigger == "搜尋" and rest[:1] not in (" ", ":", "\uff1a"):
            continue  # "搜尋引擎是什麼" is not an order
        query = clean_query(rest.lstrip(_LEADING).rstrip(_TRAILING))
        if query is not None:
            return SearchRequest(query, deep)
    return None
