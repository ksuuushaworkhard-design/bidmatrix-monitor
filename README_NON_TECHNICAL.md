# BidMatrix News Monitor

This tool creates a daily marketing brief for BidMatrix. It tracks mobile marketing, adtech, app growth, attribution, measurement, fraud, AI for marketing, creative strategy, partners, competitors, MMPs, and conferences.

## Run Manually

Open Terminal and paste:

```bash
cd /Users/kseniagolovcenko/Documents/чу
.venv/bin/bidmatrix-monitor
```

## Run Weekly Digest

```bash
cd /Users/kseniagolovcenko/Documents/чу
.venv/bin/bidmatrix-monitor --weekly
```

The weekly digest summarizes recent daily reports. It does not run new web searches.

## Edit What It Tracks

Edit these files:

- `config/tracked_topics.json` - search topics and keywords
- `config/tracked_companies.json` - partners and watchlist companies
- `config/tracked_competitors.json` - competitors
- `config/tracked_conferences.json` - conferences and events
- `config/priority_sources.json` - websites to prioritize or downrank

For plain-English guidance on which sources belong in each bucket, see:

```text
docs/SOURCE_TUNING.md
```

## Where Reports Are Saved

Reports are saved in:

```text
reports/
```

Daily files:

- `bidmatrix-monitor-YYYY-MM-DD.md` - readable marketing brief
- `bidmatrix-monitor-YYYY-MM-DD.json` - full structured output
- `bidmatrix-monitor-YYYY-MM-DD-curated.json` - clean curated output for workflows

Weekly files:

- `bidmatrix-weekly-digest-YYYY-MM-DD.md`
- `bidmatrix-weekly-digest-YYYY-MM-DD.json`

## Adjust Sensitivity

Edit:

```text
config/monitoring.json
```

Find:

```json
"sensitivity": "balanced"
```

Use one of:

- `strict` - fewer, higher-confidence items
- `balanced` - recommended default
- `broad` - more items, useful for exploration

To see why items were kept or filtered, run:

```bash
cd /Users/kseniagolovcenko/Documents/чу
.venv/bin/bidmatrix-monitor --diagnostics
```

## Delivery

Delivery is optional and off by default.

To enable it, edit:

```text
config/monitoring.json
```

Set:

```json
"delivery": {
  "enabled": true,
  "channel": "telegram",
  "send_daily": true,
  "send_weekly": true
}
```

Telegram is the recommended first option. Add these to `.env`:

```env
BIDMATRIX_DELIVERY_ENABLED=true
BIDMATRIX_DELIVERY_CHANNEL=telegram
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

Email is also supported. Set `channel` to `email` and fill in the email variables in `.env.example`.

## Daily Schedule On Mac

Use the setup script:

```bash
cd /Users/kseniagolovcenko/Documents/чу
chmod +x scripts/install_daily_launchd.sh
scripts/install_daily_launchd.sh
```

This schedules the monitor to run every day at 09:00 local Mac time.
