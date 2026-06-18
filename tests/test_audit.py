from __future__ import annotations

import json
from datetime import date, timedelta

from bidmatrix_monitor.audit import build_daily_audit_payload, write_daily_audit_report
from bidmatrix_monitor.intelligence import build_report
from bidmatrix_monitor.models import MonitorConfig, MonitorReport, NewsItem, OutputSettings, SearchSettings, SourceConfig, Topic


def _config() -> MonitorConfig:
    return MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(min_relevance_score=5, sensitivity="balanced", daily_digest_target=4),
        topics=(Topic(id="mw", label="Market Watch", query="market watch"),),
        sources=SourceConfig(high_signal_domains=("example.com",), fresh_priority_domains=("example.com",)),
    )


def _item(title: str, days_old: int = 0) -> NewsItem:
    published = (date.today() - timedelta(days=days_old)).isoformat()
    return NewsItem(
        topic_id="mw",
        topic_label="Market Watch",
        title=title,
        url=f"https://example.com/{title.lower().replace(' ', '-')}",
        published_date=published,
        source="Example Source",
        source_domain="example.com",
        source_url=f"https://example.com/{title.lower().replace(' ', '-')}",
        summary=f"{title} summary.",
        what_happened=f"{title} happened.",
        why_now=f"Published {published} as a fresh market signal.",
        company_or_topic="ExampleCo",
        mentioned_companies=["ExampleCo"],
        relevance_score=5,
    )


def test_write_daily_audit_report_writes_file(tmp_path) -> None:
    report = build_report([_item("Fresh market update")], _config())

    audit_path = write_daily_audit_report(report, tmp_path)

    assert audit_path.exists()
    payload = json.loads(audit_path.read_text(encoding="utf-8"))
    assert payload["run_date"] == report.run_date.isoformat()
    assert payload["selected_digest_items_count"] == report.diagnostics["selected_digest_items_count"]
    assert payload["candidates"]


def test_audit_generation_does_not_change_selected_report_items(tmp_path) -> None:
    report = build_report(
        [
            _item("Airbridge measurement update"),
            _item("Moloco performance CTV launch"),
        ],
        _config(),
    )
    before = [item.normalized_url for item in report.daily_digest_items]

    write_daily_audit_report(report, tmp_path)

    after = [item.normalized_url for item in report.daily_digest_items]
    assert after == before


def test_build_daily_audit_payload_uses_null_for_missing_optional_fields() -> None:
    raw_item = NewsItem(
        topic_id="mw",
        topic_label="Market Watch",
        title="Sparse candidate",
        url="https://example.com/sparse",
    )
    report = MonitorReport(
        run_date=date.today(),
        diagnostics={},
        items=[],
        trends=[],
        daily_intro="No signals.",
        daily_signals=[],
        daily_digest_items=[],
        adjacent_watchlist=[],
        top_news=[],
        actually_new_today=[],
        fresh_weak_confidence=[],
        background_items=[],
        what_this_suggests=[],
        bidmatrix_angles=[],
        watch_next_items=[],
        hot_takes=[],
        partner_signals=[],
        competitor_moves=[],
        content_angles_for_linkedin=[],
        pr_hooks=[],
        what_changed_today=[],
        raw_items=[raw_item],
        candidate_items=[],
    )

    payload = build_daily_audit_payload(report)

    entry = payload["candidates"][0]
    assert entry["source"] is None
    assert entry["source_domain"] is None
    assert entry["published_date"] is None
    assert entry["date_quality"] is None
    assert entry["final_score"] is None
    assert entry["stage_status"] == "raw_found"
