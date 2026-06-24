from __future__ import annotations

import json
from pathlib import Path

from bidmatrix_monitor import cli as cli_module
from bidmatrix_monitor.market_brief_v2 import (
    collect_market_brief_v2_payload,
    _apply_compact_markdown_quality_gate,
    _dedupe_brief_top_signals,
    _dedupe_related_signals,
    _dedupe_watchlist_items,
    _dedupe_watchlist_items_with_duplicate_urls,
    _evaluate_signal,
    _executive_summary,
    _mark_duplicate_watchlist_items,
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
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "Market Brief v2 — 2026-06-18" in markdown
    assert "## Today’s marketing insight" in markdown
    assert "## What companies are doing" in markdown

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
            "executive_summary": {
                "what_changed": "Measurement signals got more concrete.",
                "why_it_matters": "Buyers need clearer performance proof.",
                "what_bidmatrix_should_do": "Tie messaging to partner-neutral attribution.",
                "coverage_note": "This run is measurement-heavy.",
            },
            "so_what": ["Measurement players are pushing web-to-app and incrementality narratives."],
            "top_signals": [_signal()],
            "sections": {
                "Competitor / Partner Moves": [],
                "Measurement / MMP / Attribution": [_signal()],
                "Traffic Quality / Fraud / Inventory": [],
                "AI / Automation / Agentic UA": [],
            },
            "recommended_actions": ["LinkedIn post idea: compare last-click and incrementality proof."],
            "watchlist": [
                _signal(
                    title="CloudX Takes A Swing At Black-Box Mobile UA With Agentic Buying Tools",
                    category="AI / Automation / Agentic UA",
                    source="Allison Schiff",
                    source_domain="adexchanger.com",
                    what_happened="CloudX is building agentic mobile UA buying tools.",
                    skip_reason="interesting_but_not_strong_enough",
                    kept=False,
                    watchlist=True,
                )
            ],
        }
    )

    assert "Market Brief v2 — 2026-06-18" in markdown
    assert "## Today’s marketing insight" in markdown
    assert "Measurement vendors are trying to own full-funnel performance proof" in markdown
    assert "## What companies are doing" in markdown
    assert "1. AppsFlyer is using a product launch to claim more of the growth workflow." in markdown
    assert "Marketing insight:" in markdown
    assert "What BidMatrix can use:" in markdown
    assert "Content / BD idea:" in markdown
    assert "Why it matters:" not in markdown
    assert "Possible action:" not in markdown
    assert "## Watchlist" in markdown
    assert "- CloudX is building agentic mobile UA buying tools." in markdown
    assert "BidMatrix angle:" not in markdown
    assert "Suggested content/BD action:" not in markdown
    assert "## 1. Executive Summary" not in markdown
    assert "## So what for BidMatrix?" not in markdown
    assert "## 7. Recommended Actions for BidMatrix" not in markdown


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


def test_market_brief_v2_category_specific_angles_and_actions() -> None:
    ai = _evaluate_signal(
        {
            "title": "CloudX launches agentic buying tools",
            "url": "https://www.adexchanger.com/mobile/cloudx-agentic-buying/",
            "source_domain": "adexchanger.com",
            "published_date": "2026-06-17",
            "signal_type": "other",
            "category": "AI / Automation / Agentic UA",
            "what_happened": "CloudX launched agentic buying for mobile user acquisition.",
            "why_it_matters": "AI buying creates new campaign operations pressure.",
            "confidence": "high",
        }
    )
    measurement = _evaluate_signal(
        {
            "title": "AppsFlyer launches web performance measurement",
            "url": "https://marketech-apac.com/appsflyer-launches-web-performance-measurement-to-unify-web-and-mobile-attribution/",
            "source_domain": "marketech-apac.com",
            "published_date": "2026-06-15",
            "signal_type": "product_launch",
            "category": "Measurement / MMP / Attribution",
            "what_happened": "AppsFlyer launched web performance measurement for web-to-app attribution.",
            "why_it_matters": "Advertisers need partner-neutral attribution and ROAS proof.",
            "confidence": "high",
        }
    )
    quality = _evaluate_signal(
        {
            "title": "Pixalate publishes CTV fraud benchmark",
            "url": "https://www.pixalate.com/blog/q1-2026-ad-fraud-benchmarks-report-for-north-america",
            "source_domain": "pixalate.com",
            "published_date": "2026-06-12",
            "signal_type": "market_report",
            "category": "Traffic Quality / Fraud / Inventory",
            "what_happened": "Pixalate published CTV invalid traffic benchmark data.",
            "why_it_matters": "CTV buyers need inventory quality validation.",
            "confidence": "high",
        }
    )

    assert "measurable UA optimization" in ai["bidmatrix_angle"]
    assert "AI-driven bidding" in ai["suggested_action"]
    assert "partner-neutral measurement proof" in measurement["bidmatrix_angle"]
    assert "web-to-app measurement" in measurement["suggested_action"]
    assert "verified supply" in quality["bidmatrix_angle"]
    assert "fraud checks" in quality["suggested_action"]


