from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

from .exa_client import TimeoutExa


MAX_EXA_QUERIES = 14
V2_RESULTS_PER_QUERY = 3
MAX_TOP_SIGNALS = 8
MAX_WATCHLIST_ITEMS = 3
MAX_SOURCE_AGE_DAYS = 45
ALLOWED_SIGNAL_TYPES = {
    "product_launch",
    "partnership_integration",
    "funding_mna",
    "market_report",
    "fraud_quality",
    "ai_automation",
    "measurement_change",
    "other",
}


V2_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["has_signal"],
    "properties": {
        "has_signal": {"type": "boolean"},
        "title": {"type": "string"},
        "url": {"type": "string"},
        "published_date": {"type": "string"},
        "signal_type": {"type": "string"},
        "category": {"type": "string"},
        "what_happened": {"type": "string"},
        "why_it_matters": {"type": "string"},
        "bidmatrix_angle": {"type": "string"},
        "suggested_action": {"type": "string"},
    },
}


@dataclass(frozen=True)
class V2Query:
    query_id: str
    label: str
    category: str
    query: str


V2_QUERIES: tuple[V2Query, ...] = (
    V2Query(
        "measurement_mmp_product",
        "Measurement / MMP / Attribution",
        "Measurement / MMP / Attribution",
        (
            "AppsFlyer Adjust Singular Branch Kochava Airbridge Tenjin mobile attribution MMP "
            "product launch integration partnership incrementality last 30 days"
        ),
    ),
    V2Query(
        "measurement_privacy_skan",
        "Measurement / MMP / Attribution",
        "Measurement / MMP / Attribution",
        (
            "SKAN Privacy Sandbox incrementality attribution measurement app marketing report "
            "AppsFlyer Adjust Singular Branch last 30 days"
        ),
    ),
    V2Query(
        "fraud_quality_reports",
        "Traffic Quality / Fraud / Inventory",
        "Traffic Quality / Fraud / Inventory",
        (
            "Pixalate HUMAN DoubleVerify IAS Fraudlogix mobile ad fraud invalid traffic CTV "
            "inventory quality report benchmark last 30 days"
        ),
    ),
    V2Query(
        "inventory_direct_supply",
        "Traffic Quality / Fraud / Inventory",
        "Traffic Quality / Fraud / Inventory",
        (
            "programmatic in-app advertising direct supply mobile DSP SSP exchange inventory quality "
            "partnership launch last 30 days"
        ),
    ),
    V2Query(
        "ai_agentic_ua",
        "AI / Automation / Agentic UA",
        "AI / Automation / Agentic UA",
        (
            "AI media buying agentic campaign operations mobile user acquisition automation "
            "CloudX AppLovin Moloco Liftoff product launch last 30 days"
        ),
    ),
    V2Query(
        "ai_creative_optimization",
        "AI / Automation / Agentic UA",
        "AI / Automation / Agentic UA",
        (
            "creative automation AI optimization mobile app growth adtech launch partnership "
            "performance marketing last 30 days"
        ),
    ),
    V2Query(
        "competitor_mmp_moves",
        "Competitor / Partner Moves",
        "Competitor / Partner Moves",
        (
            "AppsFlyer Adjust Singular Branch Kochava Airbridge partnership integration product launch "
            "funding acquisition IPO mobile adtech last 30 days"
        ),
    ),
    V2Query(
        "competitor_media_buying_moves",
        "Competitor / Partner Moves",
        "Competitor / Partner Moves",
        (
            "AppLovin Moloco Liftoff Digital Turbine Unity ironSource Mintegral programmatic mobile "
            "adtech partnership product launch IPO acquisition funding last 30 days"
        ),
    ),
    V2Query(
        "ctv_retail_media_supply",
        "CTV / Retail Media / Direct Supply",
        "Traffic Quality / Fraud / Inventory",
        (
            "CTV retail media direct supply programmatic mobile app marketers performance advertising "
            "partnership integration launch benchmark last 30 days"
        ),
    ),
    V2Query(
        "retail_media_measurement",
        "CTV / Retail Media / Direct Supply",
        "Measurement / MMP / Attribution",
        (
            "retail media measurement CTV attribution incrementality app marketers programmatic report "
            "benchmark last 30 days"
        ),
    ),
    V2Query(
        "app_growth_reports",
        "Reports / Benchmarks / Market Data",
        "Measurement / MMP / Attribution",
        (
            "mobile app growth user acquisition performance marketing benchmark report market data "
            "adtech last 30 days"
        ),
    ),
    V2Query(
        "performance_marketing_reports",
        "Reports / Benchmarks / Market Data",
        "AI / Automation / Agentic UA",
        (
            "performance marketing mobile UA AI buying attribution fraud CTV benchmark report "
            "app marketing last 30 days"
        ),
    ),
)


def build_market_brief_v2_preview(
    *,
    report_dir: str | Path = "reports",
    max_queries: int = MAX_EXA_QUERIES,
) -> tuple[Path, Path, Path, dict[str, Any]]:
    payload = collect_market_brief_v2_payload(max_queries=max_queries)
    return write_market_brief_v2_preview(payload, report_dir)


def collect_market_brief_v2_payload(*, max_queries: int = MAX_EXA_QUERIES) -> dict[str, Any]:
    load_dotenv()
    api_key = os.environ.get("EXA_API_KEY")
    if not api_key:
        raise RuntimeError("EXA_API_KEY is not set. Add it to your environment or a local .env file.")

    query_limit = max(0, min(int(max_queries), MAX_EXA_QUERIES))
    queries = V2_QUERIES[:query_limit]
    exa = TimeoutExa(api_key=api_key, request_timeout_seconds=20)
    start = time.monotonic()
    candidates: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    timeouts = 0

    for query in queries:
        try:
            response = exa.search(
                _build_v2_query(query),
                type="deep",
                category="news",
                num_results=V2_RESULTS_PER_QUERY,
                contents={"highlights": {"max_characters": 2600}},
            )
        except Exception as exc:
            if isinstance(exc, (TimeoutError, requests.Timeout)):
                timeouts += 1
            errors.append({"query_id": query.query_id, "error_type": type(exc).__name__, "error": str(exc)})
            continue

        candidates.extend(_signals_from_response(response, query))

    deduped = _dedupe_candidates(candidates)
    evaluated = _apply_compact_markdown_quality_gate([_evaluate_signal(candidate) for candidate in deduped])
    kept = [item for item in evaluated if item["kept"]]
    top_candidates = _dedupe_related_signals(sorted(kept, key=_rank_key))
    top_signals, duplicate_top_urls = _dedupe_brief_top_signals(top_candidates, limit=MAX_TOP_SIGNALS)
    evaluated = _mark_duplicate_top_signals(evaluated, duplicate_top_urls)
    watchlist = [item for item in evaluated if item["watchlist"] and not item["kept"]]
    watchlist_items, duplicate_watchlist_urls = _dedupe_watchlist_items_with_duplicate_urls(
        sorted(watchlist, key=_rank_key),
        limit=MAX_WATCHLIST_ITEMS,
    )
    evaluated = _mark_duplicate_watchlist_items(evaluated, duplicate_watchlist_urls)
    skipped = [item for item in evaluated if not item["kept"] and not item["watchlist"]]

    run_date = date.today().isoformat()
    payload = {
        "run_date": run_date,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "preview_only": True,
        "max_exa_queries": query_limit,
        "exa_total_queries": len(queries),
        "exa_errors_count": len(errors),
        "exa_timeouts_count": timeouts,
        "exa_total_duration_seconds": round(time.monotonic() - start, 2),
        "raw_results_count": len(candidates),
        "unique_results_count": len(deduped),
        "kept_signals_count": len(top_signals),
        "skipped_signals_count": len(skipped),
        "watchlist_signals_count": len(watchlist_items),
        "executive_summary": _executive_summary(top_signals),
        "so_what": _so_what(top_signals),
        "top_signals": top_signals,
        "sections": _sections(top_signals),
        "recommended_actions": _recommended_actions(top_signals),
        "watchlist": watchlist_items,
        "audit": evaluated,
        "errors": errors,
    }
    return payload


