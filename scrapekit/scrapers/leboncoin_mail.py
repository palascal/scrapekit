"""Leboncoin via alertes e-mail IMAP — shared engine (no web scrape / DataDome)."""

from __future__ import annotations

import email
import imaplib
import re
from collections.abc import Callable
from html import unescape
from pathlib import Path

from scrapekit.base import BaseScraper
from scrapekit.env import imap_settings
from scrapekit.seen import load_seen

MatchFn = Callable[..., bool]


class LeboncoinMailScraper(BaseScraper):
    """
    Read Leboncoin alert emails over IMAP.

    Inject credentials / seen_path / match_fn — do not import project config.
    match_fn(title, prix, *, link="", description="", **job) -> bool
    """

    def __init__(
        self,
        query_jobs=None,
        url=None,
        profile_path=None,
        headless=True,
        max_results=60,
        site_key="leboncoin",
        *,
        seen_path: Path | str | None = None,
        match_fn: MatchFn | None = None,
        imap_account: str | None = None,
        imap_password: str | None = None,
        imap_server: str | None = None,
        imap_port: int | None = None,
        imap_mailbox: str | None = None,
        imap_max_emails: int | None = None,
        **_kwargs,
    ):
        self._jobs = list(query_jobs or []) or [{"url": "mail://leboncoin"}]
        self.max_results = max_results
        self.site_key = site_key
        self.seen_path = Path(seen_path) if seen_path else None
        self.match_fn = match_fn
        self.pending_seen: list[str] = []
        self.stats = {"seen": 0, "ok": 0, "skip": 0, "filter": 0}

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

    def _extract_ad_entries(self, html: str) -> list[dict]:
        """Parse alert HTML: /vi/{id}.htm (current) or /ad/... (legacy)."""
        entries = []
        seen_links: set[str] = set()
        pattern = re.compile(
            r"<a[^>]+href=[\"'](https://www\.leboncoin\.fr/(?:vi/\d+\.htm|ad/[^\"'#?]+))[^\"']*[\"'][^>]*>(.*?)</a>",
            re.IGNORECASE | re.DOTALL,
        )
        for raw_link, raw_inner in pattern.findall(html):
            link = raw_link.split("#")[0].split("?")[0]
            if link in seen_links:
                continue
            seen_links.add(link)

            title_m = re.search(
                r"font-size:\s*18px[^>]*>([^<]+)<", raw_inner, re.I
            )
            price_m = re.search(
                r"#f56b2a[^>]*>(\d[\d\s]*)\s*€\s*<", raw_inner, re.I
            )
            if not price_m:
                price_m = re.search(r">(\d[\d\s]{0,8})\s*€\s*<", raw_inner)

            title = unescape(title_m.group(1)).strip() if title_m else ""
            if not title:
                text = unescape(re.sub(r"<[^>]+>", " ", raw_inner))
                text = re.sub(r"\s+", " ", text).strip()
                title = re.sub(r"\s*\d[\d\s]*\s*€.*$", "", text).strip()
            if not title:
                title = "Annonce Leboncoin"

            price = f"{price_m.group(1).strip()} €" if price_m else "N/A"

            image = ""
            idx = html.find(raw_link)
            if idx > 0:
                chunk = html[max(0, idx - 500) : idx]
                img_m = re.search(
                    r"background-image:\s*url\((https://img\.leboncoin\.fr/[^)]+)\)",
                    chunk,
                    re.I,
                )
                if img_m:
                    image = img_m.group(1).rstrip(");")
            item = {"titre": title[:160], "prix": price, "lien": link}
            if image:
                item["image"] = image
            entries.append(item)
        return entries

    def fetch_listings(self):
        user = self._imap_account
        password = self._imap_password
        if not user:
            print("⚠️ Leboncoin mail: IMAP_EMAIL_ACCOUNT manquant (.env.local).")
            return []
        if not password:
            print(
                "⚠️ Leboncoin mail: IMAP_EMAIL_PASSWORD manquant. "
                "Pour Gmail: validation en 2 étapes → mot de passe d'application."
            )
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
                if "leboncoin" not in from_email:
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
            print(
                "   Gmail: active la validation en 2 étapes, crée un "
                "mot de passe d'application, et mets-le dans IMAP_EMAIL_PASSWORD "
                "(pas le mot de passe du compte Google)."
            )
            return []
        finally:
            try:
                mail.logout()
            except Exception:
                pass

        print(
            f"\n✅ Leboncoin (mail): {len(results)} nouvelles annonces "
            f"(seen={self.stats['seen']} filter={self.stats['filter']})"
        )
        return results
