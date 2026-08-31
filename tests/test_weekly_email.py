from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
import re

import pytest

from bidmatrix_monitor import cli as cli_module
from bidmatrix_monitor import weekly_email


def _digest() -> dict:
    return {
        "run_date": "2026-08-14",
        "week_in_one_line": "AI workflows and CTV execution are moving closer to measurable performance marketing.",
        "why_it_matters_for_bidmatrix": [
            "BidMatrix can use this to talk about transparent CTV, verified environments, and performance measurement beyond impressions."
        ],
        "what_actually_happened": [
            {
                "company": "AppLovin",
                "event": "expanded its AI-driven performance advertising platform beyond gaming apps.",
                "why_it_matters": "BidMatrix can frame this as proof that app growth platforms are chasing broader ecommerce budgets.",
                "content_angle": "Gives BidMatrix a concrete angle on independent performance growth versus large platform consolidation.",
                "source": "AdExchanger",
                "url": "https://www.adexchanger.com/the-big-story/applovins-play-to-reach-non-gaming-advertisers/",
            },
            {
                "company": "Tatari",
                "event": "launched a TV measurement integration with AppsFlyer.",
                "why_it_matters": "BidMatrix can connect CTV measurement to transparent performance proof.",
                "content_angle": "BidMatrix can use this to explain why measurable CTV matters for app marketers.",
                "source": "Business of Apps",
                "url": "https://www.businessofapps.com/news/mobile-app-marketers-now-have-a-choice-in-how-they-measure-tv/",
            },
        ],
        "limited_signal_volume": False,
    }


def test_weekly_email_text_is_external_audience_friendly() -> None:
    text = weekly_email.render_weekly_email_text(_digest())

    assert text.startswith("Subject: BidMatrix Weekly Growth Brief")
    assert "This week's market story:" in text
    assert "What this means for marketers:" in text
    assert "Moves worth reading:" in text
    assert "How to use it:" in text
    assert "Ideas to use this week" not in text
    assert "Ideas BidMatrix can use" not in text
    assert "BidMatrix can use this" not in text
    assert "BidMatrix angle:" not in text
    assert "Gives BidMatrix" not in text
    assert "Growth teams can" in text or "Marketers can" in text


def test_weekly_email_html_contains_links_and_external_sections() -> None:
    html = weekly_email.render_weekly_email_html(_digest())

    assert "<h2" in html
    assert "Weekly Growth Brief" in html
    assert ">BidMatrix</p>" in html
    assert "This week&#x27;s focus:" in html
    assert "This week's market story" in html
    assert "For marketers" in html
    assert "Moves worth reading" in html
    assert "Read source: AdExchanger" in html
    assert "font-family:Oswald, Oswaldo" in html
    assert "font-family:Roboto" in html
    assert "border-radius:18px" in html
    assert "background:#000000" in html
    assert "background:#09CAB6" in html
    assert "https://www.adexchanger.com/the-big-story/applovins-play-to-reach-non-gaming-advertisers/" in html
    assert "Ideas to use this week" not in html
    assert "BidMatrix can use this" not in html
    assert "high-signal" not in html


def test_weekly_email_html_uses_only_brand_hex_colors() -> None:
    rendered = weekly_email.render_weekly_email_html(_digest())
    colors = {color.upper() for color in re.findall(r"#[0-9a-fA-F]{6}", rendered)}

    assert colors <= {"#09CAB6", "#000000", "#FFFFFF", "#D9D9D9"}


def test_weekly_email_source_label_removes_signal_quality() -> None:
    rendered = weekly_email.render_weekly_email_html(
        {
            **_digest(),
            "what_actually_happened": [
                {
                    "company": "Adjust",
                    "event": "released a measurement guide.",
                    "source": "adjust.com (high-signal)",
                    "url": "https://www.adjust.com/blog/what-incrementality-reveals-about-marketing-spend/",
                }
            ],
        }
    )

    assert "Read source: adjust.com" in rendered
    assert "high-signal" not in rendered