def write_market_brief_v2_preview(
    payload: dict[str, Any],
    report_dir: str | Path,
) -> tuple[Path, Path, Path, dict[str, Any]]:
    output_dir = Path(report_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"market-brief-v2-{payload['run_date']}"
    markdown_path = output_dir / f"{stem}.md"
    json_path = output_dir / f"{stem}.json"
    audit_path = output_dir / f"{stem}-audit.json"

    markdown_path.write_text(render_market_brief_v2_markdown(payload), encoding="utf-8")
    json_path.write_text(json.dumps(_public_payload(payload), indent=2, ensure_ascii=False), encoding="utf-8")
    audit_path.write_text(json.dumps(build_market_brief_v2_audit(payload), indent=2, ensure_ascii=False), encoding="utf-8")
    return markdown_path, json_path, audit_path, payload


def render_market_brief_v2_markdown(payload: dict[str, Any]) -> str:
    lines = [f"# Market Brief v2 — {payload['run_date']}", ""]

    lines.extend(["## Today’s marketing insight", _today_marketing_insight(payload), ""])

    lines.extend(["## What companies are doing", ""])
    top_signals = payload.get("top_signals", [])
    if top_signals:
        for index, signal in enumerate(top_signals, start=1):
            lines.extend(_signal_lines(index, signal))
    else:
        lines.extend(["No top signals passed the v2 quality gate.", ""])

    lines.extend(["## Watchlist"])
    watchlist = payload.get("watchlist", [])
    if watchlist:
        for signal in watchlist:
            lines.append(f"- {_brief_watchlist_sentence(signal)}")
    else:
        lines.append("- No watchlist items in this preview run.")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def build_market_brief_v2_audit(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_date": payload["run_date"],
        "generated_at": payload["generated_at"],
        "preview_only": True,
        "exa_total_queries": payload["exa_total_queries"],
        "exa_errors_count": payload["exa_errors_count"],
        "exa_timeouts_count": payload["exa_timeouts_count"],
        "raw_results_count": payload["raw_results_count"],
        "unique_results_count": payload["unique_results_count"],
        "kept_signals_count": payload["kept_signals_count"],
        "skipped_signals_count": payload["skipped_signals_count"],
        "watchlist_signals_count": payload["watchlist_signals_count"],
        "candidates": payload.get("audit", []),
        "errors": payload.get("errors", []),
    }


def _public_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in {"audit"}
    }


def _build_v2_query(query: V2Query) -> str:
    return (
        f"{query.query}. Extract one concrete public market development for a B2B mobile adtech company. "
        "Use the source article/page title and canonical public URL; do not invent a Market Brief title or internal "
        "BidMatrix URL. Do not use LinkedIn posts, social profiles, BidMatrix-owned pages, Sage Intacct BidMatrix, "
        "construction estimating pages, or unrelated same-name software as sources. Return only concrete public "
        "developments from the last 30 days when possible. Focus on marketing "
        "and BD usefulness: product launches, partnerships, integrations, funding/IPO/acquisition, reports "
        "with market data, competitor positioning, MMP/measurement changes, fraud/traffic quality, CTV, "
        "in-app supply, AI buying, agentic campaign ops, and creative automation. Skip generic educational "
        "content, evergreen SEO pages, undated resources, and vague narratives. Every signal must include a "
        "specific mobile-adtech marketing or BD angle and a practical suggested action."
    )


def _signals_from_response(response: Any, query: V2Query) -> list[dict[str, Any]]:
    content = getattr(getattr(response, "output", None), "content", None) or {}
    results = getattr(response, "results", None)
    if results:
        return [_signal_from_result(result, query) for result in results if _result_attr(result, "url")]

    if not isinstance(content, dict):
        return []
    if isinstance(content.get("signals"), list):
        raw_signals = content["signals"]
    elif content.get("has_signal") is False:
        raw_signals = []
    else:
        raw_signals = [content]
    items: list[dict[str, Any]] = []
    for raw in raw_signals:
        if not isinstance(raw, dict) or not raw.get("title") or not raw.get("url"):
            continue
        url = str(raw.get("url", "")).strip()
        items.append(
            {
                "title": str(raw.get("title", "")).strip(),
                "url": url,
                "source": _optional_string(raw.get("source")),
                "source_domain": _source_domain(url),
                "published_date": _optional_string(raw.get("published_date")),
                "signal_type": _normalize_signal_type(raw.get("signal_type")),
                "category": _normalize_category(raw.get("category"), query.category),
                "what_happened": _optional_string(raw.get("what_happened")),
                "why_it_matters": _optional_string(raw.get("why_it_matters")),
                "bidmatrix_angle": _optional_string(raw.get("bidmatrix_angle")),
                "suggested_action": _optional_string(raw.get("suggested_action")),
                "confidence": _normalize_confidence(raw.get("confidence")),
                "query_id": query.query_id,
                "query_label": query.label,
            }
        )
    return items


def _signal_from_result(result: Any, query: V2Query) -> dict[str, Any]:
    url = str(_result_attr(result, "url") or "").strip()
    title = str(_result_attr(result, "title") or url).strip()
    highlights = _result_highlights(result)
    text = " ".join(
        value
        for value in (
            title,
            str(_result_attr(result, "summary") or ""),
            str(_result_attr(result, "text") or ""),
            " ".join(highlights),
        )
        if value
    )
    what_happened = _clean_sentence(text) or title
    return {
        "title": title,
        "url": url,
        "source": _optional_string(_result_attr(result, "author")),
        "source_domain": _source_domain(url),
        "published_date": _optional_string(
            _result_attr(result, "published_date") or _result_attr(result, "publishedDate")
        ),
        "signal_type": "other",
        "category": query.category,
        "what_happened": what_happened,
        "why_it_matters": _why_it_matters_from_text(text, query.category),
        "bidmatrix_angle": None,
        "suggested_action": None,
        "confidence": "medium",
        "query_id": query.query_id,
        "query_label": query.label,
    }


def _evaluate_signal(candidate: dict[str, Any]) -> dict[str, Any]:
    item = dict(candidate)
    source_url_valid = _is_valid_public_source_url(item.get("url"))
    synthetic_brief_artifact = _is_synthetic_brief_artifact(item)
    recent_enough = _is_recent_enough(item.get("published_date"))
    signal_type = _infer_signal_type(item)
    category = _infer_category(item)
    item["signal_type"] = signal_type
    item["category"] = category
    relevance_score = _relevance_score(item)
    marketing_value_score = _marketing_value_score(item, signal_type)
    bd_value_score = _bd_value_score(item, signal_type)
    confidence = _confidence(item, relevance_score, marketing_value_score, bd_value_score)
    noise_risk = _noise_risk(item, signal_type)
    total_score = relevance_score + marketing_value_score + bd_value_score - noise_risk

    keep_reason: str | None = None
    skip_reason: str | None = None
    kept = False
    watchlist = False

    if not source_url_valid:
        skip_reason = "invalid_or_self_referential_source"
    elif synthetic_brief_artifact:
        skip_reason = "synthetic_brief_artifact"
    elif not recent_enough:
        skip_reason = "stale_source_date"
    elif noise_risk >= 4:
        skip_reason = "high_noise_risk"
    elif relevance_score < 3:
        if relevance_score >= 2 and marketing_value_score + bd_value_score >= 4 and noise_risk <= 1:
            watchlist = True
            skip_reason = "interesting_but_not_strong_enough"
        else:
            skip_reason = "low_bidmatrix_relevance"
    elif marketing_value_score < 2 and bd_value_score < 2:
        if total_score >= 6 and confidence in {"high", "medium"}:
            watchlist = True
            skip_reason = "interesting_but_not_strong_enough"
        else:
            skip_reason = "low_marketing_bd_value"
    elif total_score >= 9 and confidence in {"high", "medium"}:
        kept = True
        keep_reason = _keep_reason(signal_type)
    elif total_score >= 7:
        watchlist = True
        skip_reason = "interesting_but_not_strong_enough"
    else:
        skip_reason = "weak_or_generic_signal"

    item.update(
        {
            "signal_type": signal_type,
            "category": category,
            "relevance_score": relevance_score,
            "marketing_value_score": marketing_value_score,
            "bd_value_score": bd_value_score,
            "confidence": confidence,
            "keep_reason": keep_reason,
            "skip_reason": skip_reason,
            "kept": kept,
            "watchlist": watchlist,
            "noise_risk": noise_risk,
            "bidmatrix_angle": _clean_sentence(item.get("bidmatrix_angle")) or _fallback_angle(item),
            "suggested_action": _clean_sentence(item.get("suggested_action")) or _fallback_action(item),
        }
    )
    return item


def _signal_lines(index: int, signal: dict[str, Any]) -> list[str]:
    return [
        f"{index}. {_brief_signal_sentence(signal)}",
        f"Marketing insight: {_marketing_insight(signal, index)}",
        f"What BidMatrix can use: {_bidmatrix_use(signal)}",
        f"Content / BD idea: {_content_bd_idea(signal, index)}",
        "",
    ]