def test_market_brief_v2_watchlist_includes_medium_relevance_without_noise() -> None:
    watch = _evaluate_signal(
        {
            "title": "Retail media partner launch for advertisers",
            "url": "https://example.com/retail-media-ctv-partner-launch",
            "source_domain": "example.com",
            "published_date": "2026-06-18",
            "signal_type": "partnership_integration",
            "category": "Competitor / Partner Moves",
            "what_happened": "A retail media platform announced a partner launch for app marketers.",
            "why_it_matters": "It may become relevant for partner outreach.",
            "confidence": "medium",
        }
    )
    noisy = _evaluate_signal(
        {
            "title": "Ultimate guide to retail media best practices",
            "url": "https://example.com/resources/ultimate-guide-retail-media",
            "source_domain": "example.com",
            "published_date": "2026-06-18",
            "signal_type": "other",
            "category": "Competitor / Partner Moves",
            "what_happened": "A generic SEO guide was published.",
            "why_it_matters": "It is generic educational content.",
            "confidence": "medium",
        }
    )

    assert watch["kept"] is False
    assert watch["watchlist"] is True
    assert watch["skip_reason"] == "interesting_but_not_strong_enough"
    assert noisy["watchlist"] is False
    assert noisy["skip_reason"] in {"high_noise_risk", "low_marketing_bd_value", "weak_or_generic_signal"}


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

    assert summary["coverage_note"] == (
        "This run is AI/agentic-heavy: 4 of 5 kept signals sit in that theme. Thin categories are not being force-filled."
    )
    assert set(summary) == {"what_changed", "why_it_matters", "what_bidmatrix_should_do", "coverage_note"}
    assert "agentic campaign operations" in summary["why_it_matters"]


def test_market_brief_v2_markdown_folds_strategy_into_compact_pattern_and_actions() -> None:
    payload = {
        "run_date": "2026-06-18",
        "executive_summary": _executive_summary(
            [
                _signal(title="CloudX agentic buying", category="AI / Automation / Agentic UA"),
                _signal(title="AppsFlyer web attribution", category="Measurement / MMP / Attribution"),
            ]
        ),
        "so_what": [
            "AI buying and creative automation are becoming table stakes; BidMatrix should frame its AI story around measurable optimization loops, not generic automation.",
            "Measurement players are pushing web-to-app, incrementality, and partner-neutral proof; BidMatrix can connect this to transparent performance and ROAS/LTV clarity.",
        ],
        "top_signals": [
            _signal(
                title="CloudX agentic buying",
                category="AI / Automation / Agentic UA",
                suggested_action="Use this to start a sales conversation about AI-driven bidding.",
            ),
            _signal(
                title="AppsFlyer web attribution",
                category="Measurement / MMP / Attribution",
                source_domain="appsflyer.com",
                what_happened="AppsFlyer launched web and mobile attribution for growth teams.",
            ),
        ],
        "sections": {
            "Competitor / Partner Moves": [],
            "Measurement / MMP / Attribution": [_signal(title="AppsFlyer web attribution", category="Measurement / MMP / Attribution")],
            "Traffic Quality / Fraud / Inventory": [],
            "AI / Automation / Agentic UA": [_signal(title="CloudX agentic buying", category="AI / Automation / Agentic UA")],
        },
        "recommended_actions": [
            "LinkedIn post idea: publish a short take on why agentic UA needs measurable optimization loops, not just another automation claim.",
            "BD talking point: ask prospects how they measure AI-driven campaign changes across bidding, creative testing, and budget allocation.",
            "Partner outreach idea: use appsflyer.com to start a partner conversation around attribution proof, incrementality, and shared reporting gaps.",
            "Website/positioning idea: add a proof point around partner-neutral attribution, web-to-app visibility, and ROAS/LTV clarity.",
        ],
        "watchlist": [],
    }

    markdown = render_market_brief_v2_markdown(payload)

    assert "## Today’s marketing insight" in markdown
    assert "AI campaign operations and measurement proof" in markdown
    assert "## What companies are doing" in markdown
    assert "Marketing insight:" in markdown
    assert "What BidMatrix can use:" in markdown
    assert "Content / BD idea:" in markdown
    assert "Content / BD idea: BD talking point" in markdown
    assert "Content / BD idea: LinkedIn post" in markdown
    assert "Why it matters:" not in markdown
    assert "Possible action:" not in markdown
    assert "## So what for BidMatrix?" not in markdown
    assert "Partner outreach idea:" not in markdown
    assert "Website/positioning idea:" not in markdown
    assert "write about AI" not in markdown


