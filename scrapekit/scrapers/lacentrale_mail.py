"""La Centrale via alertes e-mail IMAP — pas de scrape web / DataDome."""

from __future__ import annotations

import email
import imaplib
import re
from collections.abc import Callable
from html import unescape
from pathlib import Path
from urllib.parse import unquote

import requests

from scrapekit.base import BaseScraper
from scrapekit.env import imap_settings
from scrapekit.seen import load_seen

MatchFn = Callable[..., bool]

_FROM_NEEDLES = ("lacentrale", "mail-alerte.lacentrale")
_SKIP_SUBJECT = re.compile(
    r"cr[eé]ation\s+de\s+votre\s+alerte|confirmation|bienvenue",
    re.I,
)
_AD_PATH = re.compile(r"lacentrale\.fr/auto-occasion-annonce-", re.I)
_CLICK = re.compile(
    r"https://clicks\.mail-alerte\.lacentrale\.fr/[^\s\"'<>]+", re.I
)
_DIRECT = re.compile(
    r"https://(?:www\.)?lacentrale\.fr/auto-occasion-annonce-[^\s\"'<>#?]+",
    re.I,
)
_ANCHOR = re.compile(
    r"<a[^>]+href=[\"'](https://(?:www\.lacentrale\.fr/auto-occasion-annonce-[^\"']+|"
    r"clicks\.mail-alerte\.lacentrale\.fr/[^\"']+))[\"'][^>]*>(.*?)</a>",
    re.I | re.S,
)


