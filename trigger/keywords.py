"""Parse the manual-push keywords sent from Lark.

Accepted forms (case-insensitive for Latin keywords):

    再推一篇
    下一篇 hmbs
    next virtual-cell
    more: HMBS

The optional suffix is a checkpoint id or label.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

KEYWORDS = ("再推一篇", "下一篇", "next", "more")
_PATTERN = re.compile(
    r"^\s*(再推一篇|下一篇|next|more)\s*[:：]?\s*(.*?)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Request:
    keyword: str
    checkpoint: str | None = None


def parse(text: str) -> Request | None:
    match = _PATTERN.match(text or "")
    if not match:
        return None
    checkpoint = match.group(2).strip() or None
    return Request(keyword=match.group(1), checkpoint=checkpoint)


def resolve_checkpoint(name: str | None, cards: list[dict]) -> str | None:
    """Resolve a knowledge-card id or exact label; None means 'use the default rule'."""
    if not name:
        return None
    needle = name.strip().lower()
    for card in cards:
        card_id = str(card.get("id") or "")
        label = str(card.get("label") or "")
        if needle in {card_id.lower(), label.lower()}:
            return card_id
    return ""