def test_market_brief_v2_watchlist_dedupes_duplicate_company_theme_items() -> None:
    first = _signal(
        title="AppLovin Touts AXON-Led Growth",
        source="Renee Jackson",
        source_domain="thecerbatgem.com",
        category="AI / Automation / Agentic UA",
        what_happened="AppLovin continues to push AXON AI-led growth narratives.",
        kept=False,
        watchlist=True,
        skip_reason="interesting_but_not_strong_enough",
    )
    duplicate = _signal(
        title="AppLovin highlights AI-led growth narratives",
        source="MarketBeat",
        source_domain="marketbeat.com",
        category="AI / Automation / Agentic UA",
        what_happened="AppLovin continues to push AXON AI-led growth narratives.",
        kept=False,
        watchlist=True,
        skip_reason="interesting_but_not_strong_enough",
    )

    deduped = _dedupe_watchlist_items([first, duplicate])
    markdown = render_market_brief_v2_markdown({"run_date": "2026-06-18", "top_signals": [], "watchlist": deduped})

    assert len(deduped) == 1
    assert markdown.count("AppLovin continues to push AI-led growth narratives.") == 1


def test_market_brief_v2_watchlist_dedupes_exact_rendered_bullets() -> None:
    first = _signal(
        title="AppsFlyer web attribution watch",
        url="https://example.com/appsflyer-watch-one",
        source="AppsFlyer",
        source_domain="appsflyer.com",
        category="AI / Automation / Agentic UA",
        signal_type="other",
        what_happened="AppsFlyer published a medium-relevance measurement signal.",
        kept=False,
        watchlist=True,
    )
    duplicate = _signal(
        title="AppsFlyer AI measurement watch",
        url="https://example.com/appsflyer-watch-two",
        source="AppsFlyer",
        source_domain="appsflyer.com",
        category="Competitor / Partner Moves",
        signal_type="other",
        what_happened="AppsFlyer published a medium-relevance AI signal.",
        kept=False,
        watchlist=True,
    )

    deduped = _dedupe_watchlist_items([first, duplicate])
    markdown = render_market_brief_v2_markdown({"run_date": "2026-06-18", "top_signals": [], "watchlist": deduped})

    assert len(deduped) == 1
    assert markdown.count("AppsFlyer is worth watching for a clearer BidMatrix-relevant move.") == 1


def test_market_brief_v2_watchlist_keeps_different_companies() -> None:
    appsflyer = _signal(
        title="AppsFlyer watch",
        url="https://example.com/appsflyer-watch",
        source="AppsFlyer",
        source_domain="appsflyer.com",
        category="AI / Automation / Agentic UA",
        signal_type="other",
        what_happened="AppsFlyer published a medium-relevance signal.",
        kept=False,
        watchlist=True,
    )
    bidmachine = _signal(
        title="BidMachine explores DSP positioning",
        url="https://example.com/bidmachine-watch",
        source=None,
        source_domain="example.com",
        category="AI / Automation / Agentic UA",
        signal_type="other",
        what_happened="BidMachine is positioning around ML-powered DSP infrastructure.",
        kept=False,
        watchlist=True,
    )

    deduped = _dedupe_watchlist_items([appsflyer, bidmachine])
    markdown = render_market_brief_v2_markdown({"run_date": "2026-06-18", "top_signals": [], "watchlist": deduped})

    assert len(deduped) == 2
    assert "AppsFlyer is worth watching for a clearer BidMatrix-relevant move." in markdown
    assert "BidMachine is positioning around ML-powered DSP infrastructure." in markdown


