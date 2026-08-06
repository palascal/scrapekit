# scrapekit

Moteur de scraping partagé pour **saxbot** et **AudiTT**.

Chaque app garde : filtres métier, `site_registry`, URL builders, UI/dashboard.

## Modules

| Module | Rôle |
|--------|------|
| `browser` | Playwright launch, stealth, cookies, anti-bot |
| `scrapers.leboncoin_mail` | Alertes LBC via IMAP |
| `scrapers.generic_listing` | SERP/catalogue Playwright |
| `seen` / `listing_status` / `price` / `text` | Utilitaires |
| `telegram` | Notifications (token injecté) |
| `store` | listings.json merge / purge / report |
| `runner` | Parallel scrape workers |
| `env` | `.env.local` + IMAP |

## Dev

```powershell
cd C:\Users\coincoin\Documents\scrapekit
pip install -e .
```

Après modification, synchroniser les copies CI :

```powershell
# depuis AudiTT ou saxbot
.\scripts\sync_scrapekit.ps1
```

Localement, `_bootstrap.ensure_scrapekit()` préfère `Documents\scrapekit` s’il existe.
