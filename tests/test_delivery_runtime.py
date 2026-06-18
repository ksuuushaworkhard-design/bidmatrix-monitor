from __future__ import annotations

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
    assert "RUN_FINISHED mode=daily status=success" in output
