"""Detect sold / unavailable listings from title, price, description, card text."""

from __future__ import annotations

import re

_SOLD_RE = re.compile(
    r"(?:"
    r"\bsold(?:\s*out)?\b"
    r"|\bvendu(?:e|s|es)?\b"
    r"|\bépuis[ée]e?\b"
    r"|\bout\s+of\s+stock\b"
    r"|\bno\s+longer\s+available\b"
    r"|\bindisponible\b"
    r"|\bthis\s+listing\s+was\s+deleted\b"
    r"|\bannonce\s+(?:supprim[ée]e|retir[ée]e|expir[ée]e)\b"
    r"|\blisting\s+(?:removed|ended|expired)\b"
    r")",
    re.I,
)


def is_sold_listing(
    title: str = "",
    prix: str = "",
    description: str = "",
    card_text: str = "",
) -> bool:
    blob = " ".join(
        str(x or "") for x in (title, prix, description, card_text)
    ).strip()
    if not blob:
        return False
    desc = (description or "").strip()
    if desc.lower() in {"sold", "sold out", "vendu", "vendue", "vendus"}:
        return True
    return bool(_SOLD_RE.search(blob))
