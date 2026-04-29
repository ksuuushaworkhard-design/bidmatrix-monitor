# Mac Daily Schedule Setup

The simplest local Mac setup is `launchd`, Apple's built-in scheduler.

## Install Daily Run

Open Terminal and run:

```bash
cd /Users/kseniagolovcenko/Documents/чу
chmod +x scripts/install_daily_launchd.sh
scripts/install_daily_launchd.sh
```

This schedules:

- command: `.venv/bin/bidmatrix-monitor`
- time: every day at 09:00 local Mac time
- reports: `reports/`
- logs: `logs/daily-monitor.log` and `logs/daily-monitor-error.log`
- Telegram delivery: sent after the Markdown report is written, when `BIDMATRIX_DELIVERY_ENABLED=true` and `BIDMATRIX_DELIVERY_CHANNEL=telegram` are set in `.env`

## Confirm It Is Installed

Run:

```bash
launchctl list | grep com.bidmatrix.monitor
```

If it prints a line containing `com.bidmatrix.monitor`, the schedule is loaded.

## Run Once Now

To run the exact scheduled command manually:

```bash
cd /Users/kseniagolovcenko/Documents/чу
.venv/bin/bidmatrix-monitor
```

This writes the reports first, then sends the concise Telegram summary.

## Change The Run Time

Edit:

```text
scripts/install_daily_launchd.sh
```

Find:

```xml
<key>Hour</key>
<integer>9</integer>
<key>Minute</key>
<integer>0</integer>
```

Change the hour/minute, then rerun:

```bash
scripts/install_daily_launchd.sh
```

## Run Weekly Digest Manually

```bash
cd /Users/kseniagolovcenko/Documents/чу
.venv/bin/bidmatrix-monitor --weekly
```

The weekly digest uses the curated daily JSON reports already saved in `reports/`.

## Install Weekly Friday Summary

Open Terminal and run:

```bash
cd /Users/kseniagolovcenko/Documents/чу
chmod +x scripts/install_weekly_launchd.sh
scripts/install_weekly_launchd.sh
```

This schedules:

- command: `.venv/bin/bidmatrix-monitor --weekly`
- time: every Friday at 17:00 local Mac time
- logs: `logs/weekly-monitor.log` and `logs/weekly-monitor-error.log`

To verify both jobs are active:

```bash
launchctl list | grep com.bidmatrix.monitor
```

You should see both:

- `com.bidmatrix.monitor`
- `com.bidmatrix.monitor.weekly`
