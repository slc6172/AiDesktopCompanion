"""The block of the system prompt that tells her what is true about herself right now (spec Part 12).

Everything she "is" at this moment in one place: where she is, how her body feels, what she wears
and carries, and how close she is to the person. Plain functions — no storage, no clock of their own.
"""

HEADER = "\n\n【你現在的狀態】"


# Told to her together with the other optional tags ([好感±N], [心情:詞]) in the format rules — the one place she
# reliably follows — and, like them, written at the END of her reply. (The first version put this inside the state
# block and said "at the very start"; that contradicted the format rules and she followed it only some of the time.)
TAG_RULES = (
    "\n\n【狀態標籤】你的地點、身體狀態、持有物品是系統幫你記的,要靠你寫標籤來更新,和 [好感]、[心情] 一樣寫在這一輪回覆的最後"
    "(標籤不會被唸出來,也不會顯示給使用者)。只在事情「已經發生了改變」的那一輪才寫,不論是使用者說的還是你自己決定的:\n"
    "- [地點:新地點]——你們到了、來到、回到某處(10 字內),例如 [地點:公園],回到家寫 [地點:家裡]\n"
    "- [狀態:短詞]——你喝了酒、感冒、很累等身體狀態改變(8 字內),例如 [狀態:微醺]、[狀態:感冒];恢復正常寫 [狀態:正常]\n"
    "- [得到:物品]——你收到禮物、買了、拿到東西(10 字內),例如 [得到:紅洋裝]\n"
    "- [失去:物品]——你弄丟、送人、借出去(10 字內),例如 [失去:鑰匙]\n"
    "例:使用者說「這件洋裝送你」,你收下了,回覆最後就加上 [得到:洋裝];使用者說「我們到公園了」,最後加上 [地點:公園]。\n"
    "假設(如果……)、問句、別人的事、還沒發生的事,都不要寫。")
TAG_REMINDER = "(以上任何一項有改變時,記得照【狀態標籤】的規則在回覆最後寫標籤。)"


def effective_status(status, set_at, now, settings):
    """The body status that still holds, or None. A status wears off after its own number of hours
    (a word nobody listed uses the default), counted from when it was set; one with no recorded
    time cannot be dated, so it is treated as worn off. Worked out here, when asked — no timers."""
    if not status or set_at is None:
        return None
    hours = settings["status_ttl_hours"].get(status, settings["default_status_ttl_hours"])
    return status if now - set_at <= hours * 3600 else None


def state_block(character, outfit_lines, relationship_lines, now, settings):
    """`character` is the stored state; `outfit_lines` the clothes part (from the wardrobe, may be
    empty); `relationship_lines` the affection and mood part."""
    status = effective_status(character["status"], character["status_set_at"], now, settings)
    items = "、".join(character["items"]) if character["items"] else "沒有"
    lines = [
        "這是你目前真實的狀態,請讓你說的話和做的事與它一致。",
        f"地點:{character['location']}",
        f"身體狀態:{status or '正常'}",
        f"持有物品:{items}",
        *outfit_lines,
        *relationship_lines,
        TAG_REMINDER,
    ]
    return HEADER + "\n" + "\n".join(lines)
