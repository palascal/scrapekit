"""Shared scraping engine for listing monitors (saxbot, AudiTT, …)."""

__version__ = "0.1.2"

from scrapekit.base import BaseScraper
from scrapekit.scrape_mode import (
    catalog_urls_for_mode,
    early_stop_seen,
    get_scrape_mode,
    is_daily,
    listing_mode_kwargs,
    max_results_for,
    purge_head_checks,
    rotate_sites,
    scroll_rounds,
    should_include_extra_board,
)
from scrapekit.seen import commit_seen, load_seen, save_seen
from scrapekit.scrapers.lacentrale_mail import LacentraleMailScraper
from scrapekit.scrapers.leboncoin_mail import LeboncoinMailScraper
from scrapekit.scrapers.generic_listing import GenericListingScraper

__all__ = [
    "BaseScraper",
    "LeboncoinMailScraper",
    "LacentraleMailScraper",
    "GenericListingScraper",
    "load_seen",
    "save_seen",
    "commit_seen",
    "get_scrape_mode",
    "is_daily",
    "max_results_for",
    "scroll_rounds",
    "early_stop_seen",
    "purge_head_checks",
    "catalog_urls_for_mode",
    "should_include_extra_board",
    "rotate_sites",
    "listing_mode_kwargs",
    "__version__",
]
