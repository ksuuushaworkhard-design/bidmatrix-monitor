from __future__ import annotations

import json
from pathlib import Path

from bidmatrix_monitor import cli as cli_module
from bidmatrix_monitor.market_brief_v2 import (
    collect_market_brief_v2_payload,
    _dedupe_related_signals,
    _evaluate_signal,
    _executive_summary,
    render_market_brief_v2_markdown,
    write_market_brief_v2_preview,
)


def _signal(**overrides):
    signal = {
        "title": "AppsFlyer launches incrementality measurement workflow",
        "url": "https://www.appsflyer.com/blog/incrementality-measurement/",
        "source": "AppsFlyer",
        "source_domain": "appsflyer.com",
        "published_date": "2026-06-18",
        "signal_type": "product_launch",
        "category": "Measurement / MMP / Attribution",
        "what_happened": "AppsFlyer launched a new mobile incrementality workflow for advertisers.",
        "why_it_matters": "Measurement buyers need clearer proof of campaign lift and budget impact.",
        "bidmatrix_angle": "BidMatrix can use this as a timely angle on neutral incrementality proof for app advertisers.",
        "suggested_action": "Create a BD talking point about moving beyond last-click attribution.",
        "confidence": "high",
        "query_id": "measurement_mmp",
        "query_label": "Measurement / MMP / Attribution",
        "relevance_score": 5,
        "marketing_value_score": 3,
        "bd_value_score": 3,
        "keep_reason": "clear_product_or_platform_move",
        "skip_reason": None,
        "kept": True,
        "watchlist": False,
        "noise_risk": 0,
    }
    signal.update(overrides)
    return signal


def test_write_market_brief_v2_preview_writes_markdown_json_and_audit(tmp_path: Path) -> None:
    payload = {
        "run_date": "2026-06-18",
        "generated_at": "2026-06-18T10:00:00Z",
        "preview_only": True,
        "max_exa_queries": 20,
        "exa_total_queries": 2,
        "exa_errors_count": 0,
        "exa_timeouts_count": 0,
        "exa_total_duration_seconds": 1.0,
        "raw_results_count": 2,
        "unique_results_count": 2,
        "kept_signals_count": 1,
        "skipped_signals_count": 1,
        "watchlist_signals_count": 0,
        "executive_summary": ["Measurement signals are getting more sales-ready."],
        "top_signals": [_signal()],
        "sections": {
            "Competitor / Partner Moves": [],
            "Measurement / MMP / Attribution": [_signal()],
            "Traffic Quality / Fraud / Inventory": [],
            "AI / Automation / Agentic UA": [],
        },
        "recommended_actions": ["BD talking point: use incrementality as a buyer proof angle."],
        "watchlist": [],
        "audit": [_signal(source=None), _signal(title="Generic guide", kept=False, skip_reason="high_noise_risk")],
        "errors": [],
    }

    markdown_path, json_path, audit_path, written = write_market_brief_v2_preview(payload, tmp_path)

    assert markdown_path.exists()
    assert json_path.exists()
    assert audit_path.exists()
    assert written["preview_only"] is True
    assert "Market Brief v2 - 2026-06-18" in markdown_path.read_text(encoding="utf-8")
    assert "## 7. Recommended Actions for BidMatrix" in markdown_path.read_text(encoding="utf-8")

    public_payload = json.loads(json_path.read_text(encoding="utf-8"))
    audit_payload = json.loads(audit_path.read_text(encoding="utf-8"))
    assert "audit" not in public_payload
    assert audit_payload["exa_total_queries"] == 2
    assert audit_payload["candidates"][0]["source"] is None
    assert audit_payload["candidates"][1]["skip_reason"] == "high_noise_risk"