def test_build_weekly_email_preview_writes_html_text_and_manifest(monkeypatch, tmp_path: Path) -> None:
    source_dir = tmp_path / "source-reports"
    output_dir = tmp_path / "reports"
    source_dir.mkdir()

    seen: dict[str, object] = {}

    def fake_build_weekly_digest(report_dir: Path, days: int) -> dict:
        seen["report_dir"] = report_dir
        seen["days"] = days
        return _digest()

    monkeypatch.setattr(weekly_email, "build_weekly_digest", fake_build_weekly_digest)

    html_path, text_path, manifest_path, digest = weekly_email.build_weekly_email_preview(
        output_dir,
        days=7,
        run_date=date(2026, 8, 14),
        source_report_dir=source_dir,
    )

    assert seen == {"report_dir": source_dir, "days": 7}
    assert html_path == output_dir / "weekly-email-preview-2026-08-14.html"
    assert text_path == output_dir / "weekly-email-preview-2026-08-14.txt"
    assert manifest_path == output_dir / "weekly-email-preview-2026-08-14.json"
    assert html_path.exists()
    assert text_path.exists()
    assert manifest_path.exists()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "needs_review"
    assert manifest["approval_required"] is True
    assert manifest["approved"] is False
    assert manifest["external_send_ready"] is False
    assert manifest["recommended_audience"] == "internal_test"
    assert manifest["run_date"] == "2026-08-14"
    assert manifest["items_count"] == 2
    assert manifest["minimum_external_items"] == 3
    assert manifest["days"] == 7
    assert manifest["preview_files"]["html"] == str(html_path)
    assert manifest["preview_files"]["text"] == str(text_path)
    assert digest["email_preview"] == manifest


def test_weekly_email_preview_cli_does_not_deliver(monkeypatch, tmp_path: Path, capsys) -> None:
    html_path = tmp_path / "weekly-email-preview-2026-08-14.html"
    text_path = tmp_path / "weekly-email-preview-2026-08-14.txt"
    manifest_path = tmp_path / "weekly-email-preview-2026-08-14.json"
    digest = {
        "email_preview": {
            "email_subject": "BidMatrix Weekly Growth Brief: AI",
            "items_count": 3,
            "external_send_ready": True,
            "approval_required": True,
        }
    }

    def fake_preview(report_dir, days=7, source_report_dir=None):
        assert report_dir == tmp_path
        assert days == 7
        assert source_report_dir == "source"
        return html_path, text_path, manifest_path, digest

    def fail_delivery(*args, **kwargs):
        raise AssertionError("weekly email preview must not call delivery")

    monkeypatch.setattr(
        cli_module,
        "load_config",
        lambda path: SimpleNamespace(outputs=SimpleNamespace(report_dir=str(tmp_path))),
    )
    monkeypatch.setattr(cli_module, "build_weekly_email_preview", fake_preview)
    monkeypatch.setattr(cli_module, "maybe_deliver_report", fail_delivery)
    monkeypatch.setattr(cli_module, "maybe_deliver_marketing_insights_report", fail_delivery)
    monkeypatch.setattr(
        "sys.argv",
        ["bidmatrix-monitor", "--weekly-email-preview", "--weekly-email-source-report-dir", "source"],
    )

    cli_module.main()

    output = capsys.readouterr().out
    assert f"Wrote {html_path}" in output
    assert f"Wrote {text_path}" in output
    assert f"Wrote {manifest_path}" in output
    assert "WEEKLY_EMAIL_PREVIEW subject=BidMatrix Weekly Growth Brief: AI" in output


