# LinkedIn Watch MVP Spec

This document defines a safe v1 for a future `LinkedIn Watch` module in `bidmatrix-monitor`.

Scope of this spec:

- no LinkedIn scraping
- no LinkedIn browser automation
- no changes to the existing daily or weekly market brief pipeline
- no changes to Exa, Telegram delivery, GitHub Actions schedule, or secrets

The goal is to describe a semi-manual MVP that can be implemented later without creating risk for the production market-brief workflow.

## 1. Goal

LinkedIn Watch helps BidMatrix marketing and BD managers track expert, company, and community LinkedIn posts for:

- content ideas
- BD outreach hooks
- partner monitoring
- competitor monitoring
- sales talking points
- market trend signals
- PR/commentary angles
- deck/positioning updates

The module is meant to turn noisy LinkedIn activity into a smaller set of useful signals for practical marketing and BD use.

## 2. Source Config

The future module should use:

- `config/linkedin_watchlist.json`

That config is the source library and shortlist definition for LinkedIn Watch.

### `experts`

Individual people to monitor later, including:

- founders
- growth leaders
- measurement specialists
- fraud and traffic-quality experts
- adtech operators
- analysts and commentators

### `companies`

Official or semi-official pages such as:

- company pages
- product pages
- media pages

These are useful for platform updates, product narratives, category framing, and partner or competitor monitoring.

### `communities`

Broader LinkedIn sources such as:

- LinkedIn groups
- event pages
- media/community pages
- newsletters
- topical hubs

These sources are useful, but often noisier than direct expert or company pages.

### `mvp_shortlist.daily`

The sharpest daily set of sources to review most often.

### `mvp_shortlist.twice_weekly`

Strong backup sources that are still useful, but less urgent than the daily set.

### `mvp_shortlist.weekly`

A broader monitoring pool for lower-frequency review and future expansion.

## 3. MVP Input Method

There is no scraping in v1.

The input should be manual or exported LinkedIn post links plus copied post text.

Proposed input file:

- `data/linkedin_posts_input.json`

Proposed schema:

```json
{
  "posts": [
    {
      "source_name": "",
      "source_url": "",
      "post_url": "",
      "post_text": "",
      "published_at": "",
      "collected_at": "",
      "topic_tags": []
    }
  ]
}
```

### Notes on v1 input

- `source_name` should match a source from `config/linkedin_watchlist.json` when possible.
- `source_url` should preserve the LinkedIn page or profile URL from the source config.
- `post_url` should point to the individual post when available.
- `post_text` should contain the copied post body or meaningful excerpt.
- `published_at` is the post timestamp if known.
- `collected_at` is when the post was copied into the system.
- `topic_tags` can be carried from the source config or manually assigned during collection.

## 4. Scoring Model

Each post should be scored across a small set of practical dimensions:

- `relevance_to_bidmatrix`
- `source_priority`
- `freshness`
- `insight_quality`
- `marketing_bd_actionability`
- `novelty`
- `noise_risk`

### Suggested meaning of each score

- `relevance_to_bidmatrix`
  - How directly the post relates to app growth, measurement, fraud, programmatic supply, CTV, AI media buying, or adjacent BidMatrix concerns.

- `source_priority`
  - How important the source is in the LinkedIn Watch config.

- `freshness`
  - How recent the post is relative to collection time.

- `insight_quality`
  - Whether the post contains a real signal, operator view, launch, trend, or useful market observation instead of generic promotion.

- `marketing_bd_actionability`
  - Whether marketing, BD, or sales can actually use the post in content, outreach, positioning, or conversation prep.

- `novelty`
  - Whether the post adds something new versus repeating an already-known theme.

- `noise_risk`
  - Whether the post is vague, self-promotional, overly generic, repetitive, or otherwise weak for BidMatrix use.

The MVP does not need a complex model. A simple weighted score is enough if it consistently promotes useful posts and suppresses noisy ones.

## 5. Telegram Output Format

The future LinkedIn Watch Telegram digest should stay compact.

Target format:

```text
BidMatrix LinkedIn Watch — YYYY-MM-DD

1. [Expert/company] — [short insight]
[post URL]

2. ...
```

Use only the `3–5` strongest posts.

The output should stay short and scannable, like the current market-brief Telegram style.

## 6. What To Extract From Each Post

For each candidate post, the future module should extract:

- `short insight`
- `why it matters for BidMatrix marketing/BD`
- `possible use`

Possible use should map to one of:

- `content idea`
- `BD outreach`
- `partner monitoring`
- `sales talking point`
- `market trend`
- `PR/commentary`

Optionally, the module may also preserve:

- raw `post_text`
- matched source config entry
- scoring breakdown
- collection metadata

## 7. Safety / Compliance

Safety constraints for v1:

- no unofficial LinkedIn scraping
- no browser automation
- no cookies or session scraping
- no credential-based crawling

Use only:

- manual exports
- copied post links and post text
- approved tools
- official or clearly allowed sources

This keeps the first version low-risk and compatible with the current production workflow.

## 8. Future Automation Options

If the module proves useful, future versions may evaluate safer inputs such as:

- an approved social listening tool
- the official LinkedIn API, if permissions allow
- manual Google Sheet or Notion input
- email digest ingestion

Those paths should be evaluated later and only if they fit compliance, permissions, and product value.

## 9. Implementation Phases

### Phase 1: manual input + local scoring

- create `data/linkedin_posts_input.json`
- validate manual input
- score posts locally
- select strongest posts for review

### Phase 2: Telegram digest from manual posts

- generate a compact LinkedIn Watch digest
- send or preview only the strongest `3–5` posts

### Phase 3: scheduled semi-automated digest

- keep manual or exported input
- add a repeatable review/digest workflow
- optionally support a local operator checklist

### Phase 4: approved data-source integration

- evaluate approved ingestion sources
- keep source config stable
- avoid changing production market-brief behavior unless explicitly planned

## Working Principle

The important design rule for LinkedIn Watch v1 is:

- source config first
- manual input second
- scoring and digesting third
- automation only after the above are stable and clearly useful

That keeps the module practical, safe, and easy to evolve without risking the current BidMatrix market-brief pipeline.
