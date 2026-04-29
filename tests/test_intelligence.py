from datetime import date, timedelta

from bidmatrix_monitor.intelligence import build_report, dedupe_items
from bidmatrix_monitor.models import MonitorConfig, NewsItem, OutputSettings, SearchSettings, SourceConfig, Topic
from bidmatrix_monitor.render import render_markdown
from bidmatrix_monitor.weekly import render_weekly_markdown


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
        summary="Alpha launched new product.",
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
