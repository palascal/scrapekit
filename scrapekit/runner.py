"""Parallel scrape runner shared by product apps.

Resilience:
- Per-site soft timeout (default 15 min, env SCRAPE_SITE_TIMEOUT)
- Timed-out / failed sites are retried once at the end (serial)
- Executor does not wait forever on hung threads (shutdown wait=False)
"""

from __future__ import annotations

import importlib
import os
import time
import traceback
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
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
        "timed_out": False,
        "retried": False,
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


def _env_float(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _error_report(
    site: str,
    spec: dict | None,
    *,
    error: str,
    timed_out: bool = False,
    retried: bool = False,
    jobs: int = 0,
) -> dict:
    label = (spec or {}).get("label", site)
    return {
        "site": site,
        "label": label,
        "jobs": jobs,
        "results": 0,
        "inserted": 0,
        "telegram": 0,
        "stats": {},
        "error": error,
        "timed_out": timed_out,
        "retried": retried,
        "new_items": [],
    }


def _run_batch(
    work_list: list[tuple[str, dict, list]],
    *,
    scrape_fn: Callable[..., dict],
    site_specs: dict | None,
    max_workers: int,
    site_timeout_sec: float,
    label_prefix: str = "",
) -> list[dict]:
    """Run work items with per-site soft timeout; never block forever on one site."""
    if not work_list:
        return []

    workers = min(max_workers, max(1, len(work_list)))
    tag = f"{label_prefix} " if label_prefix else ""
    print(
        f"\n🧵 {tag}Parallel scrape ({workers} workers, "
        f"timeout={int(site_timeout_sec)}s/site)…"
    )

    reports: list[dict] = []
    work_by_site = {site: (site, spec, jobs) for site, spec, jobs in work_list}

    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        futures = {
            pool.submit(scrape_fn, site, spec, jobs): site
            for site, spec, jobs in work_list
        }
        deadlines = {fut: time.monotonic() + site_timeout_sec for fut in futures}
        pending = set(futures.keys())

        while pending:
            now = time.monotonic()
            expired = [fut for fut in list(pending) if now >= deadlines[fut]]
            for fut in expired:
                site = futures[fut]
                spec = (site_specs or {}).get(site) or work_by_site[site][1]
                jobs_n = len(work_by_site[site][2])
                print(
                    f"   ⏰ Timeout {spec.get('label', site)} "
                    f"après {int(site_timeout_sec)}s — skip / retry later"
                )
                reports.append(
                    _error_report(
                        site,
                        spec,
                        error=f"timeout after {int(site_timeout_sec)}s",
                        timed_out=True,
                        jobs=jobs_n,
                    )
                )
                pending.remove(fut)
                fut.cancel()

            if not pending:
                break

            wait_for = min(
                5.0,
                max(0.1, min(deadlines[f] - time.monotonic() for f in pending)),
            )
            done, _ = wait(pending, timeout=wait_for, return_when=FIRST_COMPLETED)
            for fut in done:
                pending.discard(fut)
                site = futures[fut]
                try:
                    report = fut.result(timeout=0)
                except Exception as e:
                    spec = (site_specs or {}).get(site) or work_by_site[site][1]
                    report = _error_report(
                        site,
                        spec,
                        error=str(e),
                        jobs=len(work_by_site[site][2]),
                    )
                reports.append(report)
    finally:
        # Never block forever on a hung Playwright thread
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            pool.shutdown(wait=False)

    return reports


def run_parallel(
    work: Iterable[tuple[str, dict, list]],
    *,
    max_workers: int = 3,
    scrape_fn: Callable[..., dict] | None = None,
    site_specs: dict | None = None,
    site_timeout_sec: float | None = None,
    retry_failed: bool | None = None,
    retry_timeout_sec: float | None = None,
) -> list[dict]:
    """
    work items: (site, spec, jobs)
    scrape_fn defaults to needing merge_fn bound by caller — pass a partial.

    Env:
      SCRAPE_SITE_TIMEOUT   seconds per site (default 900)
      SCRAPE_RETRY_FAILED   1/0 retry timed-out/errored sites once (default 1)
      SCRAPE_RETRY_TIMEOUT  seconds for retry pass (default = site timeout)
    """
    work_list = list(work)
    if not work_list:
        return []
    if scrape_fn is None:
        raise ValueError("scrape_fn is required (bind merge_fn via functools.partial)")

    timeout = (
        site_timeout_sec
        if site_timeout_sec is not None
        else _env_float("SCRAPE_SITE_TIMEOUT", 900.0)
    )
    do_retry = (
        retry_failed
        if retry_failed is not None
        else _env_bool("SCRAPE_RETRY_FAILED", True)
    )
    retry_to = (
        retry_timeout_sec
        if retry_timeout_sec is not None
        else _env_float("SCRAPE_RETRY_TIMEOUT", timeout)
    )

    reports = _run_batch(
        work_list,
        scrape_fn=scrape_fn,
        site_specs=site_specs,
        max_workers=max_workers,
        site_timeout_sec=timeout,
    )

    by_site = {r.get("site"): r for r in reports}
    failed_sites = [
        s
        for s, r in by_site.items()
        if r.get("timed_out") or r.get("error")
    ]

    if do_retry and failed_sites:
        work_by_site = {site: (site, spec, jobs) for site, spec, jobs in work_list}
        retry_work = [
            work_by_site[s]
            for s in failed_sites
            if s in work_by_site and work_by_site[s][2]
        ]
        if retry_work:
            labels = ", ".join(
                (
                    (site_specs or {}).get(s, {}).get("label")
                    or work_by_site[s][1].get("label")
                    or s
                )
                for s, _, __ in retry_work
            )
            print(f"\n🔁 Retry fin de run ({len(retry_work)} site(s)): {labels}")
            retry_reports = _run_batch(
                retry_work,
                scrape_fn=scrape_fn,
                site_specs=site_specs,
                max_workers=1,  # serial — more stable after failures
                site_timeout_sec=retry_to,
                label_prefix="retry",
            )
            for rr in retry_reports:
                rr["retried"] = True
                site = rr.get("site")
                prev = by_site.get(site) or {}
                if not rr.get("error") and not rr.get("timed_out"):
                    by_site[site] = rr
                    print(
                        f"   ✅ Retry OK {rr.get('label', site)}: "
                        f"{rr.get('inserted', 0)} ajoutées"
                    )
                else:
                    prev = dict(prev)
                    prev["retried"] = True
                    prev["error"] = rr.get("error") or prev.get("error")
                    prev["timed_out"] = bool(
                        rr.get("timed_out") or prev.get("timed_out")
                    )
                    by_site[site] = prev
                    print(
                        f"   ⏭️ Retry échec {rr.get('label', site)}: "
                        f"{rr.get('error') or 'timeout'} — skip"
                    )

    return list(by_site.values())
