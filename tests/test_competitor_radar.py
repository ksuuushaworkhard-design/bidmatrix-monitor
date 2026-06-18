from __future__ import annotations

import json
from pathlib import Path

from bidmatrix_monitor import cli as cli_module
from bidmatrix_monitor.competitor_radar import (
    build_competitor_radar_preview,
    collect_competitor_radar_payload,
    load_competitor_radar_settings,
    render_competitor_radar_markdown,
    write_competitor_radar_preview,
)


def test_load_competitor_radar_settings_reads_companies(tmp_path: Path) -> None:
    config_path = tmp_path / "competitor_sources.json"
    config_path.write_text(
        json.dumps(
            {
                "lookback_days": 30,
                "max_companies_per_run": 5,
                "num_results_per_company": 3,
                "request_timeout_seconds": 20,
                "companies": ["AppsFlyer", "Adjust"],
            }
        ),
        encoding="utf-8",
    )

    settings = load_competitor_radar_settings(config_path)

    assert settings["companies"] == ["AppsFlyer", "Adjust"]
    assert settings["max_companies_per_run"] == 5


def test_write_competitor_radar_preview_writes_markdown_and_json(tmp_path: Path) -> None:
    payload = {
        "run_date": "2026-06-18",
        "generated_at": "2026-06-18T10:00:00Z",
        "preview_only": True,
        "companies_total": 2,
        "companies_checked": 2,
        "max_companies_per_run": 2,
        "lookback_days": 30,
        "num_results_per_company": 3,
        "exa_total_queries": 2,
        "exa_errors_count": 0,
        "exa_timeouts_count": 0,
        "exa_total_duration_seconds": 1.2,
        "companies_with_useful_signals": 1,
        "companies_skipped": 1,
        "weekly_pattern": "Recent competitor signals cluster around measurement.",
        "signals": [
            {
                "company": "AppsFlyer",
                "title": "AppsFlyer launches new measurement workflow",
                "url": "https://example.com/appsflyer-measurement",
                "published_date": "2026-06-17",
                "source_name": "AppsFlyer",
                "source_domain": "example.com",
                "what_changed": "AppsFlyer launched a new measurement workflow.",
                "why_it_matters": "It reinforces measurement positioning.",
                "bidmatrix_angle": "Useful for attribution messaging.",
                "possible_use": "Content idea on measurement proof.",
                "market_theme": "measurement",
                "signal_type": "product_launch",
                "marketing_value_score": 4,
                "bd_value_score": 3,
                "noise_risk": 1,
                "kept": True,
                "keep_reason": "clear_product_launch_signal",
                "skip_reason": None,
            },
            {
                "company": "Adjust",
                "title": "What latest app changes mean for your growth strategy",
                "url": "https://adjust.com/resources/category/blog/",
                "published_date": "2026-06-10",
                "source_name": "Adjust",
                "source_domain": "adjust.com",
                "what_changed": "Adjust published an analysis.",
                "why_it_matters": "General thought leadership.",
                "bidmatrix_angle": "Generic angle.",
                "possible_use": "Generic use.",
                "market_theme": "growth",
                "signal_type": "unknown",
                "marketing_value_score": 1,
                "bd_value_score": 1,
                "noise_risk": 4,
                "kept": False,
                "keep_reason": None,
                "skip_reason": "high_noise_risk",
            }
        ],
        "errors": [],
    }

    markdown_path, json_path, written = write_competitor_radar_preview(payload, tmp_path)

    assert markdown_path.exists()
    assert json_path.exists()
    assert written["companies_with_useful_signals"] == 1
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "Competitor Marketing Radar - 2026-06-18" in markdown
    assert "Company: AppsFlyer" in markdown
    assert "Company: Adjust" not in markdown
    assert "Possible content/BD use: Content idea on measurement proof." in markdown