KNOWN_COMPANY_NAMES = (
    "AppsFlyer",
    "Adjust",
    "Singular",
    "Branch",
    "Kochava",
    "Airbridge",
    "Tenjin",
    "AppMetrica",
    "AppTweak",
    "Sensor Tower",
    "data.ai",
    "Apptica",
    "MobileAction",
    "SplitMetrics",
    "AppFollow",
    "Moloco",
    "AppLovin",
    "Liftoff",
    "Mintegral",
    "Unity",
    "ironSource",
    "Digital Turbine",
    "Smadex",
    "Jampp",
    "Kayzen",
    "Remerge",
    "YouAppi",
    "StackAdapt",
    "The Trade Desk",
    "PubMatic",
    "Magnite",
    "OpenX",
    "Equativ",
    "Index Exchange",
    "Pixalate",
    "HUMAN",
    "DoubleVerify",
    "Integral Ad Science",
    "IAS",
    "Fraudlogix",
    "GeoEdge",
    "Mfilterit",
    "TrafficGuard",
    "mParticle",
    "Braze",
    "CleverTap",
    "OneSignal",
    "Iterable",
    "MoEngage",
    "RevenueCat",
    "Superwall",
    "Adapty",
    "Qonversion",
    "Amplitude",
    "Mixpanel",
    "Appsumer",
    "Funnel",
    "Adriel",
    "Marin Software",
    "Luna Labs",
    "Geeklab",
    "YellowHEAD",
    "Bidalgo",
    "Consumer Acquisition",
    "AppAgent",
    "Phiture",
    "Growth Gems",
    "Mobile Dev Memo",
    "Business of Apps",
    "Bedrock",
    "Advertible",
    "CloudX",
    "Bigabid",
    "Affle",
    "AdColony",
    "Mobkoi",
    "xpln.ai",
    "Cint",
    "Nexxen",
    "InMobi",
    "BidMachine",
    "Perion",
    "WunderKIND Ads",
    "Wunderkind",
    "TripleLift",
    "Walmart Connect",
    "Verve",
)


MMP_COMPANY_NAMES = {"AppsFlyer", "Adjust", "Singular", "Branch", "Kochava", "Airbridge", "Tenjin", "AppMetrica"}
QUALITY_COMPANY_NAMES = {"Pixalate", "HUMAN", "DoubleVerify", "Integral Ad Science", "IAS", "Fraudlogix", "GeoEdge", "Mfilterit", "TrafficGuard"}


def _display_run_date(run_date: str) -> str:
    try:
        parsed = date.fromisoformat(run_date)
    except ValueError:
        return run_date
    return f"{parsed.strftime('%B')} {parsed.day}, {parsed.year}"


def _today_marketing_insight(payload: dict[str, Any]) -> str:
    signals = payload.get("top_signals", [])
    if not signals:
        return "No strong BidMatrix-relevant marketing insight passed the v2 quality gate."
    categories = {signal.get("category") for signal in signals}
    if "AI / Automation / Agentic UA" in categories and "Measurement / MMP / Attribution" in categories:
        return "AI campaign operations and measurement proof are becoming the main stories competitors want to own in mobile growth. BidMatrix can use this to connect AI, traffic quality, and measurable performance in one clearer narrative."
    if "AI / Automation / Agentic UA" in categories:
        return "Competitors are framing AI as a campaign-operations story, not just an automation feature. BidMatrix can answer with a measurable optimization and traffic-quality narrative."
    if "Measurement / MMP / Attribution" in categories:
        return "Measurement vendors are trying to own full-funnel performance proof. BidMatrix can connect this to transparent ROAS, user quality, and partner-neutral reporting."
    if "Traffic Quality / Fraud / Inventory" in categories:
        return "Verification and quality companies are turning fraud risk into a budget-protection story. BidMatrix can use the same pressure to strengthen verified traffic positioning."
    if "Competitor / Partner Moves" in categories:
        return "Partner moves are creating new ecosystem stories that BD teams can use as timely outreach hooks. BidMatrix can turn them into counter-positioning and partner conversations."
    return "Fresh market signals are creating practical positioning angles for BidMatrix marketing and BD."


def _brief_signal_sentence(signal: dict[str, Any]) -> str:
    company = _signal_company_subject(signal)
    text = _signal_search_text(signal)
    effective_category = _effective_brief_category(signal)
    if _has_terms(text, "mobkoi", "xpln"):
        return "Mobkoi and xpln.ai are framing creative intelligence as part of campaign measurement."
    if company == "Cint" and _has_any(text.lower(), ("brand", "measurement")):
        return "Cint is positioning brand measurement as a performance-marketing input."
    if company == "Nexxen" and "mcp" in text.lower():
        return "Nexxen is building an agentic workflow story around MCP tools."
    if effective_category == "Traffic Quality / Fraud / Inventory" and _has_any(text.lower(), ("fraud", "ivt", "invalid traffic", "traffic quality")):
        return f"{company} is using fraud and inventory-quality risk to strengthen its verification narrative."
    if _is_mmp_company(company) and _has_terms(text, "web", "mobile", "attribution"):
        return f"{company} is expanding the attribution narrative from app-only measurement to full web-to-app performance proof."
    if _has_terms(text, "agentic", "creative") and ("Bedrock" in company or "Advertible" in company):
        return "Bedrock and Advertible are framing AI as an operational loop, not just a creative generator."
    if _has_terms(text, "ctv", "fraud") and ("DoubleVerify" in company or "DV" in text):
        return "DoubleVerify is using CTV fraud research to strengthen the verification narrative."
    if _has_terms(text, "fraud", "benchmark"):
        return f"{company} is turning fraud and traffic-quality benchmarks into a sales narrative."
    if _has_terms(text, "creator marketplace"):
        return f"{company} is positioning creator-led CTV inventory as a new programmatic supply story."
    if _has_terms(text, "cortex") or _has_terms(text, "axon"):
        return f"{company} is pushing AI-led optimization as the core mobile growth narrative."
    if _has_terms(text, "applovin", "integration") or _has_terms(text, "partner", "integration"):
        return f"{company} is using partner integrations to make its growth stack look more connected."
    if _has_terms(text, "acquisition", "adcolony"):
        return f"{company} is using adtech asset consolidation to strengthen its platform story."
    signal_type = signal.get("signal_type")
    if signal_type == "product_launch":
        return f"{company} is using a product launch to claim more of the growth workflow."
    if signal_type == "partnership_integration":
        if effective_category == "AI / Automation / Agentic UA":
            return f"{company} is positioning integrations as the connective tissue for AI campaign workflows."
        if effective_category == "Measurement / MMP / Attribution":
            return f"{company} is using integrations to own more of the attribution and audience workflow."
        return f"{company} is using partnerships to expand its platform narrative."
    if signal_type == "market_report":
        return f"{company} is using market benchmarks to support its sales and positioning story."
    if signal_type == "funding_mna":
        return f"{company} is using a market-structure move to reinforce its platform credibility."
    return f"{company} is testing a market narrative worth monitoring."


def _brief_why_it_matters(signal: dict[str, Any], index: int = 1) -> str:
    category = _effective_brief_category(signal)
    text = _signal_search_text(signal)
    if _is_mmp_company(_signal_company_subject(signal)) and _has_terms(text, "web", "mobile", "attribution"):
        return "MMPs are moving beyond app-only attribution and trying to own the full web-to-app journey."
    if _has_terms(text, "ctv", "fraud"):
        return "As CTV grows, advertisers will need stronger fraud protection and inventory validation."
    if category == "AI / Automation / Agentic UA":
        variants = (
            "AI is moving from standalone tools to workflows that help teams decide, test, and optimize campaigns.",
            "Growth teams are starting to expect AI tools to connect creative decisions with budget and performance feedback.",
            "Agentic campaign tools are becoming a positioning battleground for mobile UA and performance media.",
        )
        return variants[(index - 1) % len(variants)]
    if category == "Measurement / MMP / Attribution":
        return "Advertisers need clearer proof of lift, payback, and performance across channels."
    if category == "Traffic Quality / Fraud / Inventory":
        return "Budget protection depends on cleaner supply, better fraud checks, and stronger traffic validation."
    if category == "Competitor / Partner Moves":
        return "Partner moves can create timely outreach hooks and clearer counter-positioning."
    return _one_sentence(signal.get("why_it_matters") or "It creates a practical marketing and BD signal for BidMatrix.")


