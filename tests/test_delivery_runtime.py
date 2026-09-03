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
      "title": "Web-to-App Measurement & ROAS Guide",
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
      "url": "https://www.adjust.com/webinars/incrementality/",
      "source_domain": "adjust.com",
      "signal_type": "webinar",
      "kept": false,
      "what_changed": "Adjust promoted an incrementality webinar series."
    },
    {
      "company": "Kayzen",
      "title": "DSP infrastructure playbook",
      "url": "https://www.kayzen.io/playbooks/dsp-infrastructure/",
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


def _marketing_topic_depth_report(tmp_path: Path) -> Path:
    markdown_path = tmp_path / "marketing-insights-radar-2026-06-11.md"
    markdown_path.write_text(
        "# Marketing Insights Radar — 2026-06-11\n\n## Today’s marketing pattern\nTopic-rich marketing moves.\n",
        encoding="utf-8",
    )
    (tmp_path / "marketing-insights-radar-2026-06-11.json").write_text(
        """
{
  "run_date": "2026-06-11",
  "signals": [
    {
      "company": "AppLovin",
      "title": "AppLovin Ads is now open to all advertisers",
      "url": "https://www.applovin.com/blog/applovin-ads-open-to-all-advertisers/",
      "source_domain": "applovin.com",
      "signal_type": "product_launch",
      "kept": true,
      "what_changed": "AppLovin opened its self-serve advertising platform to all advertisers."
    },
    {
      "company": "Sensor Tower",
      "title": "Sensor Tower Releases State of AI 2026 Report",
      "url": "https://sensortower.com/blog/state-of-ai-2026-report",
      "source_domain": "sensortower.com",
      "signal_type": "report_benchmark",
      "kept": true,
      "what_changed": "Sensor Tower released a State of AI 2026 report."
    },
    {
      "company": "Moloco",
      "title": "Moloco leads major investment round in mobile measurement partner AppsFlyer",
      "url": "https://www.appsflyer.com/company/newsroom/pr/appsflyer-investment-moloco-google-meta-unity/",
      "source_domain": "appsflyer.com",
      "signal_type": "funding_mna",
      "kept": true,
      "what_changed": "Moloco appeared in an AppsFlyer-owned investment announcement."
    },
    {
      "company": "AppsFlyer",
      "title": "Axios State of AI 2026 Report",
      "url": "https://www.axios.com/example-state-of-ai-report",
      "source_domain": "axios.com",
      "signal_type": "report_benchmark",
      "kept": true,
      "what_changed": "AppsFlyer appeared in an unrelated Axios report summary."
    },
    {
      "company": "Jampp",
      "title": "MAU Vegas: CTV as the next performance engine",
      "url": "https://www.jampp.com/blog/mau-vegas-ctv-performance-engine",
      "source_domain": "jampp.com",
      "signal_type": "event_promo",
      "kept": true,
      "what_changed": "Jampp used MAU Vegas content to talk about CTV as a performance channel."
    },
    {
      "company": "Adjust",
      "title": "Adjust Rolls Out New Attribution Tier and AppLovin Integration",
      "url": "https://themedialinks.com/adjust-attribution-tier-applovin-integration/",
      "source_domain": "themedialinks.com",
      "signal_type": "media_placement",
      "kept": true,
      "what_changed": "Adjust appeared in external coverage about attribution tiers and AppLovin integration."
    },
    {
      "company": "Kochava",
      "title": "Ampersand, Fandango, and Kochava Launch Closed-Loop TV Attribution for Movie Ticket Sales",
      "url": "https://martechedge.com/news/ampersand-fandango-kochava-closed-loop-tv-attribution",
      "source_domain": "martechedge.com",
      "signal_type": "partnership",
      "kept": true,
      "what_changed": "Kochava co-announced closed-loop TV attribution with Ampersand and Fandango."
    },
    {
      "company": "data.ai",
      "title": "Sensor Tower State of AI 2026 Report",
      "url": "https://finance.yahoo.com/technology/ai/articles/sensor-tower-state-ai-2026-103000739.html",
      "source_domain": "finance.yahoo.com",
      "signal_type": "report_benchmark",
      "kept": true,
      "what_changed": "data.ai appeared with a Sensor Tower report title."
    },
    {
      "company": "ironSource",
      "title": "Company presentation",
      "url": "https://inderes.se/releases/company-presentation",
      "source_domain": "inderes.se",
      "signal_type": "media_placement",
      "kept": true,
      "what_changed": "ironSource had a vague external listing."
    }
  ],
  "watchlist": [
    {
      "company": "Singular",
      "title": "Market report mention",
      "url": "https://www.providencejournal.com/story/example",
      "source_domain": "providencejournal.com",
      "signal_type": "report_benchmark",
      "kept": false,
      "what_changed": "Singular appeared in an unclear external source."
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
    assert "<b>Today’s marketing takeaway</b>" in message
    assert "<b>Moves worth checking</b>" in message
    assert "<b>Company insights</b>" not in message
    assert "1. AppsFlyer — trying to make measurement feel closer to growth decisions and budget proof." in message
    assert "BidMatrix angle:" in message
    assert "<b>Watchlist</b>" in message
    assert len(message) < 1800


def test_marketing_insights_telegram_uses_concrete_marketing_moves_from_json(tmp_path) -> None:
    message = delivery._marketing_insights_telegram_message_from_report(
        _marketing_moves_report(tmp_path),
        date(2026, 6, 11),
    )

    assert "<b>Moves worth checking</b>" in message
    assert "<b>AppsFlyer</b> — published web-to-app measurement content to make full-funnel performance proof more visible." in message
    assert "<b>DoubleVerify</b> — published fraud or inventory-quality research to turn risk data into a sales argument." in message
    assert 'Source: <a href="https://www.appsflyer.com/resources/guides/web-to-app-measurement/">appsflyer.com — Web-to-App Measurement &amp; ROAS Guide</a>' in message
    assert 'Source: <a href="https://doubleverify.com/reports/ctv-fraud-research/">doubleverify.com — CTV Fraud Research Report</a>' in message
    assert "Mintegral" not in message
    assert "positioning around AI-led campaign operations" not in message


def test_marketing_insights_telegram_uses_strategic_bidmatrix_angles(tmp_path) -> None:
    message = delivery._marketing_insights_telegram_message_from_report(
        _marketing_moves_report(tmp_path),
        date(2026, 6, 11),
    )
    angle_lines = [line for line in message.splitlines() if line.startswith("BidMatrix angle:")]

    assert angle_lines
    assert any("Messaging steal" in line for line in angle_lines)
    assert any("Proof asset" in line for line in angle_lines)
    assert "Ideas for BidMatrix" not in message
    assert "make a LinkedIn post" not in message


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
    assert 'Adjust — monitor <a href="https://www.adjust.com/webinars/incrementality/">adjust.com — Incrementality webinar series</a> for new webinars or measurement resources.' in message
    assert 'Kayzen — monitor <a href="https://www.kayzen.io/playbooks/dsp-infrastructure/">kayzen.io — DSP infrastructure playbook</a> for new playbooks or DSP infrastructure content.' in message


def test_marketing_insights_telegram_interprets_topic_depth_from_titles(tmp_path) -> None:
    message = delivery._marketing_insights_telegram_message_from_report(
        _marketing_topic_depth_report(tmp_path),
        date(2026, 6, 11),
    )

    assert "<b>AppLovin</b> — opened its self-serve ad platform to all advertisers and used access as a market-expansion story." in message
    assert "<b>Sensor Tower</b> — released a State of AI report to own the AI market-data narrative." in message
    assert "<b>Jampp</b> — used CTV content to frame connected TV as the next performance channel." in message
    assert "<b>Adjust</b> — appeared in external coverage about attribution tiers and AppLovin integration." in message
    assert "Moloco" not in message
    assert "Axios State of AI" not in message
    assert "ironSource" not in message
    assert "data.ai" not in message
    assert "used partner content with" not in message
    assert "turned a product or positioning update into a marketing asset" not in message
    assert "published AppLovin" not in message
    assert "promoted an event with a clear growth-market message" not in message


def test_marketing_insights_telegram_does_not_render_old_labels(tmp_path) -> None:
    message = delivery._marketing_insights_telegram_message_from_report(
        _marketing_topic_depth_report(tmp_path),
        date(2026, 6, 11),
    )

    assert "<b>Today’s marketing takeaway</b>" in message
    assert "<b>Moves worth checking</b>" in message
    assert "Hidden play:" in message
    assert "BidMatrix angle:" in message
    assert "<b>Strategic angles for BidMatrix</b>" in message
    assert "Today’s useful marketing moves" not in message
    assert "Marketing moves to check" not in message
    assert "Why it matters:" not in message
    assert "Use for BidMatrix:" not in message


def test_marketing_insights_telegram_hidden_play_and_angle_reference_extracted_topics(tmp_path) -> None:
    message = delivery._marketing_insights_telegram_message_from_report(
        _marketing_topic_depth_report(tmp_path),
        date(2026, 6, 11),
    )

    assert "Hidden play: They are trying to make access feel like momentum and inevitability." in message
    assert "Hidden play: They are making their data feel like market infrastructure, not just a one-off report." in message
    assert "Hidden play: They are moving CTV away from brand awareness and into performance budget conversations." in message
    assert "Hidden play: They are using third-party distribution to make their claims feel less self-promotional." in message
    assert "BidMatrix angle: Counter-narrative — open access is not quality growth" in message
    assert "BidMatrix angle: Proof asset — create a recurring UA Quality Evidence File" in message
    assert "BidMatrix angle: Category gap — own a quality-first CTV angle" in message
    assert "BidMatrix angle: Distribution clue — build a shortlist of proof-led media formats" in message


def test_marketing_insights_telegram_includes_strategic_angles_section(tmp_path) -> None:
    message = delivery._marketing_insights_telegram_message_from_report(
        _marketing_topic_depth_report(tmp_path),
        date(2026, 6, 11),
    )

    assert "<b>Strategic angles for BidMatrix</b>" in message
    assert "Counter-narrative: open access is not quality growth." in message
    assert "Proof asset: package small recurring quality signals" in message
    assert "Category gap: define CTV performance around quality leakage" in message
    assert "Distribution clue: prioritize proof-led media/source formats" in message


def test_marketing_insights_partner_integration_maps_to_partner_wedge() -> None:
    signal = {
        "company": "Kochava",
        "title": "Ampersand, Fandango, and Kochava Launch Closed-Loop TV Attribution for Movie Ticket Sales",
        "source_domain": "martechedge.com",
        "signal_type": "partnership",
        "kept": True,
        "what_changed": "Kochava co-announced closed-loop TV attribution with Ampersand and Fandango.",
    }

    assert "borrowing partner credibility" in delivery._marketing_move_hidden_play(signal)
    assert "Partner wedge" in delivery._marketing_move_bidmatrix_angle(signal)


def test_marketing_insights_telegram_watchlist_uses_links_for_sources(tmp_path) -> None:
    message = delivery._marketing_insights_telegram_message_from_report(
        _marketing_topic_depth_report(tmp_path),
        date(2026, 6, 11),
    )

    assert '<a href="https://www.providencejournal.com/story/example">providencejournal.com — Market report mention</a>' in message


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
