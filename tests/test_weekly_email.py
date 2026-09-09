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
    assert manifest["minimum_external_items"] == 5
    assert manifest["days"] == 7
    assert manifest["preview_files"]["html"] == str(html_path)
    assert manifest["preview_files"]["text"] == str(text_path)
    assert digest["email_preview"] == manifest


def test_build_weekly_email_preview_uses_requested_run_date_when_digest_has_no_date(
    monkeypatch, tmp_path: Path
) -> None:
    digest_without_date = dict(_digest())
    digest_without_date.pop("run_date")
    monkeypatch.setattr(weekly_email, "build_weekly_digest", lambda report_dir, days: digest_without_date)

    _html_path, text_path, manifest_path, digest = weekly_email.build_weekly_email_preview(
        tmp_path,
        days=7,
        run_date=date(2026, 9, 7),
    )

    assert digest["run_date"] == "2026-09-07"
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["run_date"] == "2026-09-07"
    assert "BidMatrix Weekly Growth Brief - 2026-09-07" in text_path.read_text(encoding="utf-8")


def test_weekly_email_preview_prefers_pipeline_selected_digest_items(monkeypatch, tmp_path: Path) -> None:
    source_dir = tmp_path / "source-reports"
    output_dir = tmp_path / "reports"
    source_dir.mkdir()
    items = [
        {
            "company_or_topic": "AppsFlyer",
            "title": "AppsFlyer released fraud report",
            "url": "https://www.appsflyer.com/resources/reports/state-fraud-marketers/",
            "source_domain": "appsflyer.com",
            "published_date": "2026-08-14",
            "signal_type": "fraud_quality",
            "what_happened": "AppsFlyer released a fraud report for mobile marketers.",
            "why_it_matters_for_bidmatrix": "Supports positioning around traffic quality and verified growth.",
            "content_angle": "Use this to explain why fraud proof matters for app campaigns.",
            "hot_topics": ["fraud", "traffic quality"],
        },
        {
            "company_or_topic": "Moloco",
            "title": "Moloco launched agency partner program",
            "url": "https://digiday.com/media-buying/moloco-launches-an-agency-partner-program/",
            "source_domain": "digiday.com",
            "published_date": "2026-08-13",
            "signal_type": "partnership",
            "what_happened": "Moloco launched an agency partner program to expand beyond mobile programmatic.",
            "why_it_matters_for_bidmatrix": "Shows performance platforms using agencies as a distribution path.",
            "content_angle": "Use this to discuss partner-led growth in performance advertising.",
            "hot_topics": ["partner", "programmatic"],
        },
        {
            "company_or_topic": "AppLovin",
            "title": "AppLovin expands beyond gaming advertisers",
            "url": "https://www.adexchanger.com/the-big-story/applovins-play-to-reach-non-gaming-advertisers/",
            "source_domain": "adexchanger.com",
            "published_date": "2026-08-12",
            "signal_type": "platform_update",
            "what_happened": "AppLovin expanded its AI-driven performance platform beyond gaming advertisers.",
            "why_it_matters_for_bidmatrix": "Shows app-growth platforms chasing broader ecommerce budgets.",
            "content_angle": "Use this to discuss why AI ad buying is moving beyond gaming.",
            "hot_topics": ["AI", "app growth"],
        },
        {
            "company_or_topic": "Tatari",
            "title": "Tatari launched AppsFlyer TV measurement integration",
            "url": "https://www.businessofapps.com/news/mobile-app-marketers-now-have-a-choice-in-how-they-measure-tv/",
            "source_domain": "businessofapps.com",
            "published_date": "2026-08-11",
            "signal_type": "partnership",
            "what_happened": "Tatari launched a TV measurement integration with AppsFlyer.",
            "why_it_matters_for_bidmatrix": "Connects CTV measurement to transparent performance proof.",
            "content_angle": "Use this to explain why measurable CTV matters for app marketers.",
            "hot_topics": ["CTV", "measurement"],
        },
    ]
    source_payload = {
        "run_date": "2026-08-14",
        "daily_digest_items": items,
        "top_news": [
            *items,
            {
                "company_or_topic": "Unity",
                "title": "Unity Studio adds real-time collaboration",
                "url": "https://unity.com/blog/unity-studio-real-time-collaboration",
                "source_domain": "unity.com",
                "published_date": "2026-08-10",
                "signal_type": "platform_update",
                "what_happened": "Unity Studio added real-time collaboration for creative and production teams.",
                "why_it_matters_for_bidmatrix": "Shows app platforms packaging workflow speed as a growth advantage.",
                "content_angle": "Use this to discuss why creative workflows are becoming part of growth infrastructure.",
                "hot_topics": ["creative", "workflow"],
            },
        ],
    }
    (source_dir / "bidmatrix-monitor-2026-08-14-curated.json").write_text(
        json.dumps(source_payload),
        encoding="utf-8",
    )

    def fake_build_weekly_digest(report_dir: Path, days: int) -> dict:
        return {
            **_digest(),
            "what_actually_happened": [
                {
                    "company": "Only One",
                    "event": "Only one item survived the older weekly selector.",
                    "source": "example.com",
                    "url": "https://example.com/one",
                }
            ],
            "limited_signal_volume": True,
            "diagnostics": {"weekly_selected_items_count": 1},
        }

    monkeypatch.setattr(weekly_email, "build_weekly_digest", fake_build_weekly_digest)

    _html_path, text_path, manifest_path, digest = weekly_email.build_weekly_email_preview(
        output_dir,
        days=7,
        run_date=date(2026, 8, 14),
        source_report_dir=source_dir,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    text = text_path.read_text(encoding="utf-8")

    assert manifest["items_count"] == 5
    assert manifest["external_send_ready"] is True
    assert manifest["limited_signal_volume"] is False
    assert digest["diagnostics"]["weekly_email_selection_source"] == "pipeline_selected_items"
    assert digest["diagnostics"]["weekly_email_base_weekly_items_count"] == 1
    assert "AppsFlyer" in text
    assert "Moloco" in text
    assert "AppLovin" in text
    assert "Tatari" in text
    assert "Unity" in text
    assert "Only One" not in text


def test_weekly_email_preview_uses_distinct_companies_for_main_items(monkeypatch, tmp_path: Path) -> None:
    source_dir = tmp_path / "source-reports"
    output_dir = tmp_path / "reports"
    source_dir.mkdir()
    items = [
        {
            "company_or_topic": "Adjust",
            "title": "Adjust published mobile ad fraud report",
            "url": "https://www.adjust.com/blog/mobile-ad-fraud-2026/",
            "source_domain": "adjust.com",
            "what_happened": "Adjust published a mobile ad fraud report.",
            "why_it_matters_for_bidmatrix": "Fraud prevention is being tied to performance protection.",
            "content_angle": "Explain how traffic quality protects media budgets.",
            "hot_topics": ["fraud"],
        },
        {
            "company_or_topic": "Adjust",
            "title": "Adjust added Snapchat attribution support",
            "url": "https://www.adjust.com/blog/snap/",
            "source_domain": "adjust.com",
            "what_happened": "Adjust added Snapchat attribution support.",
            "why_it_matters_for_bidmatrix": "Measurement partners are pushing real-time optimization hooks.",
            "content_angle": "Talk about measurement that changes buying decisions.",
            "hot_topics": ["measurement"],
        },
        {
            "company_or_topic": "Adjust",
            "title": "Adjust released Japan app benchmarks",
            "url": "https://www.adjust.com/blog/topics/app-trends/",
            "source_domain": "adjust.com",
            "what_happened": "Adjust released Japan app benchmarks.",
            "why_it_matters_for_bidmatrix": "Benchmarks are being used as sales enablement.",
            "content_angle": "Use benchmark content to frame market maturity.",
            "hot_topics": ["benchmarking"],
        },
        {
            "company_or_topic": "Innovid",
            "title": "Innovid launched NIVO AI assistant integration",
            "url": "https://www.exchangewire.com/blog/2026/09/09/innovid-expands-nivo-with-meta-ads-mcp-integration/",
            "source_domain": "exchangewire.com",
            "what_happened": "Innovid integrated its NIVO AI assistant with Meta Ads.",
            "why_it_matters_for_bidmatrix": "AI is moving closer to campaign operations.",
            "content_angle": "Discuss AI that improves decisions, not just reporting speed.",
            "hot_topics": ["AI"],
        },
        {
            "company_or_topic": "AppsFlyer and Roku SRN Integration",
            "title": "AppsFlyer and Roku launched SRN integration",
            "url": "https://www.adexchanger.com/tv/appsflyer-and-rokus-new-srn-integration-will-shed-light-on-ctv-campaign-impact/",
            "source_domain": "adexchanger.com",
            "what_happened": "AppsFlyer and Roku launched a CTV campaign measurement integration.",
            "why_it_matters_for_bidmatrix": "CTV is being framed around performance proof.",
            "content_angle": "Explain measurable CTV for app marketers.",
            "hot_topics": ["CTV", "measurement"],
        },
        {
            "company_or_topic": "Moloco",
            "title": "Moloco launched agency partner program",
            "url": "https://digiday.com/media-buying/moloco-launches-an-agency-partner-program/",
            "source_domain": "digiday.com",
            "what_happened": "Moloco launched an agency partner program.",
            "why_it_matters_for_bidmatrix": "Performance platforms are using agencies as distribution.",
            "content_angle": "Talk about partner-led growth.",
            "hot_topics": ["partner"],
        },
        {
            "company_or_topic": "Unity",
            "title": "Unity Studio adds real-time collaboration",
            "url": "https://unity.com/blog/unity-studio-real-time-collaboration",
            "source_domain": "unity.com",
            "what_happened": "Unity Studio added real-time collaboration.",
            "why_it_matters_for_bidmatrix": "Creative workflows are becoming growth infrastructure.",
            "content_angle": "Discuss creative workflow speed.",
            "hot_topics": ["creative"],
        },
    ]
    (source_dir / "bidmatrix-monitor-2026-09-09-curated.json").write_text(
        json.dumps({"daily_digest_items": items}),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        weekly_email,
        "build_weekly_digest",
        lambda report_dir, days: {
            **_digest(),
            "what_actually_happened": [
                {
                    "company": "Only One",
                    "event": "Only one item survived the older weekly selector.",
                    "source": "example.com",
                    "url": "https://example.com/one",
                }
            ],
            "limited_signal_volume": True,
            "diagnostics": {"weekly_selected_items_count": 1},
        },
    )

    _html_path, text_path, manifest_path, digest = weekly_email.build_weekly_email_preview(
        output_dir,
        days=7,
        run_date=date(2026, 9, 9),
        source_report_dir=source_dir,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    companies = [item["company"] for item in manifest["selected_items"]]
    text = text_path.read_text(encoding="utf-8")

    assert manifest["items_count"] == 5
    assert len({weekly_email._company_dedupe_key(company) for company in companies}) == 5
    assert companies.count("Adjust") == 1
    assert "This week's clearest moves came from Adjust, Innovid, and AppsFlyer and Roku SRN Integration." in text
    assert digest["diagnostics"]["weekly_email_selected_items_count"] == 5


def test_weekly_email_preview_uses_telegram_pipeline_items_not_background_fillers(
    monkeypatch, tmp_path: Path
) -> None:
    source_dir = tmp_path / "source-reports"
    output_dir = tmp_path / "reports"
    source_dir.mkdir()
    source_payload = {
        "daily_digest_items": [
            {
                "company_or_topic": "Adjust",
                "title": "Adjust published mobile ad fraud report",
                "url": "https://www.adjust.com/blog/mobile-ad-fraud-2026/",
                "source_domain": "adjust.com",
                "what_happened": "Adjust published a mobile ad fraud report.",
                "why_it_matters_for_bidmatrix": "Fraud prevention is being tied to performance protection.",
                "content_angle": "Explain how traffic quality protects media budgets.",
            },
            {
                "company_or_topic": "Innovid",
                "title": "Innovid launched NIVO AI assistant integration",
                "url": "https://www.exchangewire.com/blog/2026/09/09/innovid-expands-nivo-with-meta-ads-mcp-integration/",
                "source_domain": "exchangewire.com",
                "what_happened": "Innovid integrated its NIVO AI assistant with Meta Ads.",
                "why_it_matters_for_bidmatrix": "AI is moving closer to campaign operations.",
                "content_angle": "Discuss AI that improves decisions, not just reporting speed.",
            },
        ],
        "background_items": [
            {
                "company_or_topic": "Old Context One",
                "title": "Old context one",
                "url": "https://example.com/old-one",
                "source_domain": "example.com",
                "what_happened": "Old context should not become a weekly email main item.",
            },
            {
                "company_or_topic": "Old Context Two",
                "title": "Old context two",
                "url": "https://example.com/old-two",
                "source_domain": "example.com",
                "what_happened": "Old context should not become a weekly email main item.",
            },
            {
                "company_or_topic": "Old Context Three",
                "title": "Old context three",
                "url": "https://example.com/old-three",
                "source_domain": "example.com",
                "what_happened": "Old context should not become a weekly email main item.",
            },
        ],
    }
    (source_dir / "bidmatrix-monitor-2026-09-09-curated.json").write_text(
        json.dumps(source_payload),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        weekly_email,
        "build_weekly_digest",
        lambda report_dir, days: {
            **_digest(),
            "what_actually_happened": [
                {"company": "Legacy One", "event": "legacy item", "source": "legacy.com"},
                {"company": "Legacy Two", "event": "legacy item", "source": "legacy.com"},
                {"company": "Legacy Three", "event": "legacy item", "source": "legacy.com"},
                {"company": "Legacy Four", "event": "legacy item", "source": "legacy.com"},
                {"company": "Legacy Five", "event": "legacy item", "source": "legacy.com"},
            ],
            "limited_signal_volume": False,
        },
    )

    _html_path, text_path, manifest_path, digest = weekly_email.build_weekly_email_preview(
        output_dir,
        days=7,
        run_date=date(2026, 9, 9),
        source_report_dir=source_dir,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    text = text_path.read_text(encoding="utf-8")

    assert manifest["items_count"] == 2
    assert manifest["external_send_ready"] is False
    assert manifest["limited_signal_volume"] is True
    assert digest["diagnostics"]["weekly_email_selection_source"] == "pipeline_selected_items"
    assert "Adjust" in text
    assert "Innovid" in text
    assert "Old Context" not in text
    assert "Legacy One" not in text


def test_weekly_email_manifest_counts_distinct_companies_only(monkeypatch, tmp_path: Path) -> None:
    digest = {
        **_digest(),
        "what_actually_happened": [
            {
                "company": "Adjust",
                "event": "published a fraud report.",
                "source": "adjust.com",
                "url": "https://www.adjust.com/fraud",
            },
            {
                "company": "Adjust",
                "event": "added Snapchat attribution support.",
                "source": "adjust.com",
                "url": "https://www.adjust.com/snap",
            },
            {
                "company": "AppsFlyer",
                "event": "released fraud controls.",
                "source": "appsflyer.com",
                "url": "https://www.appsflyer.com/fraud",
            },
        ],
    }
    monkeypatch.setattr(weekly_email, "build_weekly_digest", lambda report_dir, days: digest)

    _html_path, text_path, manifest_path, _digest_result = weekly_email.build_weekly_email_preview(
        tmp_path,
        run_date=date(2026, 9, 9),
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    text = text_path.read_text(encoding="utf-8")

    assert manifest["items_count"] == 2
    assert manifest["external_send_ready"] is False
    assert text.count("Adjust -") == 1
    assert "Adjust, Adjust" not in text


def test_weekly_email_recovers_company_from_generic_topic_subject() -> None:
    item = {
        "company_or_topic": "AI Creative Automation",
        "mentioned_companies": ["OpenAI", "AppLovin"],
        "title": "OpenAI and AppLovin expand AI creative automation suites",
    }

    assert weekly_email._company_from_pipeline_item(item) == "OpenAI"


def test_weekly_email_preview_cli_does_not_deliver(monkeypatch, tmp_path: Path, capsys) -> None:
    html_path = tmp_path / "weekly-email-preview-2026-08-14.html"
    text_path = tmp_path / "weekly-email-preview-2026-08-14.txt"
    manifest_path = tmp_path / "weekly-email-preview-2026-08-14.json"
    digest = {
        "email_preview": {
            "email_subject": "BidMatrix Weekly Growth Brief: AI",
            "items_count": 5,
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


def _preview_files(tmp_path: Path, manifest_overrides: dict | None = None) -> Path:
    html_path = tmp_path / "weekly-email-preview-2026-08-14.html"
    text_path = tmp_path / "weekly-email-preview-2026-08-14.txt"
    manifest_path = tmp_path / "weekly-email-preview-2026-08-14.json"
    manifest = {
        "email_subject": "BidMatrix Weekly Growth Brief: AI",
        "approval_required": True,
        "approved": False,
        "recommended_audience": "internal_test",
        "preview_files": {"html": str(html_path), "text": str(text_path)},
    }
    if manifest_overrides:
        manifest.update(manifest_overrides)
    html_path.write_text("<p>Hello</p>", encoding="utf-8")
    text_path.write_text("Hello\n", encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
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
    manifest_path = _preview_files(
        tmp_path,
        {
            "items_count": 5,
            "minimum_external_items": 5,
            "limited_signal_volume": False,
            "external_send_ready": True,
        },
    )
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


def test_weekly_email_test_send_skips_when_items_are_below_external_minimum(monkeypatch, tmp_path: Path) -> None:
    manifest_path = _preview_files(
        tmp_path,
        {
            "items_count": 1,
            "minimum_external_items": 5,
            "limited_signal_volume": True,
            "external_send_ready": False,
        },
    )

    monkeypatch.setattr(
        weekly_email,
        "_send_resend_email",
        lambda payload: pytest.fail("thin weekly email must not call Resend"),
    )
    monkeypatch.delenv("WEEKLY_EMAIL_TEST_TO", raising=False)
    monkeypatch.delenv("WEEKLY_EMAIL_FROM", raising=False)

    result = weekly_email.send_weekly_email_test(manifest_path, env_path=tmp_path / "missing.env")

    assert result["mode"] == "skipped"
    assert result["skip_reason"] == "insufficient_items:1_of_5"
    assert result["items_count"] == 1
    assert result["minimum_external_items"] == 5
    assert result["external_send_ready"] is False
    assert result["recipients"] == []


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
            {"email_preview": {"items_count": 5, "external_send_ready": True}},
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
    assert result["items_count"] == 5
    assert result["external_send_ready"] is True
    assert result["recipients"] == ["ksenia@bid-matrix.com", "mark@bid-matrix.com", "nastya@bid-matrix.com"]


def test_weekly_email_test_run_skips_thin_preview_without_resend(monkeypatch, tmp_path: Path) -> None:
    output_dir = tmp_path / "reports"
    output_dir.mkdir()
    manifest_path = _preview_files(
        output_dir,
        {
            "items_count": 1,
            "minimum_external_items": 5,
            "limited_signal_volume": True,
            "external_send_ready": False,
        },
    )

    def fake_preview(report_dir, days=7, source_report_dir=None):
        return (
            output_dir / "weekly-email-preview-2026-08-14.html",
            output_dir / "weekly-email-preview-2026-08-14.txt",
            manifest_path,
            {"email_preview": {"items_count": 1, "external_send_ready": False}},
        )

    monkeypatch.setattr(weekly_email, "build_weekly_email_preview", fake_preview)
    monkeypatch.setattr(
        weekly_email,
        "_send_resend_email",
        lambda payload: pytest.fail("thin weekly email test-run must not call Resend"),
    )

    result = weekly_email.build_and_send_weekly_email_test_run(output_dir)

    assert result["mode"] == "skipped"
    assert result["skip_reason"] == "insufficient_items:1_of_5"
    assert result["items_count"] == 1
    assert result["external_send_ready"] is False


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
            "items_count": 5,
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
    fake_report = SimpleNamespace(diagnostics={"selected_digest_items_count": 5})

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
            "items_count": 5,
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
    assert seen["max_age_hours"] == 336
    assert fake_config.search.max_age_hours == 24
    assert "WEEKLY_EMAIL_SOURCE_REFRESH_STARTED" in output
    assert "lookback_hours=336" in output
    assert "WEEKLY_EMAIL_SOURCE_REFRESH_WRITTEN" in output
    assert "WEEKLY_EMAIL_TEST_RUN_FINISHED mode=dry_run" in output


def test_weekly_email_source_config_uses_wider_search_without_mutating_daily_config() -> None:
    config = SimpleNamespace(
        search=SimpleNamespace(
            max_age_hours=24,
            num_results_per_topic=8,
            max_total_results_per_topic=10,
            max_total_results_per_layer=24,
            max_strategic_background_queries=3,
            max_market_watch_queries=7,
            max_results_per_market_watch_query=5,
            max_total_results_per_market_watch=18,
            daily_total_budget_seconds=240,
        ),
        outputs=SimpleNamespace(daily_digest_target=4),
    )

    weekly_config = cli_module._weekly_email_source_config(config, days=7)

    assert weekly_config.search.max_age_hours == 336
    assert weekly_config.search.num_results_per_topic == 10
    assert weekly_config.search.max_total_results_per_topic == 14
    assert weekly_config.search.max_total_results_per_layer == 60
    assert weekly_config.search.max_strategic_background_queries == 5
    assert weekly_config.search.max_market_watch_queries == 7
    assert weekly_config.search.max_results_per_market_watch_query == 7
    assert weekly_config.search.max_total_results_per_market_watch == 35
    assert weekly_config.search.daily_total_budget_seconds == 420
    assert weekly_config.outputs.daily_digest_target == 5
    assert config.search.max_age_hours == 24
    assert config.search.num_results_per_topic == 8
    assert config.outputs.daily_digest_target == 4


def test_weekly_email_source_refresh_expands_market_watch_when_digest_is_thin(monkeypatch) -> None:
    base_item = {"title": "One fresh source", "url": "https://example.com/one"}
    extra_items = [
        {"title": "Second weekly source", "url": "https://example.com/two"},
        {"title": "Third weekly source", "url": "https://example.com/three"},
        {"title": "Fourth weekly source", "url": "https://example.com/four"},
        {"title": "Fifth weekly source", "url": "https://example.com/five"},
    ]
    report = SimpleNamespace(
        diagnostics={"selected_digest_items_count": 1},
        raw_items=[base_item],
        items=[],
        exa_errors=[],
    )
    client_calls: list[str] = []

    class FakeClient:
        def should_run_market_watch_recent(self):
            client_calls.append("should_run_market_watch_recent")
            return True

        def search_market_watch_recent(self):
            client_calls.append("search_market_watch_recent")
            return extra_items

        def pop_errors(self):
            return []

        def collection_stats(self):
            return {"exa_total_queries": 7}

    def fake_build_report(items, config, exa_errors=None, exa_meta=None):
        assert items == [base_item, *extra_items]
        assert exa_errors == []
        assert exa_meta == {"exa_total_queries": 7}
        return SimpleNamespace(diagnostics={"selected_digest_items_count": 5}, raw_items=items, items=items, exa_errors=[])

    monkeypatch.setattr(cli_module, "build_report", fake_build_report)

    expanded = cli_module._expand_weekly_email_source_report_if_needed(report, FakeClient(), SimpleNamespace())

    assert client_calls == ["should_run_market_watch_recent", "search_market_watch_recent"]
    assert expanded.diagnostics["selected_digest_items_count"] == 5


def test_weekly_email_source_refresh_does_not_expand_when_digest_has_enough_items(monkeypatch) -> None:
    report = SimpleNamespace(
        diagnostics={"selected_digest_items_count": 5},
        raw_items=[],
        items=[],
        exa_errors=[],
    )

    class FakeClient:
        def should_run_market_watch_recent(self):
            raise AssertionError("market watch should not run when weekly email already has enough items")

    assert cli_module._expand_weekly_email_source_report_if_needed(report, FakeClient(), SimpleNamespace()) is report


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
