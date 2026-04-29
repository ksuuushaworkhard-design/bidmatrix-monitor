# BidMatrix Source Tuning Guide

Use this guide when editing `config/priority_sources.json`.

## Fresh Priority Sources

Fresh sources are used to find same-day and weekly market signals. Add a domain here when it regularly publishes dated updates.

Good fresh sources:

- Official company newsrooms
- Product update blogs
- Release notes and changelogs
- Announcement-heavy conference news, speaker, agenda, and sponsor pages
- Trusted adtech and mobile marketing media with frequent updates

Current fresh source groups:

- MMP and measurement newsrooms: Adjust, AppsFlyer, Branch, Singular, Kochava, Airbridge, Tenjin
- Mobile adtech company updates: AppLovin, Moloco, Liftoff, Unity, InMobi, Mintegral, Digital Turbine, LoopMe, Smadex, Remerge, YouAppi, BidMachine
- Trusted industry media: Business of Apps, AdExchanger, ExchangeWire, Mobile Marketing Magazine, Digiday, Marketing Brew, Adweek
- Announcement-heavy conference updates: App Promotion Summit, Mobile Growth Summit, DMEXCO, MWC, Advertising Week

Avoid adding product landing pages or generic blogs to the fresh list unless they publish clearly dated news or release notes.

### Fresh Source Rationale

| Domain | Why it is fresh-priority |
| --- | --- |
| `adjust.com` | Official MMP newsroom, benchmarks, and product announcements. |
| `appsflyer.com` | Official MMP newsroom and product/measurement announcements. |
| `branch.io` | Official attribution, deep linking, and product update source. |
| `singular.net` | Official MMP blog/newsroom for measurement and SKAN updates. |
| `kochava.com` | Official measurement, fraud, and product update source. |
| `airbridge.io` | Official MMP and attribution product source. |
| `tenjin.com` | Mobile measurement and app growth updates, especially gaming. |
| `applovin.com` | Official competitor newsroom and product announcements. |
| `moloco.com` | Official competitor blog/newsroom for AI, growth, and ads updates. |
| `liftoff.io` | Official mobile growth, monetization, and product update source. |
| `unity.com` | Official Unity Ads/LevelPlay ecosystem updates. |
| `inmobi.com` | Official mobile adtech and exchange updates. |
| `mintegral.com` | Official mobile advertising and monetization updates. |
| `digitalturbine.com` | Official app distribution, mobile growth, and adtech updates. |
| `loopme.com` | Official mobile/adtech competitor and product news source. |
| `smadex.com` | Official DSP/mobile performance advertising updates. |
| `remerge.io` | Official retargeting and app growth product updates. |
| `youappi.com` | Official app retargeting and mobile growth updates. |
| `bidmachine.io` | Mobile in-app bidding and SSP competitor updates. |
| `businessofapps.com` | Frequent mobile app marketing, app growth, MMP, and conference news. |
| `adexchanger.com` | High-signal adtech, programmatic, privacy, and platform news. |
| `exchangewire.com` | Frequent adtech and programmatic industry coverage. |
| `mobilemarketingmagazine.com` | Mobile marketing and app advertising news. |
| `digiday.com` | Media, advertising, commerce, and platform shifts with marketing implications. |
| `marketingbrew.com` | Frequent marketing-platform and advertising trend coverage. |
| `adweek.com` | Brand, platform, and agency-side marketing news. |
| `apppromotionsummit.com` | App marketing event announcements and agenda updates. |
| `mobilegrowthsummit.com` | Mobile growth conference news and event updates. |
| `dmexco.com` | European marketing/adtech conference news. |
| `mwcbarcelona.com` | Mobile industry event announcements and agenda updates. |
| `advertisingweek.com` | Marketing and advertising event announcements. |

## Background Priority Sources

Background sources are used for strategic context. They can include evergreen pages when the content helps explain a market shift.

Good background sources:

- Benchmark reports
- Market reports
- Privacy and measurement standards
- Long-form explainers
- Product strategy pages from high-signal companies
- Industry analysis that is not necessarily same-day news
- Evergreen-prone conference and standards pages that are useful strategically but noisy for daily freshness

Examples: Sensor Tower, data.ai, IAB, IAB Tech Lab, Mobile Dev Memo, MMP benchmark reports, and major adtech company thought leadership.

### Background Source Rationale

