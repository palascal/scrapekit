"""Shared price helpers for card text extraction."""

from __future__ import annotations

import re

from scrapekit.price import _price_to_float as price_to_float  # noqa: F401


def best_price_from_text(
    card_text: str,
    text: str = "",
    price_re: re.Pattern | None = None,
    *,
    min_val: float = 80,
    max_val: float = 40_000,
) -> str:
    """Pick the most plausible price match from card/title text."""
    blob = f"{card_text or ''} {text or ''}"
    windows = [blob[-120:], blob]
    matches: list[str] = []
    for window in windows:
        preferred = re.findall(
            r"(?:\$|£)\s?\d{1,3}(?:,\d{3})+(?:\.\d{2})?"
            r"|(?:\$|£)\s?\d+\.\d{2}"
            r"|€\s?\d{1,3}(?:\.\d{3})+(?:,\d{2})?"
            r"|€\s?\d{1,3}(?:,\d{3})+(?:\.\d{2})?"
            r"|€\s?\d+[.,]\d{2}(?!\d)"
            r"|(?<!\d)\d(?:[ \u00a0]\d{3})+[.,]\d{2}\s*€"
            r"|(?<!\d)\d{1,2}(?:[ \u00a0]\d{3})+\s*€"
            r"|(?<=\s)\d{3,5}[.,]\d{2}\s*€"
            r"|(?<![\d.,])\d{3,5}\s*€",
            window,
        )
        matches = [m.strip() for m in preferred if re.search(r"\d", m)]
        if matches:
            break
    if not matches and price_re is not None:
        matches = [m.group(0).strip() for m in price_re.finditer(blob)]
        matches = [m for m in matches if re.search(r"\d", m)]
    if not matches:
        # Car-range FR amounts
        matches = re.findall(
            r"(?<!\d)\d(?:[\s\u00a0]\d{3})+(?:[.,]\d{2})?\s*€"
            r"|(?<!\d)\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{2})?\s*€"
            r"|(?<!\d)\d{3,6}\s*€"
            r"|€\s?\d[\d\s.,]*",
            blob or "",
        )
        matches = [m.strip() for m in matches if re.search(r"\d", m)]
    if not matches:
        return "N/A"
    scored = []
    for i, m in enumerate(matches):
        val = price_to_float(m)
        if val is not None and min_val <= val <= max_val:
            scored.append((val, i, m))
    if scored:
        mx = max(v for v, _, _ in scored)
        near = [(v, i, m) for v, i, m in scored if v >= mx * 0.85]
        near.sort(key=lambda x: x[1])
        return near[-1][2]
    return matches[-1]