def test_market_brief_v2_duplicate_watchlist_item_is_marked_for_audit() -> None:
    first = _signal(
        title="AppsFlyer watch one",
        url="https://example.com/appsflyer-watch-one",
        source="AppsFlyer",
        source_domain="appsflyer.com",
        category="AI / Automation / Agentic UA",
        signal_type="other",
        what_happened="AppsFlyer published a medium-relevance measurement signal.",
        kept=False,
        watchlist=True,
    )
    duplicate = _signal(
        title="AppsFlyer watch two",
        url="https://example.com/appsflyer-watch-two",
        source="AppsFlyer",
        source_domain="appsflyer.com",
        category="Competitor / Partner Moves",
        signal_type="other",
        what_happened="AppsFlyer published a medium-relevance AI signal.",
        kept=False,
        watchlist=True,
    )

    deduped, duplicate_urls = _dedupe_watchlist_items_with_duplicate_urls([first, duplicate])
    marked = _mark_duplicate_watchlist_items([first, duplicate], duplicate_urls)

    assert len(deduped) == 1
    assert duplicate_urls == {"https://example.com/appsflyer-watch-two"}
    assert marked[1]["skip_reason"] == "duplicate_watchlist_item"
    assert marked[1]["watchlist"] is False


def test_market_brief_v2_top_signals_dedupe_liftoff_style_duplicate_rendered_sentence() -> None:
    ipo = _signal(
        title="Liftoff Mobile successfully completed its IPO",
        url="https://example.com/liftoff-ipo",
        source="Morningstar",
        source_domain="morningstar.com",
        category="AI / Automation / Agentic UA",
        signal_type="funding_mna",
        what_happened="Liftoff announced a market-structure IPO move for mobile advertising.",
    )
    funding = _signal(
        title="Liftoff market structure update",
        url="https://example.com/liftoff-market-structure",
        source="PR Newswire",
        source_domain="prnewswire.com",
        category="Competitor / Partner Moves",
        signal_type="funding_mna",
        what_happened="Liftoff announced another market-structure move worth tracking.",
    )

    deduped, duplicate_urls = _dedupe_brief_top_signals([ipo, funding])
    markdown = render_market_brief_v2_markdown({"run_date": "2026-06-18", "top_signals": deduped, "watchlist": []})

    assert len(deduped) == 1
    assert duplicate_urls == {"https://example.com/liftoff-market-structure"}
    assert markdown.count("Liftoff is using a market-structure move to reinforce its platform credibility.") == 1


def test_market_brief_v2_duplicate_top_signal_is_marked_in_audit(monkeypatch) -> None:
    monkeypatch.setenv("EXA_API_KEY", "token")

    class _FakeExa:
        def __init__(self, api_key: str, request_timeout_seconds: int) -> None:
            self.api_key = api_key
            self.request_timeout_seconds = request_timeout_seconds

        def search(self, query: str, **kwargs):
            signals = [
                {
                    "title": "Liftoff Mobile successfully completed its IPO",
                    "url": "https://example.com/liftoff-ipo",
                    "source": "Morningstar",
                    "source_domain": "morningstar.com",
                    "published_date": "2026-06-18",
                    "signal_type": "funding_mna",
                    "category": "AI / Automation / Agentic UA",
                    "what_happened": "Liftoff announced a market-structure IPO move for mobile advertising.",
                    "why_it_matters": "Mobile growth platforms are being valued by public markets.",
                    "bidmatrix_angle": "BidMatrix can use this as a benchmark for mobile growth platforms.",
                    "suggested_action": "Create a BD note about market structure.",
                    "confidence": "high",
                },
                {
                    "title": "Liftoff market structure update",
                    "url": "https://example.com/liftoff-market-structure",
                    "source": "PR Newswire",
                    "source_domain": "prnewswire.com",
                    "published_date": "2026-06-18",
                    "signal_type": "funding_mna",
                    "category": "Competitor / Partner Moves",
                    "what_happened": "Liftoff announced another market-structure move worth tracking.",
                    "why_it_matters": "Mobile growth platforms are being valued by public markets.",
                    "bidmatrix_angle": "BidMatrix can use this as a benchmark for mobile growth platforms.",
                    "suggested_action": "Create a BD note about market structure.",
                    "confidence": "high",
                },
            ]

            class _Response:
                output = type("Output", (), {"content": {"signals": signals}})

            return _Response()

    monkeypatch.setattr("bidmatrix_monitor.market_brief_v2.TimeoutExa", _FakeExa)

    payload = collect_market_brief_v2_payload(max_queries=1)

    assert payload["kept_signals_count"] == 1
    assert any(item["skip_reason"] == "duplicate_top_signal" for item in payload["audit"])