def _brief_possible_action(signal: dict[str, Any], index: int = 1) -> str:
    category = _effective_brief_category(signal)
    text = _signal_search_text(signal)
    company = _signal_company_subject(signal)
    if _is_mmp_company(company) and _has_terms(text, "web", "mobile", "attribution"):
        return 'LinkedIn post idea — "Why web-to-app measurement is becoming a key part of mobile growth."'
    if _has_terms(text, "ctv", "fraud") or category == "Traffic Quality / Fraud / Inventory":
        variants = (
            "Website idea — strengthen BidMatrix messaging around traffic quality, anti-fraud protection, and budget safety.",
            'BD talking point — "How are you validating inventory quality before scaling CTV or in-app budgets?"',
        )
        return variants[(index - 1) % len(variants)]
    if category == "AI / Automation / Agentic UA":
        variants = (
            'BD talking point — "Can your current UA setup connect creative performance with budget decisions automatically?"',
            "LinkedIn post idea — explain why AI buying needs closed-loop performance proof, not just faster asset generation.",
            "Partner outreach idea — ask creative or measurement partners where AI workflow data should connect back to UA decisions.",
        )
        return variants[(index - 1) % len(variants)]
    if category == "Measurement / MMP / Attribution":
        return 'BD talking point — "Can your attribution setup prove lift across web, app, and partner channels?"'
    if category == "Competitor / Partner Moves":
        return "Partner outreach idea — use this move as a timely reason to ask how the partner stack is changing."
    return "LinkedIn post idea — turn this signal into a short practical take for app growth teams."


def _marketing_insight(signal: dict[str, Any], index: int = 1) -> str:
    category = _effective_brief_category(signal)
    company = _signal_company_subject(signal)
    text = _signal_search_text(signal)
    if _is_mmp_company(company) and _has_terms(text, "web", "mobile", "attribution"):
        return "MMPs are trying to own more of the growth stack by connecting web, app, and ROAS proof in one story."
    if _has_terms(text, "ctv", "fraud") or category == "Traffic Quality / Fraud / Inventory":
        return "Verification companies are turning fraud risk into a sales argument for stronger traffic validation."
    if _has_terms(text, "agentic", "creative") and ("Bedrock" in company or "Advertible" in company):
        return "The market is moving from “AI makes ads” to “AI helps decide what to test, where to spend, and how to optimize.”"
    if category == "AI / Automation / Agentic UA":
        variants = (
            "AI vendors are trying to own the campaign-operations layer, not just the automation layer.",
            "Creative and media workflows are being packaged as one optimization story.",
            "Agentic UA is becoming a positioning shortcut for control, speed, and measurable performance.",
        )
        return variants[(index - 1) % len(variants)]
    if category == "Measurement / MMP / Attribution":
        return "Measurement companies are using proof, incrementality, and full-funnel attribution to claim more strategic budget influence."
    if category == "Competitor / Partner Moves":
        return "Partner moves are becoming narrative signals: companies want to look more connected, scalable, and ecosystem-friendly."
    return "This signal shows a company trying to turn a product or report into a clearer market position."


def _bidmatrix_use(signal: dict[str, Any]) -> str:
    category = _effective_brief_category(signal)
    company = _signal_company_subject(signal)
    text = _signal_search_text(signal)
    if _is_mmp_company(company) and _has_terms(text, "web", "mobile", "attribution"):
        return "BidMatrix can connect this to transparent performance, ROAS clarity, and measurable user quality."
    if _has_terms(text, "ctv", "fraud") or category == "Traffic Quality / Fraud / Inventory":
        return "BidMatrix can reinforce anti-fraud, verified traffic, and budget-protection messaging for CTV and in-app inventory."
    if _has_terms(text, "agentic", "creative") and ("Bedrock" in company or "Advertible" in company):
        return "BidMatrix should describe AI as part of real UA workflows: creative testing, budget control, traffic quality, and campaign optimization."
    if category == "AI / Automation / Agentic UA":
        return "BidMatrix can frame AI around measurable optimization loops, not generic automation claims."
    if category == "Measurement / MMP / Attribution":
        return "BidMatrix can use this to talk about partner-neutral measurement, performance proof, and quality-aware ROAS."
    if category == "Competitor / Partner Moves":
        return "BidMatrix can use this as a counter-positioning or partner-outreach hook."
    return "BidMatrix can turn this into a short positioning note for marketing and BD."


def _content_bd_idea(signal: dict[str, Any], index: int = 1) -> str:
    category = _effective_brief_category(signal)
    company = _signal_company_subject(signal)
    text = _signal_search_text(signal)
    if _is_mmp_company(company) and _has_terms(text, "web", "mobile", "attribution"):
        return "LinkedIn post: “Why mobile growth is moving from app attribution to full-funnel performance proof.”"
    if _has_terms(text, "ctv", "fraud") or category == "Traffic Quality / Fraud / Inventory":
        return "Website idea: add stronger language around budget protection, verified supply, and fraud-resistant growth."
    if _has_terms(text, "agentic", "creative") and ("Bedrock" in company or "Advertible" in company):
        return "BD talking point: “Is your creative performance data connected to your media-buying decisions?”"
    if category == "AI / Automation / Agentic UA":
        variants = (
            "BD talking point: “Where does AI actually improve your UA workflow today: creative, bids, budget, or quality control?”",
            "LinkedIn post: “AI in mobile growth only matters when it changes optimization decisions.”",
            "Partner outreach: ask creative and measurement partners where workflow data should feed media-buying decisions.",
        )
        return variants[(index - 1) % len(variants)]
    if category == "Measurement / MMP / Attribution":
        return "BD talking point: “Can your current stack prove performance across web, app, ROAS, and user quality?”"
    if category == "Competitor / Partner Moves":
        return "Counter-positioning angle: show where BidMatrix offers a clearer or more transparent path."
    return "LinkedIn post: turn this into a short practical lesson for app growth teams."


def _brief_watchlist_sentence(signal: dict[str, Any]) -> str:
    company = _signal_company_subject(signal)
    text = _signal_search_text(signal)
    if _has_terms(text, "agentic", "buying"):
        return f"{company} is building agentic mobile UA buying tools."
    if _has_terms(text, "axon") or _has_terms(text, "ai-led", "growth"):
        return f"{company} continues to push AI-led growth narratives."
    if _has_terms(text, "rtb fabric") or _has_terms(text, "ml", "dsp"):
        return f"{company} is positioning around ML-powered DSP infrastructure."
    if signal.get("category") == "Measurement / MMP / Attribution":
        return f"{company} is worth watching for measurement and attribution positioning."
    if signal.get("category") == "Traffic Quality / Fraud / Inventory":
        return f"{company} is worth watching for traffic-quality and fraud signals."
    return f"{company} is worth watching for a clearer BidMatrix-relevant move."


def _effective_brief_category(signal: dict[str, Any]) -> str:
    company = _signal_company_subject(signal)
    text = _signal_search_text(signal).lower()
    if _is_quality_company(company) or _has_any(text, ("fraud", "ivt", "invalid traffic", "traffic quality", "inventory validation")):
        return "Traffic Quality / Fraud / Inventory"
    return str(signal.get("category") or "")


def _is_mmp_company(company: str) -> bool:
    return company.lower() in {name.lower() for name in MMP_COMPANY_NAMES}


def _is_quality_company(company: str) -> bool:
    return company.lower() in {name.lower() for name in QUALITY_COMPANY_NAMES}


def _signal_company_subject(signal: dict[str, Any]) -> str:
    text = _signal_search_text(signal)
    matches = [name for name in KNOWN_COMPANY_NAMES if re.search(rf"\b{re.escape(name)}\b", text, flags=re.IGNORECASE)]
    if "Bedrock" in matches and "Advertible" in matches:
        return "Bedrock and Advertible"
    if "Affle" in matches and "AdColony" in matches:
        return "Affle"
    if matches:
        return matches[0]
    source = str(signal.get("source") or "").strip()
    if source and not _looks_like_publisher_or_author(source):
        return source
    return _clean_company_from_title(str(signal.get("title") or "A company"))


def _signal_search_text(signal: dict[str, Any]) -> str:
    return " ".join(
        str(signal.get(key) or "")
        for key in ("title", "source", "source_domain", "what_happened", "why_it_matters", "bidmatrix_angle", "suggested_action")
    )


def _has_terms(text: str, *terms: str) -> bool:
    lower_text = text.lower()
    return all(term.lower() in lower_text for term in terms)


