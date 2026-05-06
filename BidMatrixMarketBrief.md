# BidMatrix Market Brief Context

## Project Purpose

This project generates BidMatrix market-intelligence briefs for:
- daily Telegram delivery
- weekly digest delivery
- JSON/curated artifacts for debugging and iteration

The product goal is not a one-item alert. It is a compact, useful market-news digest for BidMatrix:
- focused on mobile UA, app growth, mobile adtech, measurement, fraud, CTV, AI campaign ops, programmatic in-app supply
- useful for Telegram, LinkedIn, PR, sales, and positioning
- honest about freshness and fallback level


## Channel Audience And Purpose

The Telegram channel audience is:
- BidMatrix marketers
- Business Development managers
- sales and other client-facing team members

The channel purpose is:
- not just to list industry news
- but to provide actionable industry intelligence that helps the team plan marketing, BD, partnerships, positioning, sales conversations, and content

Daily brief should answer:
1. What happened?
2. What part of the market does it affect?
3. Why should BidMatrix care?
4. How can marketing or BD use this?

The content should be useful for:
- LinkedIn and content ideas
- PR and commentary angles
- partner outreach
- sales talking points
- client conversation hooks
- competitor and partner monitoring
- positioning updates

Avoid:
- generic summaries
- one-off news with no clear BidMatrix use
- overly technical details unless they affect marketing or BD decisions
- old context unless it helps explain a current move


## Main Repo

Primary working repo:
- `/Users/kseniagolovcenko/Projects/bidmatrix-monitor`

There is also another local copy under:
- `/Users/kseniagolovcenko/Documents/чу`

When in doubt, treat `Projects/bidmatrix-monitor` as the source-of-truth repo for code, commits, and GitHub Actions.


## Delivery Channels

Telegram delivery is live and working.

Important:
- Telegram test message worked, so bot token and chat ID are valid.
- GitHub Actions scheduled/daily dispatch is working.
- Main quality work has been around signal selection, recency, fallback, digest composition, and Telegram formatting.


## Key Files

Important implementation files:
- `/Users/kseniagolovcenko/Projects/bidmatrix-monitor/src/bidmatrix_monitor/intelligence.py`
- `/Users/kseniagolovcenko/Projects/bidmatrix-monitor/src/bidmatrix_monitor/render.py`
- `/Users/kseniagolovcenko/Projects/bidmatrix-monitor/src/bidmatrix_monitor/delivery.py`
- `/Users/kseniagolovcenko/Projects/bidmatrix-monitor/src/bidmatrix_monitor/exa_client.py`
- `/Users/kseniagolovcenko/Projects/bidmatrix-monitor/src/bidmatrix_monitor/cli.py`
- `/Users/kseniagolovcenko/Projects/bidmatrix-monitor/src/bidmatrix_monitor/models.py`

Config:
- `/Users/kseniagolovcenko/Projects/bidmatrix-monitor/config/monitoring.json`
- `/Users/kseniagolovcenko/Projects/bidmatrix-monitor/config/monitoring.yml`
- `/Users/kseniagolovcenko/Projects/bidmatrix-monitor/config/tracked_topics.json`
- `/Users/kseniagolovcenko/Projects/bidmatrix-monitor/config/priority_sources.json`
- `/Users/kseniagolovcenko/Projects/bidmatrix-monitor/config/sources.json`

Tests:
- `/Users/kseniagolovcenko/Projects/bidmatrix-monitor/tests/test_intelligence.py`


## Current Product Rules

### 1. Daily brief must be a digest

Daily brief should aim for:
- 3 digest items when possible
- minimum 2 items if 2 useful items exist
- 1 item only if there is truly only 1 usable candidate across all pools

This applies across:
- core
- core_plus_context
- adjacent
- market_watch
- market_watch_14d
- market_watch_best_available


### 2. Signal priority for BidMatrix

Highest-value topics:
1. attribution / MMP / measurement / SKAN / Privacy Sandbox
2. mobile UA / app growth / performance marketing
3. fraud / IVT / traffic quality / verified supply
4. CTV as performance media for apps
5. AI media buying / campaign ops / creative testing / budget optimization
6. programmatic / in-app inventory / supply / DSP / SSP infrastructure
7. partner / competitor updates relevant to BidMatrix
8. industry reports / conferences relevant to mobile growth