def test_market_brief_v2_top_signals_dedupe_same_company_type_and_theme() -> None:
    first = _signal(
        title="AppLovin expands AXON growth platform",
        url="https://example.com/applovin-axon-one",
        source="MarketWatch",
        source_domain="marketwatch.com",
        category="AI / Automation / Agentic UA",
        signal_type="ai_automation",
        what_happened="AppLovin expanded its AXON AI-led growth platform narrative.",
    )
    second = _signal(
        title="AppLovin highlights AI-led growth platform update",
        url="https://example.com/applovin-axon-two",
        source="MarketBeat",
        source_domain="marketbeat.com",
        category="AI / Automation / Agentic UA",
        signal_type="ai_automation",
        what_happened="AppLovin continues to push AXON AI-led growth narratives.",
    )

    deduped, duplicate_urls = _dedupe_brief_top_signals([first, second])

    assert len(deduped) == 1
    assert duplicate_urls == {"https://example.com/applovin-axon-two"}


def test_market_brief_v2_top_signals_keep_same_company_different_themes() -> None:
    web_attribution = _signal(
        title="AppsFlyer launches web performance measurement",
        url="https://example.com/appsflyer-web",
        source="AppsFlyer",
        source_domain="appsflyer.com",
        category="Measurement / MMP / Attribution",
        signal_type="product_launch",
        what_happened="AppsFlyer launched web and mobile attribution for growth teams.",
    )
    fraud_report = _signal(
        title="AppsFlyer publishes fraud benchmark",
        url="https://example.com/appsflyer-fraud",
        source="AppsFlyer",
        source_domain="appsflyer.com",
        category="Traffic Quality / Fraud / Inventory",
        signal_type="market_report",
        what_happened="AppsFlyer published fraud benchmark data for app advertisers.",
    )

    deduped, duplicate_urls = _dedupe_brief_top_signals([web_attribution, fraud_report])

    assert len(deduped) == 2
    assert duplicate_urls == set()


def test_market_brief_v2_pixalate_quality_signal_avoids_mmp_web_attribution_wording() -> None:
    markdown = render_market_brief_v2_markdown(
        {
            "run_date": "2026-06-18",
            "top_signals": [
                _signal(
                    title="Pixalate publishes Q1 2026 mobile app invalid traffic benchmark",
                    source="Pixalate",
                    source_domain="pixalate.com",
                    category="Measurement / MMP / Attribution",
                    signal_type="market_report",
                    what_happened="Pixalate published mobile app IVT and ad fraud benchmark data.",
                    why_it_matters="CTV and in-app buyers need stronger inventory validation.",
                    bidmatrix_angle="BidMatrix can use this for traffic quality positioning.",
                    suggested_action="Create a website proof point around fraud detection.",
                )
            ],
            "watchlist": [],
        }
    )

    assert "Pixalate is using fraud and inventory-quality risk to strengthen its verification narrative." in markdown
    assert "web and mobile attribution" not in markdown
    assert "web-to-app measurement" not in markdown
    assert "budget protection, verified supply, and fraud-resistant growth" in markdown


def test_market_brief_v2_opening_sentences_use_clean_company_action_phrasing() -> None:
    markdown = render_market_brief_v2_markdown(
        {
            "run_date": "2026-06-18",
            "top_signals": [
                _signal(
                    title="Cint merges brand and performance measurement",
                    source="press release",
                    source_domain="example.com",
                    category="AI / Automation / Agentic UA",
                    signal_type="partnership_integration",
                    what_happened="Cint updated brand measurement positioning for advertisers.",
                ),
                _signal(
                    title="Nexxen Launches MCP for Agentic Advertising",
                    source="press release",
                    source_domain="example.com",
                    category="AI / Automation / Agentic UA",
                    signal_type="partnership_integration",
                    what_happened="Nexxen launched MCP tools for agentic media workflows.",
                ),
            ],
            "watchlist": [],
        }
    )

    assert "Cint is positioning brand measurement as a performance-marketing input." in markdown
    assert "Nexxen is building an agentic workflow story around MCP tools." in markdown
    assert "Cint merges brand connected" not in markdown
    assert "Nexxen Launches MCP connected" not in markdown