def _looks_like_publisher_or_author(source: str) -> bool:
    lower_source = source.lower()
    if " " in source and not any(name.lower() in lower_source for name in KNOWN_COMPANY_NAMES):
        return True
    return any(
        marker in lower_source
        for marker in (
            "wire",
            "news",
            "pressbox",
            "morningstar",
            "businesswire",
            "globenewswire",
            "ppc.land",
            "exchange",
            "adexchanger",
        )
    )


def _clean_company_from_title(title: str) -> str:
    cleaned = re.split(r"\s[-|]\s", title, maxsplit=1)[0]
    cleaned = re.sub(r"^(global study|report|study):\s*", "", cleaned, flags=re.IGNORECASE)
    words = cleaned.split()
    return " ".join(words[:3]) if words else "A company"


def _one_sentence(text: str) -> str:
    sentence = re.split(r"(?<=[.!?])\s+", str(text).strip(), maxsplit=1)[0]
    return sentence.rstrip(".") + "."


def _sections(signals: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    headings = (
        "Competitor / Partner Moves",
        "Measurement / MMP / Attribution",
        "Traffic Quality / Fraud / Inventory",
        "AI / Automation / Agentic UA",
    )
    return {heading: [item for item in signals if item["category"] == heading] for heading in headings}


def _executive_summary(signals: list[dict[str, Any]]) -> dict[str, str]:
    if not signals:
        return {}
    category_counts: dict[str, int] = {}
    for signal in signals:
        category_counts[signal["category"]] = category_counts.get(signal["category"], 0) + 1
    top_categories = sorted(category_counts.items(), key=lambda item: (-item[1], item[0]))[:3]
    top_category, top_count = top_categories[0]
    lead_signals = ", ".join(_plain_signal_theme(signal) for signal in signals[:3])
    if top_count / len(signals) >= 0.6:
        coverage_note = (
            f"This run is {_category_short_label(top_category)}-heavy: "
            f"{top_count} of {len(signals)} kept signals sit in that theme. Thin categories are not being force-filled."
        )
    else:
        coverage_note = (
            "Strongest signals are spread across "
            + ", ".join(category for category, _count in top_categories)
            + "; categories with no strong items are left empty."
        )
    return {
        "what_changed": f"{lead_signals} are the strongest public signals in this preview run.",
        "why_it_matters": _summary_why_it_matters(signals, top_category),
        "what_bidmatrix_should_do": _summary_recommendation(signals, top_category),
        "coverage_note": coverage_note,
    }


def _so_what(signals: list[dict[str, Any]]) -> list[str]:
    bullets: list[str] = []
    categories = {signal["category"] for signal in signals}
    if "AI / Automation / Agentic UA" in categories:
        bullets.append(
            "AI buying and creative automation are becoming table stakes; BidMatrix should frame its AI story around measurable optimization loops, not generic automation."
        )
    if "Measurement / MMP / Attribution" in categories:
        bullets.append(
            "Measurement players are pushing web-to-app, incrementality, and partner-neutral proof; BidMatrix can connect this to transparent performance and ROAS/LTV clarity."
        )
    if "Traffic Quality / Fraud / Inventory" in categories:
        bullets.append(
            "Fraud and inventory-quality signals should feed BidMatrix's verified-supply, anti-fraud, and budget-protection positioning."
        )
    if "Competitor / Partner Moves" in categories:
        bullets.append(
            "Competitor and partner moves are useful outreach triggers; BD can reference them as timely context rather than cold generic check-ins."
        )
    return bullets[:4]


def _summary_why_it_matters(signals: list[dict[str, Any]], top_category: str) -> str:
    if top_category == "AI / Automation / Agentic UA":
        return (
            "The market is moving from point automation toward agentic campaign operations, creative testing, and optimization loops that buyers will expect to connect to measurable performance."
        )
    if top_category == "Measurement / MMP / Attribution":
        return (
            "Measurement vendors are competing on proof quality, cross-channel attribution, and incrementality, which raises buyer expectations for transparent performance evidence."
        )
    if top_category == "Traffic Quality / Fraud / Inventory":
        return (
            "Advertisers are treating verified supply, fraud resistance, and CTV/in-app quality as budget-protection requirements rather than back-office checks."
        )
    if top_category == "Competitor / Partner Moves":
        return (
            "Partner and competitor moves create practical hooks for BD outreach, counter-positioning, and ecosystem monitoring."
        )
    return f"{len(signals)} kept signals point to a focused market shift that BidMatrix can use for marketing and BD."


def _summary_recommendation(signals: list[dict[str, Any]], top_category: str) -> str:
    if top_category == "AI / Automation / Agentic UA":
        return (
            "Package BidMatrix's AI narrative around measurable UA workflows: campaign ops, creative testing, budget control, and optimization proof."
        )
    if top_category == "Measurement / MMP / Attribution":
        return (
            "Tie product messaging to partner-neutral attribution, web-to-app measurement, incrementality, and ROAS/LTV clarity."
        )
    if top_category == "Traffic Quality / Fraud / Inventory":
        return (
            "Use these signals to sharpen verified traffic, anti-fraud, inventory-quality, and CTV/in-app validation positioning."
        )
    if top_category == "Competitor / Partner Moves":
        return (
            "Turn the strongest move into a BD trigger: who changed, what it signals, and how BidMatrix can offer an alternative or complementary path."
        )
    return "Use the strongest signal as a concise internal talking point and test one content/BD angle before expanding the theme."


def _plain_signal_theme(signal: dict[str, Any]) -> str:
    title = str(signal.get("title") or "").split(" | ", 1)[0].split(" - ", 1)[0]
    return title.strip() or str(signal.get("source_domain") or "market signal")


def _category_short_label(category: str) -> str:
    return {
        "AI / Automation / Agentic UA": "AI/agentic",
        "Measurement / MMP / Attribution": "measurement",
        "Traffic Quality / Fraud / Inventory": "traffic-quality",
        "Competitor / Partner Moves": "competitor/partner",
    }.get(category, category.lower())


def _recommended_actions(signals: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    if not signals:
        return actions
    first = signals[0]
    actions.append(f"LinkedIn post idea: { _linkedin_post_idea(first) }")
    actions.append(f"BD talking point: { _bd_talking_point(first) }")
    outreach_signal = _first_signal_in_category(signals, "Competitor / Partner Moves") or signals[min(1, len(signals) - 1)]
    actions.append(f"Partner outreach idea: { _partner_outreach_idea(outreach_signal) }")
    positioning_signal = _first_signal_in_category(signals, "Measurement / MMP / Attribution") or first
    actions.append(f"Website/positioning idea: { _website_positioning_idea(positioning_signal) }")
    return actions[:5]


def _first_signal_in_category(signals: list[dict[str, Any]], category: str) -> dict[str, Any] | None:
    return next((signal for signal in signals if signal["category"] == category), None)


def _linkedin_post_idea(signal: dict[str, Any]) -> str:
    category = signal["category"]
    if category == "AI / Automation / Agentic UA":
        return "publish a short take on why agentic UA needs measurable optimization loops, not just another automation claim."
    if category == "Measurement / MMP / Attribution":
        return "explain why web-to-app and incrementality proof matter when performance teams compare partner-neutral attribution options."
    if category == "Traffic Quality / Fraud / Inventory":
        return "turn the signal into a practical post on protecting UA budgets with verified supply and quality traffic checks."
    if category == "Competitor / Partner Moves":
        return f"use {signal.get('source_domain') or 'this source'} as a timely hook for what the partner ecosystem is telling advertisers."
    return f"turn {_plain_signal_theme(signal)} into a concise market note for app growth teams."


def _bd_talking_point(signal: dict[str, Any]) -> str:
    category = signal["category"]
    if category == "AI / Automation / Agentic UA":
        return "ask prospects how they measure AI-driven campaign changes across bidding, creative testing, and budget allocation."
    if category == "Measurement / MMP / Attribution":
        return "ask whether their current stack can connect web-to-app journeys, incrementality, and ROAS/LTV proof without platform bias."
    if category == "Traffic Quality / Fraud / Inventory":
        return "ask how they verify CTV/in-app supply quality before scaling budgets, and where fraud checks enter optimization."
    if category == "Competitor / Partner Moves":
        return "use the move as a reason to compare BidMatrix's position against the prospect's current partner mix."
    return signal["suggested_action"]


def _partner_outreach_idea(signal: dict[str, Any]) -> str:
    source = signal.get("source_domain") or "the source"
    if signal["category"] == "Measurement / MMP / Attribution":
        return f"use {source} to start a partner conversation around attribution proof, incrementality, and shared reporting gaps."
    if signal["category"] == "AI / Automation / Agentic UA":
        return f"use {source} to ask partners where AI-assisted bidding or creative workflows need clearer measurement hooks."
    if signal["category"] == "Traffic Quality / Fraud / Inventory":
        return f"use {source} to ask supply or verification partners how they prove quality before budget scaling."
    return f"use {source} as a warm context point for a focused ecosystem check-in."


def _website_positioning_idea(signal: dict[str, Any]) -> str:
    if signal["category"] == "Measurement / MMP / Attribution":
        return "add a proof point around partner-neutral attribution, web-to-app visibility, and ROAS/LTV clarity."
    if signal["category"] == "AI / Automation / Agentic UA":
        return "tighten AI copy around measurable optimization workflows: bidding, creative testing, controls, and outcomes."
    if signal["category"] == "Traffic Quality / Fraud / Inventory":
        return "make verified traffic, fraud-aware optimization, and inventory validation more visible in programmatic/CTV messaging."
    if signal["category"] == "Competitor / Partner Moves":
        return "add a comparison-friendly line that clarifies where BidMatrix fits in the partner ecosystem."
    return "turn the strongest signal into one concrete proof point on the website."


def _dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_url: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        key = _normalized_url(candidate["url"])
        existing = by_url.get(key)
        if existing is None or len(str(candidate.get("why_it_matters") or "")) > len(str(existing.get("why_it_matters") or "")):
            by_url[key] = candidate
    return list(by_url.values())


def _dedupe_related_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    output: list[dict[str, Any]] = []
    for signal in signals:
        key = _related_signal_key(signal)
        if not key:
            output.append(_with_source_fields(signal, []))
            continue
        grouped.setdefault(key, []).append(signal)

    for group in grouped.values():
        primary = min(group, key=_primary_source_rank)
        secondary = [item for item in group if item is not primary]
        output.append(_with_source_fields(primary, secondary))

    return sorted(output, key=_rank_key)


def _apply_compact_markdown_quality_gate(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for signal in signals:
        item = dict(signal)
        if item.get("kept") and _is_awkward_action_sentence(_brief_signal_sentence(item)):
            item["kept"] = False
            item["watchlist"] = True
            item["keep_reason"] = None
            item["skip_reason"] = "awkward_action_sentence"
        if (item.get("kept") or item.get("watchlist")) and _has_malformed_rendered_subject(item):
            item["kept"] = False
            item["watchlist"] = False
            item["keep_reason"] = None
            item["skip_reason"] = "malformed_subject"
        output.append(item)
    return output


def _dedupe_brief_top_signals(signals: list[dict[str, Any]], *, limit: int | None = None) -> tuple[list[dict[str, Any]], set[str]]:
    seen_keys: set[str] = set()
    seen_sentences: set[str] = set()
    output: list[dict[str, Any]] = []
    duplicate_urls: set[str] = set()
    for signal in signals:
        keys = _brief_signal_keys(signal)
        sentence = _normalize_text(_brief_signal_sentence(signal))
        duplicate = bool(keys & seen_keys) or sentence in seen_sentences
        if duplicate or (limit is not None and len(output) >= limit):
            duplicate_urls.add(str(signal.get("url") or ""))
            continue
        seen_keys.update(keys)
        seen_sentences.add(sentence)
        output.append(signal)
    return output, duplicate_urls


def _mark_duplicate_top_signals(signals: list[dict[str, Any]], duplicate_urls: set[str]) -> list[dict[str, Any]]:
    if not duplicate_urls:
        return signals
    output: list[dict[str, Any]] = []
    for signal in signals:
        item = dict(signal)
        if str(item.get("url") or "") in duplicate_urls:
            item["kept"] = False
            item["watchlist"] = False
            item["keep_reason"] = None
            item["skip_reason"] = "duplicate_top_signal"
        output.append(item)
    return output


def _dedupe_watchlist_items(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items, _duplicate_urls = _dedupe_watchlist_items_with_duplicate_urls(signals)
    return items


def _dedupe_watchlist_items_with_duplicate_urls(
    signals: list[dict[str, Any]],
    *,
    limit: int | None = None,
) -> tuple[list[dict[str, Any]], set[str]]:
    seen_keys: set[str] = set()
    seen_bullets: set[str] = set()
    output: list[dict[str, Any]] = []
    duplicate_urls: set[str] = set()
    for signal in signals:
        keys = _brief_watchlist_keys(signal)
        bullet = _normalize_text(_brief_watchlist_sentence(signal))
        duplicate = bool(keys & seen_keys) or bullet in seen_bullets
        if duplicate or (limit is not None and len(output) >= limit):
            duplicate_urls.add(str(signal.get("url") or ""))
            continue
        seen_keys.update(keys)
        seen_bullets.add(bullet)
        output.append(signal)
    return output, duplicate_urls


def _mark_duplicate_watchlist_items(signals: list[dict[str, Any]], duplicate_urls: set[str]) -> list[dict[str, Any]]:
    if not duplicate_urls:
        return signals
    output: list[dict[str, Any]] = []
    for signal in signals:
        item = dict(signal)
        if str(item.get("url") or "") in duplicate_urls:
            item["kept"] = False
            item["watchlist"] = False
            item["keep_reason"] = None
            item["skip_reason"] = "duplicate_watchlist_item"
        output.append(item)
    return output


def _brief_signal_key(signal: dict[str, Any]) -> str:
    return next(iter(sorted(_brief_signal_keys(signal))))


def _brief_signal_keys(signal: dict[str, Any]) -> set[str]:
    company = _normalize_text(_signal_company_subject(signal))
    signal_type = _normalize_text(signal.get("signal_type"))
    theme = _brief_theme_key(signal)
    keys = {f"{company}:{signal_type}:{theme}"}
    if theme == "market_structure":
        keys.add(f"{company}:{theme}")
    return keys


def _brief_watchlist_key(signal: dict[str, Any]) -> str:
    return next(iter(sorted(_brief_watchlist_keys(signal))))


def _brief_watchlist_keys(signal: dict[str, Any]) -> set[str]:
    company = _normalize_text(_signal_company_subject(signal))
    theme = _brief_theme_key(signal)
    bullet = _normalize_text(_brief_watchlist_sentence(signal))
    return {f"{company}:{theme}", f"bullet:{bullet}"}


def _brief_theme_key(signal: dict[str, Any]) -> str:
    text = _signal_search_text(signal).lower()
    if _has_any(text, ("ipo", "funding", "raises", "raised", "acquisition", "acquires", "acquired", "market-structure", "market structure")):
        return "market_structure"
    if _has_terms(text, "web", "mobile", "attribution"):
        return "web_mobile_attribution"
    if _has_any(text, ("fraud", "ivt", "invalid traffic", "traffic quality")):
        return "traffic_quality_fraud"
    if _has_any(text, ("agentic", "creative", "axon", "cortex", "mcp")):
        return "ai_campaign_ops"
    if _has_any(text, ("partner", "integration", "integrates", "connected")):
        return "partner_integration"
    return _normalize_text(str(signal.get("title") or ""))[:80]


def _is_awkward_action_sentence(sentence: str) -> bool:
    lowered = sentence.lower()
    awkward_patterns = (
        "launches launched",
        "launched launched",
        "merges brand connected",
        "launches mcp connected",
        "connected connected",
        "connected two parts of the growth stack",
    )
    return any(pattern in lowered for pattern in awkward_patterns)


def _has_malformed_rendered_subject(signal: dict[str, Any]) -> bool:
    subject = _rendered_subject(signal)
    if not subject:
        return True
    if _is_known_rendered_subject(subject):
        return False
    normalized = _normalize_text(subject)
    if normalized in {
        "ad techs next",
        "ad tech next",
        "agentic ad tech the",
        "agentic adtech the",
        "retail medias hidden",
        "retail media hidden",
        "the",
        "a",
    }:
        return True
    if re.match(r"^(retail media|ad tech|agentic ad-tech|agentic adtech|the|a|how|why|what)\b", subject, flags=re.IGNORECASE):
        return True
    if ":" in subject:
        return True
    if re.search(r"\b(releases|launches|announces|introduces|expands|rolls out|unveils)\b", subject, flags=re.IGNORECASE):
        return True
    if re.search(r"(?:'s|’s)\s+\w+", subject):
        return True
    if re.search(r"\b(ad|ads|first-party|hidden|next|report|study|market|media|performance)$", subject, flags=re.IGNORECASE):
        return True
    if len(subject.split()) > 4 and not any(name.lower() in subject.lower() for name in KNOWN_COMPANY_NAMES):
        return True
    return False


def _is_known_rendered_subject(subject: str) -> bool:
    normalized_subject = _normalize_text(subject)
    return any(normalized_subject == _normalize_text(name) for name in KNOWN_COMPANY_NAMES)


def _rendered_subject(signal: dict[str, Any]) -> str:
    sentence = _brief_signal_sentence(signal)
    match = re.match(
        r"(.+?)\s+(?:is|are)\s+(?:expanding|framing|using|building|positioning|pushing|turning|testing|exploring|trying)\b",
        sentence,
    )
    if match:
        return match.group(1).strip()
    match = re.match(r"(.+?)\s+(?:connected|published|highlighted|shared|announced|introduced|launched|updated|added|made)\b", sentence)
    if match:
        return match.group(1).strip()
    return sentence.split(" is ", 1)[0].strip()


def _with_source_fields(primary: dict[str, Any], secondary: list[dict[str, Any]]) -> dict[str, Any]:
    item = dict(primary)
    item["primary_source"] = _source_ref(primary)
    item["secondary_sources"] = [_source_ref(source) for source in secondary]
    return item


def _source_ref(signal: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": signal.get("title"),
        "url": signal.get("url"),
        "source_domain": signal.get("source_domain"),
        "published_date": signal.get("published_date"),
    }


def _primary_source_rank(signal: dict[str, Any]) -> tuple[int, tuple[int, int, int, str], int]:
    return _source_quality_rank(signal), _rank_key(signal), len(str(signal.get("title") or ""))


def _source_quality_rank(signal: dict[str, Any]) -> int:
    domain = str(signal.get("source_domain") or "").lower()
    company = _company_key(signal)
    official_domains = {
        "appsflyer": ("appsflyer.com",),
        "doubleverify": ("doubleverify.com",),
        "pubmatic": ("pubmatic.com",),
        "unity": ("unity.com",),
        "adjust": ("adjust.com",),
        "singular": ("singular.net",),
        "branch": ("branch.io",),
        "kochava": ("kochava.com",),
        "airbridge": ("airbridge.io",),
        "moloco": ("moloco.com",),
    }
    if company and any(domain == value or domain.endswith(f".{value}") for value in official_domains.get(company, ())):
        return 0
    if domain in {"adexchanger.com", "exchangewire.com", "marketech-apac.com"}:
        return 1
    if domain in {"ppc.land", "businessofapps.com", "digiday.com"}:
        return 2
    return 3


def _related_signal_key(signal: dict[str, Any]) -> str | None:
    company = _company_key(signal)
    topic = _topic_key(signal)
    if not company or not topic:
        return None
    return f"{company}:{topic}"


def _company_key(signal: dict[str, Any]) -> str | None:
    text = _content_text(signal)
    domain = str(signal.get("source_domain") or "").lower()
    companies = {
        "doubleverify": ("doubleverify", "double verify", "dv neura"),
        "appsflyer": ("appsflyer",),
        "pubmatic": ("pubmatic",),
        "unity": ("unity", "ironsource"),
        "adzymic": ("adzymic", "agenx"),
        "bedrock": ("bedrock", "advertible"),
        "cloudx": ("cloudx",),
        "google": ("google", "gemini", "asset studio"),
        "pixalate": ("pixalate",),
        "human": ("human security",),
        "moloco": ("moloco",),
    }
    for company, needles in companies.items():
        if any(needle in text or needle in domain for needle in needles):
            return company
    return None


def _topic_key(signal: dict[str, Any]) -> str | None:
    text = _content_text(signal)
    topics = {
        "dv_neura": ("dv neura", "dynamic ai engine", "neura"),
        "agenx": ("agenx", "creative agent"),
        "asset_studio": ("asset studio", "gemini omni", "1-click creative testing"),
        "web_performance_measurement": ("web performance measurement", "web and mobile attribution"),
        "decision_fabric": ("decision fabric",),
        "creator_marketplace": ("creator marketplace",),
        "cloudx_agentic_buying": ("cloudx", "black-box mobile ua"),
        "bedrock_advertible": ("bedrock", "advertible", "agentic loop"),
        "unity_vector_roas": ("vector-based roas", "player value"),
        "ad_fraud_benchmark": ("ad fraud benchmark", "invalid traffic", "ivt"),
    }
    for topic, needles in topics.items():
        if any(needle in text for needle in needles):
            return topic
    return None


def _infer_signal_type(item: dict[str, Any]) -> str:
    text = _content_text(item)
    provided = _normalize_signal_type(item.get("signal_type"))
    if _has_any(text, ("ipo", "funding", "raises", "raised", "acquisition of", "acquires", "acquired")):
        return "funding_mna"
    if _has_any(text, ("partner", "partnership", "integration", "integrates", "integrated", "connection", "connector", "sync")):
        return "partnership_integration"
    if _has_ai_signal(text):
        return "ai_automation"
    if _has_any(text, ("launch", "launched", "introduces", "introduced", "rolls out")):
        return "product_launch"
    if _has_any(text, ("report", "benchmark", "study", "index", "survey")):
        return "market_report"
    if _has_any(text, ("fraud", "invalid traffic", "ivt", "brand safety", "inventory quality")):
        return "fraud_quality"
    if provided != "other":
        return provided
    return "other"


def _infer_category(item: dict[str, Any]) -> str:
    text = _content_text(item)
    category = _normalize_category(item.get("category"), "")
    if _has_ai_signal(text) or "media buying" in text:
        return "AI / Automation / Agentic UA"
    if _has_any(text, ("appsflyer", "adjust", "singular", "branch", "kochava", "airbridge", "tenjin", "attribution", "measurement", "mmp", "skan", "incrementality")):
        return "Measurement / MMP / Attribution"
    if _has_any(text, ("fraud", "invalid traffic", "ivt", "pixalate", "human", "doubleverify", "ias", "inventory", "ctv", "supply")):
        return "Traffic Quality / Fraud / Inventory"
    if category:
        return category
    return "Competitor / Partner Moves"


def _relevance_score(item: dict[str, Any]) -> int:
    text = _content_text(item)
    score = 0
    if _has_any(text, ("mobile", "app", "adtech", "advertising", "ua", "user acquisition", "programmatic")):
        score += 2
    if _has_any(text, ("measurement", "attribution", "mmp", "skan", "incrementality", "privacy")):
        score += 2
    if _has_any(text, ("fraud", "traffic quality", "ctv", "inventory", "supply")) or _has_ai_signal(text):
        score += 2
    if _has_any(text, ("bidmatrix", "marketing", "bd", "sales", "positioning", "content")):
        score += 1
    return min(score, 5)


def _marketing_value_score(item: dict[str, Any], signal_type: str) -> int:
    text = _content_text(item)
    score = 0
    if signal_type in {"product_launch", "partnership_integration", "funding_mna", "market_report", "ai_automation"}:
        score += 2
    if _has_any(text, ("positioning", "narrative", "report", "benchmark", "market data", "case study")):
        score += 1
    if _has_any(text, ("linkedin", "content", "website", "pr", "commentary")):
        score += 1
    return min(score, 4)


def _bd_value_score(item: dict[str, Any], signal_type: str) -> int:
    text = _content_text(item)
    score = 0
    if signal_type in {"partnership_integration", "funding_mna", "product_launch", "ai_automation"}:
        score += 2
    if _has_any(text, ("partner", "outreach", "sales", "bd", "customer", "advertiser", "agency")):
        score += 1
    if _has_any(text, ("integration", "migration", "benchmark", "competitive", "competitor")):
        score += 1
    return min(score, 4)


def _noise_risk(item: dict[str, Any], signal_type: str) -> int:
    text = _content_text(item)
    url = str(item.get("url") or "").lower()
    risk = 0
    if _has_any(text, ("ultimate guide", "best practices", "how to", "what is ", "glossary")):
        risk += 2
    if _has_any(url, ("/tag/", "/category/", "/glossary/", "/resources/")) and signal_type == "other":
        risk += 1
    if not item.get("bidmatrix_angle") or not item.get("suggested_action"):
        risk += 1
    return min(risk, 5)


def _confidence(item: dict[str, Any], relevance: int, marketing: int, bd: int) -> str:
    raw = _normalize_confidence(item.get("confidence"))
    if raw == "high" and relevance >= 4:
        return "high"
    if relevance + marketing + bd >= 9:
        return "high"
    if relevance + marketing + bd >= 7:
        return "medium"
    return "low"


def _keep_reason(signal_type: str) -> str:
    return {
        "product_launch": "clear_product_or_platform_move",
        "partnership_integration": "clear_partner_or_integration_move",
        "funding_mna": "clear_market_structure_move",
        "market_report": "fresh_market_data_with_positioning_value",
        "fraud_quality": "clear_traffic_quality_signal",
        "ai_automation": "clear_ai_or_automation_signal",
    }.get(signal_type, "clear_bidmatrix_relevance")


def _fallback_angle(item: dict[str, Any]) -> str:
    category = item["category"]
    signal_type = item["signal_type"]
    if category == "AI / Automation / Agentic UA":
        if signal_type == "partnership_integration":
            return "This points to agentic campaign workflows becoming integrated across buying and creative stacks, giving BidMatrix a sharper AI operations positioning hook."
        return "This gives BidMatrix a way to frame AI around measurable UA optimization, creative testing, and campaign-control loops."
    if category == "Measurement / MMP / Attribution":
        return "This supports BidMatrix messaging around partner-neutral measurement proof, web-to-app visibility, incrementality, and ROAS/LTV clarity."
    if category == "Traffic Quality / Fraud / Inventory":
        return "This reinforces BidMatrix positioning around verified supply, fraud-aware optimization, quality traffic, and budget protection."
    if category == "Competitor / Partner Moves":
        return "This creates a counter-positioning and BD outreach trigger around how the partner ecosystem is shifting."
    return f"This gives BidMatrix a concrete marketing and BD angle on {category.lower()}."


def _fallback_action(item: dict[str, Any]) -> str:
    category = item["category"]
    if category == "AI / Automation / Agentic UA":
        return "Use this to start a sales conversation about how prospects measure AI-driven bidding, creative testing, and optimization changes."
    if category == "Measurement / MMP / Attribution":
        return "Use this as a BD prompt about attribution proof, incrementality, web-to-app measurement, and ROAS/LTV reporting gaps."
    if category == "Traffic Quality / Fraud / Inventory":
        return "Use this as a buyer-facing prompt about verified traffic, fraud checks, CTV/in-app validation, and budget protection."
    if category == "Competitor / Partner Moves":
        return "Use this as a partner or competitor-monitoring hook for a targeted outreach note."
    return f"Use this as a short internal talking point for {category.lower()} outreach."


def _why_it_matters_from_text(text: str, category: str) -> str:
    normalized = _normalize_text(text)
    if "agentic" in normalized or _has_ai_signal(normalized):
        return "AI-driven campaign operations are becoming a sharper competitive theme for mobile growth teams."
    if _has_any(normalized, ("attribution", "measurement", "incrementality", "skan", "privacy")):
        return "Measurement fragmentation is creating new proof, reporting, and budget-allocation pressure for advertisers."
    if _has_any(normalized, ("fraud", "invalid traffic", "ivt", "inventory", "ctv")):
        return "Traffic quality and inventory transparency remain practical buying criteria for performance marketers."
    if _has_any(normalized, ("partnership", "integration", "partner", "launch")):
        return "A concrete partner or product move gives BidMatrix a timely sales and positioning hook."
    return f"This is a recent {category.lower()} signal that may matter for BidMatrix marketing and BD."


def _rank_key(item: dict[str, Any]) -> tuple[int, int, int, str]:
    total = item["relevance_score"] + item["marketing_value_score"] + item["bd_value_score"] - item["noise_risk"]
    confidence_rank = {"high": 0, "medium": 1, "low": 2}.get(item["confidence"], 2)
    return -total, confidence_rank, item["noise_risk"], item["title"].lower()


def _normalize_signal_type(value: Any) -> str:
    text = _normalize_token(value)
    aliases = {
        "ai_marketing": "ai_automation",
        "ai_buying": "ai_automation",
        "funding": "funding_mna",
        "ipo": "funding_mna",
        "acquisition": "funding_mna",
        "partner_signal": "partnership_integration",
        "partnership": "partnership_integration",
        "integration": "partnership_integration",
        "platform_update": "product_launch",
        "privacy_measurement": "measurement_change",
        "fraud_quality": "fraud_quality",
    }
    normalized = aliases.get(text, text or "other")
    return normalized if normalized in ALLOWED_SIGNAL_TYPES else "other"


def _normalize_category(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    allowed = {
        "Competitor / Partner Moves",
        "Measurement / MMP / Attribution",
        "Traffic Quality / Fraud / Inventory",
        "AI / Automation / Agentic UA",
    }
    if text in allowed:
        return text
    return fallback if fallback in allowed else ""


def _normalize_confidence(value: Any) -> str:
    text = _normalize_token(value)
    return text if text in {"high", "medium", "low"} else "medium"


def _result_attr(result: Any, name: str) -> Any:
    if isinstance(result, dict):
        return result.get(name)
    return getattr(result, name, None)


def _result_highlights(result: Any) -> list[str]:
    raw = _result_attr(result, "highlights") or []
    if isinstance(raw, str):
        return [raw]
    if not isinstance(raw, list):
        return []
    highlights: list[str] = []
    for value in raw:
        if isinstance(value, str):
            highlights.append(value)
        elif isinstance(value, dict):
            text = value.get("text") or value.get("highlight")
            if text:
                highlights.append(str(text))
        else:
            text = getattr(value, "text", None) or getattr(value, "highlight", None)
            if text:
                highlights.append(str(text))
    return highlights


def _combined_text(item: dict[str, Any]) -> str:
    return _normalize_text(
        " ".join(
            str(item.get(key) or "")
            for key in (
                "title",
                "what_happened",
                "why_it_matters",
                "bidmatrix_angle",
                "suggested_action",
                "category",
                "signal_type",
            )
        )
    )


def _content_text(item: dict[str, Any]) -> str:
    return _normalize_text(
        " ".join(
            str(item.get(key) or "")
            for key in (
                "title",
                "source",
                "source_domain",
                "what_happened",
                "why_it_matters",
                "bidmatrix_angle",
                "suggested_action",
            )
        )
    )


def _clean_sentence(value: Any) -> str | None:
    text = _optional_string(value)
    if not text:
        return None
    text = re.sub(r"\s+", " ", text)
    sentences = re.split(r"(?<=[.!?])\s+", text)
    cleaned = sentences[0].strip() if sentences else text
    if len(re.sub(r"[^A-Za-z]+", "", cleaned)) < 12:
        return None
    return cleaned


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _source_domain(url: str) -> str | None:
    return urlparse(url).netloc.lower().removeprefix("www.") or None


def _source_label(signal: dict[str, Any]) -> str:
    return str(signal.get("source") or signal.get("source_domain") or "source").strip()


def _is_valid_public_source_url(value: Any) -> bool:
    url = str(value or "").strip()
    if ";" in url or re.search(r"\s", url):
        return False
    parsed = urlparse(url)
    domain = parsed.netloc.lower().removeprefix("www.")
    if parsed.scheme not in {"http", "https"} or not domain:
        return False
    if not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", domain):
        return False
    blocked_domains = {
        "bidmatrix.com",
        "bidmatrix.ai",
        "bid-matrix.com",
        "linkedin.com",
        "instagram.com",
        "youtube.com",
        "facebook.com",
        "x.com",
    }
    blocked_suffixes = (
        ".bidmatrix.com",
        ".bidmatrix.ai",
        ".bid-matrix.com",
        ".linkedin.com",
        ".instagram.com",
        ".youtube.com",
        ".facebook.com",
        ".x.com",
    )
    if domain in blocked_domains or domain.endswith(blocked_suffixes):
        return False
    if "bidmatrix" in domain:
        return False
    return True


def _is_synthetic_brief_artifact(item: dict[str, Any]) -> bool:
    title = _normalize_text(item.get("title"))
    return (
        "market brief v2" in title
        or title.startswith("bidmatrix strategic market brief")
        or title.startswith("strategic market brief:")
    )


def _is_recent_enough(value: Any) -> bool:
    text = _optional_string(value)
    if not text:
        return True
    try:
        published = date.fromisoformat(text[:10])
    except ValueError:
        return True
    today = date.today()
    return today - timedelta(days=MAX_SOURCE_AGE_DAYS) <= published <= today + timedelta(days=7)


def _normalized_url(url: str) -> str:
    return str(url).split("?", 1)[0].rstrip("/").replace("/amp", "")


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _normalize_token(value: Any) -> str:
    return _normalize_text(value).replace("-", "_").replace(" ", "_")


def _has_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def _has_ai_signal(text: str) -> bool:
    return bool(re.search(r"\bai\b", text)) or _has_any(
        text,
        (
            "agentic",
            "automation",
            "automate",
            "automated",
            "autonomous",
            "creative optimization",
        ),
    )
