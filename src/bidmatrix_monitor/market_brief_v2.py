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
MAX_WATCHLIST_ITEMS = 4
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
    evaluated = [_evaluate_signal(candidate) for candidate in deduped]
    kept = [item for item in evaluated if item["kept"]]
    skipped = [item for item in evaluated if not item["kept"] and not item["watchlist"]]
    watchlist = [item for item in evaluated if item["watchlist"] and not item["kept"]]
    top_signals = _dedupe_related_signals(sorted(kept, key=_rank_key))[:MAX_TOP_SIGNALS]
    watchlist_items = sorted(watchlist, key=_rank_key)[:MAX_WATCHLIST_ITEMS]

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
    lines = [f"# Market Brief v2 - {payload['run_date']}", ""]

    lines.extend(["## 1. Executive Summary"])
    summary = payload.get("executive_summary") or []
    if summary:
        lines.extend([f"- {item}" for item in summary])
    else:
        lines.append("- No strong BidMatrix-relevant market signals passed the v2 quality gate.")
    lines.append("")

    lines.extend(["## 2. Top Signals", ""])
    top_signals = payload.get("top_signals", [])
    if top_signals:
        for index, signal in enumerate(top_signals, start=1):
            lines.extend(_signal_lines(index, signal))
    else:
        lines.extend(["No top signals passed the v2 quality gate.", ""])

    for heading in (
        "Competitor / Partner Moves",
        "Measurement / MMP / Attribution",
        "Traffic Quality / Fraud / Inventory",
        "AI / Automation / Agentic UA",
    ):
        section_items = payload.get("sections", {}).get(heading, [])
        lines.extend([f"## {heading}", ""])
        if section_items:
            for signal in section_items:
                lines.append(
                    f"- **{signal['title']}** — {signal['bidmatrix_angle']} "
                    f"[{_source_label(signal)}]({signal['url']})"
                )
        else:
            lines.append("No strong signals in this preview run.")
        lines.append("")

    lines.extend(["## 7. Recommended Actions for BidMatrix"])
    actions = payload.get("recommended_actions") or []
    if actions:
        lines.extend([f"- {action}" for action in actions])
    else:
        lines.append("- No recommended actions until stronger signals appear.")
    lines.append("")

    lines.extend(["## 8. Watchlist"])
    watchlist = payload.get("watchlist", [])
    if watchlist:
        for signal in watchlist:
            reason = signal.get("skip_reason") or "watchlist_signal"
            lines.append(f"- **{signal['title']}** — {reason}. [{_source_label(signal)}]({signal['url']})")
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
    item["bidmatrix_angle"] = _clean_sentence(item.get("bidmatrix_angle")) or _fallback_angle(item)
    item["suggested_action"] = _clean_sentence(item.get("suggested_action")) or _fallback_action(item)
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
        }
    )
    return item


def _signal_lines(index: int, signal: dict[str, Any]) -> list[str]:
    return [
        f"### {index}. {signal['title']}",
        f"- Source: [{_source_label(signal)}]({signal['url']})",
        f"- Date: {signal.get('published_date') or 'Unknown'}",
        f"- What happened: {signal.get('what_happened') or 'Unknown.'}",
        f"- Why it matters: {signal.get('why_it_matters') or 'Unknown.'}",
        f"- BidMatrix angle: {signal['bidmatrix_angle']}",
        f"- Suggested content/BD action: {signal['suggested_action']}",
        f"- Signal type: {signal['signal_type']}",
        f"- Confidence: {signal['confidence']}",
        "",
    ]


def _sections(signals: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    headings = (
        "Competitor / Partner Moves",
        "Measurement / MMP / Attribution",
        "Traffic Quality / Fraud / Inventory",
        "AI / Automation / Agentic UA",
    )
    return {heading: [item for item in signals if item["category"] == heading] for heading in headings}


def _executive_summary(signals: list[dict[str, Any]]) -> list[str]:
    if not signals:
        return []
    summaries: list[str] = []
    category_counts: dict[str, int] = {}
    for signal in signals:
        category_counts[signal["category"]] = category_counts.get(signal["category"], 0) + 1
    top_categories = sorted(category_counts.items(), key=lambda item: (-item[1], item[0]))[:3]
    top_category, top_count = top_categories[0]
    if top_count / len(signals) >= 0.6:
        summaries.append(
            f"This run is concentrated around {top_category}: {top_count} of {len(signals)} kept signals sit in that theme."
        )
    else:
        summaries.append(
            "Strongest signals cluster around "
            + ", ".join(category for category, _count in top_categories)
            + "."
        )
    for signal in signals[:3]:
        summaries.append(f"{signal['title']}: {signal['bidmatrix_angle']}")
    return summaries[:5]


def _recommended_actions(signals: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    if not signals:
        return actions
    first = signals[0]
    actions.append(f"LinkedIn post idea: turn '{first['title']}' into a short take on {first['category'].lower()}.")
    actions.append(f"BD talking point: {first['suggested_action']}")
    for signal in signals[1:3]:
        actions.append(f"Partner outreach idea: use {signal['source_domain']} signal as context for a targeted check-in.")
    if any(item["category"] == "Measurement / MMP / Attribution" for item in signals):
        actions.append("Website/positioning idea: add sharper proof points around measurement, incrementality, and partner-neutral optimization.")
    return actions[:5]


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
    return f"This gives BidMatrix a timely angle on {item['category'].lower()} for marketing and BD conversations."


def _fallback_action(item: dict[str, Any]) -> str:
    return f"Use this as a short internal talking point for {item['category'].lower()} outreach."


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
