from __future__ import annotations

import json
from pathlib import Path

from bidmatrix_monitor import cli as cli_module
from bidmatrix_monitor.marketing_insights_radar import (
    _apply_subject_gate,
    _dedupe_marketing_signals,
    _watchlist,
    collect_marketing_insights_radar_payload,
    render_marketing_insights_radar_markdown,
    write_marketing_insights_radar_preview,
)


def _signal(**overrides):
    signal = {
        "company": "AppsFlyer",
        "title": "AppsFlyer launches web performance measurement",
        "url": "https://www.appsflyer.com/blog/web-performance-measurement/",
        "source_domain": "appsflyer.com",
        "published_date": "2026-06-18",
        "signal_type": "product_launch",
        "marketing_value_score": 4,
        "bd_value_score": 3,
        "noise_risk": 0,
        "kept": True,
        "keep_reason": "clear_product_launch_signal",
        "skip_reason": None,
        "what_changed": "AppsFlyer launched web and mobile attribution for growth teams.",
        "why_it_matters": "It creates a stronger cross-channel measurement story.",
        "bidmatrix_angle": "Competitors can use this for measurement positioning and sales messaging.",
        "possible_use": "Content idea on omnichannel measurement proof.",
        "market_theme": "measurement",
        "marketing_insight": "Measurement companies are trying to own more of the growth conversation.",
        "bidmatrix_use": "BidMatrix can connect this to transparent ROAS and user quality.",
        "content_bd_idea": "LinkedIn post: “Why mobile growth teams need performance proof beyond last-click attribution.”",
    }
    signal.update(overrides)
    return signal


def test_write_marketing_insights_radar_preview_uses_product_paths(tmp_path: Path) -> None:
    payload = {
        "run_date": "2026-06-18",
        "generated_at": "2026-06-18T10:00:00Z",
        "preview_only": True,
        "companies_checked": 1,
        "companies_with_useful_signals": 1,
        "watchlist_signals_count": 0,
        "exa_total_queries": 1,
        "exa_errors_count": 0,
        "exa_timeouts_count": 0,
        "today_marketing_pattern": "Competitors are clustering around measurement proof.",
        "signals": [_signal()],
        "watchlist": [],
        "errors": [],
    }

    markdown_path, json_path, written = write_marketing_insights_radar_preview(payload, tmp_path)

    assert markdown_path.name == "marketing-insights-radar-2026-06-18.md"
    assert json_path.name == "marketing-insights-radar-2026-06-18.json"
    assert written["preview_only"] is True
    assert "Marketing Insights Radar" in markdown_path.read_text(encoding="utf-8")
    assert json.loads(json_path.read_text(encoding="utf-8"))["signals"][0]["company"] == "AppsFlyer"


def test_marketing_insights_radar_markdown_uses_insight_structure() -> None:
    markdown = render_marketing_insights_radar_markdown(
        {
            "run_date": "2026-06-18",
            "today_marketing_pattern": "Competitors are clustering around measurement proof.",
            "signals": [_signal()],
            "watchlist": [],
        }
    )

    assert "# Marketing Insights Radar — 2026-06-18" in markdown
    assert "## Today’s marketing pattern" in markdown
    assert "## What companies are doing" in markdown
    assert "AppsFlyer is expanding the measurement-proof narrative for growth teams." in markdown
    assert "Marketing insight:" in markdown
    assert "What BidMatrix can use:" in markdown
    assert "Content / BD idea:" in markdown
    assert "Why it matters:" not in markdown
    assert "Possible action:" not in markdown


def test_signals_focus_on_marketing_insights_not_generic_news() -> None:
    markdown = render_marketing_insights_radar_markdown(
        {
            "run_date": "2026-06-18",
            "signals": [
                _signal(
                    company="Pixalate",
                    title="Pixalate publishes CTV fraud benchmark",
                    signal_type="report_benchmark",
                    what_changed="Pixalate published CTV fraud and invalid traffic benchmark data.",
                    market_theme="traffic quality",
                    marketing_insight=None,
                    bidmatrix_use=None,
                    content_bd_idea=None,
                )
            ],
            "watchlist": [],
        }
    )

    assert "Pixalate is using fraud or inventory-quality signals to strengthen its verification story." in markdown
    assert "Marketing insight: Verification and traffic-quality narratives are becoming a sales argument" in markdown
    assert "What BidMatrix can use: BidMatrix can strengthen messaging around verified traffic" in markdown
    assert "Source:" not in markdown


