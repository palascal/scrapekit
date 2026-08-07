# Shared scraping engine for [saxbot](https://github.com/palascal/saxbot) and [AudiTT](https://github.com/palascal/auditt).

Leboncoin IMAP, Playwright helpers, seen/store/runner, telegram — **no product filters or dashboards**.

## Install

```bash
pip install "git+https://github.com/palascal/scrapekit.git@master"
# or editable (CI / local sibling):
pip install -e ./scrapekit
```

Local (Windows): keep this repo next to the apps:

```
Documents/
  scrapekit/
  saxbot/
  AudiTT/
```

Each app `_bootstrap.ensure_scrapekit()` prefers the sibling folder, then the installed package.

## CI (product repos)

```yaml
- uses: actions/checkout@v4
  with:
    repository: palascal/scrapekit
    path: scrapekit
    ref: master
- run: pip install -e ./scrapekit
```

## Shared GitHub secrets (set on each product repo — same values)

| Secret | Used by |
|--------|---------|
| `IMAP_EMAIL_ACCOUNT` | Leboncoin mail |
| `IMAP_EMAIL_PASSWORD` | Gmail app password |
| `IMAP_SERVER` | e.g. `imap.gmail.com` |
| `CLOUDFLARE_API_TOKEN` | Pages / KV publish |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare account |
| `TELEGRAM_BOT_TOKEN` | Prefer **one bot per app** |
| `TELEGRAM_CHAT_ID` | Chat destination |

Tip: if you create a GitHub **Organization**, set these once as org secrets and grant both repos access.

## Develop

```powershell
cd C:\Users\coincoin\Documents\scrapekit
# edit, then:
git add -A && git commit -m "…" && git push
```

Product apps pick up the new `master` on next Actions run (they pin `ref: master`).

## Scrape mode (`SCRAPE_MODE`)

Shared by saxbot and AudiTT via `scrapekit.scrape_mode`:

| Env | Behaviour |
|-----|-----------|
| `daily` (default) | Caps, early-stop on already-seen ads, lighter scroll, fewer purge HEAD checks |
| `full` | Deeper pass (more results, more scroll, broader purge) |

In CI, set `SCRAPE_MODE` from `workflow_dispatch` (`daily` \| `full`) or leave default for cron.
