# BidMatrix News Monitoring

Python workflow for daily Exa-powered market intelligence across mobile marketing, adtech, app growth, AI for marketing, attribution, measurement, fraud, creative strategy, conferences, partners, and competitors.

The workflow prioritizes fresh, relevant, deduplicated developments and produces Markdown plus JSON reports with:

- compact summaries
- why-it-matters analysis
- hot topic and recurring trend detection
- LinkedIn, PR, and positioning opportunities
- source URLs for follow-up

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Add your Exa API key to `.env`:

```env
EXA_API_KEY=your_key_here
```

Do not commit `.env`.

## Validate

```bash
bidmatrix-monitor --dry-run
```

## Run

```bash
bidmatrix-monitor
```

Reports are written to `reports/`:

- `bidmatrix-monitor-YYYY-MM-DD.md`
- `bidmatrix-monitor-YYYY-MM-DD.json`
- `bidmatrix-monitor-YYYY-MM-DD-curated.json`

## Configure Topics

Edit these files to tune the monitor without touching Python code:

- `config/tracked_topics.json` - search topics and priority keywords
- `config/tracked_companies.json` - partners and broader watchlist companies
- `config/tracked_competitors.json` - competitors
- `config/tracked_conferences.json` - conferences and events to watch
- `config/priority_sources.json` - high-signal and low-value domains for scoring
- `config/monitoring.json` - result counts, thresholds, and file wiring

Sensitivity is controlled in `config/monitoring.json`:

- `strict` - fewer items, strongest sources and scores only
- `balanced` - default
- `broad` - more exploratory, allows neutral sources into curation

Run with diagnostics to see the curation funnel:

```bash
bidmatrix-monitor --diagnostics
```

The default search settings use:

- `type: deep`
- `category: news`
- compact highlights
- `max_age_hours: 24`

The Markdown report is structured for marketing review:

- `what_changed_today`
- `top_news`
- `hot_takes`
- `partner_signals`
- `competitor_moves`
- `content_angles_for_linkedin`
- `pr_hooks`

The curated JSON contains only final report-ready items and angles. The full JSON keeps the richer internal fields for auditing and downstream workflows.

## Weekly Digest

```bash
bidmatrix-monitor --weekly
```

The weekly digest reads recent `*-curated.json` daily reports and writes:

- `bidmatrix-weekly-digest-YYYY-MM-DD.md`
- `bidmatrix-weekly-digest-YYYY-MM-DD.json`

## Optional Delivery

Delivery is off by default. Enable it in `config/monitoring.json` and `.env`.

Telegram is the recommended first option:

```env
BIDMATRIX_DELIVERY_ENABLED=true
BIDMATRIX_DELIVERY_CHANNEL=telegram
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

Email is supported with `BIDMATRIX_DELIVERY_CHANNEL=email` plus the SMTP variables in `.env.example`.

## Non-Technical Guide

See `README_NON_TECHNICAL.md`.

## Mac Daily Schedule

See `docs/MAC_DAILY_SCHEDULE.md`.

## Optional Codex MCP Setup

You can add Exa as a Codex MCP server with `codex mcp add exa --url ...`, but keep API keys out of shared docs and rotate any key that has been pasted into chat or committed.