def test_collect_market_brief_v2_payload_caps_queries_and_quality_gate(monkeypatch) -> None:
    monkeypatch.setenv("EXA_API_KEY", "token")
    calls: list[str] = []

    class _FakeExa:
        def __init__(self, api_key: str, request_timeout_seconds: int) -> None:
            self.api_key = api_key
            self.request_timeout_seconds = request_timeout_seconds

        def search(self, query: str, **kwargs):
            calls.append(query)
            if len(calls) == 1:
                signals = [
                    {
                        "title": "AppsFlyer launches incrementality measurement workflow",
                        "url": "https://www.appsflyer.com/blog/incrementality-measurement/",
                        "source": "AppsFlyer",
                        "published_date": "2026-06-18",
                        "signal_type": "product_launch",
                        "category": "Measurement / MMP / Attribution",
                        "what_happened": "AppsFlyer launched a mobile incrementality workflow for advertisers.",
                        "why_it_matters": "Advertisers need proof of lift and budget impact.",
                        "bidmatrix_angle": "BidMatrix can use this for marketing and BD conversations about incrementality.",
                        "suggested_action": "Create a sales talking point about measurement proof.",
                        "confidence": "high",
                    },
                    {
                        "title": "How to improve your app marketing strategy",
                        "url": "https://example.com/resources/app-marketing-guide/",
                        "source": "Example",
                        "published_date": "2026-06-17",
                        "signal_type": "other",
                        "category": "Competitor / Partner Moves",
                        "what_happened": "A generic evergreen guide was published.",
                        "why_it_matters": "General education for marketers.",
                        "confidence": "medium",
                    },
                ]
            else:
                signals = [
                    {
                        "title": "HUMAN publishes CTV fraud benchmark",
                        "url": "https://www.humansecurity.com/resources/ctv-fraud-benchmark/",
                        "source": "HUMAN",
                        "published_date": "2026-06-18",
                        "signal_type": "market_report",
                        "category": "Traffic Quality / Fraud / Inventory",
                        "what_happened": "HUMAN published CTV fraud and invalid traffic benchmark data.",
                        "why_it_matters": "CTV buyers need cleaner inventory quality proof.",
                        "bidmatrix_angle": "BidMatrix can frame CTV quality as part of performance media buying.",
                        "suggested_action": "Prepare a BD talking point about fraud-aware CTV optimization.",
                        "confidence": "medium",
                    }
                ]

            class _Response:
                output = type("Output", (), {"content": {"signals": signals}})

            return _Response()

    monkeypatch.setattr("bidmatrix_monitor.market_brief_v2.TimeoutExa", _FakeExa)

    payload = collect_market_brief_v2_payload(max_queries=2)

    assert len(calls) == 2
    assert payload["exa_total_queries"] == 2
    assert payload["raw_results_count"] == 3
    assert payload["kept_signals_count"] == 2
    assert payload["skipped_signals_count"] == 1
    assert payload["watchlist_signals_count"] == 0
    assert [item["title"] for item in payload["top_signals"]] == [
        "AppsFlyer launches incrementality measurement workflow",
        "HUMAN publishes CTV fraud benchmark",
    ]
    skipped = next(item for item in payload["audit"] if item["title"] == "How to improve your app marketing strategy")
    assert skipped["kept"] is False
    assert skipped["skip_reason"] in {"high_noise_risk", "low_marketing_bd_value", "weak_or_generic_signal"}


def test_render_market_brief_v2_markdown_keeps_requested_structure() -> None:
    markdown = render_market_brief_v2_markdown(
        {
            "run_date": "2026-06-18",
            "executive_summary": ["Measurement and traffic quality are the strongest themes."],
            "top_signals": [_signal()],
            "sections": {
                "Competitor / Partner Moves": [],
                "Measurement / MMP / Attribution": [_signal()],
                "Traffic Quality / Fraud / Inventory": [],
                "AI / Automation / Agentic UA": [],
            },
            "recommended_actions": ["LinkedIn post idea: compare last-click and incrementality proof."],
            "watchlist": [],
        }
    )

    assert "## 1. Executive Summary" in markdown
    assert "## 2. Top Signals" in markdown
    assert "## Competitor / Partner Moves" in markdown
    assert "## Measurement / MMP / Attribution" in markdown
    assert "## Traffic Quality / Fraud / Inventory" in markdown
    assert "## AI / Automation / Agentic UA" in markdown
    assert "## 7. Recommended Actions for BidMatrix" in markdown
    assert "## 8. Watchlist" in markdown
    assert "- Suggested content/BD action:" in markdown


