from datetime import date, timedelta

from bidmatrix_monitor.intelligence import build_report, dedupe_items
from bidmatrix_monitor.models import MonitorConfig, NewsItem, OutputSettings, SearchSettings, SourceConfig, Topic
from bidmatrix_monitor.render import render_markdown
from bidmatrix_monitor.weekly import render_weekly_markdown
from bidmatrix_monitor.delivery import _telegram_message


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

    assert len(report.daily_signals) == 1
    assert report.daily_signals[0].title == fresh.title
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
    assert report.daily_intro == "No fresh high-confidence signals found today. Here are useful background items worth tracking."


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
    assert "## Strategic Context" in markdown
    assert "Background context, not a fresh daily signal." in markdown
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
    report = build_report([item], config)
    assert report.daily_signals[0].company_or_topic == "DAIVID x ADIN.AI"


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
    rendered = render_markdown(report)
    assert "Creative intelligence is moving from post-campaign reporting into live media optimization and budget allocation." in rendered


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
    assert "## Top Signal" in rendered


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



def test_daily_telegram_message_includes_top_signal_fields() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-04-29

## Today's Useful Signal
Today's brief uses the best relevant signals from the last 72 hours.

## Top Signal
### 1. DAIVID x ADIN.AI — AI creative-effectiveness data moves closer to media optimization
- What happened: DAIVID partnered with ADIN.AI to bring AI creative-effectiveness data into media optimization.
- Why it matters: Creative intelligence is moving into live media decisioning.
- Market context: Creative intelligence is moving from reporting into budget allocation.
- BidMatrix angle: Useful for BidMatrix AI-native positioning.
- Content angle: AI in user acquisition is starting to decide which creatives deserve budget.
- Action: Track whether creative intelligence vendors integrate more directly with media buying platforms.
- Watch next: Track whether creative intelligence vendors integrate more directly with media buying platforms.
- Source: [DAIVID & ADIN.AI Partner](https://example.com/daivid) - exchangewire.com (high-signal) - confidence: high

## Strategic Context
- No useful background context was kept.
"""
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-04-29", markdown, "daily")
    assert "Top signal" in message
    assert "What happened" in message
    assert "Why it matters" in message
    assert "BidMatrix angle" in message
    assert "Content angle" in message
    assert "Action" in message
    assert "Source" in message
    assert "https://example.com/daivid" in message


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
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-04-29", markdown, "daily")
    assert "AppsFlyer" in message
    assert "Overwolf Ads" not in message


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
    message = _telegram_message("BidMatrix Daily Market Brief - 2026-04-29", markdown, "daily")
    assert "No core BidMatrix-relevant signals found today." in message
    assert "Adjacent watchlist" in message
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
    markdown = """# BidMatrix Daily Brief - 2026-04-29

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
- Source: [One](https://example.com/1) - example.com - confidence: high
### 2. Signal Two — B
- What happened: B.
- Why it matters: B.
- BidMatrix angle: B.
- Content angle: B.
- Action: B.
- Source: [Two](https://example.com/2) - example.com - confidence: medium
"""
    message = _telegram_message('BidMatrix Daily Market Brief - 2026-04-29', markdown, 'daily')
    assert 'Found 2 core signals worth attention today.' in message
    assert '<b>Top signals</b>' in message


def test_low_confidence_items_are_not_rendered_as_top_signals() -> None:
    markdown = """# BidMatrix Daily Brief - 2026-04-29

## Today's Useful Signals
Found 2 core signals worth attention today.

## Top Signals
### 1. Strong Signal — A
- What happened: A.
- Why it matters: A.
- BidMatrix angle: A.
- Content angle: A.
- Action: A.
- Source: [One](https://example.com/1) - example.com - confidence: high
### 2. Weak Signal — B
- What happened: B.
- Why it matters: B.
- BidMatrix angle: B.
- Content angle: B.
- Action: B.
- Source: [Two](https://example.com/2) - example.com - confidence: low
"""
    message = _telegram_message('BidMatrix Daily Market Brief - 2026-04-29', markdown, 'daily')
    assert 'Strong Signal' in message
    assert 'Weak Signal' not in message
    assert 'Found 1 core signal worth attention today.' in message


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