| Domain | Why it is background-priority |
| --- | --- |
| `adjust.com` | Benchmark reports and attribution/measurement explainers. |
| `appsflyer.com` | Performance indexes, measurement explainers, and MMP reports. |
| `branch.io` | Attribution, linking, and mobile growth explainers. |
| `singular.net` | Measurement, SKAN, and ROI analysis. |
| `kochava.com` | Measurement, fraud, and traffic quality context. |
| `airbridge.io` | Attribution and mobile measurement strategy content. |
| `sensortower.com` | App market benchmarks and category-level intelligence. |
| `data.ai` | App economy reports and market benchmarks. |
| `businessofapps.com` | Market explainers, app growth guides, and ecosystem summaries. |
| `mobiledevmemo.com` | High-signal mobile advertising strategy analysis. |
| `iab.com` | Standards, policy, and market education. |
| `iabtechlab.com` | Privacy, measurement, and technical standards context. |
| `appgrowthsummit.com` | Valuable event context, but often returns evergreen event pages rather than daily news. |
| `mauvegas.com` | Major mobile growth event context, but frequently event-page oriented. |
| `possibleevent.com` | Useful marketing event context, but often broader/evergreen. |
| `gamesforum.com` | Mobile games monetization event context, often agenda/event-page heavy. |
| `pgconnects.com` | Mobile games and app ecosystem event context, often evergreen/event-page heavy. |
| `moloco.com` | AI, performance advertising, and app growth thought leadership. |
| `applovin.com` | Competitor positioning, product pages, and market strategy context. |
| `liftoff.io` | App growth benchmarks and mobile advertising reports. |
| `unity.com` | Mobile games monetization and ad network context. |
| `inmobi.com` | Mobile advertising, exchange, and market strategy content. |
| `digitalturbine.com` | App distribution, device, and mobile growth context. |

## High-Signal Domains

High-signal domains are trusted enough to receive a quality boost across either fresh or background searches.

Add a domain here when it is:

- Official to a tracked company, competitor, platform, conference, or standards body
- A trusted industry publication
- A recurring source of useful BidMatrix marketing or sales intelligence

Do not use this list as a general web whitelist. It should stay focused on mobile marketing, app growth, measurement, adtech, and conferences.

High-signal includes the trusted fresh and background domains above. A domain can be high-signal without being fresh-priority if it is excellent for strategic context but mostly publishes reports, evergreen explainers, or periodic analysis.

## Low-Value Domains

Low-value domains are downranked because they usually add noise.

Common examples:

- PR syndication copies
- Finance portals reposting press releases
- Thin news aggregators
- Generic wire services
- Duplicate announcement mirrors

Keep official company newsrooms preferred over PR wires. For example, use an AppsFlyer or AppLovin newsroom post when available instead of the same announcement syndicated on a wire service.

### Low-Value Source Rationale

| Domain | Why it is low-value |
| --- | --- |
| `einnews.com` | Aggregates and reposts broad news with limited added context. |
| `einpresswire.com` | PR syndication rather than primary company source. |
| `openpr.com` | Generic press release distribution. |
| `issuewire.com` | Generic press release distribution. |
| `newsfilecorp.com` | Wire distribution and investor-release mirrors. |
| `globenewswire.com` | Wire distribution; prefer official company posts. |
| `prnewswire.com` | Wire distribution; often duplicates official announcements. |
| `businesswire.com` | Wire distribution; prefer official newsroom posts. |
| `accesswire.com` | Wire distribution and duplicate announcements. |
| `abnewswire.com` | Low-context PR distribution. |
| `prweb.com` | Generic PR syndication. |
| `marketscreener.com` | Finance aggregation and press release mirrors. |
| `finance.yahoo.com` | Finance aggregation and duplicated wire content. |
| `yahoo.com` | Broad aggregation; frequently low-context for this use case. |
| `benzinga.com` | Finance/news aggregation; often not marketing-actionable. |
| `investing.com` | Finance aggregation; usually not mobile marketing specific. |
| `seekingalpha.com` | Investor analysis; useful rarely, but noisy for daily marketing monitoring. |

## When To Edit Each File

- `config/priority_sources.json`: change which websites get prioritized or downranked
- `config/tracked_topics.json`: change the search themes and keywords
- `config/tracked_companies.json`: change partners, platforms, and watchlist companies
- `config/tracked_competitors.json`: change competitor and adjacent-company tracking
- `config/tracked_conferences.json`: change event tracking

## Practical Maintenance Rhythm

Review the source configuration every 2-4 weeks.

Add a fresh source when the report misses relevant same-week updates from a trusted company or conference.

Move a source from fresh to background when it mostly returns evergreen product pages, comparison pages, guides, or old reports.

Add a low-value domain when diagnostics show repeated duplicate PR, finance, or aggregator results.