def test_market_brief_v2_cleans_known_company_subject_fragments() -> None:
    markdown = render_market_brief_v2_markdown(
        {
            "run_date": "2026-06-18",
            "top_signals": [
                _signal(
                    title="WunderKIND Ads Releases New Measurement Integration",
                    source=None,
                    source_domain="example.com",
                    category="Measurement / MMP / Attribution",
                    signal_type="partnership_integration",
                    what_happened="WunderKIND Ads released a measurement integration for marketers.",
                ),
                _signal(
                    title="TripleLift's Offsite Retail Media Product Expands",
                    source=None,
                    source_domain="example.com",
                    category="AI / Automation / Agentic UA",
                    signal_type="product_launch",
                    what_happened="TripleLift expanded offsite retail media positioning for advertisers.",
                ),
            ],
            "watchlist": [],
        }
    )

    assert "WunderKIND Ads is using integrations to own more of the attribution and audience workflow." in markdown
    assert "TripleLift is using a product launch to claim more of the growth workflow." in markdown
    assert "WunderKIND Ads Releases" not in markdown
    assert "TripleLift's Offsite Retail" not in markdown


def test_market_brief_v2_malformed_subjects_are_skipped_with_reason() -> None:
    signals = [
        _signal(
            title="Ad tech’s next chapter is agentic",
            source=None,
            source_domain="example.com",
            category="AI / Automation / Agentic UA",
            signal_type="other",
            what_happened="An article discussed broad agentic ad-tech trends without a clear company.",
            kept=True,
            watchlist=False,
        ),
        _signal(
            title="Agentic Ad-Tech: The next era of advertising",
            source=None,
            source_domain="example.com",
            category="AI / Automation / Agentic UA",
            signal_type="other",
            what_happened="A generic headline did not identify a specific company.",
            kept=True,
            watchlist=False,
        ),
    ]

    gated = _apply_compact_markdown_quality_gate(signals)

    assert [item["skip_reason"] for item in gated] == ["malformed_subject", "malformed_subject"]
    assert all(item["kept"] is False for item in gated)
    assert all(item["watchlist"] is False for item in gated)


def test_market_brief_v2_watchlist_does_not_render_malformed_subjects() -> None:
    malformed = _signal(
        title="Agentic Ad-Tech: The next era of advertising",
        source=None,
        source_domain="example.com",
        category="AI / Automation / Agentic UA",
        signal_type="other",
        what_happened="Agentic Ad-Tech: The article described agentic buying tools.",
        kept=False,
        watchlist=True,
    )
    clean = _signal(
        title="Perion explores AI search positioning",
        source=None,
        source_domain="example.com",
        category="AI / Automation / Agentic UA",
        signal_type="other",
        what_happened="Perion is exploring AI search or agentic ad-tech positioning.",
        kept=False,
        watchlist=True,
    )

    gated = _apply_compact_markdown_quality_gate([malformed, clean])
    watchlist = _dedupe_watchlist_items([item for item in gated if item["watchlist"]])
    markdown = render_market_brief_v2_markdown({"run_date": "2026-06-18", "top_signals": [], "watchlist": watchlist})

    assert "Agentic Ad-Tech: The" not in markdown
    assert "Perion" in markdown
    assert next(item for item in gated if item["title"].startswith("Agentic"))["skip_reason"] == "malformed_subject"


def test_market_brief_v2_rejects_generic_subject_fragments() -> None:
    retail_media = _signal(
        title="Retail media's hidden performance report",
        source=None,
        source_domain="example.com",
        category="Measurement / MMP / Attribution",
        signal_type="market_report",
        what_happened="Retail media's hidden performance report discussed benchmark data without a clear company.",
        kept=True,
        watchlist=False,
    )
    agentic_headline = _signal(
        title="Agentic Ad-Tech: The next era",
        source=None,
        source_domain="example.com",
        category="AI / Automation / Agentic UA",
        signal_type="other",
        what_happened="Agentic Ad-Tech: The article discussed broad industry trends.",
        kept=True,
        watchlist=False,
    )

    gated = _apply_compact_markdown_quality_gate([retail_media, agentic_headline])

    assert [item["skip_reason"] for item in gated] == ["malformed_subject", "malformed_subject"]
    assert all(item["kept"] is False for item in gated)
    assert all(item["watchlist"] is False for item in gated)