def test_market_brief_v2_rejects_invalid_or_self_referential_sources() -> None:
    invalid = _evaluate_signal(
        {
            "title": "BidMatrix Market Brief v2 internal synthesis",
            "url": "N/A (Internal Strategic Document)",
            "source": None,
            "source_domain": None,
            "published_date": "2026-06-19",
            "signal_type": "strategic_infrastructure_shift",
            "category": "AI / Automation / Agentic UA",
            "what_happened": "Several adtech platforms launched agentic advertising products.",
            "why_it_matters": "AI media buying and CTV fraud create positioning pressure for mobile adtech.",
            "bidmatrix_angle": "BidMatrix can frame this as a strategic agentic operations shift.",
            "suggested_action": "1.",
            "confidence": "high",
        }
    )
    self_referential = _evaluate_signal(
        {
            "title": "Market Brief v2: Agentic Shifts",
            "url": "https://www.bidmatrix.com/market-briefs/june-2026",
            "source": None,
            "source_domain": "bidmatrix.com",
            "published_date": "2026-06-19",
            "signal_type": "market_report",
            "category": "Traffic Quality / Fraud / Inventory",
            "what_happened": "A synthesized market brief mentions AI-powered fraud.",
            "why_it_matters": "CTV inventory quality is under pressure.",
            "bidmatrix_angle": "BidMatrix can use the signal for fraud-aware positioning.",
            "suggested_action": "Create a BD note about CTV transparency.",
            "confidence": "high",
        }
    )

    assert invalid["kept"] is False
    assert invalid["watchlist"] is False
    assert invalid["skip_reason"] == "invalid_or_self_referential_source"
    assert invalid["suggested_action"] != "1."

    assert self_referential["kept"] is False
    assert self_referential["skip_reason"] == "invalid_or_self_referential_source"


def test_market_brief_v2_rejects_synthetic_brief_artifacts() -> None:
    malformed_bidmatrix_url = _evaluate_signal(
        {
            "title": "BidMatrix Strategic Market Brief: The Rise of Agentic AdTech",
            "url": "https://www.bidmatrix.ai (Assumed Corporate Site)",
            "source": None,
            "source_domain": "bidmatrix.ai (assumed corporate site)",
            "published_date": "2026-06-19",
            "signal_type": "market_report",
            "category": "AI / Automation / Agentic UA",
            "what_happened": "A synthesized brief references agentic buying launches.",
            "why_it_matters": "Mobile adtech teams need to understand AI buying shifts.",
            "bidmatrix_angle": "BidMatrix can use this for positioning.",
            "suggested_action": "Create a sales note about agentic ad operations.",
            "confidence": "high",
        }
    )
    synthetic_valid_url = _evaluate_signal(
        {
            "title": "Market Brief v2: Agentic-Era Fraud & CTV Measurement Maturity",
            "url": "https://www.doubleverify.com/lp/report/ctv/verify/2026-dv-global-insights-streaming-tv",
            "source": None,
            "source_domain": "doubleverify.com",
            "published_date": "2026-06-19",
            "signal_type": "market_report",
            "category": "Traffic Quality / Fraud / Inventory",
            "what_happened": "DoubleVerify published CTV measurement and fraud benchmarks.",
            "why_it_matters": "CTV buyers need stronger traffic quality proof.",
            "bidmatrix_angle": "BidMatrix can use this for CTV quality positioning.",
            "suggested_action": "Build a BD talking point about CTV transparency.",
            "confidence": "high",
        }
    )

    assert malformed_bidmatrix_url["kept"] is False
    assert malformed_bidmatrix_url["skip_reason"] == "invalid_or_self_referential_source"
    assert synthetic_valid_url["kept"] is False
    assert synthetic_valid_url["skip_reason"] == "synthetic_brief_artifact"