Lower-priority / adjacent:
- PC gaming audience products
- broad brand / generic media news
- publisher monetization without a strong app-growth angle


### 3. Relevance tiers

Signals are classified as:
- `core`
- `adjacent`
- `background`
- `ignore`

Hard rule:
- non-core items must not appear as top daily core signals
- if a signal effectively says “indirect relevance / watchlist only”, it must not lead as a top core signal


### 4. Freshness and fallback ladder

Daily selection ladder:
1. fresh core last 24h
2. if thin, core last 72h
3. if still thin, core or strong recent signals within last 7d
4. if still thin, broader recent market-watch signals
5. if still thin, supplement with recent/background context

Important:
- if raw Exa results exist, do not say “no Exa results were available”
- monitor error is only for real Exa/config failure states
- if freshness filters remove everything, system must fall back, not emit a fake empty brief


### 5. Shared final supplement stage

Very important current behavior:
- there is now a shared post-selection supplement stage after all initial paths
- this was added because older live runs stopped too early after `market_watch_14d`
- this stage fills the digest to target count using:
  - core items
  - adjacent items
  - background context
  - market watch candidates
  - best available recent items

This is one of the most important fixes from the recent work.


## Telegram Rules

### Output shape

Telegram daily output should be compact and mobile-friendly.

Current target shape:
- title
- short intro
- `Top market signals`
- max 3 rendered items in Telegram
- if more than 3 exist in full digest:
  - show top 3 in Telegram
  - add: `More items saved in the full report artifact.`
- if 2+ digest items:
  - include `What this suggests`
  - include `BidMatrix angles`
  - include `Watch next`

Telegram item shape is intentionally compact:
- title
- what happened
- BidMatrix takeaway
- source

Preferred Telegram item format:

1. `[Company / topic] — [short news headline]`

What happened:
- 1 concise sentence.

Why it matters for the market:
- 1 concise sentence about the affected market area: mobile UA, attribution, fraud, CTV, programmatic, AI media buying, traffic quality, partnerships, and similar areas.

How BidMatrix can use it:
- 1 practical sentence for marketing, BD, sales, or positioning.

Source:
- title + domain + URL

Do not expand long `What happened` blocks in Telegram unless specifically needed.


### Telegram quality constraints

Important rules already developed:
- avoid duplicate company items in Telegram shortlist when better distinct-company candidates exist
- older technical SDK/release-note items should lose to fresher strategic items when slots are limited
- low-confidence filler should not push out better strategic items
- no action leakage between items
- no broken title fragments like:
  - `TikTok — and Vistar Media ...`


## Item-Level Writing Rules

Each selected signal should aim to provide:
- what happened
- why it matters now
- BidMatrix angle
- action
- source

Avoid generic filler like:
- “good hook for a post about...”
- “watch follow-up moves”
- “supports privacy-safe growth”

Prefer concrete wording tied to actual signal type.


## BidMatrix Angle Mapping

Use topic-specific mapping:

### Attribution / SKAN / Privacy Sandbox / MMP
- attribution resilience
- privacy-safe optimization
- cleaner performance decision-making
- measurement clarity

### Fraud / IVT / traffic quality
- verified traffic
- cleaner supply
- performance protection
- anti-fraud positioning

### CTV / performance CTV
- transparent CTV
- verified environments
- measurement beyond impressions
- CTV as measurable app-growth media

### AI media buying / campaign ops
- AI-native positioning
- automation with transparency
- measurable campaign decisions
- human QA around performance

### Programmatic / in-app supply / direct demand
- curated in-app inventory
- premium inventory quality
- direct brand-demand paths into app inventory

### Cross-screen / DOOH
- broad cross-screen context only
- only strategically relevant if it becomes measurable for app campaigns or retargeting


## Action Mapping Rules

Action must be item-specific.

Hard rule:
- action must never reference a company not present in the current selected item
- no leakage from previous selected item

Examples already established:

### Kochava / partner-quality / measurement
- `Track whether Kochava turns these certified integrations into measurable workflow or partner-quality claims for app marketers.`

### AppsFlyer SDK / technical update
- `Track whether AppsFlyer connects this SDK update to attribution reliability, network compatibility, or Privacy Sandbox measurement workflows.`

