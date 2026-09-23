"""
Generic Playwright listing scraper — driven by an injected SITE_SPECS entry.

Apps supply site_specs + match_fn (+ optional post_skip_fn for domain gates).
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from urllib.parse import unquote

from playwright.sync_api import sync_playwright

from scrapekit.base import BaseScraper
from scrapekit.browser import (
    dismiss_cookies,
    open_browser_context,
    resolve_profile_dir,
)
from scrapekit.card_price import best_price_from_text
from scrapekit.listing_status import is_sold_listing
from scrapekit.price import price_within_max_eur
from scrapekit.scrape_mode import listing_mode_kwargs
from scrapekit.seen import load_seen

MatchFn = Callable[..., bool]
PostSkipFn = Callable[..., bool]  # True => skip listing


class GenericListingScraper(BaseScraper):
    def __init__(
        self,
        site_key: str,
        query_jobs=None,
        url=None,
        profile_path=None,
        headless=True,
        max_results=None,
        *,
        site_specs: Mapping[str, dict] | None = None,
        match_fn: MatchFn | None = None,
        post_skip_fn: PostSkipFn | None = None,
        data_dir: Path | str | None = None,
        browser_profile_env: tuple[str, ...] = (
            "SCRAPEKIT_BROWSER_PROFILE",
            "SAXBOT_BROWSER_PROFILE",
            "AUDIT_BROWSER_PROFILE",
        ),
        price_min: float = 80,
        price_max_band: float = 40_000,
        allow_unknown_price: bool = False,
        fr_locales: frozenset[str] | None = None,
        scroll_rounds: int | None = None,
        early_stop_seen: int | None = None,
        stop_site_when_warm: bool | None = None,
        **_kwargs,
    ):
        specs = dict(site_specs or {})
        if site_key not in specs:
            raise ValueError(f"Unknown site_key: {site_key}")
        mode = listing_mode_kwargs(site_key)
        self.site_key = site_key
        self.spec = specs[site_key]
        self.match_fn = match_fn
        self.post_skip_fn = post_skip_fn
        self.data_dir = Path(data_dir) if data_dir else None
        self.browser_profile_env = browser_profile_env
        self.price_min = price_min
        self.price_max_band = price_max_band
        self.allow_unknown_price = allow_unknown_price
        self.scroll_rounds = max(
            0, int(mode["scroll_rounds"] if scroll_rounds is None else scroll_rounds)
        )
        self.early_stop_seen = max(
            0,
            int(mode["early_stop_seen"] if early_stop_seen is None else early_stop_seen),
        )
        self.stop_site_when_warm = (
            mode["stop_site_when_warm"]
            if stop_site_when_warm is None
            else bool(stop_site_when_warm)
        )
        self.fr_locales = fr_locales or frozenset(
            {"reverb", "leboncoin", "audiofanzine", "zikinf", "vinted"}
        )
        if query_jobs is not None:
            self._jobs = list(query_jobs)
        elif url:
            self._jobs = [{"url": url, "price_max": float("inf"), "keywords": None}]
        else:
            self._jobs = []
        self.headless = headless
        self.max_results = int(
            mode["max_results"] if max_results is None else max_results
        )
        self.cache_file = str(self.spec["seen_path"])
        self.pending_seen: list[str] = []
        self.stats = {
            "seen": 0,
            "filter": 0,
            "price": 0,
            "sold": 0,
            "skip": 0,
            "ok": 0,
        }

    def _load_seen(self):
        return load_seen(self.cache_file)

    def _normalize_link(self, href: str) -> str | None:
        if not href:
            return None
        substr = self.spec["link_substr"]
        if substr not in href:
            return None
        for excl in self.spec.get("link_exclude") or []:
            if excl in href:
                return None
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = self.spec["base_url"].rstrip("/") + href
        href = href.split("#")[0].split("?")[0].rstrip("/")
        href = re.sub(r"://www\.", "://", href)
        link_re = self.spec.get("link_regex")
        if link_re and not re.search(link_re, href, re.I):
            return None
        return href

    def _item_id(self, link: str) -> str:
        return link

    def _matches(self, title: str, prix: str, keywords, price_max: float) -> bool:
        if self.match_fn is None:
            return True
        try:
            return bool(
                self.match_fn(
                    title,
                    prix,
                    keywords=keywords,
                    price_max=price_max,
                )
            )
        except TypeError:
            return bool(self.match_fn(title, prix, keywords, price_max))

    def fetch_listings(self):
        results = []
        if not self._jobs:
            return results

        seen = self._load_seen()
        link_substr = self.spec["link_substr"]
        wait_sel = self.spec.get("wait_selector") or f"a[href*='{link_substr}']"
        price_re = re.compile(self.spec.get("price_regex") or r"[\d.,]+", re.I)
        label = self.spec.get("label", self.site_key)

        with sync_playwright() as p:
            profile_dir = resolve_profile_dir(
                env_keys=self.browser_profile_env,
                data_dir=self.data_dir,
                requires_residential=bool(self.spec.get("requires_residential")),
                site_key=self.site_key,
            )
            locale = "fr-FR" if self.site_key in self.fr_locales else "en-US"
            browser, ctx, page = open_browser_context(
                p,
                headless=self.headless,
                profile_dir=profile_dir,
                locale=locale,
                timezone_id=None,
                viewport={"width": 1365, "height": 900},
            )
            try:
                for j_idx, job in enumerate(self._jobs, start=1):
                    url = job["url"]
                    price_max = float(job.get("price_max", float("inf")))
                    keywords = job.get("keywords")
                    if "apply_filters" in job:
                        apply_filters = bool(job["apply_filters"])
                    else:
                        apply_filters = bool(self.spec.get("require_keywords"))
                    print(f"  → [{label}] {j_idx}/{len(self._jobs)}: {url[:100]}...")

                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=90_000)
                    except Exception as e:
                        print(f"   ⚠️ goto: {e}")
                        continue

                    time.sleep(1.2 if self.scroll_rounds <= 2 else 2)
                    try:
                        page.wait_for_load_state("networkidle", timeout=12_000)
                    except Exception:
                        pass
                    dismiss_cookies(page)
                    for _ in range(self.scroll_rounds):
                        try:
                            page.mouse.wheel(0, 2200)
                        except Exception:
                            break
                        time.sleep(0.45)
                    try:
                        page.wait_for_selector(wait_sel, timeout=35_000)
                    except Exception:
                        print(
                            f"   ⚠️ Timeout wait ({wait_sel}) — tentative d'extraction quand même"
                        )
                        print(f"   [diag] title={page.title()!r} url={page.url}")

                    candidates = page.evaluate(
                        """(substr) => {
                          const byKey = new Map();
                          const cardSel = [
                            '.store-item', '.grid-product__wrap-inner', '.grid-product',
                            'article', 'li.product', '.product',
                            '.card', '.grid__item', '.product-item', '.product-card',
                            '.s-item', '[data-product]', '.collection-product',
                            '.woocommerce-LoopProduct-link', '.product-wrapper',
                            '.listing-item', '.ad-list-item'
                          ].join(', ');

                          const score = (c) => {
                            let s = 0;
                            const t = c.text || '';
                            const ct = c.cardText || '';
                            if (t.length >= 8) s += 12;
                            if (c.fromCard) s += 20;
                            if (/(\\$|€|£)\\s?\\d|[\\d.,]+\\s?(€|EUR|USD|GBP)/i.test(ct)) s += 10;
                            if (ct.length > 15 && ct.length < 350) s += 15;
                            else if (ct.length >= 350) s -= 12;
                            if (/<img|javascript:/i.test(t)) s -= 20;
                            if (/^(NEW!|€\\d|\\$\\d)/i.test(t)) s -= 8;
                            return s;
                          };

                          const tightRoot = (a) => {
                            const card = a.closest(cardSel);
                            if (card) return { root: card, fromCard: true };
                            let best = a.parentElement;
                            let el = a.parentElement;
                            for (let i = 0; i < 8 && el; i++) {
                              const t = (el.innerText || '').trim().replace(/\\s+/g, ' ');
                              const prices = t.match(/(\\$|€|£)\\s?[\\d.,]+|[\\d.,]+\\s*€/g) || [];
                              if (t.length > 25 && t.length < 420) {
                                best = el;
                                if (prices.length === 1) break;
                              }
                              if (t.length > 800) break;
                              el = el.parentElement;
                            }
                            return { root: best || a.parentElement, fromCard: false };
                          };

                          for (const a of document.querySelectorAll('a[href]')) {
                            const href = a.getAttribute('href') || '';
                            if (!href.includes(substr)) continue;
                            const abs = (a.href || href).split('?')[0].split('#')[0]
                              .replace(/[/]$/, '').replace('://www.', '://');
                            const key = abs;
                            const { root, fromCard } = tightRoot(a);
                            const linkText = (a.innerText || a.textContent || '')
                              .trim().replace(/\\s+/g, ' ');
                            const titleEl = root && root.querySelector(
                              '.store-item-title, .product-title, .product__title, .product-name, .grid-product__title, .listing-title, h2, h3, .title'
                            );
                            let titleText = titleEl
                              ? (titleEl.innerText || titleEl.textContent || '').trim().replace(/\\s+/g, ' ')
                              : '';
                            if (titleText.length > 180) titleText = titleText.slice(0, 180);
                            const img = (root && root.querySelector('img')) || a.querySelector('img');
                            const image = img
                              ? (img.currentSrc || img.src || img.getAttribute('data-src')
                                 || img.getAttribute('data-lazy-src') || '')
                              : '';
                            const imgAlt = img ? (img.alt || '').trim() : '';
                            let cardText = root
                              ? (root.innerText || root.textContent || '').trim().replace(/\\s+/g, ' ')
                              : linkText;
                            if (cardText.length > 450) cardText = cardText.slice(0, 450);
                            let text = titleText || '';
                            if (!text && linkText && linkText.length >= 12
                                && !/^(NEW!|Sold Out|€[\\d.,]+ off|\\$[\\d.,]+ off)$/i.test(linkText)) {
                              text = linkText;
                            }
                            if (!text) text = imgAlt || '';
                            const cand = { href, text, cardText, image, fromCard };
                            const prev = byKey.get(key);
                            if (!prev || score(cand) > score(prev)) byKey.set(key, cand);
                          }
                          return Array.from(byKey.values());
                        }""",
                        link_substr,
                    )

                    print(f"   Liens bruts: {len(candidates)}")
                    added = 0
                    n_seen = n_filter = n_price = n_sold = n_skip = 0
                    consecutive_seen = 0
                    stopped_early = False
                    for entry in candidates:
                        if added >= self.max_results:
                            break
                        link = self._normalize_link(entry.get("href", ""))
                        if not link:
                            n_skip += 1
                            continue
                        item_id = self._item_id(link)
                        if item_id in seen:
                            n_seen += 1
                            consecutive_seen += 1
                            if (
                                self.early_stop_seen
                                and consecutive_seen >= self.early_stop_seen
                            ):
                                print(
                                    f"   ⛔ {consecutive_seen} déjà vus d'affilée → fin de page"
                                )
                                stopped_early = True
                                break
                            continue
                        consecutive_seen = 0

                        text = (entry.get("text") or "").strip()
                        card_text = (entry.get("cardText") or text).strip()
                        text = re.sub(
                            r"^(?:\d+\s+)+(?:PRO\s+)?", "", text, flags=re.I
                        ).strip()
                        title = text[:160] if text else f"Annonce {label}"
                        if title.lower().startswith("<img") or "class=" in title[:40]:
                            title = f"Annonce {label}"
                        if len(title) < 8 or title.lower().startswith("annonce "):
                            slug = unquote(link.rsplit("/", 1)[-1])
                            slug = re.sub(r"\.html?$", "", slug, flags=re.I)
                            slug = re.sub(r"-P\d+$", "", slug, flags=re.I)
                            slug = re.sub(r"-p\d+$", "", slug, flags=re.I)
                            slug = re.sub(r"^\d+-", "", slug)
                            slug_title = slug.replace("-", " ").strip()
                            if len(slug_title) >= 8:
                                title = slug_title[:160]
                            else:
                                n_skip += 1
                                continue

                        exclude_words = [
                            w.lower() for w in (self.spec.get("title_exclude") or [])
                        ]
                        hay = f"{title} {link} {card_text}".lower()
                        if exclude_words and any(w in hay for w in exclude_words):
                            n_skip += 1
                            continue

                        prix = best_price_from_text(
                            card_text,
                            text,
                            price_re,
                            min_val=self.price_min,
                            max_val=self.price_max_band,
                        )

                        if apply_filters and not self._matches(
                            title, prix, keywords, price_max
                        ):
                            n_filter += 1
                            continue

                        if keywords is not None and not apply_filters:
                            if not self._matches(title, prix, keywords, price_max):
                                n_filter += 1
                                continue

                        if job.get("price_only") and price_max < float("inf"):
                            if not price_within_max_eur(
                                prix,
                                price_max,
                                allow_unknown=self.allow_unknown_price,
                            ):
                                n_price += 1
                                continue

                        desc = card_text or text
                        if title and desc.lower().startswith(title.lower()):
                            desc = desc[len(title) :].strip()
                        if prix and prix in desc:
                            desc = desc.replace(prix, "").strip()
                        desc = re.sub(
                            r"\b(Add to Cart|Add to Wishlist|Quick View|Buy Now|NEW!)\b",
                            "",
                            desc,
                            flags=re.I,
                        )
                        desc = re.sub(r"\s+", " ", desc).strip()[:280]

                        if is_sold_listing(title, prix, desc, card_text):
                            n_sold += 1
                            continue

                        if self.post_skip_fn is not None and self.post_skip_fn(
                            title=title,
                            prix=prix,
                            description=desc,
                            card_text=card_text,
                            link=link,
                        ):
                            n_skip += 1
                            continue

                        image = (entry.get("image") or "").strip()
                        if image.startswith("//"):
                            image = "https:" + image

                        seen.add(item_id)
                        self.pending_seen.append(item_id)
                        results.append(
                            {
                                "titre": title,
                                "prix": prix or "N/A",
                                "lien": link,
                                "image": image,
                                "description": desc,
                            }
                        )
                        added += 1
                        self.stats["ok"] += 1
                        print(f"   [{added}] {title[:55]}… | {prix}")

                    self.stats["seen"] += n_seen
                    self.stats["filter"] += n_filter
                    self.stats["price"] += n_price
                    self.stats["sold"] += n_sold
                    self.stats["skip"] += n_skip
                    if added == 0 and candidates:
                        print(
                            f"   (skip: déjà vus={n_seen}, filtre={n_filter}, "
                            f"prix={n_price}, vendu={n_sold}, autre={n_skip})"
                        )
                    # Incremental daily: first page already known → skip remaining URLs
                    if (
                        self.stop_site_when_warm
                        and added == 0
                        and n_seen > 0
                        and n_seen >= max(3, (n_seen + n_filter + n_skip + n_sold) // 2)
                        and (stopped_early or j_idx < len(self._jobs))
                    ):
                        remaining = len(self._jobs) - j_idx
                        if remaining > 0:
                            print(
                                f"   ⏭️ Site déjà à jour ({n_seen} vus) → "
                                f"skip {remaining} page(s) restante(s)"
                            )
                            break
            finally:
                ctx.close()
                if browser is not None:
                    browser.close()

        print(f"\n✅ {label}: {len(results)} nouvelles annonces")
        return results