def test_market_brief_v2_rejects_linkedin_and_stale_sources() -> None:
    linkedin = _evaluate_signal(
        {
            "title": "Tenjin and Xsolla Integration Closes Web Shop Attribution Gap",
            "url": "https://www.linkedin.com/posts/tenjin_tenjin-and-xsolla-are-now-connected-via-activity-7462087140508880896-Ychs",
            "source": None,
            "source_domain": "linkedin.com",
            "published_date": "2026-06-18",
            "signal_type": "partnership_integration",
            "category": "Measurement / MMP / Attribution",
            "what_happened": "Tenjin and Xsolla connected web shop attribution for gaming marketers.",
            "why_it_matters": "Mobile growth teams need web-to-app attribution proof.",
            "bidmatrix_angle": "BidMatrix can use this as a partner-monitoring signal.",
            "suggested_action": "Create a BD note about web shop attribution.",
            "confidence": "high",
        }
    )
    stale = _evaluate_signal(
        {
            "title": "Programmatic and CTV are overlooked by app marketers",
            "url": "https://www.businessofapps.com/news/programmatic-and-ctv-are-overlooked-by-app-marketers-bidmatrixs-new-ua-expansion-kit-aims-to-fix-that/",
            "source": None,
            "source_domain": "businessofapps.com",
            "published_date": "2025-11-05",
            "signal_type": "product_launch",
            "category": "Traffic Quality / Fraud / Inventory",
            "what_happened": "BidMatrix released a UA expansion kit.",
            "why_it_matters": "App marketers need programmatic and CTV diversification.",
            "bidmatrix_angle": "BidMatrix can use this for positioning.",
            "suggested_action": "Create a website note about CTV expansion.",
            "confidence": "high",
        }
    )

    assert linkedin["kept"] is False
    assert linkedin["skip_reason"] == "invalid_or_self_referential_source"
    assert stale["kept"] is False
    assert stale["skip_reason"] == "stale_source_date"


def test_market_brief_v2_rejects_same_name_construction_and_social_sources() -> None:
    construction = _evaluate_signal(
        {
            "title": "Bid Insights",
            "url": "https://help.bidmatrix.intacct.com/Content/ReleaseNotes/Version3_7/Version3_7_Bid-insights.htm",
            "source": None,
            "source_domain": "help.bidmatrix.intacct.com",
            "published_date": "2026-06-18",
            "signal_type": "product_launch",
            "category": "Traffic Quality / Fraud / Inventory",
            "what_happened": "A construction estimating tool released bid insights.",
            "why_it_matters": "This is unrelated same-name software.",
            "bidmatrix_angle": "This should not be used for BidMatrix mobile adtech.",
            "suggested_action": "Skip it.",
            "confidence": "high",
        }
    )
    instagram = _evaluate_signal(
        {
            "title": "Today, I made the Forbes 30u30",
            "url": "https://www.instagram.com/p/DY4hMUygfPT/",
            "source": None,
            "source_domain": "instagram.com",
            "published_date": "2026-06-18",
            "signal_type": "other",
            "category": "Competitor / Partner Moves",
            "what_happened": "A social post mentioned adtech.",
            "why_it_matters": "Social posts are not valid v2 market brief sources.",
            "bidmatrix_angle": "Skip social content.",
            "suggested_action": "Skip it.",
            "confidence": "medium",
        }
    )

    assert construction["kept"] is False
    assert construction["skip_reason"] == "invalid_or_self_referential_source"
    assert instagram["kept"] is False
    assert instagram["skip_reason"] == "invalid_or_self_referential_source"