class LacentraleMailScraper(BaseScraper):
    """
    Read La Centrale saved-search alert emails over IMAP.

    Listing links are often wrapped in clicks.mail-alerte.lacentrale.fr trackers;
    we resolve redirects to keep only /auto-occasion-annonce- URLs.
    """

    def __init__(
        self,
        query_jobs=None,
        url=None,
        profile_path=None,
        headless=True,
        max_results=60,
        site_key="lacentrale",
        *,
        seen_path: Path | str | None = None,
        match_fn: MatchFn | None = None,
        imap_account: str | None = None,
        imap_password: str | None = None,
        imap_server: str | None = None,
        imap_port: int | None = None,
        imap_mailbox: str | None = None,
        imap_max_emails: int | None = None,
        resolve_clicks: bool = True,
        **_kwargs,
    ):
        self._jobs = list(query_jobs or []) or [{"url": "mail://lacentrale"}]
        self.max_results = max_results
        self.site_key = site_key
        self.seen_path = Path(seen_path) if seen_path else None
        self.match_fn = match_fn
        self.resolve_clicks = resolve_clicks
        self.pending_seen: list[str] = []
        self.stats = {"seen": 0, "ok": 0, "skip": 0, "filter": 0}
        self._redirect_cache: dict[str, str | None] = {}

        cfg = imap_settings()
        self._imap_account = (
            imap_account if imap_account is not None else cfg["account"]
        ).strip()
        self._imap_password = (
            imap_password if imap_password is not None else cfg["password"]
        ).strip().replace(" ", "")
        self._imap_server = imap_server if imap_server is not None else cfg["server"]
        self._imap_port = int(imap_port if imap_port is not None else cfg["port"])
        self._imap_mailbox = (
            imap_mailbox if imap_mailbox is not None else cfg["mailbox"]
        )
        self._imap_max_emails = int(
            imap_max_emails if imap_max_emails is not None else cfg["max_emails"]
        )

    def _job_ctx(self) -> dict:
        return dict(self._jobs[0]) if self._jobs else {}

    def _extract_html_parts(self, msg) -> list[str]:
        parts = []
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() != "text/html":
                    continue
                payload = part.get_payload(decode=True) or b""
                parts.append(payload.decode(errors="ignore"))
        elif msg.get_content_type() == "text/html":
            payload = msg.get_payload(decode=True) or b""
            parts.append(payload.decode(errors="ignore"))
        return parts

    def _decode_subject(self, msg) -> str:
        raw = msg.get("Subject") or ""
        try:
            from email.header import decode_header

            bits = []
            for part, enc in decode_header(raw):
                if isinstance(part, bytes):
                    bits.append(part.decode(enc or "utf-8", errors="replace"))
                else:
                    bits.append(part)
            return "".join(bits)
        except Exception:
            return str(raw)

    def _resolve_final_url(self, url: str) -> str | None:
        url = url.strip()
        if _AD_PATH.search(url):
            return url.split("#")[0].split("?")[0]
        if "clicks.mail-alerte.lacentrale.fr" not in url.lower():
            return None
        if url in self._redirect_cache:
            return self._redirect_cache[url]
        final = None
        try:
            r = requests.get(
                url,
                timeout=12,
                allow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 scrapekit-lacentrale-mail/1.0"},
            )
            cand = r.url or ""
            if _AD_PATH.search(cand):
                final = cand.split("#")[0].split("?")[0]
        except Exception:
            final = None
        self._redirect_cache[url] = final
        return final

    def _title_price_from_inner(self, raw_inner: str) -> tuple[str, str]:
        text = unescape(re.sub(r"<[^>]+>", " ", raw_inner or ""))
        text = re.sub(r"\s+", " ", text).strip()
        price_m = re.search(r"(\d[\d\s]{0,10})\s*€", text)
        price = f"{price_m.group(1).strip()} €" if price_m else "N/A"
        title = text
        if price_m:
            title = text[: price_m.start()].strip(" -–|·") or text
        title = re.sub(r"\s+", " ", title).strip()[:160]
        if not title:
            title = "Annonce La Centrale"
        return title, price

    def _extract_ad_entries(self, html: str) -> list[dict]:
        entries = []
        seen_links: set[str] = set()

        # Prefer anchors (title/price context), then bare URLs.
        candidates: list[tuple[str, str]] = []
        for href, inner in _ANCHOR.findall(html):
            candidates.append((href, inner))
        for href in _DIRECT.findall(html):
            candidates.append((href, ""))
        if self.resolve_clicks:
            for href in _CLICK.findall(html):
                candidates.append((href, ""))

        for href, inner in candidates:
            link = self._resolve_final_url(href) if self.resolve_clicks else None
            if not link:
                if _AD_PATH.search(href):
                    link = href.split("#")[0].split("?")[0]
                else:
                    continue
            if link in seen_links:
                continue
            seen_links.add(link)

            title, price = self._title_price_from_inner(inner)
            if title == "Annonce La Centrale":
                # Fallback: slug from URL
                slug = unquote(link.rstrip("/").split("/")[-1])
                slug = re.sub(r"^auto-occasion-annonce-", "", slug, flags=re.I)
                slug = re.sub(r"\.html?$", "", slug, flags=re.I)
                words = [w for w in slug.replace("_", "-").split("-") if w and not w.isdigit()]
                if len(words) >= 2:
                    title = " ".join(words)[:160].title()

            image = ""
            idx = html.find(href)
            if idx > 0:
                chunk = html[max(0, idx - 600) : idx + 200]
                img_m = re.search(
                    r"<img[^>]+src=[\"'](https://[^\"']+)[\"']", chunk, re.I
                )
                if img_m and "cdn" in img_m.group(1):
                    image = img_m.group(1)

            item = {"titre": title, "prix": price, "lien": link}
            if image:
                item["image"] = image
            entries.append(item)
        return entries

    def fetch_listings(self):
        user = self._imap_account
        password = self._imap_password
        if not user:
            print("⚠️ La Centrale mail: IMAP_EMAIL_ACCOUNT manquant (.env.local).")
            return []
        if not password:
            print("⚠️ La Centrale mail: IMAP_EMAIL_PASSWORD manquant.")
            return []

        seen = load_seen(self.seen_path) if self.seen_path else set()
        results = []
        job = self._job_ctx()
        apply_filters = job.get("apply_filters", True)

        print(f"🔐 Connexion IMAP {self._imap_server}:{self._imap_port} ({user})…")
        mail = imaplib.IMAP4_SSL(self._imap_server, self._imap_port)
        try:
            mail.login(user, password)
            status, select_data = mail.select(self._imap_mailbox)
            if status != "OK":
                print(
                    f"⚠️ Boîte IMAP introuvable ou refusée: "
                    f"{self._imap_mailbox!r} ({select_data})"
                )
                return []
            status, messages = mail.search(None, "ALL")
            if status != "OK":
                print("⚠️ IMAP search a échoué.")
                return []

            email_ids = messages[0].split()
            print(f"📬 IMAP: {len(email_ids)} emails dans {self._imap_mailbox}")

            for eid in reversed(email_ids[-self._imap_max_emails :]):
                status, msg_data = mail.fetch(eid, "(RFC822)")
                if status != "OK" or not msg_data or not msg_data[0]:
                    continue

                msg = email.message_from_bytes(msg_data[0][1])
                from_email = (msg.get("From") or "").lower()
                if not any(n in from_email for n in _FROM_NEEDLES):
                    continue
                subject = self._decode_subject(msg)
                if _SKIP_SUBJECT.search(subject or ""):
                    continue

                for body_html in self._extract_html_parts(msg):
                    for item in self._extract_ad_entries(body_html):
                        if item["lien"] in seen:
                            self.stats["seen"] += 1
                            continue
                        if apply_filters and self.match_fn is not None:
                            ok = self.match_fn(
                                item["titre"],
                                item["prix"],
                                link=item["lien"],
                                description="",
                                year_min=job.get("year_min"),
                                year_max=job.get("year_max"),
                                engines=job.get("engines"),
                                price_max=job.get("price_max"),
                                keywords=job.get("keywords"),
                            )
                            if not ok:
                                self.stats["filter"] += 1
                                continue
                        seen.add(item["lien"])
                        self.pending_seen.append(item["lien"])
                        results.append(item)
                        self.stats["ok"] += 1
                        if len(results) >= self.max_results:
                            break
                    if len(results) >= self.max_results:
                        break
                if len(results) >= self.max_results:
                    break
        except imaplib.IMAP4.error as e:
            print(f"⚠️ Échec authentification IMAP: {e}")
            return []
        finally:
            try:
                mail.logout()
            except Exception:
                pass

        print(
            f"\n✅ La Centrale (mail): {len(results)} nouvelles annonces "
            f"(seen={self.stats['seen']} filter={self.stats['filter']})"
        )
        return results