def test_collect_competitor_radar_payload_caps_companies(monkeypatch) -> None:
    settings = {
        "lookback_days": 30,
        "max_companies_per_run": 5,
        "num_results_per_company": 3,
        "request_timeout_seconds": 20,
        "companies": ["AppsFlyer", "Adjust", "Singular"],
    }

    monkeypatch.setenv("EXA_API_KEY", "token")

    class _FakeExa:
        def __init__(self, api_key: str, request_timeout_seconds: int) -> None:
            self.calls: list[str] = []

        def search(self, query: str, **kwargs):
            self.calls.append(query)
            if '"AppsFlyer"' in query:
                content = {
                    "company": "AppsFlyer",
                    "has_signal": True,
                    "title": "AppsFlyer launches web performance measurement",
                    "url": "https://www.appsflyer.com/blog/web-performance-measurement/",
                    "published_date": "2026-06-14",
                    "what_changed": "AppsFlyer launched a web measurement product for unified attribution.",
                    "why_it_matters": "It creates a stronger cross-channel measurement story.",
                    "bidmatrix_angle": "Competitors can use this for measurement positioning and sales messaging.",
                    "possible_use": "Content idea on omnichannel measurement proof.",
                    "market_theme": "measurement",
                }
            elif '"Adjust"' in query:
                content = {
                    "company": "Adjust",
                    "has_signal": True,
                    "title": "What latest app changes mean for your growth strategy",
                    "url": "https://www.adjust.com/resources/category/blog/",
                    "published_date": "2026-06-15",
                    "what_changed": "Adjust published an analysis of broad growth strategy themes.",
                    "why_it_matters": "General thought leadership for marketers.",
                    "bidmatrix_angle": "Broad awareness message.",
                    "possible_use": "Generic thought-leadership follow-up.",
                    "market_theme": "growth",
                }
            else:
                content = {
                    "company": "Singular",
                    "has_signal": False,
                }

            class _Response:
                output = type("Output", (), {"content": content})

            return _Response()

    monkeypatch.setattr("bidmatrix_monitor.competitor_radar.TimeoutExa", _FakeExa)

    payload = collect_competitor_radar_payload(settings, max_companies=3)

    assert payload["companies_checked"] == 3
    assert payload["exa_total_queries"] == 3
    assert payload["companies_with_useful_signals"] == 1
    assert payload["companies_skipped"] == 2

    appsflyer = next(item for item in payload["signals"] if item["company"] == "AppsFlyer")
    adjust = next(item for item in payload["signals"] if item["company"] == "Adjust")
    singular = next(item for item in payload["signals"] if item["company"] == "Singular")

    assert appsflyer["kept"] is True
    assert appsflyer["signal_type"] == "product_launch"
    assert appsflyer["keep_reason"] == "clear_product_launch_signal"

    assert adjust["kept"] is False
    assert adjust["skip_reason"] == "high_noise_risk"
    assert adjust["signal_type"] == "unknown"

    assert singular["kept"] is False
    assert singular["skip_reason"] == "no_recent_concrete_signal"

    for item in payload["signals"]:
        assert "kept" in item
        assert "keep_reason" in item
        assert "skip_reason" in item
        assert "signal_type" in item
        assert "marketing_value_score" in item
        assert "bd_value_score" in item
        assert "noise_risk" in item


def test_cli_competitor_radar_preview_does_not_call_delivery(monkeypatch, tmp_path: Path) -> None:
    markdown_path = tmp_path / "competitor-radar-2026-06-18.md"
    json_path = tmp_path / "competitor-radar-2026-06-18.json"
    markdown_path.write_text("preview", encoding="utf-8")
    json_path.write_text("{}", encoding="utf-8")

    def fake_build(config_path, max_companies=None):
        return markdown_path, json_path, {
            "companies_checked": 25,
            "companies_with_useful_signals": 4,
            "exa_total_queries": 25,
            "exa_errors_count": 1,
        }

    def fail_delivery(*args, **kwargs):
        raise AssertionError("maybe_deliver_report should not be called for competitor radar preview")

    monkeypatch.setattr(cli_module, "build_competitor_radar_preview", fake_build)
    monkeypatch.setattr(cli_module, "maybe_deliver_report", fail_delivery)
    monkeypatch.setattr(
        "sys.argv",
        ["bidmatrix-monitor", "--competitor-radar-preview"],
    )

    cli_module.main()


def test_render_competitor_radar_markdown_handles_empty_payload() -> None:
    markdown = render_competitor_radar_markdown(
        {
            "run_date": "2026-06-18",
            "companies_checked": 25,
            "signals": [],
        }
    )

    assert "No useful public competitor signals were found in this preview run." in markdown
    assert "Companies checked: 25" in markdown


def test_render_competitor_radar_markdown_only_renders_kept_signals() -> None:
    markdown = render_competitor_radar_markdown(
        {
            "run_date": "2026-06-18",
            "signals": [
                {
                    "company": "AppsFlyer",
                    "title": "AppsFlyer launches web performance measurement",
                    "url": "https://example.com/appsflyer",
                    "what_changed": "AppsFlyer launched a measurement workflow.",
                    "why_it_matters": "It matters for cross-channel attribution.",
                    "bidmatrix_angle": "Competitive positioning for measurement buyers.",
                    "possible_use": "Content idea.",
                    "kept": True,
                },
                {
                    "company": "Adjust",
                    "title": "What latest app changes mean for your growth strategy",
                    "url": "https://example.com/adjust",
                    "what_changed": "Adjust published an analysis.",
                    "why_it_matters": "General thought leadership.",
                    "bidmatrix_angle": "Generic angle.",
                    "possible_use": "Generic use.",
                    "kept": False,
                    "skip_reason": "high_noise_risk",
                },
            ],
        }
    )

    assert "Company: AppsFlyer" in markdown
    assert "Company: Adjust" not in markdown
