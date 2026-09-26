"""Shared scrape intensity (daily incremental vs full deep pass).

Used by saxbot and any app on scrapekit.
Override with env SCRAPE_MODE=daily|full.
"""

from __future__ import annotations

import os
from datetime import date
from typing import Iterable


def get_scrape_mode() -> str:
    raw = (os.getenv("SCRAPE_MODE") or "daily").strip().lower()
    return "full" if raw in {"full", "deep", "all"} else "daily"


def is_daily() -> bool:
    return get_scrape_mode() == "daily"


def max_results_for(site: str | None = None) -> int:
    """Cap of *new* listings accepted per site scrape."""
    if is_daily():
        if site == "ebay":
            return 25
        return 20
    if site == "ebay":
        return 40
    return 60


def scroll_rounds() -> int:
    return 2 if is_daily() else 6


def early_stop_seen() -> int:
    """Stop a SERP/catalog page after N consecutive already-seen IDs (0 = off)."""
    return 8 if is_daily() else 12


def purge_head_checks() -> int:
    return 40 if is_daily() else 120


def catalog_urls_for_mode(urls: Iterable[str]) -> list[str]:
    """Daily: keep first pages only (drop deep /page/N). Full: all URLs."""
    urls = list(urls)
    if not is_daily():
        return urls
    primary = [u for u in urls if "/page/" not in u.lower()]
    return primary or urls[:1]


def should_include_extra_board() -> bool:
    """Daily: skip bulky 'all listings' boards. Full: include."""
    return not is_daily()


def rotate_sites(
    site_key: str,
    rotating_keys: list[str],
    *,
    always_keys: Iterable[str] | None = None,
    per_day: int = 2,
) -> bool:
    """
    Daily: always scrape `always_keys`; rotate through `rotating_keys`
    (~per_day sites per calendar day). Full: everything.
    """
    if not is_daily():
        return True
    always = set(always_keys or ())
    if site_key in always:
        return True
    if site_key not in rotating_keys:
        return True
    if not rotating_keys:
        return True
    n = len(rotating_keys)
    take = max(1, min(per_day, n))
    start = date.today().toordinal() % n
    chosen = {rotating_keys[(start + i) % n] for i in range(take)}
    return site_key in chosen


def listing_mode_kwargs(site_key: str | None = None) -> dict:
    """Kwargs for GenericListingScraper / similar Playwright scrapers."""
    return {
        "max_results": max_results_for(site_key),
        "scroll_rounds": scroll_rounds(),
        "early_stop_seen": early_stop_seen(),
        "stop_site_when_warm": is_daily(),
    }
