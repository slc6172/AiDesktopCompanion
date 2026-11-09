"""Pure helpers behind the character's sense of time (spec Part 11). No I/O, no clock of its
own: callers pass in epoch seconds and a tzinfo (None = this computer's local time zone), which
is what makes all of it testable with a fake clock."""
from datetime import datetime

WEEKDAYS = "一二三四五六日"


def local_datetime(epoch, tz):
    """The wall-clock datetime for an epoch time in `tz` (None = the computer's local zone)."""
    if tz is None:
        return datetime.fromtimestamp(epoch).astimezone()
    return datetime.fromtimestamp(epoch, tz)


def format_time(epoch, tz):
    """e.g. "2026-10-07(週三) 21:40" — the one format used everywhere the model is shown a time."""
    dt = local_datetime(epoch, tz)
    return f"{dt:%Y-%m-%d}(週{WEEKDAYS[dt.weekday()]}) {dt:%H:%M}"


# (first hour of the part, name): the part of the day lasts until the next entry starts.
DAY_PARTS = [(0, "凌晨"), (5, "早上"), (11, "中午"), (13, "下午"), (18, "晚上"), (23, "深夜")]


def day_part(epoch, tz):
    hour = local_datetime(epoch, tz).hour
    return [name for start, name in DAY_PARTS if hour >= start][-1]


# (lower bound in seconds, label, what it means for how to behave) — the bound is inclusive.
GAP_TIERS = [
    (0, "接續", "視為連續的對話,直接接著聊。"),
    (30 * 60, "隔了一陣子", "話題多半還接得上,可以自然帶過。"),
    (6 * 3600, "過了半天以上", "話題未必接得上,不要硬接上一個話題。"),
    (24 * 3600, "隔了好幾天", "不要當成剛剛才說的話,可以自然問候近況。"),
    (7 * 24 * 3600, "很久沒聊", "有好久不見的感覺,不要假裝什麼都沒發生。"),
]


def gap_tier(seconds):
    return [tier for tier in GAP_TIERS if seconds >= tier[0]][-1]


def format_date(epoch, tz):
    """e.g. "2026-10-07 週三" — just the day, for dating events in the long-term memory."""
    dt = local_datetime(epoch, tz)
    return f"{dt:%Y-%m-%d} 週{WEEKDAYS[dt.weekday()]}"


def humanize(seconds):
    """Roughly how long, rounded down, in the largest unit that fits."""
    if seconds < 60:
        return "不到 1 分鐘"
    if seconds < 3600:
        return f"{int(seconds // 60)} 分鐘"
    if seconds < 24 * 3600:
        return f"{int(seconds // 3600)} 小時"
    days = int(seconds // (24 * 3600))
    if days < 14:
        return f"{days} 天"
    if days < 56:
        return f"{days // 7} 週"
    return f"{days // 30} 個月"


def _about(text):
    return text if text.startswith("不到") else f"約 {text}"


def in_range(minutes, start, end):
    """Is `minutes` (since midnight) in [start, end)? An end that is not after the start means the
    range crosses midnight."""
    return start <= minutes < end if start < end else (minutes >= start or minutes < end)


def in_quiet_hours(epoch, tz, quiet):
    dt = local_datetime(epoch, tz)
    return quiet["enabled"] and in_range(dt.hour * 60 + dt.minute, quiet["start"], quiet["end"])


def current_period(epoch, tz, routine):
    """The first routine entry whose time range contains `epoch`, or None. An entry whose end is
    not after its start crosses midnight (23:00 -> 07:00 means 23:00 onwards, or before 07:00)."""
    dt = local_datetime(epoch, tz)
    minutes = dt.hour * 60 + dt.minute
    for entry in routine:
        start, end = entry["start"], entry["end"]
        if in_range(minutes, start, end):
            return entry
    return None


def period_instance(epoch, tz, entry):
    """Which occurrence of a period `epoch` belongs to: (name, the date that occurrence began).
    The small hours of a night that began yesterday belong to yesterday's occurrence, so 23:30 and
    the 01:00 after it are one night, while 23:30 on two different days are two."""
    from datetime import timedelta

    dt = local_datetime(epoch, tz)
    began = dt.date()
    if entry["start"] >= entry["end"] and dt.hour * 60 + dt.minute < entry["end"]:
        began -= timedelta(days=1)
    return (entry["name"], began)


def time_block(now, tz, last_time=None, period=None):
    """The "what time is it" part of the system prompt. `last_time` is when the previous message
    was written (epoch seconds) or None if there is none / it isn't known."""
    lines = ["\n\n【時間資訊(系統提供)】", f"現在是 {format_time(now, tz)},{day_part(now, tz)}。"]
    if last_time is not None:
        gap = max(0.0, now - last_time)  # a clock that went backwards counts as "no time passed"
        _, label, meaning = gap_tier(gap)
        lines.append(f"距離上一則訊息:{_about(humanize(gap))}({label}:{meaning})")
        lines.append(f"上一則訊息的時間:{format_time(last_time, tz)}")
    if period is not None:
        lines.append(f"現在是{period['name']}時段:{period['hint']}")
    lines.append(
        "請依這些時間資訊自然地反應,不要逐項報時(除非使用者問);"
        "不要把久遠的對話當成剛剛才說的。"
        "對話紀錄裡的時間註記(例如「距上一句約…」)是系統加的,不要在回覆中複述。"
    )
    return "\n".join(lines)


def gap_marker(seconds):
    """The one-line note put in front of a message that came after a long silence."""
    return f"(距上一句{_about(humanize(seconds))})"
