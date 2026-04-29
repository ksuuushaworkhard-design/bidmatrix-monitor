from datetime import date

from bidmatrix_monitor.intelligence import build_report, dedupe_items
from bidmatrix_monitor.models import MonitorConfig, NewsItem, OutputSettings, SearchSettings, SourceConfig, Topic


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