def test_market_brief_v2_rejects_multi_url_source_bundles() -> None:
    bundled = _evaluate_signal(
        {
            "title": "Recent Shifts in Unified Attribution and Measurement Ecosystems",
            "url": "https://forbusiness.snapchat.com/blog/announcing-unified-attribution; https://example.com/second-source",
            "source": None,
            "source_domain": "forbusiness.snapchat.com",
            "published_date": "2026-06-11",
            "signal_type": "partnership_integration",
            "category": "Measurement / MMP / Attribution",
            "what_happened": "Several platforms released attribution updates.",
            "why_it_matters": "Measurement fragmentation is getting worse.",
            "bidmatrix_angle": "BidMatrix can use this for measurement positioning.",
            "suggested_action": "Create a BD note about unified attribution.",
            "confidence": "high",
        }
    )

    assert bundled["kept"] is False
    assert bundled["skip_reason"] == "invalid_or_self_referential_source"


def test_market_brief_v2_prefers_text_signal_type_over_bad_exa_label() -> None:
    signal = _evaluate_signal(
        {
            "title": "Audiences partner connections - Help Center - AppsFlyer support",
            "url": "https://support.appsflyer.com/hc/en-us/articles/360013960577-Audiences-partner-connections",
            "source": None,
            "source_domain": "support.appsflyer.com",
            "published_date": "2026-06-04",
            "signal_type": "funding_mna",
            "category": "Measurement / MMP / Attribution",
            "what_happened": "AppsFlyer updated partner connections for API-based audience syncing.",
            "why_it_matters": "Marketers can automate cross-platform audience management.",
            "bidmatrix_angle": "BidMatrix remains an active integrated partner in the AppsFlyer ecosystem.",
            "suggested_action": "Use this as a BD talking point about MMP interoperability.",
            "confidence": "high",
        }
    )

    assert signal["kept"] is True
    assert signal["signal_type"] == "partnership_integration"
    assert signal["keep_reason"] == "clear_partner_or_integration_move"


def test_market_brief_v2_does_not_treat_user_acquisition_as_mna() -> None:
    signal = _evaluate_signal(
        {
            "title": "CloudX Takes A Swing At Black-Box Mobile UA With Agentic Buying Tools",
            "url": "https://www.adexchanger.com/mobile/cloudx-takes-a-swing-at-black-box-mobile-ua-with-agentic-buying/",
            "source": None,
            "source_domain": "adexchanger.com",
            "published_date": "2026-06-17",
            "signal_type": "funding_mna",
            "category": "Measurement / MMP / Attribution",
            "what_happened": "CloudX launched agentic buying capabilities for mobile user acquisition.",
            "why_it_matters": "Agentic buying tools challenge black-box UA networks.",
            "bidmatrix_angle": "BidMatrix can position around transparent AI-assisted UA.",
            "suggested_action": "Create a sales talking point about transparent agentic UA.",
            "confidence": "high",
        }
    )

    assert signal["kept"] is True
    assert signal["signal_type"] == "ai_automation"
    assert signal["category"] == "AI / Automation / Agentic UA"
    assert signal["keep_reason"] == "clear_ai_or_automation_signal"


