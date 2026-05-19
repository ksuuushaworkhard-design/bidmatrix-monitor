# LinkedIn Watch Sources

This document describes the current source configuration for a future `LinkedIn Watch` module in `bidmatrix-monitor`.

## Purpose

`LinkedIn Watch` is a future module for BidMatrix marketing and BD managers.

Its job will be to help monitor expert, company, and community posts for:

- content ideas
- BD outreach hooks
- partner monitoring
- competitor monitoring
- sales talking points
- market trend signals
- PR/commentary
- deck/positioning angles

This pass adds source configuration and documentation only.

## Current Source Library Counts

- experts: **238**
- companies: **60**
- communities: **48**

## JSON Structure

The source of truth is:

- `config/linkedin_watchlist.json`

Top-level structure:

```json
{
  "experts": [],
  "companies": [],
  "communities": [],
  "mvp_shortlist": {
    "daily": [],
    "twice_weekly": [],
    "weekly": []
  }
}
```

### `experts`

Individual people to monitor later, such as founders, growth leaders, measurement experts, fraud specialists, and adtech operators.

Common fields:

- `id`
- `name`
- `linkedin_url`
- `company`
- `role`
- `watchlist_groups`
- `source_categories`
- `topic_tags`
- `expected_use`
- `priority`
- `relationship_types`
- `needs_verification`
- `monitoring_frequency`
- `notes`
- `verification_notes`

### `companies`

LinkedIn company pages, product pages, or media pages that should be tracked later as official or semi-official market voices.

Common fields:

- `id`
- `name`
- `linkedin_url`
- `company`
- `role`
- `watchlist_groups`
- `source_categories`
- `topic_tags`
- `expected_use`
- `priority`
- `relationship_types`
- `page_type`
- `needs_verification`
- `monitoring_frequency`
- `notes`
- `verification_notes`

### `communities`

LinkedIn groups, event pages, media/community pages, associations, newsletters, and discovery-style community hubs.

Common fields:

- `id`
- `name`
- `linkedin_url`
- `community_type`
- `estimated_relevance`
- `topic_tags`
- `expected_use`
- `priority`
- `needs_verification`
- `monitoring_frequency`
- `who_is_likely_inside`
- `notes`
- `verification_url`
- `verification_notes`

### `mvp_shortlist.daily`

The sharpest daily monitoring set.

- target size: **25**
- purpose: highest-signal sources worth checking most often

### `mvp_shortlist.twice_weekly`

Strong backup sources that are useful, but less urgent or slightly broader than daily.

### `mvp_shortlist.weekly`

Broader monitoring pool for lower-frequency review and future expansion.

## MVP Shortlist Logic

- **Daily** = 25 highest-signal sources
- **Twice weekly** = strong backup or less urgent sources
- **Weekly** = broader monitoring pool

The shortlist is intentionally narrower than the full library. The full library is the long-term source universe; the shortlist is the practical monitoring cadence.

## Final Daily MVP List

Current daily shortlist:

1. Adjust
2. Branch
3. Airbridge
4. AppsFlyer
5. AppTweak
6. Kochava
7. Singular
8. Moloco
9. HUMAN Security
10. Pixalate
11. Moritz Daan
12. Adam Landis
13. Alexandra De Clerck
14. Nadir Garouche
15. Kevser Imirogullari
16. Peter Fodor
17. Scott Pierce
18. Ari Paparo
19. Chris Kane
20. Krzysztof Franaszek
21. AdExchanger
22. Gadi Eliashiv
23. Fraudlogix
24. Jason Fairchild
25. Mobile Dev Memo

## Daily Topic Coverage

Current daily shortlist coverage:

- MMP / attribution / measurement: **15**
- mobile UA / app growth: **13**
- fraud / traffic quality: **12**
- CTV / performance TV: **8**
- AI media buying / agentic workflows: **19**
- programmatic / in-app supply: **7**
- media/news/market commentary: **2**

## Cleanup Notes

These sources were downgraded from `daily` to `twice_weekly` because they are broader, more event-heavy, or more community-heavy than the current daily shortlist should be:

- Business of Apps / App Promotion Summit
- Ad Exchange Masters
- App Growth Summit®
- IAB LinkedIn Group

These sources were promoted into `daily` to sharpen the shortlist:

- Gadi Eliashiv
- Fraudlogix
- Jason Fairchild
- Mobile Dev Memo

## Safety / Compliance Note

No LinkedIn scraping or automation is implemented yet.

This branch only adds source configuration and documentation.

Any future LinkedIn Watch MVP should start from manual or exported post links, or from other approved source inputs, before any automation work is considered.

## How To Update The List Later

When this source config is updated later:

1. Add the source to the correct master section:
   - `experts`
   - `companies`
   - `communities`
2. Normalize topic tags instead of introducing near-duplicate variants.
3. Normalize `expected_use` to the approved values:
   - `content idea`
   - `BD outreach`
   - `partner monitoring`
   - `competitor monitoring`
   - `sales talking point`
   - `market trend`
   - `PR/commentary`
   - `deck/positioning angle`
4. Assign a clear `priority`:
   - `high`
   - `medium`
   - `low`
5. Set the appropriate monitoring bucket:
   - `daily`
   - `twice_weekly`
   - `weekly`
   - `monthly`
6. Place the source in `mvp_shortlist.daily`, `mvp_shortlist.twice_weekly`, or `mvp_shortlist.weekly` only if it improves the shortlist.
7. Run JSON validation after edits.

Note:
- the current config uses `priority`, not a separate `priority_score`
- shortlist placement should be driven by source quality and monitoring usefulness, not by adding every new source to `daily`
