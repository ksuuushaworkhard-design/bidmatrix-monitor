from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError

import pytest

from bidmatrix_monitor import cli, delivery
from bidmatrix_monitor.models import DeliveryConfig, MonitorConfig, OutputSettings, SearchSettings


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return b"{}"


def _config() -> MonitorConfig:
    return MonitorConfig(
        brand_name="BidMatrix",
        brand_description="Adtech",
        search=SearchSettings(),
        outputs=OutputSettings(report_dir="reports"),
        topics=(),
        delivery=DeliveryConfig(enabled=True, channel="telegram", send_daily=True, send_weekly=True),
    )


def _markdown(tmp_path: Path) -> Path:
    path = tmp_path / "bidmatrix-monitor-2026-06-11.md"
    path.write_text("Daily brief skipped: not enough relevant market signals found today.", encoding="utf-8")
    return path


def _marketing_markdown(tmp_path: Path) -> Path:
    path = tmp_path / "marketing-insights-radar-2026-06-11.md"
    path.write_text(
        "\n".join(
            [
                "# Marketing Insights Radar — 2026-06-11",
                "",
                "## Today’s marketing pattern",
                "Competitors are clustering around AI campaign operations and measurement proof.",
                "",
                "## What companies are doing",
                "",
                "1. AppsFlyer is expanding the measurement-proof narrative for growth teams.",
                "",
                "Marketing insight: Measurement companies are trying to own more of the growth conversation.",
                "",
                "What BidMatrix can use: BidMatrix can connect this to transparent ROAS and user quality.",
                "",
                "Content / BD idea: LinkedIn post: why mobile growth teams need performance proof.",
                "",
                "2. DoubleVerify is using fraud or inventory-quality signals to strengthen its verification story.",
                "",
                "Marketing insight: Verification and traffic-quality narratives are becoming a sales argument.",
                "",
                "What BidMatrix can use: BidMatrix can strengthen verified traffic messaging.",
                "",
                "Content / BD idea: Website message: strengthen budget protection language.",
                "",
                "## Watchlist",
                "- AppLovin is worth watching for a clearer AI campaign operations move.",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _generic_ai_marketing_markdown(tmp_path: Path) -> Path:
    path = tmp_path / "marketing-insights-radar-2026-06-11.md"
    path.write_text(
        "\n".join(
            [
                "# Marketing Insights Radar — 2026-06-11",
                "",
                "## Today’s marketing pattern",
                "Competitors are clustering around AI campaign operations and market credibility.",
                "",
                "## What companies are doing",
                "",
                "1. AppFollow is positioning around AI-led campaign operations.",
                "",
                "Marketing insight: AI is being positioned less as a feature and more as an operating layer for planning, testing, and optimizing growth.",
                "",
                "What BidMatrix can use: BidMatrix can frame AI around real UA workflows.",
                "",
                "Content / BD idea: BD talking point: Can your UA setup connect creative performance with budget decisions?",
                "",
                "2. Kochava is positioning around AI-led campaign operations.",
                "",
                "Marketing insight: AI is being positioned less as a feature and more as an operating layer for planning, testing, and optimizing growth.",
                "",
                "What BidMatrix can use: BidMatrix can frame AI around measurement and UA workflows.",
                "",
                "Content / BD idea: LinkedIn post: explain why AI buying needs measurable optimization loops.",
                "",
                "3. Mintegral is positioning around AI-led campaign operations.",
                "",
                "Marketing insight: AI is being positioned less as a feature and more as an operating layer for planning, testing, and optimizing growth.",
                "",
                "What BidMatrix can use: BidMatrix can frame AI around bidding optimization and campaign decisions.",
                "",
                "Content / BD idea: Sales deck note: show how AI campaign operations connect testing and spend control.",
                "",
                "4. Liftoff is using a market-structure move to strengthen its platform positioning.",
                "",
                "Marketing insight: Companies are using market-structure moves to look bigger, more integrated, and harder to replace in the growth stack.",
                "",
                "What BidMatrix can use: BidMatrix can use this for counter-positioning against broad platform claims.",
                "",
                "Content / BD idea: Counter-positioning angle: contrast BidMatrix’s focused growth story with broader platform-consolidation claims.",
                "",
                "## Watchlist",
                "- Adjust is worth watching for a clearer AI campaign operations move.",
                "- AppMetrica is worth watching for a clearer AI campaign operations move.",
                "- Kayzen is worth watching for a clearer market credibility move.",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _marketing_moves_report(tmp_path: Path) -> Path:
    markdown_path = tmp_path / "marketing-insights-radar-2026-06-11.md"
    markdown_path.write_text(
        "\n".join(
            [
                "# Marketing Insights Radar — 2026-06-11",
                "",
                "## Today’s marketing pattern",
                "Competitors are using reports, guides, and partner content to educate growth teams.",
                "",
                "## What companies are doing",
                "",
                "1. AppsFlyer is expanding the measurement-proof narrative for growth teams.",
                "",
                "Marketing insight: Measurement companies are trying to own more of the growth conversation.",
                "",
                "What BidMatrix can use: BidMatrix can connect this to transparent ROAS and user quality.",
                "",
                "Content / BD idea: LinkedIn post: why mobile growth teams need performance proof.",
                "",
                "## Watchlist",
                "- Adjust is worth watching for a clearer AI campaign operations move.",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "marketing-insights-radar-2026-06-11.json").write_text(
        """
{
  "run_date": "2026-06-11",
  "signals": [
    {
      "company": "AppsFlyer",
      "title": "Web-to-App Measurement Guide",
      "url": "https://www.appsflyer.com/resources/guides/web-to-app-measurement/",
      "source_domain": "appsflyer.com",
      "signal_type": "report_benchmark",
      "kept": true,
      "what_changed": "AppsFlyer published a web-to-app measurement guide on its resources hub.",
      "why_it_matters": "They are educating growth teams around full-funnel measurement.",
      "bidmatrix_angle": "BidMatrix can connect traffic quality to full-funnel proof.",
      "possible_use": "LinkedIn post about full-funnel performance proof."
    },
    {
      "company": "DoubleVerify",
      "title": "CTV Fraud Research Report",
      "url": "https://doubleverify.com/reports/ctv-fraud-research/",
      "source_domain": "doubleverify.com",
      "signal_type": "report_benchmark",
      "kept": true,
      "what_changed": "DoubleVerify published fraud and CTV quality research.",
      "why_it_matters": "They are turning risk data into sales enablement content.",
      "bidmatrix_angle": "BidMatrix can strengthen anti-fraud messaging.",
      "possible_use": "Website message about budget protection."
    },
    {
      "company": "Mintegral",
      "title": "Mintegral is positioning around AI-led campaign operations",
      "source_domain": "mintegral.com",
      "signal_type": "positioning_shift",
      "kept": true,
      "what_changed": "Mintegral is positioning around AI-led campaign operations.",
      "why_it_matters": "AI positioning.",
      "bidmatrix_angle": "AI positioning.",
      "possible_use": "AI positioning."
    }
  ],
  "watchlist": [
    {
      "company": "Adjust",
      "title": "Incrementality webinar series",
      "source_domain": "adjust.com",
      "signal_type": "webinar",
      "kept": false,
      "what_changed": "Adjust promoted an incrementality webinar series."
    },
    {
      "company": "Kayzen",
      "title": "DSP infrastructure playbook",
      "source_domain": "kayzen.io",
      "signal_type": "playbook",
      "kept": false,
      "what_changed": "Kayzen shared a DSP infrastructure playbook."
    }
  ]
}
""",
        encoding="utf-8",
    )
    return markdown_path


def _delivery_state(tmp_path: Path) -> Path:
    return tmp_path / "delivery-state.json"


def test_maybe_deliver_report_logs_success(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv("BIDMATRIX_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("BIDMATRIX_DELIVERY_CHANNEL", "telegram")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setattr(delivery, "urlopen", lambda request, timeout=30: _Response())

    delivery.maybe_deliver_report(_config(), _markdown(tmp_path), "daily")

    output = capsys.readouterr().out
    assert "DELIVERY_ATTEMPT report_type=daily channel=telegram" in output
    assert "DELIVERY_SUCCEEDED report_type=daily channel=telegram" in output
    state = _delivery_state(tmp_path).read_text(encoding="utf-8")
    assert '"2026-06-11"' in state
    assert '"status": "sent"' in state


def test_second_daily_run_same_date_skips_telegram(monkeypatch, tmp_path, capsys) -> None:
    calls = {"count": 0}

    def fake_urlopen(request, timeout=30):
        calls["count"] += 1
        return _Response()

    monkeypatch.setenv("BIDMATRIX_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("BIDMATRIX_DELIVERY_CHANNEL", "telegram")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setattr(delivery, "urlopen", fake_urlopen)

    markdown_path = _markdown(tmp_path)
    delivery.maybe_deliver_report(_config(), markdown_path, "daily")
    delivery.maybe_deliver_report(_config(), markdown_path, "daily")

    output = capsys.readouterr().out
    assert calls["count"] == 1
    assert "DAILY_DELIVERY_SKIPPED reason=already_sent_today date=2026-06-11" in output


def test_maybe_deliver_report_retries_once(monkeypatch, tmp_path, capsys) -> None:
    calls = {"count": 0}

    def flaky_urlopen(request, timeout=30):
        calls["count"] += 1
        if calls["count"] == 1:
            raise URLError("temporary failure")
        return _Response()

    monkeypatch.setenv("BIDMATRIX_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("BIDMATRIX_DELIVERY_CHANNEL", "telegram")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setattr(delivery, "urlopen", flaky_urlopen)
    monkeypatch.setattr(delivery.time, "sleep", lambda _: None)

    delivery.maybe_deliver_report(_config(), _markdown(tmp_path), "daily")

    output = capsys.readouterr().out
    assert calls["count"] == 2
    assert "DELIVERY_RETRY channel=telegram attempt=2" in output
    assert "DELIVERY_SUCCEEDED report_type=daily channel=telegram" in output


def test_maybe_deliver_report_raises_delivery_error_after_retry(monkeypatch, tmp_path, capsys) -> None:
    calls = {"count": 0}

    def failing_urlopen(request, timeout=30):
        calls["count"] += 1
        raise URLError("still failing")

    monkeypatch.setenv("BIDMATRIX_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("BIDMATRIX_DELIVERY_CHANNEL", "telegram")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setattr(delivery, "urlopen", failing_urlopen)
    monkeypatch.setattr(delivery.time, "sleep", lambda _: None)

    with pytest.raises(delivery.DeliveryError):
        delivery.maybe_deliver_report(_config(), _markdown(tmp_path), "daily")

    output = capsys.readouterr().out
    assert calls["count"] == 2
    assert "DELIVERY_RETRY channel=telegram attempt=2" in output
    assert "DELIVERY_FAILED report_type=daily channel=telegram" in output
    assert not _delivery_state(tmp_path).exists()


def test_daily_retry_after_failure_is_allowed(monkeypatch, tmp_path, capsys) -> None:
    calls = {"count": 0}

    def flaky_then_ok(request, timeout=30):
        calls["count"] += 1
        if calls["count"] <= 2:
            raise URLError("still failing")
        return _Response()

    monkeypatch.setenv("BIDMATRIX_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("BIDMATRIX_DELIVERY_CHANNEL", "telegram")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setattr(delivery, "urlopen", flaky_then_ok)
    monkeypatch.setattr(delivery.time, "sleep", lambda _: None)

    markdown_path = _markdown(tmp_path)
    with pytest.raises(delivery.DeliveryError):
        delivery.maybe_deliver_report(_config(), markdown_path, "daily")

    delivery.maybe_deliver_report(_config(), markdown_path, "daily")

    output = capsys.readouterr().out
    assert calls["count"] == 3
    assert output.count("DELIVERY_ATTEMPT report_type=daily channel=telegram") == 2
    assert "DELIVERY_SUCCEEDED report_type=daily channel=telegram" in output
    assert '"status": "sent"' in _delivery_state(tmp_path).read_text(encoding="utf-8")


def test_weekly_delivery_is_not_blocked_by_daily_state(monkeypatch, tmp_path, capsys) -> None:
    calls = {"count": 0}

    def fake_urlopen(request, timeout=30):
        calls["count"] += 1
        return _Response()

    monkeypatch.setenv("BIDMATRIX_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("BIDMATRIX_DELIVERY_CHANNEL", "telegram")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setattr(delivery, "urlopen", fake_urlopen)

    daily_path = _markdown(tmp_path)
    weekly_path = tmp_path / "bidmatrix-weekly-digest-2026-06-11.md"
    weekly_path.write_text("Not enough strong weekly signals for a useful recap this week.", encoding="utf-8")

    delivery.maybe_deliver_report(_config(), daily_path, "daily")
    delivery.maybe_deliver_report(_config(), weekly_path, "weekly")

    output = capsys.readouterr().out
    assert calls["count"] == 2
    assert "DAILY_DELIVERY_SKIPPED" not in output


def test_marketing_insights_delivery_sends_as_separate_daily_message(monkeypatch, tmp_path, capsys) -> None:
    calls = {"count": 0}

    def fake_urlopen(request, timeout=30):
        calls["count"] += 1
        return _Response()

    monkeypatch.setenv("BIDMATRIX_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("BIDMATRIX_DELIVERY_CHANNEL", "telegram")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setattr(delivery, "urlopen", fake_urlopen)

    delivery.maybe_deliver_report(_config(), _markdown(tmp_path), "daily")
    delivery.maybe_deliver_marketing_insights_report(_config(), _marketing_markdown(tmp_path))

    output = capsys.readouterr().out
    state = _delivery_state(tmp_path).read_text(encoding="utf-8")
    assert calls["count"] == 2
    assert "DELIVERY_SUCCEEDED report_type=daily channel=telegram" in output
    assert "MARKETING_INSIGHTS_DELIVERY_SUCCEEDED channel=telegram" in output
    assert '"daily"' in state
    assert '"telegram"' in state
    assert '"marketing_insights_radar"' in state


def test_v1_sent_state_does_not_block_marketing_insights_delivery(monkeypatch, tmp_path, capsys) -> None:
    state_path = _delivery_state(tmp_path)
    state_path.write_text(
        '{\n  "daily": {\n    "telegram": {\n      "2026-06-11": {\n        "status": "sent"\n      }\n    }\n  }\n}\n',
        encoding="utf-8",
    )
    calls = {"count": 0}

    def fake_urlopen(request, timeout=30):
        calls["count"] += 1
        return _Response()

    monkeypatch.setenv("BIDMATRIX_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("BIDMATRIX_DELIVERY_CHANNEL", "telegram")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setattr(delivery, "urlopen", fake_urlopen)

    delivery.maybe_deliver_marketing_insights_report(_config(), _marketing_markdown(tmp_path))

    output = capsys.readouterr().out
    assert calls["count"] == 1
    assert "MARKETING_INSIGHTS_DELIVERY_ATTEMPT channel=telegram" in output
    assert "MARKETING_INSIGHTS_DELIVERY_SUCCEEDED channel=telegram" in output


def test_marketing_insights_sent_state_blocks_duplicate_same_day(monkeypatch, tmp_path, capsys) -> None:
    calls = {"count": 0}

    def fake_urlopen(request, timeout=30):
        calls["count"] += 1
        return _Response()

    monkeypatch.setenv("BIDMATRIX_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("BIDMATRIX_DELIVERY_CHANNEL", "telegram")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setattr(delivery, "urlopen", fake_urlopen)

    markdown_path = _marketing_markdown(tmp_path)
    delivery.maybe_deliver_marketing_insights_report(_config(), markdown_path)
    delivery.maybe_deliver_marketing_insights_report(_config(), markdown_path)

    output = capsys.readouterr().out
    assert calls["count"] == 1
    assert "MARKETING_INSIGHTS_DELIVERY_SKIPPED reason=already_sent_today date=2026-06-11" in output


def test_failed_marketing_insights_delivery_does_not_mark_sent(monkeypatch, tmp_path, capsys) -> None:
    def failing_urlopen(request, timeout=30):
        raise URLError("temporary failure")

    monkeypatch.setenv("BIDMATRIX_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("BIDMATRIX_DELIVERY_CHANNEL", "telegram")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setattr(delivery, "urlopen", failing_urlopen)
    monkeypatch.setattr(delivery.time, "sleep", lambda _: None)

    with pytest.raises(delivery.DeliveryError):
        delivery.maybe_deliver_marketing_insights_report(_config(), _marketing_markdown(tmp_path))

    output = capsys.readouterr().out
    assert "MARKETING_INSIGHTS_DELIVERY_FAILED channel=telegram" in output
    assert not _delivery_state(tmp_path).exists()


def test_marketing_insights_telegram_message_is_concise() -> None:
    message = delivery._marketing_insights_telegram_message(
        _marketing_markdown(Path("/tmp")).read_text(encoding="utf-8"),
        date(2026, 6, 11),
    )

    assert "<b>Marketing Insights Radar — 2026-06-11</b>" in message
    assert "<b>Today’s useful marketing moves</b>" in message
    assert "<b>Marketing moves to check</b>" in message
    assert "<b>Company insights</b>" not in message
    assert "1. AppsFlyer — trying to make measurement feel closer to growth decisions and budget proof." in message
    assert "Use for BidMatrix: LinkedIn post —" in message
    assert "<b>Watchlist</b>" in message
    assert len(message) < 1800


def test_marketing_insights_telegram_uses_concrete_marketing_moves_from_json(tmp_path) -> None:
    message = delivery._marketing_insights_telegram_message_from_report(
        _marketing_moves_report(tmp_path),
        date(2026, 6, 11),
    )

    assert "<b>Marketing moves to check</b>" in message
    assert "AppsFlyer — published Web-to-App Measurement Guide." in message
    assert "DoubleVerify — published CTV Fraud Research Report." in message
    assert "Source: appsflyer.com — Web-to-App Measurement Guide" in message
    assert "Source: doubleverify.com — CTV Fraud Research Report" in message
    assert "Mintegral" not in message
    assert "positioning around AI-led campaign operations" not in message


def test_marketing_insights_telegram_use_lines_are_practical(tmp_path) -> None:
    message = delivery._marketing_insights_telegram_message_from_report(
        _marketing_moves_report(tmp_path),
        date(2026, 6, 11),
    )
    use_lines = [line for line in message.splitlines() if line.startswith("Use for BidMatrix:")]

    assert use_lines
    assert any("LinkedIn post" in line for line in use_lines)
    assert any("Sales deck note" in line or "Website message" in line for line in use_lines)
    assert max(use_lines.count(line) for line in set(use_lines)) <= 2


def test_marketing_insights_telegram_watchlist_avoids_placeholder_copy(tmp_path) -> None:
    message = delivery._marketing_insights_telegram_message_from_report(
        _marketing_moves_report(tmp_path),
        date(2026, 6, 11),
    )

    assert "worth watching for a clearer" not in message
    assert "more webinar" not in message
    assert "more playbook" not in message
    assert "more report" not in message
    assert "more article" not in message
    assert "more podcast" not in message
    assert "Adjust — monitor adjust.com for new webinars or measurement resources." in message
    assert "Kayzen — monitor kayzen.io for new playbooks or DSP infrastructure content." in message


def test_cli_daily_logs_delivery_failure_cleanly(monkeypatch, tmp_path, capsys) -> None:
    markdown_path = tmp_path / "bidmatrix-monitor-2026-06-11.md"
    json_path = tmp_path / "bidmatrix-monitor-2026-06-11.json"
    curated_path = tmp_path / "bidmatrix-monitor-2026-06-11-curated.json"
    for path in (markdown_path, json_path, curated_path):
        path.write_text("x", encoding="utf-8")

    fake_config = SimpleNamespace(
        outputs=SimpleNamespace(report_dir=str(tmp_path)),
        delivery=SimpleNamespace(enabled=True, channel="telegram", send_daily=True, send_weekly=True),
    )
    fake_client = SimpleNamespace(print_collection_summary=lambda: None)
    fake_report = SimpleNamespace(diagnostics={})
    audit_path = tmp_path / "bidmatrix-monitor-2026-06-11-audit.json"
    audit_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(cli, "load_config", lambda path: fake_config)
    monkeypatch.setattr(cli, "_build_daily_report", lambda config, debug_exa=False: (fake_report, fake_client))
    monkeypatch.setattr(cli, "write_report", lambda report, report_dir: (markdown_path, json_path, curated_path))
    monkeypatch.setattr(cli, "write_daily_audit_report", lambda report, report_dir: audit_path)

    def fail_delivery(config, markdown_path, report_type):
        raise delivery.DeliveryError("telegram delivery failed for daily report")

    monkeypatch.setattr(cli, "maybe_deliver_report", fail_delivery)
    monkeypatch.setattr("sys.argv", ["bidmatrix-monitor"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 2
    output = capsys.readouterr().out
    assert "RUN_START mode=daily" in output
    assert "REPORTS_WRITTEN mode=daily" in output
    assert "RUN_FINISHED mode=daily status=delivery_failed" in output


def test_cli_daily_still_writes_reports_when_delivery_is_already_sent(monkeypatch, tmp_path, capsys) -> None:
    markdown_path = tmp_path / "bidmatrix-monitor-2026-06-11.md"
    json_path = tmp_path / "bidmatrix-monitor-2026-06-11.json"
    curated_path = tmp_path / "bidmatrix-monitor-2026-06-11-curated.json"
    for path in (markdown_path, json_path, curated_path):
        path.write_text("x", encoding="utf-8")

    fake_config = SimpleNamespace(
        outputs=SimpleNamespace(report_dir=str(tmp_path)),
        delivery=SimpleNamespace(enabled=True, channel="telegram", send_daily=True, send_weekly=True),
    )
    fake_client = SimpleNamespace(print_collection_summary=lambda: None)
    fake_report = SimpleNamespace(diagnostics={})
    audit_path = tmp_path / "bidmatrix-monitor-2026-06-11-audit.json"
    audit_path.write_text("{}", encoding="utf-8")

    state_path = tmp_path / "delivery-state.json"
    state_path.write_text(
        '{\n  "daily": {\n    "telegram": {\n      "2026-06-11": {\n        "status": "sent"\n      }\n    }\n  }\n}\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(cli, "load_config", lambda path: fake_config)
    monkeypatch.setattr(cli, "_build_daily_report", lambda config, debug_exa=False: (fake_report, fake_client))
    monkeypatch.setattr(cli, "write_report", lambda report, report_dir: (markdown_path, json_path, curated_path))
    monkeypatch.setattr(cli, "write_daily_audit_report", lambda report, report_dir: audit_path)
    monkeypatch.setattr(
        cli,
        "build_marketing_insights_radar_preview",
        lambda: (_marketing_markdown(tmp_path), tmp_path / "marketing-insights-radar-2026-06-11.json", {}),
    )
    monkeypatch.setattr(cli, "maybe_deliver_marketing_insights_report", lambda config, markdown_path: None)
    monkeypatch.setenv("BIDMATRIX_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("BIDMATRIX_DELIVERY_CHANNEL", "telegram")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setattr(delivery, "urlopen", lambda request, timeout=30: pytest.fail("urlopen should not be called"))
    monkeypatch.setattr("sys.argv", ["bidmatrix-monitor"])

    cli.main()

    output = capsys.readouterr().out
    assert "REPORTS_WRITTEN mode=daily" in output
    assert "DAILY_DELIVERY_SKIPPED reason=already_sent_today date=2026-06-11" in output
    assert "MARKETING_INSIGHTS_REPORT_WRITTEN" in output


def test_cli_daily_generates_and_delivers_marketing_insights_after_v1(monkeypatch, tmp_path, capsys) -> None:
    markdown_path = tmp_path / "bidmatrix-monitor-2026-06-11.md"
    json_path = tmp_path / "bidmatrix-monitor-2026-06-11.json"
    curated_path = tmp_path / "bidmatrix-monitor-2026-06-11-curated.json"
    for path in (markdown_path, json_path, curated_path):
        path.write_text("x", encoding="utf-8")

    marketing_markdown_path = _marketing_markdown(tmp_path)
    marketing_json_path = tmp_path / "marketing-insights-radar-2026-06-11.json"
    marketing_json_path.write_text("{}", encoding="utf-8")
    calls: list[str] = []

    fake_config = SimpleNamespace(
        outputs=SimpleNamespace(report_dir=str(tmp_path)),
        delivery=SimpleNamespace(enabled=True, channel="telegram", send_daily=True, send_weekly=True),
    )
    fake_client = SimpleNamespace(print_collection_summary=lambda: None)
    fake_report = SimpleNamespace(diagnostics={})
    audit_path = tmp_path / "bidmatrix-monitor-2026-06-11-audit.json"
    audit_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(cli, "load_config", lambda path: fake_config)
    monkeypatch.setattr(cli, "_build_daily_report", lambda config, debug_exa=False: (fake_report, fake_client))
    monkeypatch.setattr(cli, "write_report", lambda report, report_dir: (markdown_path, json_path, curated_path))
    monkeypatch.setattr(cli, "write_daily_audit_report", lambda report, report_dir: audit_path)
    monkeypatch.setattr(cli, "maybe_deliver_report", lambda config, path, report_type: calls.append(f"v1:{report_type}"))
    monkeypatch.setattr(
        cli,
        "build_marketing_insights_radar_preview",
        lambda: (marketing_markdown_path, marketing_json_path, {"companies_with_useful_signals": 2}),
    )
    monkeypatch.setattr(
        cli,
        "maybe_deliver_marketing_insights_report",
        lambda config, path: calls.append(f"marketing:{path.name}"),
    )
    monkeypatch.setattr("sys.argv", ["bidmatrix-monitor"])

    cli.main()

    output = capsys.readouterr().out
    assert calls == ["v1:daily", "marketing:marketing-insights-radar-2026-06-11.md"]
    assert "MARKETING_INSIGHTS_RUN_STARTED" in output
    assert "MARKETING_INSIGHTS_REPORT_WRITTEN" in output
    assert "RUN_FINISHED mode=daily status=success" in output
    assert "RUN_FINISHED mode=daily status=success" in output
