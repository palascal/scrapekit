"""Playwright browser helpers shared by listing scrapers."""

from __future__ import annotations

import os
import re
from pathlib import Path

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['fr-FR', 'fr', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
window.chrome = { runtime: {} };
"""

LAUNCH_ARGS = [
    "--disable-dev-shm-usage",
    "--no-sandbox",
    "--disable-blink-features=AutomationControlled",
]

COOKIE_SELECTORS = (
    "button:has-text('Accept all')",
    "button:has-text('Accept All')",
    "button:has-text('Accept')",
    "button:has-text('Tout accepter')",
    "button:has-text('Accepter tout')",
    "button:has-text('Accepter')",
    "button:has-text('Agree')",
    "button:has-text('I agree')",
    "button:has-text('J\\'accepte')",
    "#onetrust-accept-btn-handler",
    ".fc-cta-consent",
    ".cc-btn.cc-dismiss",
    "[aria-label='Accept cookies']",
    "#shopify-pc__banner button",
)


def resolve_profile_dir(
    *,
    env_keys: tuple[str, ...] = ("SCRAPEKIT_BROWSER_PROFILE",),
    data_dir: Path | str | None = None,
    requires_residential: bool = False,
) -> str | None:
    for key in env_keys:
        val = (os.getenv(key) or "").strip()
        if val:
            return val
    if data_dir:
        default = Path(data_dir) / "browser_profile"
        if default.exists() or requires_residential:
            return str(default)
    return None


def open_browser_context(
    playwright,
    *,
    headless: bool = True,
    profile_dir: str | None = None,
    locale: str = "fr-FR",
    timezone_id: str | None = "Europe/Paris",
    viewport: dict | None = None,
    user_agent: str = DEFAULT_UA,
    stealth: bool = True,
    extra_http_headers: dict | None = None,
):
    """
    Returns (browser_or_None, context, page).
    Caller must close context (and browser if not None).
    """
    vp = viewport or {"width": 1365, "height": 900}
    headers = extra_http_headers
    browser = None
    if profile_dir:
        Path(profile_dir).mkdir(parents=True, exist_ok=True)
        print(f"   🌐 Profil navigateur: {profile_dir}")
        kwargs = dict(
            user_data_dir=profile_dir,
            headless=headless,
            locale=locale,
            viewport=vp,
            user_agent=user_agent,
            ignore_https_errors=True,
            args=LAUNCH_ARGS,
        )
        if timezone_id:
            kwargs["timezone_id"] = timezone_id
        if headers:
            kwargs["extra_http_headers"] = headers
        ctx = playwright.chromium.launch_persistent_context(**kwargs)
        if stealth:
            ctx.add_init_script(STEALTH_JS)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        return None, ctx, page

    browser = playwright.chromium.launch(headless=headless, args=LAUNCH_ARGS)
    ctx_kwargs = dict(
        user_agent=user_agent,
        locale=locale,
        viewport=vp,
        ignore_https_errors=True,
    )
    if timezone_id:
        ctx_kwargs["timezone_id"] = timezone_id
    if headers:
        ctx_kwargs["extra_http_headers"] = headers
    ctx = browser.new_context(**ctx_kwargs)
    if stealth:
        ctx.add_init_script(STEALTH_JS)
    page = ctx.new_page()
    return browser, ctx, page


def dismiss_cookies(page, pause_ms: int = 1500) -> None:
    import time

    for sel in COOKIE_SELECTORS:
        try:
            btn = page.locator(sel).first
            if btn.count() and btn.is_visible(timeout=1500):
                btn.click(timeout=2000)
                time.sleep(pause_ms / 1000)
                return
        except Exception:
            continue
    # Role-based FR/EN fallbacks (car sites)
    for label in (
        "Tout accepter",
        "Accepter tout",
        "Accept all",
        "Accepter",
        "J'accepte",
        "Agree",
        "OK",
    ):
        try:
            btn = page.get_by_role("button", name=re.compile(label, re.I))
            if btn.count():
                btn.first.click(timeout=1500)
                page.wait_for_timeout(500)
                return
        except Exception:
            continue


def page_looks_blocked(page, status: int | None = None) -> bool:
    if status in {403, 429, 503}:
        return True
    try:
        title = (page.title() or "").lower()
        body = (page.inner_text("body") or "")[:800].lower()
    except Exception:
        return status == 403
    needles = (
        "datadome",
        "captcha",
        "access denied",
        "unusual traffic",
        "vérifiez que vous êtes",
        "please verify",
        "just a moment",
        "cf-browser-verification",
    )
    blob = title + " " + body
    return any(n in blob for n in needles)