def test_market_brief_v2_dedupes_same_company_product_signal_and_keeps_secondary_sources() -> None:
    exchange_wire = _signal(
        title="DoubleVerify Introduces DV Neura, the Dynamic AI Engine - ExchangeWire.com",
        url="https://www.exchangewire.com/blog/2026/06/18/doubleverify-introduces-dv-neura-the-dynamic-ai-engine/",
        source_domain="exchangewire.com",
        published_date="2026-06-18",
        signal_type="ai_automation",
        category="AI / Automation / Agentic UA",
        bidmatrix_angle="DV Neura gives BidMatrix a point of comparison for agentic campaign controls.",
        suggested_action="Use this in a BD note about agentic optimization.",
    )
    ppc_land = _signal(
        title="DoubleVerify launches DV Neura, its AI engine for agentic ad campaigns",
        url="https://ppc.land/doubleverify-launches-dv-neura-its-ai-engine-for-agentic-ad-campaigns/",
        source_domain="ppc.land",
        published_date="2026-06-17",
        signal_type="ai_automation",
        category="AI / Automation / Agentic UA",
        bidmatrix_angle="DV Neura gives BidMatrix another source for agentic campaign controls.",
        suggested_action="Use this as a second source.",
    )
    cloudx = _signal(
        title="CloudX Takes A Swing At Black-Box Mobile UA With Agentic Buying Tools",
        url="https://www.adexchanger.com/mobile/cloudx-takes-a-swing-at-black-box-mobile-ua-with-agentic-buying/",
        source_domain="adexchanger.com",
        published_date="2026-06-17",
        signal_type="ai_automation",
        category="AI / Automation / Agentic UA",
    )

    deduped = _dedupe_related_signals([exchange_wire, ppc_land, cloudx])

    assert len(deduped) == 2
    dv = next(item for item in deduped if "DV Neura" in item["title"])
    assert dv["primary_source"]["source_domain"] == "exchangewire.com"
    assert dv["secondary_sources"] == [
        {
            "title": "DoubleVerify launches DV Neura, its AI engine for agentic ad campaigns",
            "url": "https://ppc.land/doubleverify-launches-dv-neura-its-ai-engine-for-agentic-ad-campaigns/",
            "source_domain": "ppc.land",
            "published_date": "2026-06-17",
        }
    ]
    assert any("CloudX" in item["title"] for item in deduped)


def test_market_brief_v2_summary_calls_out_category_concentration() -> None:
    summary = _executive_summary(
        [
            _signal(title="AI signal 1", category="AI / Automation / Agentic UA"),
            _signal(title="AI signal 2", category="AI / Automation / Agentic UA"),
            _signal(title="AI signal 3", category="AI / Automation / Agentic UA"),
            _signal(title="AI signal 4", category="AI / Automation / Agentic UA"),
            _signal(title="Measurement signal", category="Measurement / MMP / Attribution"),
        ]
    )

    assert summary[0] == (
        "This run is concentrated around AI / Automation / Agentic UA: 4 of 5 kept signals sit in that theme."
    )


def test_cli_market_brief_v2_preview_does_not_call_v1_or_delivery(monkeypatch, tmp_path: Path, capsys) -> None:
    markdown_path = tmp_path / "market-brief-v2-2026-06-18.md"
    json_path = tmp_path / "market-brief-v2-2026-06-18.json"
    audit_path = tmp_path / "market-brief-v2-2026-06-18-audit.json"
    for path in (markdown_path, json_path, audit_path):
        path.write_text("preview", encoding="utf-8")

    def fake_build(*, max_queries=20):
        return markdown_path, json_path, audit_path, {
            "exa_total_queries": max_queries,
            "exa_errors_count": 0,
            "exa_timeouts_count": 0,
            "raw_results_count": 3,
            "kept_signals_count": 2,
            "watchlist_signals_count": 1,
        }

    def fail_load_config(*args, **kwargs):
        raise AssertionError("load_config should not be called for --market-brief-v2-preview")

    def fail_delivery(*args, **kwargs):
        raise AssertionError("maybe_deliver_report should not be called for --market-brief-v2-preview")

    monkeypatch.setattr(cli_module, "build_market_brief_v2_preview", fake_build)
    monkeypatch.setattr(cli_module, "load_config", fail_load_config)
    monkeypatch.setattr(cli_module, "maybe_deliver_report", fail_delivery)
    monkeypatch.setattr(
        "sys.argv",
        ["bidmatrix-monitor", "--market-brief-v2-preview", "--market-brief-v2-max-queries", "7"],
    )

    cli_module.main()

    output = capsys.readouterr().out
    assert f"Wrote {markdown_path}" in output
    assert f"Wrote {json_path}" in output
    assert f"Wrote {audit_path}" in output
    assert "MARKET_BRIEF_V2_PREVIEW exa_total_queries=7" in output
