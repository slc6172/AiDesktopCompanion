"""The always-present part of her memory, as text for the system prompt (spec Part 12, section 8):
the long-term facts, then today's and yesterday's journal. Plain functions — no storage, no clock.

Both parts have a size limit. Over it, the facts keep their earlier lines (sections come in a fixed
order, the most important first) and a day's journal keeps its LATEST lines: what happened last is
what matters most today.
"""
from .history import SECTIONS


def _fit_facts(facts, max_chars):
    """[(section, [lines that fit])] in showing order, within `max_chars` (headings not counted)."""
    fitted, used = [], 0
    for section in SECTIONS:
        kept = []
        for line in facts.get(section, "").splitlines():
            if not line.strip():
                continue
            if used + len(line) + 1 > max_chars:
                break
            kept.append(line)
            used += len(line) + 1
        if kept:
            fitted.append((section, kept))
        if used >= max_chars:
            break
    return fitted


def long_term_block(facts, max_chars):
    lines = []
    for section, kept in _fit_facts(facts, max_chars):
        lines += [f"〔{section}〕", *kept]
    return "\n\n【長期記憶(自然運用,不要逐條複述)】\n" + "\n".join(lines) if lines else ""


def left_out_fact_lines(facts, max_chars):
    """The fact lines that did NOT fit into the always-present block (so they are worth looking up)."""
    shown = {(section, line) for section, kept in _fit_facts(facts, max_chars) for line in kept}
    return [line for section in SECTIONS for line in facts.get(section, "").splitlines()
            if line.strip() and (section, line) not in shown]


def _journal_line(event):
    return "- " + (f"{event['time']} " if event.get("time") else "") + event["text"]


def _latest_that_fit(events, max_chars):
    kept, used = [], 0
    for event in reversed(events):
        line = _journal_line(event)
        if used + len(line) + 1 > max_chars:
            break
        kept.append(line)
        used += len(line) + 1
    return list(reversed(kept))


def journal_block(yesterday, today, yesterday_events, today_events, max_chars):
    parts = []
    for label, date, events in (("昨天", yesterday, yesterday_events), ("今天", today, today_events)):
        lines = _latest_that_fit(events, max_chars)
        if lines:
            parts.append(f"{label} {date}:\n" + "\n".join(lines))
    return "\n\n【最近的日誌】\n" + "\n".join(parts) if parts else ""
