# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
poetry install
playwright install chromium
cp .env.example .env   # fill in tokens
```

## Running

```bash
# Standalone scrape + save to docs/discounts.json (used by GitHub Actions)
python scripts/scrape_and_save.py

# Full FastAPI web server (local development)
uvicorn taiwan_discounts.main:app --reload
# → http://localhost:8000
```

## Architecture

Two deployment modes share the same scraper/aggregator/notifier code:

**GitHub Actions + Pages mode** (production):
- `scripts/scrape_and_save.py` runs on schedule, writes results to `docs/discounts.json`, commits back to `main`
- `docs/index.html` is a standalone static page served by GitHub Pages — it fetches `./discounts.json` at load time, no server needed
- `.github/workflows/scrape.yml` defines the schedule (8:00 and 18:00 TST) and push-notification logic via repo secrets

**FastAPI mode** (local/self-hosted):
- `src/taiwan_discounts/main.py` serves the same `docs/index.html` at `/` and exposes JSON API endpoints
- `src/taiwan_discounts/api/routes.py` provides `GET /api/discounts`, `POST /api/notify/telegram`, `POST /api/notify/line`, `POST /api/refresh`
- Results are cached in-memory; `/api/refresh` triggers a background re-scrape

## Scraper Design

All scrapers live in `src/taiwan_discounts/scrapers/` and extend `BaseScraper` (`base.py`).

Each scraper receives a Playwright `Page` already initialised with `locale=zh-TW`. The scrape strategy is:
1. **XHR/API interception** — register `page.on("response", ...)` before `goto()` to capture JSON API calls from SPAs (used in `hami.py`)
2. **DOM scraping** — try a list of CSS selectors for card elements; parse title, discount text, deadline, link from each card
3. **Text fallback** — scan `page.inner_text("body")` for lines containing discount keywords (回饋/折/%/倍/優惠)

`BaseScraper` provides shared helpers: `parse_discount_pct(text)`, `parse_points_multiplier(text)`, `parse_deadline(text)`, `make_id(title)`.

## Data Model

`src/taiwan_discounts/models/discount.py` — `Discount` (Pydantic v2):
- `discount_value_pct`: normalised numeric %, used for filtering and sorting
- `value_score`: computed field = discount % + points bonus, boosted +10 if deadline ≤ 3 days
- High-value filter thresholds are read from env: `MIN_CASHBACK_PCT` (default 5), `MIN_DISCOUNT_PCT` (default 20), `MIN_POINTS_MULTIPLIER` (default 3)

## Adding a New Platform

1. Create `src/taiwan_discounts/scrapers/newplatform.py` extending `BaseScraper`
2. Add a new `Platform` enum value in `models/discount.py`
3. Import and add the scraper's `scrape_*` function to `aggregator/engine.py` → `_run_all_scrapers()`

## Known Limitations

- **Line Pay** (`event-pay.line.me/tw/`) requires LINE login; currently returns 0 results. Consider scraping aggregator sites (cardu.com.tw, money101.com.tw) instead.
- Scraper CSS selectors are best-effort guesses — sites may change structure and require selector updates.
- `PLAYWRIGHT_HEADLESS=true` is required in GitHub Actions; set to `false` for local debugging.

## Notifications

- **Telegram**: set `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` secrets; set `NOTIFY_MODE=telegram` variable
- **Line Notify**: set `LINE_NOTIFY_TOKEN` secret; set `NOTIFY_MODE=line` (or `both`)
- Secrets are configured in GitHub repo → Settings → Secrets and variables → Actions
