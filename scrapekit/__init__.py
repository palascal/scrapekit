"""Shared scraping engine for listing monitors (saxbot, AudiTT, …)."""

__version__ = "0.1.0"

from scrapekit.base import BaseScraper
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
    "__version__",
]