def _preview_files(tmp_path: Path) -> Path:
    html_path = tmp_path / "weekly-email-preview-2026-08-14.html"
    text_path = tmp_path / "weekly-email-preview-2026-08-14.txt"
    manifest_path = tmp_path / "weekly-email-preview-2026-08-14.json"
    html_path.write_text("<p>Hello</p>", encoding="utf-8")
    text_path.write_text("Hello\n", encoding="utf-8")
    manifest_path.write_text(
        json.dumps(
            {
                "email_subject": "BidMatrix Weekly Growth Brief: AI",
                "approval_required": True,
                "approved": False,
                "recommended_audience": "internal_test",
                "preview_files": {"html": str(html_path), "text": str(text_path)},
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def test_weekly_email_test_send_dry_run_uses_manifest_and_env(monkeypatch, tmp_path: Path) -> None:
    manifest_path = _preview_files(tmp_path)
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "RESEND_API_KEY=re_test",
                "WEEKLY_EMAIL_FROM=BidMatrix <weekly@updates.bid-matrix.com>",
                "WEEKLY_EMAIL_TEST_TO=ksenia@bid-matrix.com",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        weekly_email,
        "_send_resend_email",
        lambda payload: pytest.fail("dry-run must not call Resend"),
    )

    result = weekly_email.send_weekly_email_test(manifest_path, dry_run=True, env_path=env_path)

    assert result["mode"] == "dry_run"
    assert result["to"] == "ksenia@bid-matrix.com"
    assert result["recipients"] == ["ksenia@bid-matrix.com"]
    assert result["from"] == "BidMatrix <weekly@updates.bid-matrix.com>"
    assert result["subject"] == "TEST - BidMatrix Weekly Growth Brief: AI"
    assert result["approval_required"] is True
    assert result["approved"] is False


def test_weekly_email_test_send_uses_resend_payload(monkeypatch, tmp_path: Path) -> None:
    manifest_path = _preview_files(tmp_path)
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("WEEKLY_EMAIL_FROM", "BidMatrix <weekly@updates.bid-matrix.com>")
    monkeypatch.setenv(
        "WEEKLY_EMAIL_TEST_TO",
        "ksenia@bid-matrix.com, mark@bid-matrix.com; nastya@bid-matrix.com",
    )
    captured: dict[str, object] = {}

    def fake_send(payload: dict) -> dict:
        captured["payload"] = payload
        return {"id": "email_123"}

    monkeypatch.setattr(weekly_email, "_send_resend_email", fake_send)

    result = weekly_email.send_weekly_email_test(manifest_path)

    assert result["mode"] == "sent"
    assert result["resend_response"] == {"id": "email_123"}
    assert captured["payload"] == {
        "from": "BidMatrix <weekly@updates.bid-matrix.com>",
        "to": ["ksenia@bid-matrix.com", "mark@bid-matrix.com", "nastya@bid-matrix.com"],
        "subject": "TEST - BidMatrix Weekly Growth Brief: AI",
        "html": "<p>Hello</p>",
        "text": "Hello\n",
    }
    assert result["to"] == "ksenia@bid-matrix.com, mark@bid-matrix.com, nastya@bid-matrix.com"


def test_weekly_email_test_run_builds_preview_and_sends(monkeypatch, tmp_path: Path) -> None:
    output_dir = tmp_path / "reports"
    source_dir = tmp_path / "source"
    output_dir.mkdir()
    source_dir.mkdir()
    calls: list[tuple[str, object]] = []

    def fake_preview(report_dir, days=7, source_report_dir=None):
        calls.append(("preview", (report_dir, days, source_report_dir)))
        manifest_path = _preview_files(output_dir)
        return (
            output_dir / "weekly-email-preview-2026-08-14.html",
            output_dir / "weekly-email-preview-2026-08-14.txt",
            manifest_path,
            {"email_preview": {"items_count": 3, "external_send_ready": True}},
        )

    def fake_send(manifest_path, dry_run=False, env_path=None):
        calls.append(("send", (manifest_path, dry_run, env_path)))
        return {
            "mode": "dry_run",
            "to": "ksenia@bid-matrix.com, mark@bid-matrix.com, nastya@bid-matrix.com",
            "recipients": ["ksenia@bid-matrix.com", "mark@bid-matrix.com", "nastya@bid-matrix.com"],
            "from": "BidMatrix <weekly@updates.bid-matrix.com>",
            "subject": "TEST - BidMatrix Weekly Growth Brief: AI",
            "manifest_path": str(manifest_path),
        }

    monkeypatch.setattr(weekly_email, "build_weekly_email_preview", fake_preview)
    monkeypatch.setattr(weekly_email, "send_weekly_email_test", fake_send)

    result = weekly_email.build_and_send_weekly_email_test_run(
        output_dir,
        days=7,
        source_report_dir=source_dir,
        dry_run=True,
        env_path=tmp_path / ".env",
    )

    assert calls[0] == ("preview", (output_dir, 7, source_dir))
    assert calls[1][0] == "send"
    assert result["mode"] == "dry_run"
    assert result["items_count"] == 3
    assert result["external_send_ready"] is True
    assert result["recipients"] == ["ksenia@bid-matrix.com", "mark@bid-matrix.com", "nastya@bid-matrix.com"]


def test_weekly_email_send_test_cli_does_not_load_config_or_deliver(monkeypatch, capsys) -> None:
    def fail_load_config(*args, **kwargs):
        raise AssertionError("weekly email test-send must not load monitor config")

    def fail_delivery(*args, **kwargs):
        raise AssertionError("weekly email test-send must not call Telegram delivery")

    monkeypatch.setattr(cli_module, "load_config", fail_load_config)
    monkeypatch.setattr(cli_module, "maybe_deliver_report", fail_delivery)
    monkeypatch.setattr(cli_module, "maybe_deliver_marketing_insights_report", fail_delivery)
    monkeypatch.setattr(
        cli_module,
        "send_weekly_email_test",
        lambda manifest, dry_run=False, env_path=None: {
            "mode": "dry_run",
            "to": "ksenia@bid-matrix.com",
            "from": "BidMatrix <weekly@updates.bid-matrix.com>",
            "subject": "TEST - BidMatrix Weekly Growth Brief: AI",
            "manifest_path": manifest,
        },
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "bidmatrix-monitor",
            "--weekly-email-send-test",
            "reports/weekly-email-preview-2026-08-14.json",
            "--weekly-email-send-dry-run",
            "--weekly-email-env-file",
            ".env",
        ],
    )

    cli_module.main()

    output = capsys.readouterr().out
    assert "WEEKLY_EMAIL_TEST_SEND mode=dry_run" in output
    assert "to=ksenia@bid-matrix.com" in output


def test_weekly_email_test_run_cli_builds_and_sends_without_v1_delivery(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    calls: list[str] = []

    def fail_delivery(*args, **kwargs):
        raise AssertionError("weekly email test-run must not call Telegram delivery")

    def fake_run(report_dir, days=7, source_report_dir=None, dry_run=False, env_path=None):
        calls.append(f"{report_dir}:{days}:{source_report_dir}:{dry_run}:{env_path}")
        return {
            "mode": "dry_run",
            "to": "ksenia@bid-matrix.com, mark@bid-matrix.com, nastya@bid-matrix.com",
            "from": "BidMatrix <weekly@updates.bid-matrix.com>",
            "subject": "TEST - BidMatrix Weekly Growth Brief",
            "html_path": str(tmp_path / "weekly-email-preview-2026-08-14.html"),
            "text_path": str(tmp_path / "weekly-email-preview-2026-08-14.txt"),
            "manifest_path": str(tmp_path / "weekly-email-preview-2026-08-14.json"),
            "items_count": 3,
            "external_send_ready": True,
        }

    monkeypatch.setattr(
        cli_module,
        "load_config",
        lambda path: SimpleNamespace(outputs=SimpleNamespace(report_dir=str(tmp_path))),
    )
    monkeypatch.setattr(cli_module, "build_and_send_weekly_email_test_run", fake_run)
    monkeypatch.setattr(cli_module, "maybe_deliver_report", fail_delivery)
    monkeypatch.setattr(cli_module, "maybe_deliver_marketing_insights_report", fail_delivery)
    monkeypatch.setattr(
        "sys.argv",
        [
            "bidmatrix-monitor",
            "--weekly-email-test-run",
            "--weekly-email-send-dry-run",
            "--weekly-email-env-file",
            ".env",
            "--weekly-email-source-report-dir",
            "reports",
        ],
    )

    cli_module.main()

    output = capsys.readouterr().out
    assert calls == [f"{tmp_path}:7:reports:True:.env"]
    assert "WEEKLY_EMAIL_TEST_RUN_STARTED" in output
    assert "WEEKLY_EMAIL_TEST_RUN_FINISHED mode=dry_run" in output
    assert "to=ksenia@bid-matrix.com, mark@bid-matrix.com, nastya@bid-matrix.com" in output


def test_weekly_email_test_run_can_refresh_source_report_without_delivery(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    markdown_path = tmp_path / "bidmatrix-monitor-2026-08-31.md"
    json_path = tmp_path / "bidmatrix-monitor-2026-08-31.json"
    curated_path = tmp_path / "bidmatrix-monitor-2026-08-31-curated.json"
    audit_path = tmp_path / "bidmatrix-monitor-2026-08-31-audit.json"
    calls: list[str] = []
    seen: dict[str, object] = {}
    fake_config = SimpleNamespace(
        outputs=SimpleNamespace(report_dir=str(tmp_path)),
        search=SimpleNamespace(max_age_hours=24),
    )
    fake_client = SimpleNamespace(print_collection_summary=lambda: calls.append("print_collection_summary"))
    fake_report = SimpleNamespace(diagnostics={"selected_digest_items_count": 3})

    def fail_delivery(*args, **kwargs):
        raise AssertionError("weekly email source refresh must not call Telegram delivery")

    def fake_run(report_dir, days=7, source_report_dir=None, dry_run=False, env_path=None):
        calls.append("email_test_run")
        return {
            "mode": "dry_run",
            "to": "ksenia@bid-matrix.com",
            "from": "BidMatrix <weekly@updates.bid-matrix.com>",
            "subject": "TEST - BidMatrix Weekly Growth Brief",
            "html_path": str(tmp_path / "weekly-email-preview-2026-08-31.html"),
            "text_path": str(tmp_path / "weekly-email-preview-2026-08-31.txt"),
            "manifest_path": str(tmp_path / "weekly-email-preview-2026-08-31.json"),
            "items_count": 3,
            "external_send_ready": True,
        }

    def fake_build_daily_report(config, debug_exa=False):
        seen["max_age_hours"] = config.search.max_age_hours
        return fake_report, fake_client

    monkeypatch.setattr(cli_module, "load_config", lambda path: fake_config)
    monkeypatch.setattr(cli_module, "_build_daily_report", fake_build_daily_report)
    monkeypatch.setattr(cli_module, "write_report", lambda report, report_dir: (markdown_path, json_path, curated_path))
    monkeypatch.setattr(cli_module, "write_daily_audit_report", lambda report, report_dir: audit_path)
    monkeypatch.setattr(cli_module, "maybe_deliver_report", fail_delivery)
    monkeypatch.setattr(cli_module, "maybe_deliver_marketing_insights_report", fail_delivery)
    monkeypatch.setattr(cli_module, "build_and_send_weekly_email_test_run", fake_run)
    monkeypatch.setattr(
        "sys.argv",
        [
            "bidmatrix-monitor",
            "--weekly-email-test-run",
            "--weekly-email-refresh-source-report",
            "--weekly-email-send-dry-run",
        ],
    )

    cli_module.main()

    output = capsys.readouterr().out
    assert calls == ["print_collection_summary", "email_test_run"]
    assert seen["max_age_hours"] == 168
    assert fake_config.search.max_age_hours == 24
    assert "WEEKLY_EMAIL_SOURCE_REFRESH_STARTED" in output
    assert "lookback_hours=168" in output
    assert "WEEKLY_EMAIL_SOURCE_REFRESH_WRITTEN" in output
    assert "WEEKLY_EMAIL_TEST_RUN_FINISHED mode=dry_run" in output


def test_weekly_email_github_workflow_runs_monday_noon_moscow_without_telegram() -> None:
    workflow = Path(".github/workflows/weekly-email.yml").read_text(encoding="utf-8")

    assert "BidMatrix Weekly Email Beta" in workflow
    assert "cron: '0 9 * * 1'" in workflow
    assert "bidmatrix-monitor --weekly-email-test-run --weekly-email-refresh-source-report" in workflow
    assert "RESEND_API_KEY" in workflow
    assert "WEEKLY_EMAIL_FROM" in workflow
    assert "WEEKLY_EMAIL_TEST_TO" in workflow
    assert "TELEGRAM_BOT_TOKEN" not in workflow
    assert "BIDMATRIX_DELIVERY_CHANNEL" not in workflow
    assert "\n        run: bidmatrix-monitor --weekly\n" not in workflow
