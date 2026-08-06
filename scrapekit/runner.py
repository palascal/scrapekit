"""Parallel scrape runner shared by product apps."""

from __future__ import annotations

import importlib
import traceback
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from scrapekit.seen import commit_seen


def load_scraper(path: str, **kwargs):
    module_name, class_name = path.rsplit(".", 1)
    module = importlib.import_module(module_name)
    return getattr(module, class_name)(**kwargs)


def scrape_one(
    site: str,
    spec: dict,
    jobs: list,
    *,
    merge_fn: Callable[[str, str, list], list],
    resolve_seen_path: Callable[[str, dict], Any] | None = None,
    scraper_kwargs: dict | None = None,
) -> dict:
    label = spec.get("label", site)
    out = {
        "site": site,
        "label": label,
        "jobs": len(jobs),
        "results": 0,
        "inserted": 0,
        "telegram": 0,
        "stats": {},
        "error": None,
        "new_items": [],
    }
    if not jobs:
        return out
    try:
        kwargs = {
            "query_jobs": jobs,
            "headless": True,
            "site_key": site,
            **(scraper_kwargs or {}),
        }
        scraper = load_scraper(spec["scraper"], **kwargs)
        results = scraper.fetch_listings() or []
        out["results"] = len(results)
        out["stats"] = dict(getattr(scraper, "stats", {}) or {})
        inserted_items = merge_fn(site, label, results)
        out["inserted"] = len(inserted_items)
        out["new_items"] = inserted_items
        pending = list(getattr(scraper, "pending_seen", []) or [])
        seen_path = spec.get("seen_path")
        if resolve_seen_path is not None:
            seen_path = resolve_seen_path(site, spec) or seen_path
        if seen_path and pending:
            commit_seen(seen_path, pending)
    except Exception as e:
        out["error"] = str(e)
        traceback.print_exc()
    return out


def run_parallel(
    work: Iterable[tuple[str, dict, list]],
    *,
    max_workers: int = 3,
    scrape_fn: Callable[..., dict] | None = None,
    site_specs: dict | None = None,
) -> list[dict]:
    """
    work items: (site, spec, jobs)
    scrape_fn defaults to needing merge_fn bound by caller — pass a partial.
    """
    work_list = list(work)
    if not work_list:
        return []
    if scrape_fn is None:
        raise ValueError("scrape_fn is required (bind merge_fn via functools.partial)")

    workers = min(max_workers, max(1, len(work_list)))
    print(f"\n🧵 Parallel scrape ({workers} workers)…")
    reports: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(scrape_fn, site, spec, jobs): site
            for site, spec, jobs in work_list
        }
        for fut in as_completed(futures):
            site = futures[fut]
            try:
                report = fut.result()
            except Exception as e:
                label = (site_specs or {}).get(site, {}).get("label", site)
                report = {
                    "site": site,
                    "label": label,
                    "error": str(e),
                    "inserted": 0,
                    "new_items": [],
                    "stats": {},
                }
            reports.append(report)
    return reports
