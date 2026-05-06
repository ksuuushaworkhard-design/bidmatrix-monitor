from datetime import date, timedelta
from typing import Optional, List

from bidmatrix_monitor.intelligence import build_report, dedupe_items
from bidmatrix_monitor.models import MonitorConfig, NewsItem, OutputSettings, SearchSettings, SourceConfig, Topic
from bidmatrix_monitor.render import render_markdown, _event_line
from bidmatrix_monitor.weekly import render_weekly_markdown
from bidmatrix_monitor import delivery as delivery_module
from bidmatrix_monitor.delivery import _send_telegram, _telegram_message, _telegram_quality_gate_reasons
from bidmatrix_monitor.exa_client import ExaCollectionStats, ExaMonitorClient


def test_dedupe_keeps_highest_relevance_for_url() -> None:
    low = NewsItem(topic_id="a", topic_label="A", title="Old", url="https://example.com/a?utm=1", relevance_score=2)
    high = NewsItem(topic_id="b", topic_label="B", title="New", url="https://example.com/a", relevance_score=5)

    assert dedupe_items([low, high]) == [high]


def test_build_report_detects_recurring_trends() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(recurring_trend_min_mentions=2, min_relevance_score=1),
        topics=(Topic(id="ai", label="AI", query="ai"),),
        sources=SourceConfig(high_signal_domains=("a.com", "b.com")),
    )
    items = [
        NewsItem(
            topic_id="ai",
            topic_label="AI",
            title="A",
            url="https://a.com",
            published_date=date.today().isoformat(),
            hot_topics=["SKAN"],
            relevance_score=5,
        ),
        NewsItem(
            topic_id="ai",
            topic_label="AI",
            title="B",
            url="https://b.com",
            published_date=date.today().isoformat(),
            hot_topics=["skan"],
            relevance_score=4,
        ),
    ]

    report = build_report(items, config)

    assert report.trends == [("skan", 2)]


def test_dedupe_removes_near_duplicate_titles() -> None:
    first = NewsItem(
        topic_id="ai",
        topic_label="AI",
        title="Segwise launches AI creative analytics for mobile marketers",
        url="https://example.com/segwise-ai-creative-analytics",
        mentioned_companies=["Segwise"],
        relevance_score=5,
    )
    repost = NewsItem(
        topic_id="ai",
        topic_label="AI",
        title="Segwise Launches Advanced AI Creative Analytics For Mobile Marketing",
        url="https://another.com/segwise-launches-creative-analytics",
        mentioned_companies=["Segwise"],
        relevance_score=4,
    )

    assert dedupe_items([first, repost]) == [first]


def test_build_report_keeps_daily_top_signals_recent_only() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(recurring_trend_min_mentions=2, min_relevance_score=5),
        topics=(Topic(id="adtech", label="Adtech", query="adtech", priority_keywords=("adtech", "launch")),),
        sources=SourceConfig(
            high_signal_domains=("a.com", "b.com", "c.com"),
            fresh_priority_domains=("a.com",),
            background_priority_domains=("b.com", "c.com"),
        ),
    )
    fresh = NewsItem(
        topic_id="adtech",
        topic_label="Adtech",
        title="Alpha launches new in-app bidding product",
        url="https://a.com/2026/04/29/alpha-launches",
        published_date=date.today().isoformat(),
        summary="Alpha launched a new in-app bidding product for app advertisers.",
        why_it_matters="It expands programmatic options for mobile growth teams.",
        hot_topics=["programmatic", "launch"],
        mentioned_companies=["Alpha"],
        relevance_score=5,
    )
    background_one = NewsItem(
        topic_id="adtech",
        topic_label="Adtech",
        title="Beta benchmark on fraud and traffic quality",
        url="https://b.com/reports/beta-benchmark",
        published_date=(date.today() - timedelta(days=10)).isoformat(),
        summary="Beta published a benchmark on fraud and traffic quality across app campaigns.",
        why_it_matters="It gives buyers a clearer view of quality risk in mobile acquisition.",
        hot_topics=["fraud", "traffic quality"],
        mentioned_companies=["Beta"],
        relevance_score=5,
    )
    background_two = NewsItem(
        topic_id="adtech",
        topic_label="Adtech",
        title="Gamma guide to incrementality measurement",
        url="https://c.com/resources/reports/gamma-incrementality",
        published_date=(date.today() - timedelta(days=12)).isoformat(),
        summary="Gamma shared an incrementality guide for app advertisers.",
        why_it_matters="It keeps measurement strategy in view when fresh news is thin.",
        hot_topics=["measurement", "incrementality"],
        mentioned_companies=["Gamma"],
        relevance_score=5,
    )

    report = build_report([fresh, background_one, background_two], config)

    assert len(report.daily_signals) >= 1
    assert report.diagnostics["fallback_level_used"] == "core_plus_context"
    assert len(report.daily_digest_items) >= 2
    assert report.daily_intro


def test_build_report_skips_when_no_usable_signals_exist() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(recurring_trend_min_mentions=2, min_relevance_score=8),
        topics=(Topic(id="ai", label="AI", query="ai"),),
        sources=SourceConfig(low_value_domains=("wire.com",)),
    )
    item = NewsItem(
        topic_id="ai",
        topic_label="AI",
        title="Thin syndicated repost",
        url="https://wire.com/post",
        summary="A reposted generic roundup.",
        why_it_matters="",
        relevance_score=1,
    )

    report = build_report([item], config)

    assert report.daily_signals == []
    assert "no usable market signals passed the relevance filters" in report.daily_intro
    assert report.diagnostics["telegram_message_state"] == "filtered_empty"


def test_old_background_items_do_not_appear_as_daily_top_signals() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="broad"),
        topics=(Topic(id="m", label="Measurement", query="measurement"),),
        sources=SourceConfig(background_priority_domains=("adjust.com",), high_signal_domains=("adjust.com",)),
    )
    old_item = NewsItem(
        topic_id="m",
        topic_label="Measurement",
        title="Adjust benchmark",
        url="https://adjust.com/reports/benchmark",
        published_date=(date.today() - timedelta(days=40)).isoformat(),
        summary="Older benchmark worth context only.",
        why_it_matters="Older context.",
        mentioned_companies=["Adjust"],
        hot_topics=["benchmark", "measurement"],
        relevance_score=5,
    )

    report = build_report([old_item], config)
    markdown = render_markdown(report)

    assert report.daily_signals == []
    assert "## Top Signals" not in markdown
    assert "## Strategic Context" not in markdown
    assert "## Diagnostic Summary" not in markdown


def test_weekly_marks_limited_volume_when_items_are_old() -> None:
    digest = {
        "run_date": date.today().isoformat(),
        "report_count": 1,
        "limited_signal_volume": True,
        "week_in_one_line": "Fresh signal volume was limited this week, so this brief stays focused on the small number of developments worth tracking.",
        "what_actually_happened": [],
        "background_watchlist": [
            {
                "company": "LoopMe",
                "event": "LoopMe launched Chartboost Direct to bring more brand demand into mobile apps.",
                "source": "exchangewire.com (high-signal)",
                "date": "2026-04-09",
            }
        ],
        "what_this_suggests": [],
        "why_it_matters_for_bidmatrix": [],
        "best_content_angles": [],
        "best_pr_positioning_angles": [],
        "watch_next_week": ["Watch whether LoopMe follows this move with a broader rollout or partner update next week."],
        "evidence": [],
    }

    markdown = render_weekly_markdown(digest)

    assert markdown.startswith("# Weekly Watchlist - limited fresh signal volume")
    assert "Background context, not a new weekly signal." in markdown
    assert "No strong fresh weekly developments were found." in markdown



def test_weekly_specific_synthesis_for_ctv_and_gaming() -> None:
    digest = {
        "run_date": date.today().isoformat(),
        "report_count": 2,
        "limited_signal_volume": False,
        "week_in_one_line": "A focused week with accountable media signals.",
        "what_actually_happened": [
            {
                "company": "Overwolf Ads",
                "event": "Overwolf Ads launched Gamer Grid using deterministic gameplay behavior and hardware signals.",
                "source": "exchangewire.com (high-signal)",
                "date": date.today().isoformat(),
            },
            {
                "company": "IAS",
                "event": "IAS launched Total TV with viewability, invalid traffic, and device verification across premium CTV inventory.",
                "source": "exchangewire.com (high-signal)",
                "date": date.today().isoformat(),
            },
        ],
        "background_watchlist": [],
        "what_this_suggests": [
            "Overwolf Ads and IAS both show a shift toward more accountable media environments: one through deterministic gamer audience data, the other through CTV transparency and verification.",
            "The common thread is not more inventory, but better proof of audience quality, environment quality, and measurable outcomes.",
        ],
        "why_it_matters_for_bidmatrix": [
            "BidMatrix can use this to talk about transparent CTV, verified environments, and performance measurement beyond impressions.",
            "BidMatrix can use this to talk about higher-intent gamer segments and why deterministic behavior data matters more than broad demographic reach.",
        ],
        "best_content_angles": [],
        "best_pr_positioning_angles": [],
        "watch_next_week": [],
        "evidence": [],
    }

    markdown = render_weekly_markdown(digest)

    assert "accountable media environments" in markdown
    assert "better proof of audience quality" in markdown



def test_primary_actor_prefers_announcing_companies_over_client_example() -> None:
    item = NewsItem(
        topic_id="ai",
        topic_label="AI",
        title="DAIVID & ADIN.AI Partner to Put Creative Data at The Heart of Media Decisions",
        url="https://example.com/2026/04/27/daivid-adin-ai",
        company_or_topic="Ajinomoto",
        what_happened="DAIVID partnered with ADIN.AI to embed AI creative effectiveness models into media optimization for client Ajinomoto.",
        summary="DAIVID partnered with ADIN.AI to embed AI creative effectiveness models into media optimization for client Ajinomoto.",
        relevance_score=5,
    )
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="broad"),
        topics=(Topic(id="ai", label="AI", query="ai"),),
        sources=SourceConfig(high_signal_domains=("example.com",)),
    )
    scored = dedupe_items([item], config)[0]
    assert scored.company_or_topic == "DAIVID x ADIN.AI"


def test_market_context_does_not_repeat_what_happened() -> None:
    item = NewsItem(
        topic_id="ai",
        topic_label="AI",
        title="DAIVID & ADIN.AI Partner",
        url="https://example.com/2026/04/27/daivid-adin-ai",
        what_happened="DAIVID partnered with ADIN.AI to embed AI creative effectiveness models into media optimization.",
        market_context="DAIVID partnered with ADIN.AI to embed AI creative effectiveness models into media optimization.",
        signal_type="AI_marketing",
        published_date=date.today().isoformat(),
        relevance_score=5,
    )
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="broad"),
        topics=(Topic(id="ai", label="AI", query="ai"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )
    report = build_report([item], config)
    assert report.daily_digest_items[0].market_context == "Creative intelligence is moving from post-campaign reporting into live media optimization and budget allocation."


def test_render_uses_singular_heading_for_one_daily_signal() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="broad"),
        topics=(Topic(id="a", label="Adtech", query="adtech"),),
        sources=SourceConfig(high_signal_domains=("a.com",), fresh_priority_domains=("a.com",)),
    )
    item = NewsItem(
        topic_id="a",
        topic_label="Adtech",
        title="Alpha launched new product",
        url="https://a.com/2026/04/29/alpha",
        published_date=date.today().isoformat(),
        summary="Alpha launched a new attribution product for app marketers.",
        why_it_matters="It gives app marketers a fresh measurement option.",
        relevance_score=5,
    )
    report = build_report([item], config)
    rendered = render_markdown(report)
    assert "## Today's Useful Signal" in rendered
    assert "## Top Market Signal" in rendered


def test_weekly_pr_angle_is_not_date_only_and_not_clipped() -> None:
    digest = {
        "run_date": date.today().isoformat(),
        "report_count": 1,
        "limited_signal_volume": False,
        "week_in_one_line": "A focused week.",
        "what_actually_happened": [{"company": "DAIVID x ADIN.AI", "event": "DAIVID partnered with ADIN.AI to embed AI creative effectiveness models into media platform for real-time optimization.", "source": "exchangewire.com", "date": date.today().isoformat()}],
        "background_watchlist": [],
        "what_this_suggests": ["Creative intelligence is moving from reporting into live optimization."],
        "why_it_matters_for_bidmatrix": ["BidMatrix can connect AI-native user acquisition messaging to measurable campaign decisions, not just creative generation."],
        "best_content_angles": ["AI in user acquisition is not just making creatives anymore. It is starting to decide which creatives deserve budget."],
        "best_pr_positioning_angles": ["BidMatrix can connect AI-native user acquisition messaging to measurable campaign decisions, not just creative generation."],
        "watch_next_week": ["Watch whether creative intelligence vendors integrate more directly with media buying, MMPs, or optimization platforms."],
        "evidence": [],
    }
    markdown = render_weekly_markdown(digest)
    assert "Announced" not in markdown
    assert "real-time." not in markdown



def test_daily_telegram_message_uses_short_news_digest_fields() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-05

## Today's Useful Signal
Found 1 core signal worth attention today.