def test_market_brief_v2_recovers_known_company_from_possessive_or_action_fragment() -> None:
    markdown = render_market_brief_v2_markdown(
        {
            "run_date": "2026-06-18",
            "top_signals": [
                _signal(
                    title="Walmart Connect’s ad platform expands agentic workflows",
                    source=None,
                    source_domain="example.com",
                    category="AI / Automation / Agentic UA",
                    signal_type="partnership_integration",
                    what_happened="Walmart Connect’s ad platform expanded agentic campaign workflows.",
                ),
                _signal(
                    title="Verve Introduces Verve AI campaign tools",
                    source=None,
                    source_domain="example.com",
                    category="AI / Automation / Agentic UA",
                    signal_type="product_launch",
                    what_happened="Verve introduced AI campaign tools for performance advertisers.",
                ),
            ],
            "watchlist": [
                _signal(
                    title="Walmart Connect's first-party data positioning",
                    source=None,
                    source_domain="example.com",
                    category="AI / Automation / Agentic UA",
                    signal_type="other",
                    what_happened="Walmart Connect's first-party data positioning is worth watching.",
                    kept=False,
                    watchlist=True,
                )
            ],
        }
    )

    assert "Walmart Connect is positioning integrations as the connective tissue for AI campaign workflows." in markdown
    assert "Verve is using a product launch to claim more of the growth workflow." in markdown
    assert "Walmart Connect is worth watching for a clearer BidMatrix-relevant move." in markdown
    assert "Walmart Connect’s ad" not in markdown
    assert "Verve Introduces Verve" not in markdown
    assert "Walmart Connect's first-party" not in markdown


def test_market_brief_v2_watchlist_skips_unrecoverable_subject_fragments() -> None:
    malformed = _signal(
        title="Retail media's hidden opportunity",
        source=None,
        source_domain="example.com",
        category="AI / Automation / Agentic UA",
        signal_type="other",
        what_happened="Retail media's hidden opportunity discussed agentic buying tools.",
        kept=False,
        watchlist=True,
    )
    clean = _signal(
        title="BidMachine explores DSP positioning",
        source=None,
        source_domain="example.com",
        category="AI / Automation / Agentic UA",
        signal_type="other",
        what_happened="BidMachine is positioning around ML-powered DSP infrastructure.",
        kept=False,
        watchlist=True,
    )

    gated = _apply_compact_markdown_quality_gate([malformed, clean])
    watchlist = _dedupe_watchlist_items([item for item in gated if item["watchlist"]])
    markdown = render_market_brief_v2_markdown({"run_date": "2026-06-18", "top_signals": [], "watchlist": watchlist})

    assert "Retail media" not in markdown
    assert "BidMachine" in markdown
    assert next(item for item in gated if item["title"].startswith("Retail"))["skip_reason"] == "malformed_subject"


def test_market_brief_v2_awkward_action_sentence_is_not_kept_as_top_signal() -> None:
    awkward = _signal(
        title="Merges brand connected parts",
        source=None,
        source_domain="example.com",
        category="AI / Automation / Agentic UA",
        signal_type="partnership_integration",
        what_happened="A malformed title would create a bad compact sentence.",
    )
    awkward["kept"] = True
    awkward["watchlist"] = False

    gated = _apply_compact_markdown_quality_gate([awkward])

    assert gated[0]["kept"] is False
    assert gated[0]["watchlist"] is True
    assert gated[0]["skip_reason"] == "awkward_action_sentence"


def test_market_brief_v2_compact_actions_do_not_repeat_more_than_twice() -> None:
    signals = [
        _signal(
            title=f"AI campaign workflow signal {index}",
            category="AI / Automation / Agentic UA",
            signal_type="ai_automation",
            what_happened=f"Company {index} launched agentic campaign workflow tooling.",
        )
        for index in range(6)
    ]
    markdown = render_market_brief_v2_markdown({"run_date": "2026-06-18", "top_signals": signals, "watchlist": []})
    action_lines = [line for line in markdown.splitlines() if line.startswith("Content / BD idea:")]

    assert len(action_lines) == 6
    assert max(action_lines.count(line) for line in set(action_lines)) <= 2


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
