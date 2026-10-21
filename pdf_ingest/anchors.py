"""Locate evidence quotes inside page-anchored text.

PDF extraction inserts line breaks wherever the visual line ends, so a quote
copied from a rendered paper rarely matches raw page text exactly. Matching is
therefore whitespace-insensitive: collapse runs of whitespace on both sides.
"""

from __future__ import annotations

import re
from typing import Iterable

_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    return _WS.sub(" ", text or "").strip()


def locate_quote(
    text: str, page_anchors: Iterable[dict], page: int, quote: str
) -> dict | None:
    """Return ``{page, start, end}`` when ``quote`` occurs on ``page``.

    ``start`` / ``end`` are the page's character range in the full text (not the
    quote's), so callers can show the page context. Matching ignores whitespace
    differences but not wording.
    """
    target = normalize(quote)
    if not target:
        return None
    for anchor in page_anchors:
        if anchor.get("page") != page:
            continue
        if target in normalize(text[anchor["start"] : anchor["end"]]):
            return {
                "page": page,
                "start": anchor["start"],
                "end": anchor["end"],
            }
        return None
    return None