## Top Market Signal
### 1. DAIVID x ADIN.AI — AI creative-effectiveness data moves closer to media optimization
- What happened: DAIVID partnered with ADIN.AI to bring AI creative-effectiveness data into media optimization.
- Why it matters: Creative intelligence is moving into live media decisioning.
- Market context: Creative intelligence is moving from reporting into budget allocation.
- BidMatrix angle: Useful for BidMatrix AI-native positioning.
- Content angle: AI in user acquisition is starting to decide which creatives deserve budget.
- Action: Track whether creative intelligence vendors integrate more directly with media buying platforms.
- Watch next: Track whether creative intelligence vendors integrate more directly with media buying platforms.
- Source: [DAIVID & ADIN.AI Partner](https://example.com/daivid) - exchangewire.com (high-signal) - Date: 2026-05-04 - confidence: high

    """
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-05", markdown, "daily")
    assert "Top market news" in message
    assert "What happened" in message
    assert "How BidMatrix can use it" in message
    assert "BidMatrix takeaway" not in message
    assert "What it affects" not in message
    assert "Why it matters for BidMatrix" not in message
    assert "Source" in message
    assert "https://example.com/daivid" in message
    assert "What this suggests" not in message
    assert "BidMatrix angles" not in message
    assert "Watch next" not in message


def test_quality_gate_blocks_old_telegram_format() -> None:
    message = """<b>BidMatrix Daily Brief — 2026-05-06</b>

<b>Top market news</b>
1. Test item
<b>What happened</b>
Test.
<b>What it affects</b>
Measurement.
<b>Why it matters for BidMatrix</b>
Test.
<b>Source</b>
Example
https://example.com/test
"""
    reasons = _telegram_quality_gate_reasons(message)
    assert "old_format_what_it_affects" in reasons
    assert "old_format_why_it_matters_for_bidmatrix" in reasons


def test_quality_gate_blocks_bidmatrix_self_item() -> None:
    message = """<b>BidMatrix Daily Brief — 2026-05-06</b>

<b>Top market news</b>
1. BidMatrix launches new UA kit
<b>What happened</b>
Test.
<b>How BidMatrix can use it</b>
Test.
<b>Source</b>
Example
https://example.com/test
"""
    assert "bidmatrix_self_item" in _telegram_quality_gate_reasons(message)


def test_quality_gate_blocks_2025_item() -> None:
    message = """<b>BidMatrix Daily Brief — 2026-05-06</b>

<b>Top market news</b>
1. Old item
<b>What happened</b>
Test.
<b>How BidMatrix can use it</b>
Test.
<b>Source</b>
Example - Date: 2025-06-24
https://example.com/test
"""
    assert "contains_2025_item" in _telegram_quality_gate_reasons(message)


def test_quality_gate_allows_valid_simplified_format() -> None:
    message = """<b>BidMatrix Daily Brief — 2026-05-06</b>

<b>Top market news</b>
1. AppsFlyer fraud report
<b>What happened</b>
The report highlights where fraud pressure is concentrating across channels, verticals, and acquisition patterns.
<b>How BidMatrix can use it</b>
Use this as support for content and sales conversations around verified traffic, fraud risk, and why clean acquisition sources matter for ROAS.
<b>Source</b>
AppsFlyer - appsflyer.com (high-signal) - Date: 2026-05-03 - confidence: medium
https://example.com/fraud
    """
    assert _telegram_quality_gate_reasons(message) == []


def test_quality_gate_blocks_bad_daily_send(monkeypatch) -> None:
    posted: list[object] = []

    def fake_urlopen(request, timeout=30):  # pragma: no cover
        posted.append(request)
        raise AssertionError("urlopen should not be called when quality gate fails")

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "prod-chat")
    monkeypatch.setattr(delivery_module, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        delivery_module,
        "_telegram_message",
        lambda subject, text, report_type: """<b>BidMatrix Daily Brief — 2026-05-06</b>

<b>Top market news</b>
1. BidMatrix self item
<b>What happened</b>
Test.
<b>How BidMatrix can use it</b>
Test.
<b>Source</b>
Example
https://example.com/test
""",
    )

    markdown = """# BidMatrix Daily Brief - 2026-05-06

## Today's Useful Signal
Found 1 core signal worth attention today.

## Top Market Signal
### 1. Placeholder item
- What happened: Test.
- Why it matters: Test.
- BidMatrix angle: Test.
- Source: [Example](https://example.com/test) - example.com (high-signal) - Date: 2026-05-05 - confidence: high
"""
    _send_telegram("BidMatrix Daily Market Brief - 2026-05-06", markdown, "daily")
    assert posted == []


def test_overwolf_gamer_grid_is_adjacent_not_core() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="broad"),
        topics=(Topic(id="gaming", label="Gaming", query="gaming"),),
        sources=SourceConfig(high_signal_domains=("exchangewire.com",), fresh_priority_domains=("exchangewire.com",)),
    )
    item = NewsItem(
        topic_id="gaming",
        topic_label="Gaming",
        title="Overwolf Ads launched Gamer Grid",
        url="https://www.exchangewire.com/blog/2026/04/27/overwolf-ads-launches-gamer-grid/",
        published_date=date.today().isoformat(),
        summary="Overwolf Ads launched Gamer Grid using deterministic gameplay behavior and hardware signals for PC gaming audience targeting.",
        why_it_matters="It sharpens gamer audience segmentation, but remains PC-gaming focused.",
        mentioned_companies=["Overwolf Ads"],
        relevance_score=5,
    )
    scored = dedupe_items([item], config)[0]
    assert scored.relevance_tier == "adjacent"


def test_telegram_top_signals_only_include_core_items() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="broad"),
        topics=(Topic(id="mobile", label="Mobile", query="mobile", priority_keywords=("attribution", "mmp", "app")),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )
    core = NewsItem(
        topic_id="mobile",
        topic_label="Mobile",
        title="AppsFlyer adds Privacy Sandbox revenue measurement",
        url="https://example.com/2026/04/29/appsflyer-privacy-sandbox",
        published_date=date.today().isoformat(),
        summary="AppsFlyer added Privacy Sandbox attribution revenue measurement for Android app marketers.",
        why_it_matters="It affects Android attribution and revenue measurement for app marketers.",
        mentioned_companies=["AppsFlyer"],
        relevance_score=5,
    )
    adjacent = NewsItem(
        topic_id="mobile",
        topic_label="Mobile",
        title="Overwolf Ads launched Gamer Grid",
        url="https://example.com/2026/04/29/overwolf-gamer-grid",
        published_date=date.today().isoformat(),
        summary="Overwolf Ads launched Gamer Grid using deterministic gameplay behavior and hardware signals for PC gaming audience targeting.",
        why_it_matters="It sharpens gamer audience segmentation, but remains PC-gaming focused.",
        mentioned_companies=["Overwolf Ads"],
        relevance_score=5,
    )
    report = build_report([core, adjacent], config)
    markdown = render_markdown(report)
    message = _telegram_message(f"BidMatrix Daily Market Brief - {report.run_date.isoformat()}", markdown, "daily")
    assert "AppsFlyer" in message
    assert "Overwolf Ads" in message
    assert "<b>Top market news</b>" in message


def test_no_core_signals_message_includes_adjacent_watchlist() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="broad"),
        topics=(Topic(id="gaming", label="Gaming", query="gaming"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )
    adjacent = NewsItem(
        topic_id="gaming",
        topic_label="Gaming",
        title="Overwolf Ads launched Gamer Grid",
        url="https://example.com/2026/04/29/overwolf-gamer-grid",
        published_date=date.today().isoformat(),
        summary="Overwolf Ads launched Gamer Grid using deterministic gameplay behavior and hardware signals for PC gaming audience targeting.",
        why_it_matters="Behavior-based audience products are becoming more specific, but this remains PC-gaming focused and only indirectly relevant to BidMatrix.",
        mentioned_companies=["Overwolf Ads"],
        relevance_score=5,
    )
    report = build_report([adjacent], config)
    markdown = render_markdown(report)
    message = _telegram_message(f"BidMatrix Daily Market Brief - {report.run_date.isoformat()}", markdown, "daily")
    assert "Market Watch" in message
    assert "Overwolf Ads" in message
    assert "indirect" in message.lower()


def test_bidmatrix_angle_is_complete_for_core_signal() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="broad"),
        topics=(Topic(id="ctv", label="CTV", query="ctv"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )
    item = NewsItem(
        topic_id="ctv",
        topic_label="CTV",
        title="IAS launched Total TV",
        url="https://example.com/2026/04/29/ias-total-tv",
        published_date=date.today().isoformat(),
        summary="IAS launched Total TV with viewability, invalid traffic, and device verification across premium CTV inventory.",
        mentioned_companies=["IAS"],
        relevance_score=5,
    )
    report = build_report([item], config)
    angle = report.daily_signals[0].why_it_matters_for_bidmatrix
    assert angle.endswith(".")
    assert "transparent CTV" in angle


def test_no_broken_fragment_in_telegram_preview() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-05

## Today's Useful Signal
Today's brief uses the best relevant signals from the last 72 hours.

## Top Signal
### 1. Test Signal — Example signal built on
- What happened: Example signal built on
- Why it matters: Better attribution decisions based on
- Market context: Attribution is changing.
- BidMatrix angle: Supports measurement clarity built on
- Content angle: Example angle.
- Action: Track vendor updates using
- Watch next: Watch next.
- Source: [Example](https://example.com/test) - example.com
"""
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-04-29", markdown, "daily")
    assert "built on." not in message
    assert "based on." not in message
    assert "using." not in message


def test_daily_telegram_title_is_exact_bidmatrix() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-04-29

## Today's Useful Signal
Found 1 core signal worth attention today.

## Top Signal
### 1. Test Signal — Measurement update
- What happened: Test.
- Why it matters: Test.
- BidMatrix angle: Test.
- Content angle: Test.
- Action: Test.
- Source: [Example](https://example.com/test) - example.com - confidence: high
"""
    message = _telegram_message('BidMatrix Daily Market Brief - 2026-04-29', markdown, 'daily')
    assert message.startswith('<b>BidMatrix Daily Brief — 2026-04-29</b>')


def test_intro_count_matches_rendered_top_signal_count() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-04-29

## Today's Useful Signals
Found 2 core signals worth attention today.

## Top Signals
### 1. Signal One — A
- What happened: A.
- Why it matters: A.
- BidMatrix angle: A.
- Content angle: A.
- Action: A.
- Source: [One](https://example.com/1) - example.com - Date: 2026-05-04 - confidence: high
### 2. Signal Two — B
- What happened: B.
- Why it matters: B.
- BidMatrix angle: B.
- Content angle: B.
- Action: B.
- Source: [Two](https://example.com/2) - example.com - Date: 2026-05-03 - confidence: medium
"""
    message = _telegram_message('BidMatrix Daily Market Brief - 2026-05-05', markdown, 'daily')
    assert 'Found 2 fresh BidMatrix-relevant signals worth attention today.' in message
    assert '<b>Top market news</b>' in message


def test_low_confidence_items_are_not_rendered_as_top_signals() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-05

## Today's Useful Signals
Found 2 core signals worth attention today.

## Top Signals
### 1. Strong Signal — A
- What happened: A.
- Why it matters: A.
- BidMatrix angle: A.
- Content angle: A.
- Action: A.
- Source: [One](https://example.com/1) - example.com - Date: 2026-05-04 - confidence: high
### 2. Weak Signal — B
- What happened: B.
- Why it matters: B.
- BidMatrix angle: B.
- Content angle: B.
- Action: B.
- Source: [Two](https://example.com/2) - example.com - Date: 2026-05-03 - confidence: low
"""
    message = _telegram_message('BidMatrix Daily Market Brief - 2026-05-05', markdown, 'daily')
    assert 'Strong Signal' in message
    assert 'Weak Signal' not in message
    assert 'Found 1 fresh BidMatrix-relevant signal worth attention today.' in message


def test_fresh_low_confidence_trusted_item_is_allowed_when_no_higher_confidence_items_exist() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-06

## Today's Useful Signals
No major core BidMatrix signal dominated today, but several relevant market moves are worth tracking.

## Top Market Signals
### 1. Integral Ad Science Social Optimization
- What happened: IAS reports brands using Social Optimization achieved lower suitability fail rates and lower CPMs across social campaigns.
- Why it matters: Published 2026-05-04 as advertisers push harder on measurable quality and brand safety.
- BidMatrix angle: Use this in positioning and sales conversations around media quality, measurement discipline, and cleaner decision-making.
- Source: [IAS](https://example.com/ias) - integralads.com (high-signal) - Date: 2026-05-04 - confidence: low
### 2. AppsFlyer product updates
- What happened: AppsFlyer posted a roundup of product updates across several months.
- Why it matters: Ongoing measurement platform iteration.
- BidMatrix angle: Use this in positioning and sales conversations around attribution resilience.
- Source: [AppsFlyer](https://example.com/appsflyer) - appsflyer.com (high-signal) - Date: unknown - confidence: low
### 3. Apple AAK update
- What happened: InMobi described Apple AdAttributionKit upgrades for iOS 18.4.
- Why it matters: Useful background context for privacy measurement.
- BidMatrix angle: Use this in positioning and sales conversations around privacy-safe optimization.
- Source: [InMobi](https://example.com/aak) - inmobi.com (high-signal) - Date: 2025-06-24 - confidence: low
"""
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-06", markdown, "daily")
    assert "Fresh high-confidence signals were limited, so today’s digest includes the best fresh trusted market signal available." in message
    assert "Integral Ad Science Social Optimization" in message
    assert "How BidMatrix can use it" in message
    assert "AppsFlyer product updates" not in message
    assert "Apple AAK update" not in message


def test_low_confidence_unknown_date_item_is_still_rejected() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-06

## Today's Useful Signals
No major core BidMatrix signal dominated today, but several relevant market moves are worth tracking.

## Top Market Signals
### 1. AppsFlyer product updates
- What happened: AppsFlyer posted a roundup of product updates across several months.
- Why it matters: Ongoing measurement platform iteration.
- BidMatrix angle: Use this in positioning and sales conversations around attribution resilience.
- Source: [AppsFlyer](https://example.com/appsflyer) - appsflyer.com (high-signal) - Date: unknown - confidence: low
"""
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-06", markdown, "daily")
    assert "No strong fresh market signals found today." in message
    assert "AppsFlyer product updates" not in message


def test_low_confidence_old_item_is_still_rejected() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-06

## Today's Useful Signals
No major core BidMatrix signal dominated today, but several relevant market moves are worth tracking.

## Top Market Signals
### 1. Apple AAK update
- What happened: InMobi described Apple AdAttributionKit upgrades for iOS 18.4.
- Why it matters: Useful background context for privacy measurement.
- BidMatrix angle: Use this in positioning and sales conversations around privacy-safe optimization.
- Source: [InMobi](https://example.com/aak) - inmobi.com (high-signal) - Date: 2025-06-24 - confidence: low
"""
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-06", markdown, "daily")
    assert "No strong fresh market signals found today." in message
    assert "Apple AAK update" not in message


def test_low_confidence_untrusted_source_is_still_rejected() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-06

## Today's Useful Signals
No major core BidMatrix signal dominated today, but several relevant market moves are worth tracking.

## Top Market Signals
### 1. Mistplay rewarded growth move
- What happened: Mistplay acquired MyChips to expand rewarded advertising supply.
- Why it matters: Published 2026-05-04 as rewarded media grows in app acquisition.
- BidMatrix angle: Use this as app-growth partner monitoring.
- Source: [Mistplay](https://example.com/mistplay) - prnewswire.com (lower-priority) - Date: 2026-05-04 - confidence: low
"""
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-06", markdown, "daily")
    assert "No strong fresh market signals found today." in message
    assert "Mistplay rewarded growth move" not in message


def test_medium_or_high_confidence_item_beats_low_confidence_relaxation() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-06

## Today's Useful Signals
Found 2 core signals worth attention today.

## Top Market Signals
### 1. Integral Ad Science Social Optimization
- What happened: IAS reports brands using Social Optimization achieved lower suitability fail rates and lower CPMs across social campaigns.
- Why it matters: Published 2026-05-04 as advertisers push harder on measurable quality and brand safety.
- BidMatrix angle: Use this in positioning and sales conversations around media quality, measurement discipline, and cleaner decision-making.
- Source: [IAS](https://example.com/ias) - integralads.com (high-signal) - Date: 2026-05-04 - confidence: low
### 2. Moloco performance CTV
- What happened: Moloco launched performance CTV with MMP attribution and measurable ROI across streaming inventory.
- Why it matters: Published 2026-05-05 as app marketers push CTV toward measurable performance outcomes.
- BidMatrix angle: Gives BidMatrix a concrete angle on transparent CTV, verified environments, and performance measurement beyond impressions.
- Source: [Moloco](https://example.com/moloco) - moloco.com (high-signal) - Date: 2026-05-05 - confidence: high
"""
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-06", markdown, "daily")
    assert "Found 1 fresh BidMatrix-relevant signal worth attention today." in message
    assert "Fresh high-confidence signals were limited" not in message
    assert "Moloco performance CTV" in message


def test_confidence_relaxation_replay_uses_actionable_format() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-06

## Today's Useful Signals
No major core BidMatrix signal dominated today, but several relevant market moves are worth tracking.

## Top Market Signals
### 1. Integral Ad Science Social Optimization
- What happened: IAS reports brands using Social Optimization achieved lower suitability fail rates and lower CPMs across social campaigns.
- Why it matters: Published 2026-05-04 as advertisers push harder on measurable quality and brand safety.
- BidMatrix angle: Use this in positioning and sales conversations around media quality, measurement discipline, and cleaner decision-making.
- Source: [IAS](https://example.com/ias) - integralads.com (high-signal) - Date: 2026-05-04 - confidence: low
### 2. AppsFlyer product updates
- What happened: AppsFlyer posted a roundup of product updates across several months.
- Why it matters: Ongoing measurement platform iteration.
- BidMatrix angle: Use this in positioning and sales conversations around attribution resilience.
- Source: [AppsFlyer](https://example.com/appsflyer) - appsflyer.com (high-signal) - Date: unknown - confidence: low
### 3. Apple AAK update
- What happened: InMobi described Apple AdAttributionKit upgrades for iOS 18.4.
- Why it matters: Useful background context for privacy measurement.
- BidMatrix angle: Use this in positioning and sales conversations around privacy-safe optimization.
- Source: [InMobi](https://example.com/aak) - inmobi.com (high-signal) - Date: 2025-06-24 - confidence: low
"""
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-06", markdown, "daily")
    assert "Fresh high-confidence signals were limited, so today’s digest includes the best fresh trusted market signal available." in message
    assert "<b>What happened</b>" in message
    assert "<b>How BidMatrix can use it</b>" in message
    assert "<b>Source</b>" in message


def test_empty_strategic_context_is_not_rendered_in_telegram() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-04-29

## Today's Useful Signal
Found 1 core signal worth attention today.

## Top Signal
### 1. Test Signal — A
- What happened: A.
- Why it matters: A.
- BidMatrix angle: A.
- Content angle: A.
- Action: A.
- Source: [One](https://example.com/1) - example.com - confidence: high

## Strategic Context
- Background context, not a fresh daily signal.
"""
    message = _telegram_message('BidMatrix Daily Market Brief - 2026-04-29', markdown, 'daily')
    assert '<b>Strategic context</b>' not in message


def test_no_raw_results_uses_exa_unavailable_message() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5),
        topics=(Topic(id="a", label="Adtech", query="adtech"),),
    )
    report = build_report([], config)
    assert "no Exa results were available" in report.daily_intro
    assert report.diagnostics["telegram_message_state"] == "monitor_error"


def test_exa_zero_results_telegram_uses_monitor_error() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-03

## Today's Useful Signals
Market brief monitor ran, but no Exa results were available. Please check EXA_API_KEY, Exa response logs, or source/query configuration.
"""
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-03", markdown, "daily")
    assert "<b>Monitor error</b>" in message
    assert "no Exa results were available" in message


def test_exa_failure_path_records_errors() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5),
        topics=(Topic(id="a", label="Adtech", query="adtech"),),
    )
    report = build_report([], config, exa_errors=["Mobile UA: timeout"])
    assert "no Exa results were available" in report.daily_intro
    assert report.exa_errors == ["Mobile UA: timeout"]
    assert report.diagnostics["exa_errors"] == ["Mobile UA: timeout"]


def test_exa_client_fails_open_when_market_watch_layer_times_out() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5),
        topics=(Topic(id="a", label="Adtech", query="adtech"),),
    )
    client = object.__new__(ExaMonitorClient)
    client._config = config
    client._exa = None
    client._debug_exa = False
    client._last_errors = []
    client._stats = ExaCollectionStats()
    client._query_counts = {}
    client._layer_result_counts = {}
    client._seen_raw_urls = set()
    client._fresh_items_collected = 0
    client._collection_started_at = 0.0

    good = NewsItem(topic_id="a", topic_label="Adtech", title="Good", url="https://example.com/good")

    def fake_search_topic_layer(inner_topic, layer, *, num_results=None):
        if layer == "market_watch_recent":
            raise TimeoutError("Exa search timed out for market_watch_recent")
        return [good]

    client.search_topic_layer = fake_search_topic_layer  # type: ignore[method-assign]
    client._budget_exceeded = lambda: False  # type: ignore[method-assign]

    items = client.search_market_watch_recent()

    assert items == []
    errors = client.pop_errors()
    assert errors[0].endswith("[market_watch_recent]: Exa search timed out for market_watch_recent")


def test_exa_client_skips_market_watch_when_fresh_layer_is_sufficient() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5),
        topics=(Topic(id="a", label="Adtech", query="adtech"),),
    )
    client = object.__new__(ExaMonitorClient)
    client._config = config
    client._exa = None
    client._debug_exa = False
    client._last_errors = []
    client._stats = ExaCollectionStats()
    client._query_counts = {}
    client._layer_result_counts = {}
    client._seen_raw_urls = set()
    client._fresh_items_collected = 0
    client._collection_started_at = 0.0

    topic = Topic(id="a", label="Adtech", query="adtech")
    first = NewsItem(topic_id="a", topic_label="Adtech", title="One", url="https://example.com/one")
    second = NewsItem(topic_id="a", topic_label="Adtech", title="Two", url="https://example.com/two")
    third = NewsItem(topic_id="a", topic_label="Adtech", title="Three", url="https://example.com/three")
    called_layers = []

    def fake_search_topic_layer(inner_topic, layer, *, num_results=None):
        called_layers.append(layer)
        if layer == "daily_fresh_signals":
            return [first, second]
        if layer == "strategic_background":
            return [third]
        raise AssertionError("unexpected extra layer")

    client.search_topic_layer = fake_search_topic_layer  # type: ignore[method-assign]
    client._budget_exceeded = lambda: False  # type: ignore[method-assign]
    client._can_run_layer = lambda layer: True  # type: ignore[method-assign]

    items = client.search_topic(topic)

    assert [item.title for item in items] == ["One", "Two", "Three"]
    assert called_layers == ["daily_fresh_signals", "strategic_background"]
    assert client.should_run_market_watch_recent() is True


def test_adjacent_only_signals_render_watchlist_without_strategic_context() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="broad"),
        topics=(Topic(id="gaming", label="Gaming", query="gaming"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )
    adjacent = NewsItem(
        topic_id="gaming",
        topic_label="Gaming",
        title="Overwolf Ads launched Gamer Grid",
        url="https://example.com/2026/04/29/overwolf-gamer-grid",
        published_date=date.today().isoformat(),
        summary="Overwolf Ads launched Gamer Grid using deterministic gameplay behavior and hardware signals for PC gaming audience targeting.",
        why_it_matters="Behavior-based audience products are becoming more specific, but this remains PC-gaming focused and only indirectly relevant to BidMatrix.",
        mentioned_companies=["Overwolf Ads"],
        relevance_score=5,
    )
    report = build_report([adjacent], config)
    markdown = render_markdown(report)
    assert "## Top Market Signal" in markdown
    assert "## Strategic Context" not in markdown
    assert report.diagnostics["fallback_level_used"] == "market_watch_14d"


def test_telegram_adjacent_only_case_uses_no_core_message() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-03

## Today's Useful Signals
No direct core BidMatrix signal dominated today, so this brief uses the strongest adjacent industry signals worth monitoring.

## Market Watch
### 1. Overwolf Ads — launched Gamer Grid using deterministic gameplay behavior and hardware signals for PC gaming audience targeting
- Why it may matter: Behavior-based audience products are becoming more specific, but this remains PC-gaming focused and only indirectly relevant to BidMatrix.
- BidMatrix use: Relevance to BidMatrix is indirect; keep as watchlist only.
- Source: [Overwolf Ads launched Gamer Grid](https://example.com/overwolf) - exchangewire.com (high-signal) - Date: 2026-05-03
"""
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-03", markdown, "daily")
    assert "<b>Market Watch</b>" in message
    assert "Overwolf Ads" in message
    assert "<b>Strategic context</b>" not in message


def test_no_24h_data_uses_last_72h_core_signal() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="broad"),
        topics=(Topic(id="m", label="Measurement", query="measurement"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )
    item = NewsItem(
        topic_id="m",
        topic_label="Measurement",
        title="AppsFlyer updates attribution windows",
        url="https://example.com/2026/05/02/appsflyer-update",
        published_date=(date.today() - timedelta(days=2)).isoformat(),
        summary="AppsFlyer updated attribution windows for mobile app marketers.",
        why_it_matters="It changes live measurement decisions for app marketers.",
        mentioned_companies=["AppsFlyer"],
        relevance_score=5,
    )
    report = build_report([item], config)
    assert len(report.daily_signals) == 1
    assert report.diagnostics["fallback_level_used"] == "core_72h"


def test_no_72h_data_uses_last_7d_core_signal() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="broad"),
        topics=(Topic(id="m", label="Measurement", query="measurement"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )
    item = NewsItem(
        topic_id="m",
        topic_label="Measurement",
        title="Adjust launches measurement update",
        url="https://example.com/2026/04/29/adjust-update",
        published_date=(date.today() - timedelta(days=6)).isoformat(),
        summary="Adjust launched a measurement update for mobile growth teams.",
        why_it_matters="It changes measurement workflows for app marketers.",
        mentioned_companies=["Adjust"],
        relevance_score=5,
    )
    report = build_report([item], config)
    assert len(report.daily_signals) == 1
    assert report.diagnostics["fallback_level_used"] == "core_7d"


def test_omnicom_agentic_buying_gets_specific_angles() -> None:
    config = MonitorConfig(
        brand_name='BidMatrix',
        brand_description='Adtech',
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity='broad'),
        topics=(Topic(id='ai', label='AI', query='ai'),),
        sources=SourceConfig(high_signal_domains=('example.com',), fresh_priority_domains=('example.com',)),
    )
    item = NewsItem(
        topic_id='ai',
        topic_label='AI',
        title='Omnicom rolls out agentic media buying workflow',
        url='https://example.com/2026/04/29/omnicom-agentic-buying',
        published_date=date.today().isoformat(),
        summary='Omnicom rolled out an agentic media buying workflow for live campaign operations and programmatic execution.',
        why_it_matters='It moves AI buying from concept to live media operations.',
        mentioned_companies=['Omnicom'],
        relevance_score=5,
    )
    report = build_report([item], config)
    signal = report.daily_signals[0]
    assert 'AI-native positioning' in signal.why_it_matters_for_bidmatrix or 'Agentic buying is moving from concept to live media operations' in signal.why_it_matters_for_bidmatrix
    assert 'traffic quality' not in signal.why_it_matters_for_bidmatrix.lower() or 'automated buying still needs transparent supply' in signal.why_it_matters_for_bidmatrix.lower()
    assert signal.content_angle == 'AI agents are entering media buying — but who verifies the quality of what they buy?'
    assert 'is a good hook for a post about' not in signal.content_angle


def test_partial_exa_results_still_produce_brief() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="broad"),
        topics=(Topic(id="m", label="Measurement", query="measurement"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )
    item = NewsItem(
        topic_id="m",
        topic_label="Measurement",
        title="AppsFlyer updates attribution windows",
        url="https://example.com/2026/05/02/appsflyer-update",
        published_date=date.today().isoformat(),
        summary="AppsFlyer updated attribution windows for mobile app marketers.",
        why_it_matters="It changes live measurement decisions for app marketers.",
        mentioned_companies=["AppsFlyer"],
        relevance_score=5,
    )
    report = build_report([item], config, exa_errors=["market_watch_recent: timed out"])
    markdown = render_markdown(report)
    assert "## Top Market Signal" in markdown
    assert "AppsFlyer" in markdown
    assert "no Exa results were available" not in markdown


def test_all_exa_requests_timeout_produces_monitor_error_without_placeholder() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5),
        topics=(Topic(id="m", label="Measurement", query="measurement"),),
    )
    report = build_report([], config, exa_errors=["daily_fresh_signals: timeout", "market_watch_recent: timeout"])
    markdown = render_markdown(report)
    assert "no Exa results were available" in markdown
    assert "Strategic Context" not in markdown
    assert "Background context, not a fresh daily signal." not in markdown
    assert report.diagnostics["telegram_message_state"] == "monitor_error"


def test_market_watch_recent_timeout_does_not_block_final_rendering() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="broad"),
        topics=(Topic(id="ai", label="AI", query="ai"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )
    item = NewsItem(
        topic_id="ai",
        topic_label="AI",
        title="Omnicom rolls out agentic media buying workflow",
        url="https://example.com/2026/04/29/omnicom-agentic-buying",
        published_date=date.today().isoformat(),
        summary="Omnicom rolled out an agentic media buying workflow for live campaign operations and programmatic execution.",
        why_it_matters="It moves AI buying from concept to live media operations.",
        mentioned_companies=["Omnicom"],
        relevance_score=5,
    )
    report = build_report([item], config, exa_errors=["market_watch_recent: timeout"])
    message = _telegram_message(f"BidMatrix Daily Market Brief - {report.run_date.isoformat()}", render_markdown(report), "daily")
    assert "<b>Top market news</b>" in message
    assert "Omnicom" in message
    assert "<b>Monitor error</b>" not in message


def test_market_watch_recent_timeout_does_not_crash_daily_run() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(max_market_watch_queries=2),
        outputs=OutputSettings(min_relevance_score=5),
        topics=(Topic(id="a", label="Adtech", query="adtech"),),
    )
    client = object.__new__(ExaMonitorClient)
    client._config = config
    client._exa = None
    client._debug_exa = False
    client._last_errors = []
    client._stats = ExaCollectionStats()
    client._query_counts = {}
    client._layer_result_counts = {}
    client._seen_raw_urls = set()
    client._fresh_items_collected = 0
    client._collection_started_at = 0.0
    client._budget_exceeded = lambda: False  # type: ignore[method-assign]

    def fake_search_topic_layer(inner_topic, layer, *, num_results=None):
        raise TimeoutError("network slow")

    client.search_topic_layer = fake_search_topic_layer  # type: ignore[method-assign]
    items = client.search_market_watch_recent()
    assert items == []
    assert client.pop_errors()


def test_raw_results_with_all_items_filtered_by_freshness_use_market_watch_not_monitor_error() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced"),
        topics=(Topic(id="m", label="Measurement", query="measurement"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )
    items = [
        NewsItem(
            topic_id="m",
            topic_label="Measurement",
            title="AppsFlyer attribution update",
            url="https://example.com/appsflyer-update",
            published_date=(date.today() - timedelta(days=30)).isoformat(),
            summary="AppsFlyer updated attribution guidance for app marketers.",
            why_it_matters="It affects measurement decisions for mobile teams.",
            mentioned_companies=["AppsFlyer"],
            relevance_score=5,
        ),
        NewsItem(
            topic_id="m",
            topic_label="Measurement",
            title="Adjust SKAN notes",
            url="https://example.com/adjust-skan",
            published_date=(date.today() - timedelta(days=20)).isoformat(),
            summary="Adjust published SKAN guidance for advertisers.",
            why_it_matters="It affects attribution workflows.",
            mentioned_companies=["Adjust"],
            relevance_score=5,
        ),
    ]
    report = build_report(
        items,
        config,
        exa_meta={
            "raw_items_found": 25,
            "parsed_signals_count": 13,
            "filtered_out_by_freshness": 13,
            "exa_total_raw_results": 25,
            "exa_market_watch_queries_run": 0,
        },
    )
    markdown = render_markdown(report)
    assert report.diagnostics["selected_top_signals_count"] == 0
    assert report.diagnostics["telegram_message_state"] in {"adjacent", "market_watch"}
    assert report.diagnostics["fallback_level_used"] == "market_watch_best_available"
    assert "no Exa results were available" not in report.daily_intro
    assert "## Top Market Signals" in markdown


def test_raw_results_exist_never_use_monitor_error_message() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced"),
        topics=(Topic(id="a", label="Adtech", query="adtech"),),
    )
    item = NewsItem(
        topic_id="a",
        topic_label="Adtech",
        title="Older signal",
        url="https://example.com/older-signal",
        published_date=(date.today() - timedelta(days=40)).isoformat(),
        summary="Older but relevant mobile adtech signal.",
        why_it_matters="Still useful as recent context.",
        mentioned_companies=["ExampleCo"],
        relevance_score=5,
    )
    report = build_report([item], config, exa_errors=["one layer timed out"])
    assert "no Exa results were available" not in report.daily_intro
    assert report.diagnostics["telegram_message_state"] != "monitor_error"


def test_telegram_does_not_claim_no_exa_results_when_raw_results_exist() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-04

## Today's Useful Signals
Exa returned results, but no fresh BidMatrix-core items passed the filters. Here are the strongest recent relevant items available.

## Market Watch
### 1. AppsFlyer — updated attribution guidance for app marketers
- Why it may matter: Measurement teams still need the update even though it is not a same-day signal.
- BidMatrix use: Useful background for attribution positioning.
- Source: [AppsFlyer attribution update](https://example.com/appsflyer-update) - example.com - Date: 2026-05-03
"""
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-04", markdown, "daily")
    assert "<b>Monitor error</b>" not in message
    assert "<b>Market Watch</b>" in message


def test_budget_reached_message_is_not_monitor_error() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5),
        topics=(Topic(id="a", label="Adtech", query="adtech"),),
    )
    item = NewsItem(
        topic_id="a",
        topic_label="Adtech",
        title="Older signal",
        url="https://example.com/older-signal",
        published_date=(date.today() - timedelta(days=40)).isoformat(),
        summary="Older but relevant mobile adtech signal.",
        why_it_matters="Still useful as recent context.",
        mentioned_companies=["ExampleCo"],
        relevance_score=5,
    )
    report = build_report([item], config, exa_meta={"exa_budget_exceeded": True})
    assert "fallback search budget was reached" in report.daily_intro
    assert report.diagnostics["telegram_message_state"] != "monitor_error"


def _market_watch_candidate(
    title: str,
    summary: str,
    why_now: str,
    *,
    days_old: int = 8,
    companies: Optional[List[str]] = None,
) -> NewsItem:
    slug = title.lower().replace(" ", "-").replace("/", "-")
    return NewsItem(
        topic_id="mw",
        topic_label="Market Watch",
        title=title,
        url=f"https://example.com/2026/04/{max(1, 30 - days_old):02d}/{slug}",
        published_date=(date.today() - timedelta(days=days_old)).isoformat(),
        summary=summary,
        why_now=why_now,
        mentioned_companies=companies or [],
        relevance_score=5,
    )


def test_overwolf_loses_to_attribution_market_watch_item() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced"),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )
    overwolf = _market_watch_candidate(
        "Overwolf Ads Launches Gamer Grid",
        "Overwolf Ads launched Gamer Grid for PC gaming audience targeting using deterministic gameplay behavior and hardware signals.",
        "Timely for game launches and gaming ad growth.",
        companies=["Overwolf Ads"],
    )
    attribution = _market_watch_candidate(
        "AppsFlyer updates SKAN measurement workflow",
        "AppsFlyer updated SKAN and attribution guidance for app marketers using Privacy Sandbox and MMP workflows.",
        "Measurement teams need this change for live attribution decisions.",
        companies=["AppsFlyer"],
    )
    report = build_report([overwolf, attribution], config)
    assert report.diagnostics["fallback_level_used"] == "market_watch_14d"
    assert report.adjacent_watchlist[0].title == attribution.title
    assert report.diagnostics["selected_market_watch_reason"] == "measurement_attribution_priority"
    assert report.diagnostics["selected_market_watch_priority_score"] > report.adjacent_watchlist[-1].market_watch_priority_score


def test_overwolf_loses_to_ctv_performance_item() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced"),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )
    overwolf = _market_watch_candidate(
        "Overwolf Ads Launches Gamer Grid",
        "Overwolf Ads launched Gamer Grid for PC gaming audience targeting using deterministic gameplay behavior and hardware signals.",
        "Timely for game launches and gaming ad growth.",
        companies=["Overwolf Ads"],
    )
    ctv = _market_watch_candidate(
        "Moloco launches performance CTV for app marketers",
        "Moloco launched performance CTV with connected TV campaign optimization, install outcomes, and measurable ROI across streaming inventory.",
        "CTV is being used like performance media rather than reach-only media.",
        companies=["Moloco"],
    )
    report = build_report([overwolf, ctv], config)
    assert report.adjacent_watchlist[0].title == ctv.title
    assert report.diagnostics["selected_market_watch_priority_score"] > overwolf.market_watch_priority_score


def test_overwolf_loses_to_fraud_quality_item() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced"),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )
    overwolf = _market_watch_candidate(
        "Overwolf Ads Launches Gamer Grid",
        "Overwolf Ads launched Gamer Grid for PC gaming audience targeting using deterministic gameplay behavior and hardware signals.",
        "Timely for game launches and gaming ad growth.",
        companies=["Overwolf Ads"],
    )
    fraud = _market_watch_candidate(
        "DoubleVerify expands traffic quality controls",
        "DoubleVerify expanded fraud, invalid traffic, and brand safety controls for advertisers buying mobile inventory.",
        "Traffic quality controls matter immediately for campaign performance protection.",
        companies=["DoubleVerify"],
    )
    report = build_report([overwolf, fraud], config)
    assert report.adjacent_watchlist[0].title == fraud.title
    assert report.diagnostics["selected_market_watch_reason"] == "fraud_quality_priority"


def test_overwolf_loses_to_ai_media_buying_item() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced"),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )
    overwolf = _market_watch_candidate(
        "Overwolf Ads Launches Gamer Grid",
        "Overwolf Ads launched Gamer Grid for PC gaming audience targeting using deterministic gameplay behavior and hardware signals.",
        "Timely for game launches and gaming ad growth.",
        companies=["Overwolf Ads"],
    )
    ai_ops = _market_watch_candidate(
        "Omnicom rolls out agentic media buying workflow",
        "Omnicom rolled out AI media buying and campaign optimization workflows for live media operations.",
        "AI campaign operations are moving into live media buying decisions.",
        companies=["Omnicom"],
    )
    report = build_report([overwolf, ai_ops], config)
    assert report.adjacent_watchlist[0].title == ai_ops.title
    assert report.diagnostics["selected_market_watch_reason"] == "ai_campaign_ops_priority"


def test_overwolf_selected_only_when_no_better_market_watch_exists() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced"),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )
    overwolf = _market_watch_candidate(
        "Overwolf Ads Launches Gamer Grid",
        "Overwolf Ads launched Gamer Grid for PC gaming audience targeting using deterministic gameplay behavior and hardware signals.",
        "Timely for game launches and gaming ad growth.",
        companies=["Overwolf Ads"],
    )
    report = build_report([overwolf], config)
    assert report.adjacent_watchlist[0].title == overwolf.title
    assert report.diagnostics["selected_market_watch_reason"] == "adjacent_gaming_watchlist_priority"


def test_appsflyer_skan_does_not_get_ctv_bidmatrix_use() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced"),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )
    item = _market_watch_candidate(
        "AppsFlyer updates SKAN measurement workflow",
        "AppsFlyer updated SKAN and attribution guidance for app marketers using Privacy Sandbox and MMP workflows.",
        "Measurement teams need this change for live attribution decisions.",
        companies=["AppsFlyer"],
    )
    report = build_report([item], config)
    angle = report.adjacent_watchlist[0].why_it_matters_for_bidmatrix
    assert "attribution resilience" in angle.lower()
    assert "privacy-safe optimization" in angle.lower()
    assert "ctv" not in angle.lower()


def test_ctv_item_gets_ctv_specific_bidmatrix_use() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced"),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )
    item = _market_watch_candidate(
        "Moloco launches performance CTV for app marketers",
        "Moloco launched performance CTV with connected TV campaign optimization, install outcomes, and measurable ROI across streaming inventory.",
        "CTV is being used like performance media rather than reach-only media.",
        companies=["Moloco"],
    )
    report = build_report([item], config)
    angle = report.adjacent_watchlist[0].why_it_matters_for_bidmatrix
    assert "ctv" in angle.lower()
    assert "verified environments" in angle.lower() or "measurement beyond impressions" in angle.lower()


def test_fraud_item_gets_quality_bidmatrix_use() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced"),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )
    item = _market_watch_candidate(
        "DoubleVerify expands traffic quality controls",
        "DoubleVerify expanded fraud, invalid traffic, and brand safety controls for advertisers buying mobile inventory.",
        "Traffic quality controls matter immediately for campaign performance protection.",
        companies=["DoubleVerify"],
    )
    report = build_report([item], config)
    angle = report.adjacent_watchlist[0].why_it_matters_for_bidmatrix
    assert "traffic quality" in angle.lower() or "verified traffic" in angle.lower() or "performance protection" in angle.lower()


def test_ai_media_buying_item_gets_ai_bidmatrix_use() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced"),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )
    item = _market_watch_candidate(
        "Omnicom rolls out agentic media buying workflow",
        "Omnicom rolled out AI media buying and campaign optimization workflows for live media operations.",
        "AI campaign operations are moving into live media buying decisions.",
        companies=["Omnicom"],
    )
    report = build_report([item], config)
    angle = report.adjacent_watchlist[0].why_it_matters_for_bidmatrix
    assert "ai-native" in angle.lower() or "automated buying" in angle.lower() or "decision support" in angle.lower()


def test_overwolf_stays_indirect_watchlist_only() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced"),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )
    item = _market_watch_candidate(
        "Overwolf Ads Launches Gamer Grid",
        "Overwolf Ads launched Gamer Grid for PC gaming audience targeting using deterministic gameplay behavior and hardware signals.",
        "Timely for game launches and gaming ad growth.",
        companies=["Overwolf Ads"],
    )
    report = build_report([item], config)
    angle = report.adjacent_watchlist[0].why_it_matters_for_bidmatrix
    assert "indirect" in angle.lower()
    assert "watchlist only" in angle.lower()


def test_market_watch_digest_renders_multiple_items_when_candidates_exist() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced", daily_digest_target=4),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )
    items = [
        _market_watch_candidate(
            "LoopMe launches Chartboost Direct",
            "LoopMe launched Chartboost Direct to bring direct brand demand into mobile apps with curated marketplace and PMP workflows.",
            "Brand budgets are moving into curated in-app inventory and premium publisher monetization.",
            days_old=5,
            companies=["LoopMe", "Chartboost"],
        ),
        _market_watch_candidate(
            "Moloco launches performance CTV for app marketers",
            "Moloco launched performance CTV with connected TV campaign optimization, install outcomes, and measurable ROI across streaming inventory.",
            "CTV is being used like performance media rather than reach-only media.",
            days_old=4,
            companies=["Moloco"],
        ),
        _market_watch_candidate(
            "AppsFlyer updates SKAN measurement workflow",
            "AppsFlyer updated SKAN and attribution guidance for app marketers using Privacy Sandbox and MMP workflows.",
            "Measurement teams need this change for live attribution decisions.",
            days_old=3,
            companies=["AppsFlyer"],
        ),
        _market_watch_candidate(
            "Omnicom rolls out agentic media buying workflow",
            "Omnicom rolled out AI media buying and campaign optimization workflows for live media operations.",
            "AI campaign operations are moving into live media buying decisions.",
            days_old=2,
            companies=["Omnicom"],
        ),
        _market_watch_candidate(
            "Overwolf Ads Launches Gamer Grid",
            "Overwolf Ads launched Gamer Grid for PC gaming audience targeting using deterministic gameplay behavior and hardware signals.",
            "Timely for game launches and gaming ad growth.",
            days_old=1,
            companies=["Overwolf Ads"],
        ),
    ]
    report = build_report(items, config)
    markdown = render_markdown(report)
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-04", markdown, "daily")
    assert len(report.daily_digest_items) >= 3
    assert report.diagnostics["selected_digest_items_count"] >= 3
    assert "<b>Top market news</b>" in message
    assert "1." in message and "2." in message and "3." in message


def test_overwolf_not_selected_when_three_stronger_market_watch_candidates_exist() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced", daily_digest_target=4),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )
    items = [
        _market_watch_candidate(
            "Overwolf Ads Launches Gamer Grid",
            "Overwolf Ads launched Gamer Grid for PC gaming audience targeting using deterministic gameplay behavior and hardware signals.",
            "Timely for game launches and gaming ad growth.",
            companies=["Overwolf Ads"],
        ),
        _market_watch_candidate(
            "AppsFlyer updates SKAN measurement workflow",
            "AppsFlyer updated SKAN and attribution guidance for app marketers using Privacy Sandbox and MMP workflows.",
            "Measurement teams need this change for live attribution decisions.",
            companies=["AppsFlyer"],
        ),
        _market_watch_candidate(
            "Moloco launches performance CTV for app marketers",
            "Moloco launched performance CTV with connected TV campaign optimization, install outcomes, and measurable ROI across streaming inventory.",
            "CTV is being used like performance media rather than reach-only media.",
            companies=["Moloco"],
        ),
        _market_watch_candidate(
            "Omnicom rolls out agentic media buying workflow",
            "Omnicom rolled out AI media buying and campaign optimization workflows for live media operations.",
            "AI campaign operations are moving into live media buying decisions.",
            companies=["Omnicom"],
        ),
    ]
    report = build_report(items, config)
    titles = [item.title for item in report.daily_digest_items]
    assert all("Overwolf" not in title for title in titles)


def test_only_one_fraud_item_selected_when_other_buckets_exist() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced", daily_digest_target=4),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )
    items = [
        _market_watch_candidate(
            "Fraudlogix Q1 2026 Ad Fraud Report",
            "Fraudlogix published Q1 2026 ad fraud stats with invalid traffic and geo risk insights.",
            "Traffic quality controls matter immediately for campaign performance protection.",
            companies=["Fraudlogix"],
        ),
        _market_watch_candidate(
            "Mobile ad fraud in the age of AI",
            "Business of Apps insight details AI-evolved mobile fraud, polluted funnels, and retargeting contamination.",
            "AI fraud is becoming a more practical performance risk for app growth teams.",
            companies=["Business of Apps"],
        ),
        _market_watch_candidate(
            "Unity and Index Exchange expand in-app inventory access",
            "Unity partnered with Index Exchange to activate gaming audience and app inventory signals across programmatic channels.",
            "Programmatic app inventory is being packaged with more first-party data and direct demand paths.",
            companies=["Unity", "Index Exchange"],
        ),
    ]
    report = build_report(items, config)
    fraud_titles = [item.title for item in report.daily_digest_items if "fraud" in item.title.lower()]
    assert len(fraud_titles) == 1
    assert any("Unity" in item.title for item in report.daily_digest_items)


def test_synthesis_does_not_include_ctv_angle_without_ctv_selected_item() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced", daily_digest_target=4),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )
    items = [
        _market_watch_candidate(
            "Kochava Q1 2026 Product Bulletin",
            "Kochava published product and measurement updates including partner integrations and workspace changes.",
            "Attribution workflows and measurement infrastructure are evolving.",
            companies=["Kochava"],
        ),
        _market_watch_candidate(
            "Fraudlogix Q1 2026 Ad Fraud Report",
            "Fraudlogix published Q1 2026 ad fraud stats with invalid traffic and geo risk insights.",
            "Traffic quality controls matter immediately for campaign performance protection.",
            companies=["Fraudlogix"],
        ),
    ]
    report = build_report(items, config)
    joined = " ".join(report.bidmatrix_angles + report.what_this_suggests)
    assert "transparent ctv" not in joined.lower()


def test_watch_next_does_not_include_unselected_entities() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced", daily_digest_target=4),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )
    item = _market_watch_candidate(
        "Fraudlogix Q1 2026 Ad Fraud Report",
        "Fraudlogix published Q1 2026 ad fraud stats from 26.3B impressions, with AWS and high-risk geo patterns.",
        "Published 2026-04-29 amid rising AI fraud sophistication.",
        companies=["Amazon", "Fraudlogix"],
    )
    report = build_report([item], config)
    assert "Amazon" not in report.watch_next_items[0]


def test_date_from_metadata_or_text_is_used_in_source() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced"),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )
    item = _market_watch_candidate(
        "Fraudlogix Q1 2026 Ad Fraud Report",
        "Fraudlogix published Q1 2026 ad fraud stats with invalid traffic and geo risk insights.",
        "Published 2026-04-29 amid rising AI fraud sophistication.",
        companies=["Fraudlogix"],
        days_old=30,
    )
    item.published_date = None
    report = build_report([item], config)
    markdown = render_markdown(report)
    assert "Date: 2026-04-29" in markdown


def test_digest_synthesis_reflects_selected_topic_buckets() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced", daily_digest_target=4),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )
    items = [
        _market_watch_candidate(
            "Kochava Q1 2026 Product Bulletin",
            "Kochava published product and measurement updates including partner integrations and workspace changes.",
            "Attribution workflows and measurement infrastructure are evolving.",
            companies=["Kochava"],
        ),
        _market_watch_candidate(
            "Fraudlogix Q1 2026 Ad Fraud Report",
            "Fraudlogix published Q1 2026 ad fraud stats with invalid traffic and geo risk insights.",
            "Traffic quality controls matter immediately for campaign performance protection.",
            companies=["Fraudlogix"],
        ),
        _market_watch_candidate(
            "Omnicom rolls out agentic media buying workflow",
            "Omnicom rolled out AI media buying and campaign optimization workflows for live media operations.",
            "AI campaign operations are moving into live media buying decisions.",
            companies=["Omnicom"],
        ),
    ]
    report = build_report(items, config)
    joined = " ".join(report.what_this_suggests)
    assert "Measurement and traffic quality are converging" in joined
    assert "AI is appearing on both sides of the market" in joined


def test_recent_core_selection_avoids_duplicate_fraud_when_other_bucket_exists() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced", daily_digest_target=4),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )
    items = [
        NewsItem(
            topic_id="mw",
            topic_label="Market Watch",
            title="Fraudlogix Q1 2026 Ad Fraud Report",
            url="https://example.com/fraudlogix",
            published_date=(date.today() - timedelta(days=2)).isoformat(),
            summary="Fraudlogix published ad fraud stats with IVT and geo risk findings.",
            why_now="Traffic quality controls matter immediately.",
            mentioned_companies=["Fraudlogix"],
            relevance_score=5,
        ),
        NewsItem(
            topic_id="mw",
            topic_label="Market Watch",
            title="Mobile ad fraud in the age of AI",
            url="https://example.com/boa-fraud",
            published_date=(date.today() - timedelta(days=2)).isoformat(),
            summary="Business of Apps published an AI-era fraud overview for mobile marketers.",
            why_now="AI fraud is becoming a more practical performance risk.",
            mentioned_companies=["Business of Apps"],
            relevance_score=5,
        ),
        NewsItem(
            topic_id="mw",
            topic_label="Market Watch",
            title="Unity and Index Exchange expand in-app inventory access",
            url="https://example.com/unity-index",
            published_date=(date.today() - timedelta(days=2)).isoformat(),
            summary="Unity partnered with Index Exchange to activate app inventory and first-party audience signals across programmatic channels.",
            why_now="Programmatic app inventory is being packaged with more first-party data and direct demand paths.",
            mentioned_companies=["Unity", "Index Exchange"],
            relevance_score=5,
        ),
    ]
    report = build_report(items, config)
    titles = [item.title for item in report.daily_digest_items]
    assert sum("fraud" in title.lower() for title in titles) == 1
    assert any("Unity" in title for title in titles)


def test_single_fresh_core_signal_is_supplemented_by_recent_digest_items() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced", daily_digest_target=4),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )
    items = [
        NewsItem(
            topic_id="mw",
            topic_label="Market Watch",
            title="Fraudlogix Q1 2026 Ad Fraud Report",
            url="https://example.com/fraudlogix",
            published_date=(date.today() - timedelta(days=2)).isoformat(),
            summary="Fraudlogix published ad fraud stats with IVT and geo risk findings.",
            why_now="Published 2026-04-29 amid rising AI fraud sophistication.",
            mentioned_companies=["Fraudlogix"],
            relevance_score=5,
        ),
        _market_watch_candidate(
            "Unity and Index Exchange expand in-app inventory access",
            "Unity partnered with Index Exchange to activate app inventory and first-party audience signals across programmatic channels.",
            "Published 2026-04-27 as publishers look for stronger cross-channel supply and demand paths.",
            companies=["Unity", "Index Exchange"],
            days_old=6,
        ),
        _market_watch_candidate(
            "Moloco launches performance CTV for app marketers",
            "Moloco launched performance CTV with connected TV campaign optimization, install outcomes, and measurable ROI across streaming inventory.",
            "Published 2026-04-22 as app marketers push CTV toward measurable performance outcomes.",
            companies=["Moloco"],
        ),
    ]
    report = build_report(items, config)
    assert len(report.daily_digest_items) >= 2
    assert report.diagnostics["fallback_level_used"] in {"core_plus_context", "market_watch_14d", "market_watch_best_available"}


def test_primary_actor_prefers_publisher_over_secondary_entity() -> None:
    item = NewsItem(
        topic_id="mw",
        topic_label="Market Watch",
        title="Fraudlogix Q1 2026 Ad Fraud Report",
        url="https://example.com/fraudlogix",
        summary="Fraudlogix published Q1 2026 ad fraud stats from 26.3B impressions.",
        why_now="Published 2026-04-29 amid rising AI fraud sophistication.",
        mentioned_companies=["Amazon", "Fraudlogix"],
        relevance_score=5,
    )
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced"),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )
    report = build_report([item], config)
    assert report.daily_digest_items[0].company_or_topic == "Fraudlogix"


def test_digest_synthesis_appears_when_multiple_items_selected() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced", daily_digest_target=4),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )
    items = [
        _market_watch_candidate(
            "AppsFlyer updates SKAN measurement workflow",
            "AppsFlyer updated SKAN and attribution guidance for app marketers using Privacy Sandbox and MMP workflows.",
            "Measurement teams need this change for live attribution decisions.",
            companies=["AppsFlyer"],
        ),
        _market_watch_candidate(
            "Omnicom rolls out agentic media buying workflow",
            "Omnicom rolled out AI media buying and campaign optimization workflows for live media operations.",
            "AI campaign operations are moving into live media buying decisions.",
            companies=["Omnicom"],
        ),
    ]
    report = build_report(items, config)
    markdown = render_markdown(report)
    assert report.what_this_suggests
    assert report.bidmatrix_angles
    assert report.watch_next_items
    assert "## What This Suggests" in markdown
    assert "## BidMatrix Angles" in markdown
    assert "## Watch Next" in markdown


def test_one_item_brief_only_happens_when_one_candidate_exists() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced", daily_digest_target=4),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )
    item = _market_watch_candidate(
        "LoopMe launches Chartboost Direct",
        "LoopMe launched Chartboost Direct to bring direct brand demand into mobile apps with curated marketplace and PMP workflows.",
        "Brand budgets are moving into curated in-app inventory and premium publisher monetization.",
        companies=["LoopMe", "Chartboost"],
    )
    report = build_report([item], config)
    assert len(report.daily_digest_items) == 1
    assert report.diagnostics["selected_digest_items_count"] == 1


def test_core_signal_is_supplemented_by_background_items_to_reach_digest() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced", daily_digest_target=4),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(
            high_signal_domains=("example.com", "exchangewire.com", "kochava.com"),
            fresh_priority_domains=("example.com",),
            background_priority_domains=("exchangewire.com", "kochava.com"),
        ),
    )
    items = [
        NewsItem(
            topic_id="mw",
            topic_label="Market Watch",
            title="Mobile ad fraud in the age of AI: How fraud has evolved and how brands must fight back",
            url="https://example.com/boa-fraud",
            published_date=(date.today() - timedelta(days=2)).isoformat(),
            summary="Business of Apps insight details AI evolution of mobile ad fraud and polluted retargeting funnels.",
            why_now="Published 2026-04-29 as AI fraud pressure rises for app growth teams.",
            mentioned_companies=["Business of Apps"],
            relevance_score=5,
        ),
        NewsItem(
            topic_id="mw",
            topic_label="Market Watch",
            title="Q1 2026 | Kochava Product & Partnerships Update Bulletin",
            url="https://kochava.com/blog/kochava-product-partnership-updates-bulletin-q1-2026/",
            published_date=(date.today() - timedelta(days=18)).isoformat(),
            summary="Kochava published product and measurement updates including StationOne AI open beta and workflow improvements.",
            why_now="Published 2026-04-16 as MMP workflows move toward AI-assisted optimization.",
            mentioned_companies=["Kochava"],
            relevance_score=5,
        ),
        NewsItem(
            topic_id="mw",
            topic_label="Market Watch",
            title="LoopMe Launches Chartboost Direct, Bringing Brands into Mobile Apps to Drive Publisher Growth",
            url="https://www.exchangewire.com/blog/2026/04/09/loopme-launches-chartboost-direct-bringing-brands-into-mobile-apps-to-drive-publisher-growth/",
            published_date=(date.today() - timedelta(days=24)).isoformat(),
            summary="LoopMe launched Chartboost Direct to create more direct brand-demand paths into app inventory.",
            why_now="Published 2026-04-10 as brand budgets move deeper into curated in-app supply.",
            mentioned_companies=["LoopMe", "Chartboost"],
            relevance_score=5,
        ),
    ]
    report = build_report(items, config)
    titles = [item.title for item in report.daily_digest_items]
    assert len(titles) == 3
    assert any("Kochava" in title for title in titles)
    assert any("LoopMe" in title for title in titles)
    assert report.diagnostics["selected_core_items_count"] in {0, 1}
    assert report.diagnostics["supplemental_items_count"] == 2
    assert report.diagnostics["fallback_level_used"] in {"core_plus_context", "market_watch_14d", "market_watch_best_available"}
    assert (
        "supplemented with 2 recent market signals for context" in report.daily_intro
        or "No major core BidMatrix signal dominated today" in report.daily_intro
    )


def test_supplement_avoids_duplicate_fraud_when_other_buckets_exist() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced", daily_digest_target=4),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(
            high_signal_domains=("example.com", "kochava.com", "exchangewire.com"),
            fresh_priority_domains=("example.com",),
            background_priority_domains=("kochava.com", "exchangewire.com"),
        ),
    )
    items = [
        NewsItem(
            topic_id="mw",
            topic_label="Market Watch",
            title="Fraudlogix Q1 2026 Ad Fraud Report",
            url="https://example.com/fraudlogix",
            published_date=(date.today() - timedelta(days=2)).isoformat(),
            summary="Fraudlogix published Q1 2026 ad fraud stats with IVT and geo risk findings.",
            why_now="Published 2026-04-29 amid rising AI fraud sophistication.",
            mentioned_companies=["Fraudlogix"],
            relevance_score=5,
        ),
        NewsItem(
            topic_id="mw",
            topic_label="Market Watch",
            title="Mobile ad fraud in the age of AI",
            url="https://example.com/boa-fraud",
            published_date=(date.today() - timedelta(days=18)).isoformat(),
            summary="Business of Apps published an AI-era fraud overview for mobile marketers.",
            why_now="Published 2026-04-16 as AI fraud risk becomes a more practical performance issue.",
            mentioned_companies=["Business of Apps"],
            relevance_score=5,
        ),
        NewsItem(
            topic_id="mw",
            topic_label="Market Watch",
            title="Q1 2026 | Kochava Product & Partnerships Update Bulletin",
            url="https://kochava.com/blog/kochava-product-partnership-updates-bulletin-q1-2026/",
            published_date=(date.today() - timedelta(days=18)).isoformat(),
            summary="Kochava published product and measurement updates including StationOne AI open beta and workflow improvements.",
            why_now="Published 2026-04-16 as MMP workflows move toward AI-assisted optimization.",
            mentioned_companies=["Kochava"],
            relevance_score=5,
        ),
        NewsItem(
            topic_id="mw",
            topic_label="Market Watch",
            title="LoopMe Launches Chartboost Direct, Bringing Brands into Mobile Apps to Drive Publisher Growth",
            url="https://www.exchangewire.com/blog/2026/04/09/loopme-launches-chartboost-direct-bringing-brands-into-mobile-apps-to-drive-publisher-growth/",
            published_date=(date.today() - timedelta(days=24)).isoformat(),
            summary="LoopMe launched Chartboost Direct to create more direct brand-demand paths into app inventory.",
            why_now="Published 2026-04-10 as brand budgets move deeper into curated in-app supply.",
            mentioned_companies=["LoopMe", "Chartboost"],
            relevance_score=5,
        ),
    ]
    report = build_report(items, config)
    titles = [item.title for item in report.daily_digest_items]
    assert sum("fraud" in title.lower() for title in titles) == 1
    assert any("Kochava" in title for title in titles)
    assert any("LoopMe" in title for title in titles)


def test_digest_synthesis_appears_when_digest_is_supplemented() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced", daily_digest_target=4),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(
            high_signal_domains=("example.com", "kochava.com", "exchangewire.com"),
            fresh_priority_domains=("example.com",),
            background_priority_domains=("kochava.com", "exchangewire.com"),
        ),
    )
    items = [
        NewsItem(
            topic_id="mw",
            topic_label="Market Watch",
            title="Mobile ad fraud in the age of AI",
            url="https://example.com/boa-fraud",
            published_date=(date.today() - timedelta(days=2)).isoformat(),
            summary="Business of Apps published an AI-era fraud overview for mobile marketers.",
            why_now="Published 2026-04-29 as AI fraud risk becomes a more practical performance issue.",
            mentioned_companies=["Business of Apps"],
            relevance_score=5,
        ),
        NewsItem(
            topic_id="mw",
            topic_label="Market Watch",
            title="Q1 2026 | Kochava Product & Partnerships Update Bulletin",
            url="https://kochava.com/blog/kochava-product-partnership-updates-bulletin-q1-2026/",
            published_date=(date.today() - timedelta(days=18)).isoformat(),
            summary="Kochava published product and measurement updates including StationOne AI open beta and workflow improvements.",
            why_now="Published 2026-04-16 as MMP workflows move toward AI-assisted optimization.",
            mentioned_companies=["Kochava"],
            relevance_score=5,
        ),
    ]
    report = build_report(items, config)
    assert len(report.daily_digest_items) >= 2
    assert report.what_this_suggests
    assert report.bidmatrix_angles
    assert report.watch_next_items


def test_market_watch_path_supplements_bedrock_with_background_context() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced", daily_digest_target=4),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(
            high_signal_domains=("exchangewire.com", "moloco.com", "adweek.com"),
            fresh_priority_domains=("exchangewire.com",),
            background_priority_domains=("moloco.com", "adweek.com"),
        ),
    )
    items = [
        NewsItem(
            topic_id="mw",
            topic_label="Market Watch",
            title="Bedrock Debuts Containerised DSP Deployment on Index Cloud, Enabling Model-Driven Bidding at Scale",
            url="https://www.exchangewire.com/blog/2026/04/24/bedrock-debuts-containerised-dsp-deployment-on-index-cloud-enabling-model-driven-bidding-at-scale/",
            published_date=(date.today() - timedelta(days=10)).isoformat(),
            summary="Bedrock Platform launched a containerized DSP bidder on Index Cloud for model-driven bidding at scale.",
            why_now="Announced April 2026 as programmatic shifts toward AI-driven decisioning.",
            mentioned_companies=["Bedrock Platform", "Index Exchange"],
            relevance_score=5,
        ),
        NewsItem(
            topic_id="mw",
            topic_label="Market Watch",
            title="Moloco Launches AI-Powered Performance CTV for App Marketers, Bringing Mobile-Grade Measurement and Optimization to the Living Room",
            url="https://www.moloco.com/press-releases/ai-powered-performance-ctv",
            published_date=(date.today() - timedelta(days=18)).isoformat(),
            summary="Moloco launched Performance CTV with mobile AI optimization and MMP attribution.",
            why_now="Launched April 2026 as app marketers push CTV toward measurable performance outcomes.",
            mentioned_companies=["Moloco"],
            relevance_score=5,
        ),
        NewsItem(
            topic_id="mw",
            topic_label="Market Watch",
            title="LoopMe Launches Chartboost Direct, Bringing Brands into Mobile Apps",
            url="https://www.adweek.com/adweek-wire/loopme-launches-chartboost-direct-bringing-brands-into-mobile-apps/",
            published_date=(date.today() - timedelta(days=24)).isoformat(),
            summary="LoopMe launched Chartboost Direct SDK to open more direct brand-demand paths into app inventory.",
            why_now="Published April 2026 as brand budgets move deeper into curated in-app supply.",
            mentioned_companies=["LoopMe", "Chartboost"],
            relevance_score=5,
        ),
    ]
    report = build_report(items, config)
    titles = [item.title for item in report.daily_digest_items]
    assert len(titles) == 3
    assert any("Bedrock" in title for title in titles)
    assert any("Moloco" in title for title in titles)
    assert any("LoopMe" in title for title in titles)
    assert report.diagnostics["candidate_pool_sizes"]["background"] >= 2
    assert report.diagnostics["supplemental_items_count"] == 2
    assert report.diagnostics["selected_digest_items_count"] == 3


def test_market_watch_best_available_supplements_to_three_items() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced", daily_digest_target=4),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(high_signal_domains=("example.com",), background_priority_domains=("example.com",)),
    )
    items = [
        _market_watch_candidate(
            "Bedrock containerized DSP deployment",
            "Bedrock launched a containerized DSP deployment for model-driven bidding.",
            "Published 2026-04-20 as automated ad buying infrastructure evolves.",
            companies=["Bedrock Platform"],
            days_old=14,
        ),
        _market_watch_candidate(
            "Unity and Index Exchange expand in-app inventory access",
            "Unity partnered with Index Exchange to activate app inventory and first-party audience signals across automated ad buying channels.",
            "Published 2026-04-18 as publishers look for stronger supply and demand paths.",
            companies=["Unity", "Index Exchange"],
            days_old=16,
        ),
        _market_watch_candidate(
            "AppsFlyer updates SKAN measurement workflow",
            "AppsFlyer updated SKAN and attribution guidance for app marketers using Privacy Sandbox and MMP workflows.",
            "Published 2026-04-17 as measurement teams adapt live attribution decisions.",
            companies=["AppsFlyer"],
            days_old=17,
        ),
    ]
    report = build_report(items, config)
    assert len(report.daily_digest_items) == 3
    assert report.diagnostics["selected_digest_items_count"] == 3


def test_one_item_digest_reason_is_set_when_only_one_usable_item_exists() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced", daily_digest_target=4),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )
    item = NewsItem(
        topic_id="mw",
        topic_label="Market Watch",
        title="Single usable DSP infrastructure signal",
        url="https://example.com/single-dsp-signal",
        published_date=(date.today() - timedelta(days=9)).isoformat(),
        summary="A single usable DSP infrastructure update remains available.",
        why_now="Published 2026-04-25 as automated ad buying infrastructure evolves.",
        mentioned_companies=["SingleDSP"],
        relevance_score=5,
    )
    report = build_report([item], config)
    assert len(report.daily_digest_items) == 1
    assert report.diagnostics["one_item_digest_reason"]


def test_actions_do_not_leak_between_digest_items() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced", daily_digest_target=4),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(high_signal_domains=("example.com",), background_priority_domains=("example.com",)),
    )
    items = [
        _market_watch_candidate(
            "Kochava expands Certified Partners Program",
            "Kochava expanded its certified partner program and integration quality requirements.",
            "Published 2026-04-29 as MMP and partner-quality workflows evolve.",
            companies=["Kochava"],
            days_old=5,
        ),
        _market_watch_candidate(
            "TikTok recreates its ads for billboards via Vistar Media partnership",
            "TikTok and Vistar Media are packaging DOOH creative and measurement workflows for cross-screen campaigns.",
            "Published 2026-05-04 as cross-screen creative execution expands.",
            companies=["TikTok", "Vistar Media"],
            days_old=0,
        ),
        _market_watch_candidate(
            "State of ad fraud 2026: marketer report insights",
            "AppsFlyer released a fraud report covering fraud risk, channel quality, and verified traffic.",
            "Published 2026-04-23 as app marketers face rising fraud pressure.",
            companies=["AppsFlyer"],
            days_old=11,
        ),
    ]
    report = build_report(items, config)
    by_title = {item.title: item for item in report.daily_digest_items}
    assert "Kochava turns these certified integrations" in by_title["Kochava expands Certified Partners Program"].partner_or_sales_action
    assert "TikTok connects DOOH inventory" in by_title["TikTok recreates its ads for billboards via Vistar Media partnership"].partner_or_sales_action
    assert "fraud risk, channel quality, and verified traffic" in by_title["State of ad fraud 2026: marketer report insights"].partner_or_sales_action


def test_tiktok_dooh_gets_cross_screen_angle_not_mmp_angle() -> None:
    item = _market_watch_candidate(
        "TikTok recreates its ads for billboards via Vistar Media partnership",
        "TikTok and Vistar Media are packaging DOOH creative and measurement workflows for cross-screen campaigns.",
        "Published 2026-05-04 as cross-screen creative execution expands.",
        companies=["TikTok", "Vistar Media"],
        days_old=0,
    )
    report = build_report([item], MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced"),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    ))
    assert report.daily_digest_items[0].bidmatrix_angle == "Broad cross-screen context; relevant only if DOOH becomes measurable for app campaigns or retargeting."


def test_older_than_30_days_is_penalized_vs_newer_relevant_candidate() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced"),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(high_signal_domains=("example.com",), background_priority_domains=("example.com",)),
    )
    older = _market_watch_candidate(
        "Kochava expands Certified Partners Program",
        "Kochava expanded its certified partner program and integration quality requirements.",
        "Published 2026-03-03 as partner-quality workflows evolved.",
        companies=["Kochava"],
        days_old=62,
    )
    newer = _market_watch_candidate(
        "AppsFlyer updates SKAN measurement workflow",
        "AppsFlyer updated SKAN and attribution guidance for app marketers using Privacy Sandbox and MMP workflows.",
        "Published 2026-04-26 as measurement teams adapt live attribution decisions.",
        companies=["AppsFlyer"],
        days_old=8,
    )
    report = build_report([older, newer], config)
    assert report.daily_digest_items[0].title == newer.title


def test_telegram_renders_max_four_items_even_if_artifact_has_more() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced", daily_digest_target=4),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(high_signal_domains=("example.com",), background_priority_domains=("example.com",)),
    )
    items = [
        _market_watch_candidate("Kochava expands Certified Partners Program", "Kochava expanded its certified partner program and integration quality requirements.", "Published 2026-04-29 as MMP and partner-quality workflows evolve.", companies=["Kochava"], days_old=5),
        _market_watch_candidate("TikTok recreates its ads for billboards via Vistar Media partnership", "TikTok and Vistar Media are packaging DOOH creative and measurement workflows for cross-screen campaigns.", "Published 2026-05-04 as cross-screen creative execution expands.", companies=["TikTok", "Vistar Media"], days_old=0),
        _market_watch_candidate("State of ad fraud 2026: marketer report insights", "AppsFlyer released a fraud report covering fraud risk, channel quality, and verified traffic.", "Published 2026-05-01 as app marketers face rising fraud pressure.", companies=["AppsFlyer"], days_old=4),
        _market_watch_candidate("Moloco performance CTV for app marketers", "Moloco launched performance CTV with MMP attribution and measurable ROI across streaming inventory.", "Published 2026-05-02 as app marketers push CTV toward measurable performance outcomes.", companies=["Moloco"], days_old=3),
    ]
    report = build_report(items, config)
    assert len(report.daily_digest_items) == 4
    markdown = render_markdown(report)
    message = _telegram_message(f"BidMatrix Daily Market Brief - {report.run_date.isoformat()}", markdown, "daily")
    assert "\n1. " in message and "\n2. " in message and "\n3. " in message
    assert "\n5. " not in message
    assert "More items saved in the full report artifact." not in message
    assert "[Truncated." not in message


def test_event_line_rewrites_leading_and_partner_into_clean_joint_title() -> None:
    item = NewsItem(
        topic_id="mw",
        topic_label="Market Watch",
        title="TikTok recreates its ads for billboards via Vistar Media partnership",
        url="https://digiday.com/marketing/tiktok-recreates-its-ads-for-billboards-through-vistar-partnership/",
        summary="and Vistar Media are packaging DOOH creative and measurement workflows for cross-screen campaigns.",
        company_or_topic="TikTok",
    )
    line = _event_line(item, "TikTok")
    assert "TikTok — and Vistar Media" not in line
    assert line.startswith("TikTok x Vistar Media — packaging")


def test_appsflyer_sdk_action_does_not_leak_kochava() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced"),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )
    item = _market_watch_candidate(
        "AppsFlyer Android SDK 6.18.0 Release",
        "AppsFlyer released Android SDK version 6.18.0, adding support for obtaining IPv6 addresses and improving network compatibility.",
        "Recent SDK update improves IPv6 support amid growing mobile network requirements.",
        companies=["AppsFlyer"],
        days_old=48,
    )
    report = build_report([item], config)
    action = report.daily_digest_items[0].partner_or_sales_action
    assert "Kochava" not in action
    assert "AppsFlyer" in action or "SDK update" in action or "attribution reliability" in action


def test_telegram_avoids_duplicate_appsflyer_items_when_alternatives_exist() -> None:
    config = MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced", daily_digest_target=4),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(high_signal_domains=("example.com",), background_priority_domains=("example.com",)),
    )
    items = [
        _market_watch_candidate(
            "AppsFlyer Agent Hub beta",
            "AppsFlyer launched Agent Hub beta, a centralized platform for AI-driven agents providing actionable marketing insights and fraud optimization workflows.",
            "Published 2026-04-16 as AppsFlyer expands AI workflow tools for marketers.",
            companies=["AppsFlyer"],
            days_old=6,
        ),
        _market_watch_candidate(
            "State of ad fraud 2026: marketer report insights",
            "AppsFlyer released a fraud report covering fraud risk, channel quality, and verified traffic.",
            "Published 2026-04-23 as app marketers face rising fraud pressure.",
            companies=["AppsFlyer"],
            days_old=5,
        ),
        _market_watch_candidate(
            "AppsFlyer Android SDK 6.18.0 Release",
            "AppsFlyer released Android SDK version 6.18.0, adding support for obtaining IPv6 addresses and improving network compatibility.",
            "Recent SDK update improves IPv6 support amid growing mobile network requirements.",
            companies=["AppsFlyer"],
            days_old=48,
        ),
        _market_watch_candidate(
            "Moloco performance CTV for app marketers",
            "Moloco launched performance CTV with MMP attribution and measurable ROI across streaming inventory.",
            "Published 2026-04-22 as app marketers push CTV toward measurable performance outcomes.",
            companies=["Moloco"],
            days_old=3,
        ),
        _market_watch_candidate(
            "Mobile ad fraud in the age of AI",
            "Business of Apps published analysis of AI-driven mobile ad fraud, polluted retargeting pools, and channel-quality risks.",
            "Published 2026-04-29 as app marketers face rising fraud pressure.",
            companies=["Business of Apps"],
            days_old=5,
        ),
    ]
    report = build_report(items, config)
    markdown = render_markdown(report)
    message = _telegram_message(f"BidMatrix Daily Market Brief - {report.run_date.isoformat()}", markdown, "daily")
    assert "Moloco performance CTV for app marketers" in markdown or "Mobile ad fraud in the age of AI" in markdown
    assert "AppsFlyer Android SDK 6.18.0 Release" not in message
    appsflyer_mentions = sum(
        candidate in message
        for candidate in ("AppsFlyer Agent Hub beta", "State of ad fraud 2026: marketer report insights")
    )
    assert appsflyer_mentions <= 1
    assert "Mobile ad fraud" in message or "Moloco" in message


def test_daily_telegram_excludes_bidmatrix_self_item_and_old_2025_item() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-05

## Today's Useful Signals
Found 4 core signals worth attention today.

## Top Market Signals
### 1. Moloco — launched performance CTV for app marketers
- What happened: Moloco launched performance CTV with MMP attribution and measurable ROI across streaming inventory.
- Why it matters: Published 2026-05-04 as app marketers push CTV toward measurable performance outcomes.
- BidMatrix angle: Gives BidMatrix a concrete angle on transparent CTV, verified environments, and performance measurement beyond impressions.
- Source: [Moloco](https://example.com/moloco) - moloco.com (high-signal) - Date: 2026-05-04 - confidence: high
### 2. BidMatrix 2025 UA expansion kit
- What happened: BidMatrix shared a 2025 expansion kit for user acquisition teams.
- Why it matters: Published 2025-11-20 as an internal positioning update.
- BidMatrix angle: Internal update.
- Source: [BidMatrix](https://example.com/bidmatrix-kit) - bidmatrix.ai (high-signal) - Date: 2025-11-20 - confidence: high
### 3. AppsFlyer fraud report
- What happened: AppsFlyer released a fraud report covering fraud risk, channel quality, and verified traffic.
- Why it matters: Published 2026-05-03 as app marketers face rising fraud pressure.
- BidMatrix angle: Strengthens BidMatrix positioning around quality traffic, safer in-app inventory, and performance protection.
- Source: [AppsFlyer](https://example.com/fraud) - appsflyer.com (high-signal) - Date: 2026-05-03 - confidence: high
### 4. Adjust conversion rules update
- What happened: Adjust released conversion rules updates for post-install validation and fraud controls.
- Why it matters: Published 2026-05-02 for measurement and fraud workflow teams.
- BidMatrix angle: Supports BidMatrix positioning around attribution resilience and cleaner performance decision-making.
- Source: [Adjust](https://example.com/adjust) - adjust.com (high-signal) - Date: 2026-05-02 - confidence: high
"""
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-05", markdown, "daily")
    assert "BidMatrix 2025 UA expansion kit" not in message
    assert "2025" not in message
    assert "Moloco" in message
    assert "AppsFlyer" in message
    assert "Adjust conversion rules update" in message


def test_daily_telegram_uses_only_last_seven_days_by_default() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-05

## Today's Useful Signals
Found 2 core signals worth attention today.

## Top Market Signals
### 1. Fresh measurement update
- What happened: AppsFlyer updated Privacy Sandbox measurement workflows.
- Why it matters: Published 2026-05-02 for Android attribution teams.
- BidMatrix angle: Supports BidMatrix positioning around attribution resilience and privacy-safe optimization.
- Source: [AppsFlyer](https://example.com/fresh) - appsflyer.com (high-signal) - Date: 2026-05-02 - confidence: high
### 2. Older context item
- What happened: Legacy MMP partner update.
- Why it matters: Published 2026-04-20 as older context.
- BidMatrix angle: Older context only.
- Source: [Legacy](https://example.com/old) - example.com (high-signal) - Date: 2026-04-20 - confidence: high
"""
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-05", markdown, "daily")
    assert "Fresh measurement update" in message
    assert "Older context item" in message


def test_daily_telegram_avoids_duplicate_ctv_when_other_buckets_exist() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-05

## Today's Useful Signals
Found 4 core signals worth attention today.

## Top Market Signals
### 1. Moloco performance CTV
- What happened: Moloco launched performance CTV with app-growth measurement and ROI signals.
- Why it matters: Published 2026-05-04 as CTV becomes performance media.
- BidMatrix angle: Gives BidMatrix a concrete angle on transparent CTV and performance measurement beyond impressions.
- Source: [Moloco](https://example.com/moloco) - moloco.com (high-signal) - Date: 2026-05-04 - confidence: high
### 2. IAS Total TV
- What happened: IAS expanded Total TV measurement across premium CTV inventory.
- Why it matters: Published 2026-05-03 as CTV verification broadens.
- BidMatrix angle: Gives BidMatrix a concrete angle on transparent CTV and verified environments.
- Source: [IAS](https://example.com/ias) - ias.com (high-signal) - Date: 2026-05-03 - confidence: high
### 3. AppsFlyer fraud report
- What happened: AppsFlyer released a fraud report covering fraud risk and channel quality.
- Why it matters: Published 2026-05-03 as marketers face rising IVT pressure.
- BidMatrix angle: Strengthens BidMatrix positioning around quality traffic and performance protection.
- Source: [AppsFlyer](https://example.com/fraud) - appsflyer.com (high-signal) - Date: 2026-05-03 - confidence: high
### 4. BidMatrix 2025 UA expansion kit
- What happened: BidMatrix shared a 2025 growth update.
- Why it matters: Published 2025-11-20 as an internal note.
- BidMatrix angle: Internal.
- Source: [BidMatrix](https://example.com/bidmatrix-kit) - bidmatrix.ai (high-signal) - Date: 2025-11-20 - confidence: high
"""
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-05", markdown, "daily")
    ctv_count = int("Moloco performance CTV" in message) + int("IAS Total TV" in message)
    assert ctv_count == 1
    assert "AppsFlyer fraud report" in message
    assert "BidMatrix 2025 UA expansion kit" not in message


def test_daily_telegram_uses_no_strong_fresh_message_when_no_recent_items_exist() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-05

## Today's Useful Signals
No core BidMatrix-relevant signals found today.

## Top Market Signals
### 1. Older item
- What happened: Older item.
- Why it matters: Older item.
- BidMatrix angle: Older context.
- Source: [Older](https://example.com/old) - example.com (high-signal) - Date: 2026-04-01 - confidence: high
"""
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-05", markdown, "daily")
    assert "No strong fresh market signals found today." in message
    assert "<b>Top market news</b>" not in message


def test_daily_telegram_uses_14d_context_when_7d_is_empty() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-05

## Today's Useful Signals
Found 1 core signal worth attention, supplemented with 2 recent market signals for context.

## Top Market Signals
### 1. Unity x Index Exchange
- What happened: Unity and Index Exchange opened gaming audience data to curated deals across web and CTV.
- Why it matters: Published 2026-04-22 as curated cross-channel programmatic expands.
- BidMatrix angle: Gives BidMatrix a concrete angle on transparent CTV, verified environments, and performance measurement beyond impressions.
- Source: [Unity x Index](https://example.com/unity) - adexchanger.com (high-signal) - Date: 2026-04-22 - confidence: high
### 2. Moloco performance CTV
- What happened: Moloco launched performance CTV with MMP attribution and measurable ROI across streaming inventory.
- Why it matters: Published 2026-04-25 as app marketers push CTV toward measurable performance outcomes.
- BidMatrix angle: Gives BidMatrix a concrete angle on transparent CTV, verified environments, and performance measurement beyond impressions.
- Source: [Moloco](https://example.com/moloco) - moloco.com (high-signal) - Date: 2026-04-25 - confidence: high
### 3. LoopMe direct demand
- What happened: LoopMe launched Chartboost Direct to create more direct brand-demand paths into app inventory.
- Why it matters: Published 2026-04-24 as premium in-app inventory becomes more curated.
- BidMatrix angle: Gives BidMatrix a cleaner angle on curated in-app supply and premium inventory quality.
- Source: [LoopMe](https://example.com/loopme) - exchangewire.com (high-signal) - Date: 2026-04-24 - confidence: high
"""
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-05", markdown, "daily")
    assert "Fresh signals were limited, so today’s digest uses the strongest recent market context." in message
    assert "Moloco performance CTV" in message or "Unity x Index Exchange" in message
    assert "LoopMe" in message


def test_future_dated_item_is_rejected_as_fresh() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-05

## Today's Useful Signals
Found 1 core signal worth attention today.

## Top Market Signals
### 1. Singular migration guide
- What happened: Singular updated its migration guide for switching from other MMPs.
- Why it matters: Updated 2026-05-26 as MMP migration competition intensifies.
- BidMatrix angle: Supports BidMatrix positioning around attribution resilience and cleaner performance decision-making.
- Source: [Singular](https://example.com/singular) - support.singular.net (high-signal) - Date: 2026-05-26 - confidence: high
"""
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-05", markdown, "daily")
    assert "Singular migration guide" not in message
    assert "No strong fresh market signals found today." in message


def test_unknown_date_trusted_item_is_allowed_only_as_fallback() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-05

## Today's Useful Signals
Found 1 core signal worth attention, supplemented with recent market context.

## Top Market Signals
### 1. Fresh AppsFlyer fraud report
- What happened: AppsFlyer released a fraud report covering fraud risk and verified traffic.
- Why it matters: Published 2026-05-03 as app marketers face rising IVT pressure.
- BidMatrix angle: Strengthens BidMatrix positioning around quality traffic and performance protection.
- Source: [AppsFlyer](https://example.com/fresh-fraud) - appsflyer.com (high-signal) - Date: 2026-05-03 - confidence: high
### 2. LoopMe unknown-date direct demand
- What happened: LoopMe launched Chartboost Direct to create direct brand-demand paths into app inventory.
- Why it matters: Brand budgets are moving into curated in-app inventory.
- BidMatrix angle: Gives BidMatrix a cleaner angle on curated in-app supply and premium inventory quality.
- Source: [LoopMe](https://example.com/loopme) - exchangewire.com (high-signal) - confidence: high
"""
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-05", markdown, "daily")
    assert "Fresh AppsFlyer fraud report" in message
    assert "LoopMe" in message


def test_older_than_30d_item_is_excluded_from_telegram() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-05

## Today's Useful Signals
Found 2 core signals worth attention today.

## Top Market Signals
### 1. Old Kochava bulletin
- What happened: Kochava published a product bulletin.
- Why it matters: Published 2026-03-03 as older context.
- BidMatrix angle: Supports BidMatrix positioning around attribution resilience and privacy-safe optimization.
- Source: [Kochava](https://example.com/kochava) - kochava.com (high-signal) - Date: 2026-03-03 - confidence: high
### 2. Fresh Adjust conversion rules
- What happened: Adjust released conversion rules updates for post-install validation and fraud controls.
- Why it matters: Published 2026-05-02 for attribution workflow teams.
- BidMatrix angle: Supports BidMatrix positioning around attribution resilience and cleaner performance decision-making.
- Source: [Adjust](https://example.com/adjust) - adjust.com (high-signal) - Date: 2026-05-02 - confidence: high
"""
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-05", markdown, "daily")
    assert "Old Kochava bulletin" not in message
    assert "Fresh Adjust conversion rules" in message


def test_artifact_shaped_case_uses_recent_context_instead_of_empty_message() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-05

## Today's Useful Signals
Found 1 core signal worth attention, supplemented with 3 recent market signals for context.

## Top Market Signals
### 1. Singular migration guide
- What happened: Singular updated its migration guide for switching from other MMPs.
- Why it matters: Updated 2026-05-26 as MMP migration competition intensifies.
- BidMatrix angle: Supports BidMatrix positioning around attribution resilience and cleaner performance decision-making.
- Source: [Singular](https://example.com/singular) - support.singular.net (high-signal) - Date: 2026-05-26 - confidence: high
### 2. Unity x Index Exchange
- What happened: Unity and Index Exchange opened gaming audience data to curated deals across web and CTV.
- Why it matters: Published 2026-04-22 as curated cross-channel programmatic expands.
- BidMatrix angle: Gives BidMatrix a concrete angle on transparent CTV, verified environments, and performance measurement beyond impressions.
- Source: [Unity x Index](https://example.com/unity) - adexchanger.com (high-signal) - Date: 2026-04-22 - confidence: high
### 3. Moloco performance CTV
- What happened: Moloco launched performance CTV with MMP attribution and measurable ROI across streaming inventory.
- Why it matters: Published 2026-04-15 as app marketers push CTV toward measurable performance outcomes.
- BidMatrix angle: Gives BidMatrix a concrete angle on transparent CTV, verified environments, and performance measurement beyond impressions.
- Source: [Moloco](https://example.com/moloco) - moloco.com (high-signal) - Date: 2026-04-15 - confidence: high
### 4. Kochava bulletin
- What happened: Kochava launched Atlas Performance and StationOne AI workspaces.
- Why it matters: Published 2026-04-07 as product and ecosystem expansion continued.
- BidMatrix angle: Supports BidMatrix positioning around attribution resilience and privacy-safe optimization.
- Source: [Kochava](https://example.com/kochava) - kochava.com (high-signal) - Date: 2026-04-07 - confidence: high
### 5. LoopMe direct demand
- What happened: LoopMe launched Chartboost Direct to create direct brand-demand paths into app inventory.
- Why it matters: Brand budgets are moving into curated in-app inventory.
- BidMatrix angle: Gives BidMatrix a cleaner angle on curated in-app supply and premium inventory quality.
- Source: [LoopMe](https://example.com/loopme) - exchangewire.com (high-signal) - confidence: high
### 6. FTC bars Kochava
- What happened: FTC barred Kochava from selling sensitive data without consent.
- Why it matters: Published 2026-05-04 as regulatory scrutiny increased.
- BidMatrix angle: Supports BidMatrix positioning around attribution resilience and privacy-safe optimization.
- Source: [FTC/Kochava](https://example.com/ftc-kochava) - adexchanger.com (high-signal) - confidence: low
"""
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-05", markdown, "daily")
    assert "No strong fresh market signals found today." not in message
    assert "Singular migration guide" not in message
    assert "Unity x Index Exchange" in message
    assert "Moloco performance CTV" in message or "LoopMe direct demand" in message or "Kochava bulletin" in message


def test_tiktok_cross_screen_angle_counts_as_adjacent_in_telegram() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-05

## Today's Useful Signals
Found 1 core signal worth attention today.

## Top Market Signals
### 1. TikTok x Vistar Media
- What happened: TikTok partnered with Vistar Media to reformat vertical ads into DOOH billboards.
- Why it matters: Published 2026-05-04 as cross-screen creative execution expands.
- BidMatrix angle: Broad cross-screen context; relevant only if DOOH becomes measurable for app campaigns or retargeting.
- Source: [TikTok x Vistar](https://example.com/tiktok) - digiday.com (high-signal) - Date: 2026-05-04 - confidence: high
"""
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-05", markdown, "daily")
    assert "Found 1 fresh BidMatrix-relevant signal worth attention today." not in message
    assert "No strong fresh BidMatrix-core signals found today." in message


def test_one_adjacent_only_item_uses_market_signal_to_watch() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-05

## Today's Useful Signals
Found 1 core signal worth attention today.

## Top Market Signals
### 1. TikTok x Vistar Media
- What happened: TikTok partnered with Vistar Media to reformat vertical ads into DOOH billboards.
- Why it matters: Published 2026-05-04 as cross-screen creative execution expands.
- BidMatrix angle: Broad cross-screen context; relevant only if DOOH becomes measurable for app campaigns or retargeting.
- Source: [TikTok x Vistar](https://example.com/tiktok) - digiday.com (high-signal) - Date: 2026-05-04 - confidence: high
"""
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-05", markdown, "daily")
    assert "<b>Market signal to watch</b>" in message
    assert "<b>Top market news</b>" not in message


def test_core_item_keeps_normal_top_market_news_intro() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-05

## Today's Useful Signals
Found 1 core signal worth attention today.

## Top Market Signals
### 1. Adjust conversion rules
- What happened: Adjust released conversion rules updates for post-install validation and fraud controls.
- Why it matters: Published 2026-05-02 for attribution workflow teams.
- BidMatrix angle: Supports BidMatrix positioning around attribution resilience and cleaner performance decision-making.
- Source: [Adjust](https://example.com/adjust) - adjust.com (high-signal) - Date: 2026-05-02 - confidence: high
"""
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-05", markdown, "daily")
    assert "Found 1 fresh BidMatrix-relevant signal worth attention today." in message
    assert "<b>Top market news</b>" in message


def test_relevant_only_if_item_is_not_counted_as_core() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-05

## Today's Useful Signals
Found 1 core signal worth attention today.

## Top Market Signals
### 1. Test cross-screen item
- What happened: A cross-screen item.
- Why it matters: Published 2026-05-04 as cross-screen execution expands.
- BidMatrix angle: Broad cross-screen context; relevant only if DOOH becomes measurable for app campaigns or retargeting.
- Source: [Test](https://example.com/test) - example.com (high-signal) - Date: 2026-05-04 - confidence: high
"""
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-05", markdown, "daily")
    assert "BidMatrix-relevant signal worth attention" not in message
    assert "adjacent market signal" in message or "adjacent market signal is worth watching" in message


def test_tiktok_dooh_gets_cross_screen_affects_line() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-05

## Today's Useful Signals
Found 1 core signal worth attention today.

## Top Market Signals
### 1. TikTok x Vistar Media
- What happened: TikTok partnered with Vistar Media to reformat vertical ads into DOOH billboards.
- Why it matters: Published 2026-05-04 as cross-screen creative execution expands.
- BidMatrix angle: Broad cross-screen context; relevant only if DOOH becomes measurable for app campaigns or retargeting.
    - Source: [TikTok x Vistar](https://example.com/tiktok) - digiday.com (high-signal) - Date: 2026-05-04 - confidence: high
    """
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-05", markdown, "daily")
    assert "How BidMatrix can use it" in message
    assert "Broad cross-screen context — relevant only if DOOH becomes measurable for app campaigns or retargeting." in message
    assert "What it affects" not in message


def test_appsflyer_fraud_gets_fraud_affects_line() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-05

## Today's Useful Signals
Found 1 core signal worth attention today.

## Top Market Signals
### 1. AppsFlyer fraud report
- What happened: AppsFlyer released a fraud report covering fraud risk, channel quality, verified traffic, and IVT patterns.
- Why it matters: Published 2026-05-03 as app marketers face rising fraud pressure.
- BidMatrix angle: Strengthens BidMatrix positioning around quality traffic, safer in-app inventory, and performance protection.
- Source: [AppsFlyer](https://example.com/fraud) - appsflyer.com (high-signal) - Date: 2026-05-03 - confidence: high
    """
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-05", markdown, "daily")
    assert "The report highlights where fraud pressure is concentrating across channels, verticals, and acquisition patterns." in message
    assert "AppsFlyer released a fraud report covering fraud risk, channel quality, verified traffic, and IVT patterns." not in message
    assert "How BidMatrix can use it" in message
    assert "Use this as support for content and sales conversations around verified traffic, fraud risk, and why clean acquisition sources matter for ROAS." in message


def test_mixed_core_and_adjacent_digest_gets_honest_intro() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-05

## Today's Useful Signals
Found 1 core signal worth attention, supplemented with 1 recent market signal for context.

## Top Market Signals
### 1. TikTok x Vistar Media
- What happened: TikTok partnered with Vistar Media to reformat vertical ads into DOOH billboards.
- Why it matters: Published 2026-05-04 as cross-screen creative execution expands.
- BidMatrix angle: Broad cross-screen context; relevant only if DOOH becomes measurable for app campaigns or retargeting.
- Source: [TikTok x Vistar](https://example.com/tiktok) - digiday.com (high-signal) - Date: 2026-05-04 - confidence: high
### 2. AppsFlyer fraud report
- What happened: AppsFlyer released a fraud report covering fraud risk, channel quality, verified traffic, and IVT patterns.
- Why it matters: Published 2026-04-23 as app marketers face rising fraud pressure.
- BidMatrix angle: Strengthens BidMatrix positioning around quality traffic, safer in-app inventory, and performance protection.
- Source: [AppsFlyer](https://example.com/fraud) - appsflyer.com (high-signal) - Date: 2026-04-23 - confidence: medium
"""
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-05", markdown, "daily")
    assert "Found 1 fresh signal, supplemented with 1 recent market context item." in message
    assert "Found 1 core signal, supplemented with 1 adjacent/recent market signal." not in message


def test_all_recent_context_items_get_recent_context_intro() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-05

## Today's Useful Signals
Found 2 BidMatrix-relevant signals worth attention today.

## Top Market Signals
### 1. Moloco performance CTV
- What happened: Moloco launched performance CTV with MMP attribution and measurable ROI across streaming inventory.
- Why it matters: Published 2026-04-22 as app marketers push CTV toward measurable performance outcomes.
- BidMatrix angle: Gives BidMatrix a concrete angle on transparent CTV, verified environments, and performance measurement beyond impressions.
- Source: [Moloco](https://example.com/moloco) - moloco.com (high-signal) - Date: 2026-04-22 - confidence: high
### 2. OpenAI conversion tracking
- What happened: OpenAI added a conversion tracking pixel to help advertisers measure conversions across ChatGPT ad experiences.
- Why it matters: Published 2026-04-16 as AI-native ad platforms move toward measurable performance accountability.
- BidMatrix angle: Supports BidMatrix positioning around attribution resilience and cleaner performance decision-making.
- Source: [OpenAI](https://example.com/openai) - digiday.com (high-signal) - Date: 2026-04-16 - confidence: high
"""
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-05", markdown, "daily")
    assert "Fresh signals were limited, so today’s digest uses the strongest recent market context." in message
    assert "worth attention today" not in message


def test_openai_conversion_tracking_gets_ai_platform_measurement_mapping() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-05

## Today's Useful Signals
Found 1 core signal worth attention today.

## Top Market Signals
### 1. OpenAI conversion tracking
- What happened: OpenAI added a conversion tracking pixel to help advertisers measure conversions across ChatGPT ad experiences.
- Why it matters: Published 2026-04-16 as AI-native ad platforms move toward measurable performance accountability.
- BidMatrix angle: Supports BidMatrix positioning around attribution resilience and cleaner performance decision-making.
    - Source: [OpenAI](https://example.com/openai) - digiday.com (high-signal) - Date: 2026-04-16 - confidence: high
    """
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-05", markdown, "daily")
    assert "Use this as broader context for content and sales: AI-native ad platforms are moving toward measurable advertising, which reinforces the need for attribution clarity and performance safeguards." in message
    assert "How BidMatrix can use it" in message
    assert "What it affects" not in message


def test_telegram_cleanup_removes_dangling_fragments() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-05

## Today's Useful Signals
Found 2 BidMatrix-relevant signals worth attention today.

## Top Market Signals
### 1. OpenAI ad measurement update to enable
- What happened: OpenAI added a conversion tracking pixel (e.g.
- Why it matters: Published 2026-04-16 as AI-native ad platforms move toward measurable performance accountability.
- BidMatrix angle: Supports BidMatrix positioning around attribution resilience and cleaner performance decision-making.
- Source: [OpenAI](https://example.com/openai) - digiday.com (high-signal) - Date: 2026-04-16 - confidence: high
### 2. Moloco performance CTV
- What happened: Moloco launched performance CTV to enable
- Why it matters: Published 2026-04-22 as app marketers push CTV toward measurable performance outcomes.
- BidMatrix angle: Gives BidMatrix a concrete angle on transparent CTV, verified environments, and performance measurement beyond impressions.
- Source: [Moloco](https://example.com/moloco) - moloco.com (high-signal) - Date: 2026-04-22 - confidence: high
"""
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-05", markdown, "daily")
    assert "to enable." not in message
    assert "e.g." not in message
    assert "(e.g." not in message
    assert "(\n" not in message


def test_recent_context_intro_uses_plural_signals_grammar() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-05

## Today's Useful Signals
Found 2 BidMatrix-relevant signals worth attention today.

## Top Market Signals
### 1. Moloco performance CTV
- What happened: Moloco launched performance CTV with MMP attribution and measurable ROI across streaming inventory.
- Why it matters: Published 2026-04-22 as app marketers push CTV toward measurable performance outcomes.
- BidMatrix angle: Gives BidMatrix a concrete angle on transparent CTV, verified environments, and performance measurement beyond impressions.
- Source: [Moloco](https://example.com/moloco) - moloco.com (high-signal) - Date: 2026-04-22 - confidence: high
### 2. OpenAI conversion tracking
- What happened: OpenAI added a conversion tracking pixel to help advertisers measure conversions across ChatGPT ad experiences.
- Why it matters: Published 2026-04-16 as AI-native ad platforms move toward measurable performance accountability.
- BidMatrix angle: Supports BidMatrix positioning around attribution resilience and cleaner performance decision-making.
- Source: [OpenAI](https://example.com/openai) - digiday.com (high-signal) - Date: 2026-04-16 - confidence: high
"""
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-05", markdown, "daily")
    assert "Fresh signals were limited, so today’s digest uses the strongest recent market context." in message
    assert "Fresh signal were limited" not in message


def test_meta_ctv_item_gets_ctv_mapping_not_attribution_wording() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-05

## Today's Useful Signals
Found 1 core signal worth attention today.

## Top Market Signals
### 1. Meta CTV expansion
- What happened: Meta is holding exploratory meetings with SSPs like Magnite and FreeWheel, TV OEMs, and streaming partners.
- Why it matters: Published 2026-05-04 as major ad platforms explore CTV distribution and monetization.
- BidMatrix angle: Supports BidMatrix positioning around attribution resilience, privacy-safe optimization, and cleaner performance decision-making for app growth teams.
    - Source: [Meta](https://example.com/meta-ctv) - digiday.com (high-signal) - Date: 2026-05-04 - confidence: high
    """
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-05", markdown, "daily")
    assert "Use this as broader CTV context in BD and positioning work: major ad platforms are exploring TV inventory as a performance and reach extension, but advertisers will still need measurable outcomes and verified environments." in message
    assert "Supports BidMatrix positioning around attribution resilience, privacy-safe optimization, and cleaner performance decision-making for app growth teams." not in message
    assert "How BidMatrix can use it" in message
    assert "What it affects" not in message


def test_meta_ctv_summary_cleanup_avoids_awkward_fragment() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-05

## Today's Useful Signals
Found 1 core signal worth attention today.

## Top Market Signals
### 1. Meta CTV expansion
- What happened: Meta is holding exploratory meetings with SSPs like Magnite and FreeWheel, TV OEMs.
- Why it matters: Published 2026-05-04 as major ad platforms explore CTV distribution and monetization.
- BidMatrix angle: Supports BidMatrix positioning around attribution resilience, privacy-safe optimization, and cleaner performance decision-making for app growth teams.
- Source: [Meta](https://example.com/meta-ctv) - digiday.com (high-signal) - Date: 2026-05-04 - confidence: high
"""
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-05", markdown, "daily")
    assert "Meta is exploring CTV expansion through talks with SSPs, TV OEMs, and streaming partners." in message
    assert "Magnite and FreeWheel, TV OEMs." not in message


def test_kochava_yahoo_dsp_item_gets_specific_dsp_mapping() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-06

## Today's Useful Signals
Found 1 core signal worth attention today.

## Top Market Signals
### 1. Kochava StationOne x Yahoo DSP
- What happened: Kochava connected StationOne workflows with Yahoo DSP to support agentic DSP decisioning and optimization.
- Why it matters: Published 2026-05-05 as MMP and DSP workflows move closer together through AI-assisted buying.
- BidMatrix angle: Supports BidMatrix positioning around attribution resilience, privacy-safe optimization, and cleaner performance decision-making for app growth teams.
- Source: [Kochava](https://example.com/kochava-yahoo) - kochava.com (high-signal) - Date: 2026-05-05 - confidence: high
    """
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-06", markdown, "daily")
    assert "Use this as partner and competitor monitoring: MMP and DSP workflows are moving closer together through AI-assisted media buying." in message
    assert "AI media buying, campaign optimization, and automated decision support." not in message
    assert "Supports BidMatrix positioning around attribution resilience, privacy-safe optimization, and cleaner performance decision-making for app growth teams." not in message
    assert "What it affects" not in message


def test_google_incrementality_item_gets_practical_use_line() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-06

## Today's Useful Signals
Found 1 fresh BidMatrix-relevant signal worth attention today.

## Top Market Signals
### 1. Google Ads measurement tooling for incrementality
- What happened: AdExchanger reports that Google announced updates to Google Ads' Data Manager.
- Why it matters: Published 2026-05-05 as advertisers push for cleaner measurement and lift testing.
- BidMatrix angle: Supports BidMatrix positioning around attribution resilience, privacy-safe optimization, and cleaner performance decision-making for app growth teams.
- Source: [Google Ads adds new tools for mapping incrementality](https://example.com/google) - adexchanger.com (high-signal) - Date: 2026-05-05 - confidence: high
"""
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-06", markdown, "daily")
    assert "How BidMatrix can use it" in message
    assert "Use this as a sales and content angle around incrementality: more advertisers are looking beyond last-click reporting and need cleaner ways to prove whether media spend actually drives lift." in message
    assert "Supports BidMatrix positioning around" not in message


def test_moloco_ctv_item_gets_practical_ctv_use_line() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-05-06

## Today's Useful Signals
Found 1 fresh BidMatrix-relevant signal worth attention today.

## Top Market Signals
### 1. Moloco performance CTV
- What happened: Moloco launched performance CTV with MMP attribution and measurable ROI across streaming inventory.
- Why it matters: Published 2026-05-05 as app marketers push CTV toward measurable performance outcomes.
- BidMatrix angle: Gives BidMatrix a concrete angle on transparent CTV, verified environments, and performance measurement beyond impressions.
- Source: [Moloco](https://example.com/moloco) - moloco.com (high-signal) - Date: 2026-05-05 - confidence: high
"""
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-05-06", markdown, "daily")
    assert "Use this in CTV positioning and BD conversations: app marketers increasingly expect TV inventory to work like measurable performance media, not just awareness." in message
    assert "How BidMatrix can use it" in message
