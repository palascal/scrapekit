"""Listings JSON helpers (path + dedupe hooks injected by apps)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

from scrapekit.listing_status import is_sold_listing


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_listings(path: Path | str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return data["items"]
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


def save_listings(path: Path | str, items: list[dict]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    items = [
        it
        for it in items
        if not is_sold_listing(
            it.get("titre", ""),
            it.get("prix", ""),
            it.get("description", ""),
        )
    ]
    payload = {
        "updated_at": now_iso(),
        "count": len(items),
        "items": items,
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_scrape_report(path: Path | str, report: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    report = {**report, "updated_at": now_iso()}
    p.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def merge_new_listings(
    path: Path | str,
    site: str,
    label: str,
    results: list[dict],
    *,
    dedupe_fingerprint: Callable[[str | None, str | None], str],
    default_title: str = "Annonce",
    extra_fields: tuple[str, ...] = (),
    postprocess_entry: Callable[[dict, dict], None] | None = None,
) -> list[dict]:
    """
    Merge scraped items into listings.json.
    extra_fields: copy these keys from raw into entry when present (e.g. year, posted_at).
    """
    items = load_listings(path)
    by_link = {it.get("lien"): it for it in items if it.get("lien")}
    fingerprints = {
        dedupe_fingerprint(it.get("titre"), it.get("prix")) for it in items
    }
    inserted: list[dict] = []
    for raw in results:
        lien = (raw.get("lien") or "").strip()
        if not lien:
            continue
        if is_sold_listing(
            raw.get("titre", ""),
            raw.get("prix", ""),
            raw.get("description", ""),
        ):
            if lien in by_link:
                items = [it for it in items if it.get("lien") != lien]
                by_link.pop(lien, None)
            continue
        if lien in by_link:
            existing = by_link[lien]
            if not existing.get("image") and raw.get("image"):
                existing["image"] = raw["image"]
            if not existing.get("description") and raw.get("description"):
                existing["description"] = raw["description"]
            continue
        fp = dedupe_fingerprint(raw.get("titre"), raw.get("prix"))
        if fp in fingerprints and "?" not in fp:
            continue
        entry = {
            "id": lien,
            "site": site,
            "site_label": label,
            "titre": raw.get("titre") or default_title,
            "prix": raw.get("prix") or "N/A",
            "lien": lien,
            "image": raw.get("image") or "",
            "description": (raw.get("description") or "")[:400],
            "found_at": raw.get("found_at") or now_iso(),
        }
        for key in extra_fields:
            if key in raw:
                entry[key] = raw[key]
        if postprocess_entry is not None:
            postprocess_entry(entry, raw)
        items.append(entry)
        by_link[lien] = entry
        fingerprints.add(fp)
        inserted.append(entry)

    items.sort(key=lambda x: x.get("found_at") or "", reverse=True)
    save_listings(path, items)
    return inserted


def purge_sold_and_dead(
    path: Path | str,
    *,
    max_head_checks: int = 120,
    user_agent: str = "scrapekit-purge/1.0",
    skip_hosts: tuple[str, ...] = ("ebay.", "reverb.", "soundsmarket."),
) -> dict:
    items = load_listings(path)
    before = len(items)
    kept = []
    removed_sold = 0
    removed_dead = 0
    checked = 0
    dead_statuses = {404, 410, 451}

    def _url_gone(lien: str) -> bool:
        headers = {"User-Agent": user_agent}
        try:
            r = requests.head(lien, timeout=8, allow_redirects=True, headers=headers)
            if r.status_code in dead_statuses:
                return True
            # Some shops reject HEAD; fall back to a light GET.
            if r.status_code in {405, 403, 501} or r.status_code >= 500:
                r = requests.get(
                    lien,
                    timeout=10,
                    allow_redirects=True,
                    headers=headers,
                    stream=True,
                )
                r.close()
                return r.status_code in dead_statuses
        except requests.RequestException:
            try:
                r = requests.get(
                    lien,
                    timeout=10,
                    allow_redirects=True,
                    headers=headers,
                    stream=True,
                )
                r.close()
                return r.status_code in dead_statuses
            except requests.RequestException:
                return False
        return False

    for it in items:
        if is_sold_listing(
            it.get("titre", ""),
            it.get("prix", ""),
            it.get("description", ""),
        ):
            removed_sold += 1
            continue
        lien = (it.get("lien") or "").strip()
        if lien and checked < max_head_checks:
            checked += 1
            try:
                host = urlparse(lien).netloc
                if host and not any(x in host for x in skip_hosts):
                    if _url_gone(lien):
                        removed_dead += 1
                        continue
            except Exception:
                pass
        kept.append(it)
    if len(kept) != before:
        save_listings(path, kept)
    return {
        "before": before,
        "after": len(kept),
        "removed_sold": removed_sold,
        "removed_dead": removed_dead,
        "checked": checked,
    }
