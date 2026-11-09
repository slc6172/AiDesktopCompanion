"""Finding things that are no longer in front of her (spec Part 12, section 8).

Every turn the user's message is matched against the older conversation, the journal and any facts
that did not fit into the always-present memory. Local and cheap: no model call, no index to keep.

How a match is decided (the numbers are a conservative starting point, adjustable in config):
  - The text is cut into character pairs (bigrams) — what works for Chinese, where a word is often
    two characters; FTS5 could not find those. Pairs containing a very common character (的 了 我 你 …)
    are ignored, so everyday chatter never counts as "the same topic".
  - A pair that appears in few of the candidate texts is strong evidence, one that appears in many
    is weak: each shared pair is weighted ln(1 + N/df) / ln(1 + N), so a pair found in a single text
    weighs exactly 1. A text needs a combined weight of `min_score` (default 0.6) to be shown: a pair found
    in two or three texts out of hundreds still counts, a pair found in a fifth of them does not.
"""
import math
import re
from collections import Counter

_FUNCTION_CHARS = frozenset("的了在是我你他她它們這那有不也都就和與及嗎吧呢啊喔哦呀嘛跟說")
_WORD = re.compile(r"\w+")


def grams(text):
    """The meaningful character pairs of `text`, in order, without repeats."""
    seen = {}
    for segment in _WORD.findall(text.lower()):
        for a, b in zip(segment, segment[1:]):
            if a not in _FUNCTION_CHARS and b not in _FUNCTION_CHARS:
                seen.setdefault(a + b)
    return list(seen)


def retrieve(query, docs, k, snippet_chars, min_score):
    """The best `k` of `docs` ({"text", "date", "label"}, oldest first) for `query`: (date, label, snippet)."""
    query_grams = grams(query)
    if not query_grams or not docs:
        return []
    lowered = [d["text"].lower() for d in docs]
    matched = [[g for g in query_grams if g in text] for text in lowered]
    frequency = Counter(g for found in matched for g in found)
    total = math.log(1 + len(docs))
    scored = []
    for order, (doc, text, found) in enumerate(zip(docs, lowered, matched)):
        if not found:
            continue
        score = sum(math.log(1 + len(docs) / frequency[g]) / total for g in found)
        if score >= min_score - 1e-9:
            scored.append((score, order, doc, text, found[0]))
    scored.sort(key=lambda item: (-item[0], -item[1]))  # best first; the more recent wins a tie
    return [(doc["date"], doc["label"], _snippet(doc["text"], text, first, snippet_chars))
            for _, _, doc, text, first in scored[:k]]


def _snippet(original, lowered, gram, limit):
    if len(original) <= limit:
        return original
    start = max(0, lowered.find(gram) - limit // 4)
    cut = original[start:start + limit - 2]
    return ("…" if start else "") + cut + ("…" if start + limit - 2 < len(original) else "")


def retrieval_block(hits):
    if not hits:
        return ""
    lines = [f"- {date + ' ' if date else ''}{label}:{snippet}" for date, label, snippet in hits]
    return "\n\n【可能相關的記憶】(從更早的對話與日誌找出的片段,不一定完全準確,請自然運用)\n" + "\n".join(lines)