def test_watchlist_is_deduped_and_clean() -> None:
    first = _signal(
        company="AppLovin",
        title="AppLovin continues AXON AI narrative",
        signal_type="unknown",
        kept=False,
        keep_reason=None,
        skip_reason="low_marketing_value",
        marketing_value_score=3,
        bd_value_score=2,
        noise_risk=1,
        what_changed="AppLovin continues to push AXON AI-led growth narratives.",
    )
    duplicate = dict(first, url="https://example.com/applovin-two")
    other = _signal(
        company="BidMachine",
        title="BidMachine explores ML DSP positioning",
        signal_type="unknown",
        kept=False,
        keep_reason=None,
        skip_reason="low_marketing_value",
        marketing_value_score=3,
        bd_value_score=2,
        noise_risk=1,
        what_changed="BidMachine is positioning around ML-powered DSP infrastructure.",
    )

    watchlist = _watchlist([first, duplicate, other])
    markdown = render_marketing_insights_radar_markdown({"run_date": "2026-06-18", "signals": [], "watchlist": watchlist})

    assert len(watchlist) == 2
    assert markdown.count("AppLovin is worth watching") == 1
    assert "BidMachine is worth watching" in markdown


def test_malformed_company_or_title_subjects_are_skipped() -> None:
    signals = [
        _signal(company="Retail media's hidden", title="Retail media's hidden performance report"),
        _signal(company="Ad tech’s next", title="Ad tech’s next chapter is agentic"),
        _signal(company="AppsFlyer", title="AppsFlyer launches measurement proof"),
    ]

    gated = _apply_subject_gate(signals)

    assert gated[0]["kept"] is False
    assert gated[0]["skip_reason"] == "malformed_subject"
    assert gated[1]["kept"] is False
    assert gated[1]["skip_reason"] == "malformed_subject"
    assert gated[2]["kept"] is True


def test_duplicate_company_theme_items_are_not_kept_twice() -> None:
    first = _signal(company="AppsFlyer", title="AppsFlyer launches web measurement")
    second = _signal(
        company="AppsFlyer",
        title="AppsFlyer expands attribution proof",
        url="https://example.com/appsflyer-two",
        what_changed="AppsFlyer expanded web and app measurement proof.",
    )

    deduped = _dedupe_marketing_signals([first, second])

    assert deduped[0]["kept"] is True
    assert deduped[1]["kept"] is False
    assert deduped[1]["skip_reason"] == "duplicate_company_theme"


def test_market_structure_signal_uses_market_structure_copy_not_ai_copy() -> None:
    markdown = render_marketing_insights_radar_markdown(
        {
            "run_date": "2026-06-18",
            "signals": [
                _signal(
                    company="Liftoff",
                    title="Liftoff completes IPO for mobile growth platform",
                    signal_type="funding_mna",
                    what_changed="Liftoff completed its IPO and market structure move for mobile growth.",
                    market_theme="AI media buying",
                    marketing_insight=None,
                    bidmatrix_use=None,
                    content_bd_idea=None,
                )
            ],
            "watchlist": [],
        }
    )

    assert "Liftoff is using a market-structure move to strengthen its platform positioning." in markdown
    assert "Marketing insight: Companies are using market-structure moves" in markdown
    assert "AI is being positioned less as a feature" not in markdown


def test_ai_campaign_operations_signal_uses_ai_copy_not_measurement_copy() -> None:
    markdown = render_marketing_insights_radar_markdown(
        {
            "run_date": "2026-06-18",
            "signals": [
                _signal(
                    company="Mintegral",
                    title="Mintegral positions AI bidding optimization for UA teams",
                    signal_type="positioning_shift",
                    what_changed="Mintegral is positioning AI bidding optimization and campaign management for app growth teams.",
                    market_theme="measurement",
                    marketing_insight=None,
                    bidmatrix_use=None,
                    content_bd_idea=None,
                )
            ],
            "watchlist": [],
        }
    )

    assert "Mintegral is positioning around AI-led campaign operations." in markdown
    assert "Marketing insight: AI is being positioned less as a feature" in markdown
    assert "Measurement companies are trying to own" not in markdown


def test_measurement_signal_uses_measurement_copy() -> None:
    markdown = render_marketing_insights_radar_markdown(
        {
            "run_date": "2026-06-18",
            "signals": [
                _signal(
                    company="AppsFlyer",
                    title="AppsFlyer launches incrementality reporting",
                    signal_type="product_launch",
                    what_changed="AppsFlyer launched incrementality reporting for ROAS and attribution proof.",
                    market_theme="measurement",
                    marketing_insight=None,
                    bidmatrix_use=None,
                    content_bd_idea=None,
                )
            ],
            "watchlist": [],
        }
    )

    assert "AppsFlyer is expanding the measurement-proof narrative for growth teams." in markdown
    assert "Marketing insight: Measurement companies are trying to own more of the growth conversation" in markdown