### Fraud / fraud reports
- `Use this as supporting context for BidMatrix traffic-quality messaging, especially around fraud risk, channel quality, and verified traffic.`

### Moloco / CTV
- `Watch whether Moloco publishes app-marketer case studies or MMP-attributed CTV outcomes that reinforce CTV as performance media.`

### TikTok / Vistar / DOOH
- `Treat as broad cross-screen context only; watch whether TikTok connects DOOH inventory to measurable app campaign outcomes.`


## Known Important Live Fixes Already Implemented

These were painful and should not be reintroduced:

1. No `Diagnostic Summary` in Telegram markdown
2. No fake placeholder like:
   - `Strategic context`
   - `Background context, not a fresh daily signal.`
3. No one-item market-watch brief if usable supplemental context exists
4. `market_watch_recent` / Exa fallback must fail open
5. Exa timeouts must not block the whole run
6. Telegram count must match actual rendered items
7. Top signals should not include background items mislabeled as fresh
8. Duplicate company items should not dominate Telegram shortlist


## Exa / Reliability Context

Important production lesson:
- earlier runs got stuck in `Run daily brief` because broader Exa fallback was too slow
- reliability work added:
  - per-request timeouts
  - smaller market-watch query set
  - hard total daily budget
  - fail-open behavior for slow layers
  - detailed query/debug logs

Do not casually remove that reliability work.


## Live GitHub Actions Context

Recent workflow runs proved:
- GitHub Actions schedule/dispatch works
- Telegram delivery works
- Exa can return useful data, but quality depends heavily on ranking/synthesis
- production behavior must always be validated from artifacts, not only local preview

When debugging live behavior, inspect:
- generated markdown
- curated JSON
- report JSON
- diagnostics fields


## Current Remaining Quality Gaps

As of the latest session, the system is much better, but still needs ongoing editorial/ranking refinement.

Examples of remaining likely future work:
- avoid old or overly technical items winning Telegram slots when fresher strategic alternatives exist
- improve synthesis so `What this suggests`, `BidMatrix angles`, and `Watch next` reflect the selected set more sharply
- improve per-item freshness/strategic weighting for older context
- further reduce generic entity spillover in watch-next bullets
- continue tuning partner/competitor/measurement vs fraud vs AI priorities


## Current Status / Important Reset

The MVP is already working end-to-end:
- GitHub Actions runs remotely
- Telegram delivery works
- Exa returns data
- timeout/fail-open protection is implemented
- daily digest is now multi-item when candidates exist
- weekly exists but is lower priority for now

Do not keep making micro-copy changes one by one unless they are blocking production quality.

Next priority is not endless wording polish. Next priority is:
1. audit the latest live artifacts
2. identify systematic selection/ranking issues
3. make small, scoped improvements
4. validate with one live GitHub Actions run
5. stop

Avoid changing many layers at once.


## Next Recommended Workstream

Next branch should focus on:
- digest quality audit from 3–5 real live Telegram outputs
- topic diversity and freshness weighting
- self/company exclusion
- old technical item penalties
- synthesis quality

Do not touch:
- GitHub Actions schedule
- Telegram secrets
- Exa timeout/fail-open reliability
- launchd / Mac scheduling
unless explicitly required.


## Useful Commands

Tests:
```bash
PYTHONPYCACHEPREFIX=/tmp/bidmatrix-pycache .venv/bin/python3 -m pytest -q
```

Local daily run:
```bash
BIDMATRIX_DELIVERY_ENABLED=false .venv/bin/bidmatrix-monitor
```

Local debug run:
```bash
BIDMATRIX_DELIVERY_ENABLED=false .venv/bin/bidmatrix-monitor --debug-exa
```

Trigger GitHub Actions daily:
```bash
gh workflow run market-brief.yml -f mode=daily
```

Watch run:
```bash
gh run watch <RUN_ID>
```


## Working Style For Next Session

If continuing this project in a future session:
- do not start from scratch
- inspect the latest artifact and tests first
- assume the user wants practical improvements, not theoretical analysis only
- prefer validating against the live GitHub Actions artifact path when the issue is production-only
- preserve the important product rules in this file unless the user explicitly changes them
