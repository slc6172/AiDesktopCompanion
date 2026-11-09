"""The tag registry: every bracketed tag the model may write, in one table (spec Part 12, ticket 70).

There is ONE parser (the segmenter in engine.py). A tag kind is a row here; adding a new one means
adding a row, not another parser.

Two families:
  meta    — taken wherever they appear (a state can change mid-sentence), removed from the text,
            applied only when the turn is saved. Short (<= 16 characters) for the legacy 好感/心情;
            the state tags have their own, longer scan so an over-long one is dropped instead of
            being spoken aloud.
  action  — things with consequences outside the conversation (change outfit, search, take a
            photo). Only recognised at the very START of a reply, at most one per kind per turn;
            anywhere else they are removed from the text and NOT run.

On a polluted turn (one that used web content) everything except the mood tag is ignored — the
structural defence against a web page talking the model into doing something.
"""
import re
from dataclasses import dataclass

ACTION_PAYLOAD_MAX = 120


@dataclass(frozen=True)
class TagSpec:
    name: str
    family: str                      # "meta" | "action"
    per_turn: int                    # how many may take effect in one turn
    max_payload: int | None = None   # validation limit on the payload (None = not checked here)
    group: str | None = None         # kinds sharing one per-turn budget
    legacy: bool = False             # parsed by the older <=16-character path in the segmenter


REGISTRY = {spec.name: spec for spec in (
    TagSpec("好感", "meta", 1, legacy=True),
    TagSpec("心情", "meta", 1, legacy=True),
    TagSpec("地點", "meta", 1, max_payload=10),
    TagSpec("狀態", "meta", 1, max_payload=8),
    TagSpec("得到", "meta", 2, max_payload=10, group="items"),
    TagSpec("失去", "meta", 2, max_payload=10, group="items"),
    TagSpec("換裝", "action", 1),
    TagSpec("搜尋", "action", 1),
    TagSpec("照片", "action", 1),
)}

_NAMES = "|".join(name for name, spec in REGISTRY.items() if not spec.legacy)
_BODY = r"\s*[:\uff1a]\s*([^\[\]【】]{0,%d})" % ACTION_PAYLOAD_MAX
# A complete tag of a registry kind (half- or full-width brackets and colon).
REGISTRY_TAG = re.compile(r"[\[【]\s*(" + _NAMES + r")" + _BODY + r"[\]】]")
# The beginning of one that has not been closed yet (the rest is still to come in the stream).
OPEN_REGISTRY_TAG = re.compile(r"[\[【]\s*(" + _NAMES + r")\s*[:\uff1a][^\[\]【】]{0,%d}$" % ACTION_PAYLOAD_MAX)
_ACTION_NAMES = "|".join(n for n, s in REGISTRY.items() if s.family == "action")
_ACTION_TAG = re.compile(r"[\[【]\s*(?:" + _ACTION_NAMES + r")" + _BODY + r"[\]】]")


def valid_payload(name, payload):
    """The cleaned payload of a state tag, or None when it must be thrown away."""
    payload = payload.strip()
    limit = REGISTRY[name].max_payload
    if not payload or (limit is not None and len(payload) > limit):
        return None
    return payload


def strip_action_tags(text):
    """What is saved to the history: the reply without its action tags (the features keep their own markers)."""
    return _ACTION_TAG.sub("", text)