def test_fraud_verification_signal_uses_traffic_quality_copy() -> None:
    markdown = render_marketing_insights_radar_markdown(
        {
            "run_date": "2026-06-18",
            "signals": [
                _signal(
                    company="DoubleVerify",
                    title="DoubleVerify publishes CTV fraud report",
                    signal_type="report_benchmark",
                    what_changed="DoubleVerify published CTV fraud and invalid traffic verification research.",
                    market_theme="traffic quality",
                    marketing_insight=None,
                    bidmatrix_use=None,
                    content_bd_idea=None,
                )
            ],
            "watchlist": [],
        }
    )

    assert "DoubleVerify is using fraud or inventory-quality signals to strengthen its verification story." in markdown
    assert "Marketing insight: Verification and traffic-quality narratives" in markdown
    assert "What BidMatrix can use: BidMatrix can strengthen messaging around verified traffic" in markdown


def test_repeated_content_bd_ideas_are_varied() -> None:
    signals = [
        _signal(
            company=f"AICompany{i}",
            title=f"AICompany{i} launches AI campaign optimization",
            signal_type="product_launch",
            what_changed=f"AICompany{i} launched AI campaign management and bidding optimization.",
            marketing_insight=None,
            bidmatrix_use=None,
            content_bd_idea=None,
        )
        for i in range(6)
    ]

    markdown = render_marketing_insights_radar_markdown({"run_date": "2026-06-18", "signals": signals, "watchlist": []})
    idea_lines = [line for line in markdown.splitlines() if line.startswith("Content / BD idea:")]

    assert len(idea_lines) == 6
    assert max(idea_lines.count(line) for line in set(idea_lines)) <= 2


def test_collect_marketing_insights_radar_payload_reuses_competitor_collection(monkeypatch) -> None:
    source_payload = {
        "run_date": "2026-06-18",
        "generated_at": "2026-06-18T10:00:00Z",
        "companies_total": 2,
        "companies_checked": 2,
        "max_companies_per_run": 2,
        "lookback_days": 30,
        "exa_total_queries": 2,
        "exa_errors_count": 0,
        "exa_timeouts_count": 0,
        "signals": [
            _signal(),
            _signal(company="Adjust", title="Adjust publishes broad educational guide", kept=False, skip_reason="low_marketing_value"),
        ],
        "errors": [],
    }

    monkeypatch.setattr(
        "bidmatrix_monitor.marketing_insights_radar.collect_competitor_radar_payload",
        lambda settings, max_companies=None: source_payload,
    )

    payload = collect_marketing_insights_radar_payload({"companies": ["AppsFlyer", "Adjust"]}, max_companies=2)

    assert payload["preview_only"] is True
    assert payload["exa_total_queries"] == 2
    assert payload["companies_with_useful_signals"] == 1
    assert payload["signals"][0]["marketing_insight"]
    assert payload["signals"][0]["bidmatrix_use"]
    assert payload["signals"][0]["content_bd_idea"]


def test_cli_marketing_insights_radar_preview_does_not_call_delivery_or_v1(monkeypatch, tmp_path: Path, capsys) -> None:
    markdown_path = tmp_path / "marketing-insights-radar-2026-06-18.md"
    json_path = tmp_path / "marketing-insights-radar-2026-06-18.json"
    markdown_path.write_text("preview", encoding="utf-8")
    json_path.write_text("{}", encoding="utf-8")

    def fake_build(config_path, max_companies=None):
        return markdown_path, json_path, {
            "companies_checked": 25,
            "companies_with_useful_signals": 5,
            "watchlist_signals_count": 2,
            "exa_total_queries": 25,
            "exa_errors_count": 0,
            "exa_timeouts_count": 0,
        }

    def fail_load_config(*args, **kwargs):
        raise AssertionError("load_config should not be called for Marketing Insights Radar preview")

    def fail_delivery(*args, **kwargs):
        raise AssertionError("maybe_deliver_report should not be called for Marketing Insights Radar preview")

    monkeypatch.setattr(cli_module, "build_marketing_insights_radar_preview", fake_build)
    monkeypatch.setattr(cli_module, "load_config", fail_load_config)
    monkeypatch.setattr(cli_module, "maybe_deliver_report", fail_delivery)
    monkeypatch.setattr(
        "sys.argv",
        ["bidmatrix-monitor", "--marketing-insights-radar-preview", "--marketing-insights-radar-max-companies", "25"],
    )

    cli_module.main()

    output = capsys.readouterr().out
    assert f"Wrote {markdown_path}" in output
    assert f"Wrote {json_path}" in output
    assert "MARKETING_INSIGHTS_RADAR_PREVIEW companies_checked=25 kept_signals=5" in output
