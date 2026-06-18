from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

from .exa_client import TimeoutExa


COMPETITOR_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["company", "has_signal"],
    "properties": {
        "company": {"type": "string"},
        "has_signal": {"type": "boolean"},
        "title": {"type": "string"},
        "url": {"type": "string"},
        "published_date": {"type": "string"},
        "what_changed": {"type": "string"},
        "why_it_matters": {"type": "string"},
        "bidmatrix_angle": {"type": "string"},
        "possible_use": {"type": "string"},
        "market_theme": {"type": "string"},
    },
}

STRATEGIC_THEME_KEYWORDS = (
    "ai",
    "measurement",
    "attribution",
    "incrementality",
    "privacy",
    "skan",
    "fraud",
    "traffic quality",
    "ctv",
    "performance tv",
    "user acquisition",
    "ua",
    "app growth",
    "programmatic",
    "adtech",
    "retail media",
)

BD_ANGLE_KEYWORDS = (
    "competitor",
    "competitive",
    "positioning",
    "messaging",
    "sales",
    "bd",
    "business development",
    "partner",
    "partnership",
    "integration",
    "benchmark",
    "migration",
    "threat",
    "opportunity",
    "outreach",
    "pitch",
    "content",
    "roi",
)

GENERIC_TITLE_HINTS = (
    "what latest",
    "what the latest",
    "mean for your growth strategy",
    "new partnership announcement",
    "strategy focusing on",
    "outcomes of",
    "product updates",
    "ultimate guide",
    "best practices",
    "how to ",
)

GENERIC_CONTENT_HINTS = (
    "published an analysis",
    "thought leadership",
    "educational content",
    "evergreen",
    "guide",
    "tips",
    "best practices",
    "resources page",
    "company page",
    "external signal",
    "unverified",
    "related newsroom content",
)

GENERIC_URL_HINTS = (
    "/category/",
    "/categories/",
    "/tag/",
    "/tags/",
    "/company/",
)

LOW_TRUST_DOMAINS = {
    "bouncewatch.com",
}

SYNDICATED_DOMAINS = {
    "businesswire.com",
    "finance.yahoo.com",
    "markets.businessinsider.com",
    "morningstar.com",
}

MONTH_NAMES = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def build_competitor_radar_preview(
    config_path: str | Path = "config/competitor_radar_sources.json",
    *,
    max_companies: int | None = None,
    report_dir: str | Path = "reports",
) -> tuple[Path, Path, dict[str, Any]]:
    settings = load_competitor_radar_settings(config_path)
    payload = collect_competitor_radar_payload(settings, max_companies=max_companies)
    return write_competitor_radar_preview(payload, report_dir)


def load_competitor_radar_settings(config_path: str | Path) -> dict[str, Any]:
    raw = json.loads(Path(config_path).read_text(encoding="utf-8"))
    companies = [str(value).strip() for value in raw.get("companies", []) if str(value).strip()]
    if not companies:
        raise ValueError("Competitor radar config must include at least one company or source.")
    return {
        "lookback_days": int(raw.get("lookback_days", 30)),
        "max_companies_per_run": int(raw.get("max_companies_per_run", 25)),
        "num_results_per_company": int(raw.get("num_results_per_company", 3)),
        "request_timeout_seconds": int(raw.get("request_timeout_seconds", 20)),
        "companies": companies,
    }


def collect_competitor_radar_payload(
    settings: dict[str, Any],
    *,
    max_companies: int | None = None,
) -> dict[str, Any]:
    load_dotenv()
    api_key = os.environ.get("EXA_API_KEY")
    if not api_key:
        raise RuntimeError("EXA_API_KEY is not set. Add it to your environment or a local .env file.")

    query_cap = max_companies if max_companies is not None else int(settings["max_companies_per_run"])
    companies = list(settings["companies"])
    companies_checked = companies[: max(0, query_cap)]

    exa = TimeoutExa(api_key=api_key, request_timeout_seconds=int(settings["request_timeout_seconds"]))
    start = time.monotonic()
    items: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    timeouts = 0

    for company in companies_checked:
        query = _company_query(company, int(settings["lookback_days"]))
        try:
            response = exa.search(
                query,
                type="deep",
                category="news",
                num_results=int(settings["num_results_per_company"]),
                output_schema=COMPETITOR_OUTPUT_SCHEMA,
                contents={"highlights": {"max_characters": 2400}},
            )
        except Exception as exc:
            if isinstance(exc, (TimeoutError, requests.Timeout)):
                timeouts += 1
            errors.append({"company": company, "error_type": type(exc).__name__, "error": str(exc)})
            items.append(_skipped_item(company, "exa_error", error_type=type(exc).__name__))
            continue

        candidate = _first_signal(response, company)
        items.append(_evaluate_signal(company, candidate, lookback_days=int(settings["lookback_days"])))

    kept_items = [item for item in items if item.get("kept")]
    sorted_items = sorted(items, key=_sort_key)

    payload = {
        "run_date": date.today().isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "preview_only": True,
        "companies_total": len(companies),
        "companies_checked": len(companies_checked),
        "max_companies_per_run": query_cap,
        "lookback_days": int(settings["lookback_days"]),
        "num_results_per_company": int(settings["num_results_per_company"]),
        "exa_total_queries": len(companies_checked),
        "exa_errors_count": len(errors),
        "exa_timeouts_count": timeouts,
        "exa_total_duration_seconds": round(time.monotonic() - start, 2),
        "companies_with_useful_signals": len(kept_items),
        "companies_skipped": len(sorted_items) - len(kept_items),
        "signals": sorted_items,
        "errors": errors,
        "weekly_pattern": _weekly_pattern(kept_items),
    }
    return payload


def write_competitor_radar_preview(
    payload: dict[str, Any],
    report_dir: str | Path,
) -> tuple[Path, Path, dict[str, Any]]:
    output_dir = Path(report_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"competitor-radar-{payload['run_date']}"
    markdown_path = output_dir / f"{stem}.md"
    json_path = output_dir / f"{stem}.json"

    markdown_path.write_text(render_competitor_radar_markdown(payload), encoding="utf-8")
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return markdown_path, json_path, payload


def render_competitor_radar_markdown(payload: dict[str, Any]) -> str:
    lines = [f"# Competitor Marketing Radar - {payload['run_date']}", ""]
    kept_signals = [signal for signal in payload.get("signals", []) if signal.get("kept")]
    if not kept_signals:
        lines.extend(
            [
                "No useful public competitor signals were found in this preview run.",
                "",
                f"Companies checked: {payload.get('companies_checked', 0)}",
            ]
        )
        return "\n".join(lines).rstrip() + "\n"

    for index, signal in enumerate(kept_signals, start=1):
        source_title = signal.get("title") or signal.get("source_name") or signal.get("company")
        source_url = signal.get("url") or ""
        lines.extend(
            [
                f"{index}. Company: {signal.get('company', 'Unknown')}",
                f"What changed: {signal.get('what_changed', 'Unknown.')}",
                f"Why it matters: {signal.get('why_it_matters', 'Unknown.')}",
                f"BidMatrix angle: {signal.get('bidmatrix_angle', 'Unknown.')}",
                f"Possible content/BD use: {signal.get('possible_use', 'Unknown.')}",
                f"Source: [{source_title}]({source_url})" if source_url else f"Source: {source_title}",
                "",
            ]
        )

    pattern = payload.get("weekly_pattern")
    if pattern:
        lines.extend(["Weekly pattern / market narrative:", pattern, ""])

    return "\n".join(lines).rstrip() + "\n"


def _company_query(company: str, lookback_days: int) -> str:
    return (
        f"\"{company}\" mobile marketing OR app growth OR attribution OR measurement OR SKAN OR "
        f"Privacy Sandbox OR fraud OR traffic quality OR CTV OR performance TV OR AI media buying OR "
        f"programmatic OR in-app supply OR partnership OR integration OR benchmark OR case study OR "
        f"funding OR IPO OR acquisition OR newsroom OR blog OR report in the last {lookback_days} days. "
        "Find one concrete public signal useful for competitor marketing or BD analysis. "
        "Focus on product launches, partnerships, integrations, reports, benchmarks, positioning changes, "
        "website/newsroom updates, AI/measurement/fraud/CTV/UA narratives, funding/IPO/acquisitions, or "
        "major thought-leadership themes. Ignore generic evergreen homepages or thin reposts. "
        "Return at most one useful signal; return none if nothing concrete and recent is found."
    )


def _first_signal(response: Any, company: str) -> dict[str, Any] | None:
    content = getattr(getattr(response, "output", None), "content", None) or {}
    if not isinstance(content, dict):
        return None
    if not content.get("has_signal"):
        return None
    if not content.get("title") or not content.get("url"):
        return None
    url = str(content.get("url", "")).strip()
    return {
        "company": company,
        "matched_company": _matched_company_name(content.get("company"), company),
        "title": str(content.get("title", "")).strip(),
        "url": url,
        "published_date": _optional_string(content.get("published_date")),
        "source_name": _source_name_from_url(url),
        "source_domain": _source_domain(url),
        "what_changed": _optional_string(content.get("what_changed")),
        "why_it_matters": _optional_string(content.get("why_it_matters")),
        "bidmatrix_angle": _optional_string(content.get("bidmatrix_angle")),
        "possible_use": _optional_string(content.get("possible_use")),
        "market_theme": _optional_string(content.get("market_theme")),
    }


def _evaluate_signal(
    company: str,
    candidate: dict[str, Any] | None,
    *,
    lookback_days: int,
) -> dict[str, Any]:
    if not candidate:
        return _skipped_item(company, "no_recent_concrete_signal")

    item = dict(candidate)
    item.setdefault("company", company)
    item["published_date"] = _optional_string(item.get("published_date"))
    item["matched_company"] = _optional_string(item.get("matched_company"))
    item["source_name"] = _optional_string(item.get("source_name"))
    item["source_domain"] = _optional_string(item.get("source_domain"))
    item["what_changed"] = _optional_string(item.get("what_changed"))
    item["why_it_matters"] = _optional_string(item.get("why_it_matters"))
    item["bidmatrix_angle"] = _optional_string(item.get("bidmatrix_angle"))
    item["possible_use"] = _optional_string(item.get("possible_use"))
    item["market_theme"] = _optional_string(item.get("market_theme"))

    signal_type = _infer_signal_type(item)
    freshness_days = _freshness_days(item.get("published_date"))
    official_source = _is_official_source(company, item.get("source_domain"))
    marketing_value_score = _marketing_value_score(item, signal_type)
    bd_value_score = _bd_value_score(item, signal_type)
    noise_risk = _noise_risk(item, signal_type, freshness_days, official_source)

    kept, keep_reason, skip_reason = _keep_decision(
        item,
        signal_type=signal_type,
        freshness_days=freshness_days,
        marketing_value_score=marketing_value_score,
        bd_value_score=bd_value_score,
        noise_risk=noise_risk,
        lookback_days=lookback_days,
    )

    item.update(
        {
            "official_source": official_source,
            "freshness_days": freshness_days,
            "signal_type": signal_type,
            "marketing_value_score": marketing_value_score,
            "bd_value_score": bd_value_score,
            "noise_risk": noise_risk,
            "kept": kept,
            "keep_reason": keep_reason,
            "skip_reason": skip_reason,
        }
    )
    return item


def _skipped_item(
    company: str,
    skip_reason: str,
    *,
    error_type: str | None = None,
) -> dict[str, Any]:
    return {
        "company": company,
        "title": None,
        "url": None,
        "published_date": None,
        "matched_company": None,
        "source_name": None,
        "source_domain": None,
        "what_changed": None,
        "why_it_matters": None,
        "bidmatrix_angle": None,
        "possible_use": None,
        "market_theme": None,
        "official_source": False,
        "freshness_days": None,
        "signal_type": "none",
        "marketing_value_score": 0,
        "bd_value_score": 0,
        "noise_risk": 0,
        "kept": False,
        "keep_reason": None,
        "skip_reason": skip_reason,
        "error_type": error_type,
    }


def _infer_signal_type(signal: dict[str, Any]) -> str:
    headline_text = _normalize_text(
        " ".join(str(signal.get(field) or "") for field in ("title", "what_changed"))
    )
    text = _signal_text(signal)
    title = _normalize_text(signal.get("title"))

    if _contains_any(headline_text, ("case study", "customer story", "showcasing how", "showcases how", "doubled registrations", "growing ")) and _contains_any(text, ("roas", "app growth", "ua", "user acquisition", "performance")):
        return "case_study"
    if _contains_any(headline_text, ("q1", "q2", "q3", "q4", "earnings", "revenue", "results", "performance fueled", "revenue surges")):
        return "financial_results"
    if _contains_any(headline_text, ("acquires", "acquired", "acquisition", "ipo", "initial public offering", "funding", "raises", "raised", "public offering")):
        return "funding_mna"
    if _contains_any(headline_text, ("partners with", "partnership", "partnered", "certified partner")):
        return "partnership"
    if _contains_any(headline_text, ("integration", "integrates", "integrated", "connector", "connect ", "connected ", "mcp")):
        return "integration"
    if _contains_any(headline_text, ("launches", "launched", "introduces", "introduced", "rolls out", "rolled out", "added", "adds", "new feature", "self-serve", "sunsets", "launchpad")):
        return "product_launch"
    if _contains_any(headline_text, ("report", "benchmark", "research", "study", "findings", "index", "reviews tell us")):
        return "report_benchmark"
    if _contains_any(headline_text, ("rebrand", "reposition", "positioning", "pivot", "strategy shift", "successor to seo", "ai optimization")):
        return "positioning_shift"
    if _contains_any(text, STRATEGIC_THEME_KEYWORDS) or _contains_any(title, STRATEGIC_THEME_KEYWORDS):
        return "strategic_narrative"
    return "unknown"


def _marketing_value_score(signal: dict[str, Any], signal_type: str) -> int:
    text = _signal_text(signal)
    score = 0
    if signal_type in {"product_launch", "integration", "partnership", "funding_mna"}:
        score += 2
    elif signal_type in {"report_benchmark", "case_study", "positioning_shift"}:
        score += 1
    elif signal_type == "strategic_narrative":
        score += 1
    if _contains_any(text, STRATEGIC_THEME_KEYWORDS):
        score += 1
    if _contains_any(text, ("launch", "integration", "partnership", "benchmark", "case study", "acquisition", "ipo", "funding", "self-serve", "closed-loop")):
        score += 1
    if _contains_any(_normalize_text(signal.get("possible_use")), ("content", "messaging", "benchmark", "narrative", "positioning")):
        score += 1
    return min(score, 4)


def _bd_value_score(signal: dict[str, Any], signal_type: str) -> int:
    text = _signal_text(signal)
    score = 0
    if signal_type in {"partnership", "integration", "funding_mna", "product_launch"}:
        score += 2
    elif signal_type in {"case_study", "positioning_shift", "report_benchmark"}:
        score += 1
    if _contains_any(text, BD_ANGLE_KEYWORDS):
        score += 1
    if _contains_any(text, ("migration", "cross-sell", "threat", "opportunity", "sales pitch", "competitive")):
        score += 1
    return min(score, 4)


def _noise_risk(
    signal: dict[str, Any],
    signal_type: str,
    freshness_days: int | None,
    official_source: bool,
) -> int:
    title = _normalize_text(signal.get("title"))
    text = _signal_text(signal)
    url = str(signal.get("url") or "").lower()
    domain = str(signal.get("source_domain") or "").lower()

    risk = 0
    if domain in LOW_TRUST_DOMAINS:
        risk += 3
    elif domain in SYNDICATED_DOMAINS:
        risk += 1

    if freshness_days is not None:
        if freshness_days > 60:
            risk += 2
        elif freshness_days > 30:
            risk += 1

    if signal_type in {"strategic_narrative", "unknown"}:
        risk += 1

    if _contains_any(title, GENERIC_TITLE_HINTS):
        risk += 2
    elif _contains_any(text, GENERIC_CONTENT_HINTS):
        risk += 1

    if _contains_any(url, GENERIC_URL_HINTS) and signal_type in {"report_benchmark", "positioning_shift", "strategic_narrative", "unknown"}:
        risk += 2

    if not official_source and not _contains_any(text, ("acquisition", "ipo", "funding", "launch", "integration", "partnership", "benchmark", "case study")):
        risk += 1

    if not _has_bidmatrix_angle(signal):
        risk += 1

    if signal.get("matched_company") and not _signal_mentions_company(signal.get("company", ""), signal):
        risk += 2

    return min(risk, 5)


def _keep_decision(
    signal: dict[str, Any],
    *,
    signal_type: str,
    freshness_days: int | None,
    marketing_value_score: int,
    bd_value_score: int,
    noise_risk: int,
    lookback_days: int,
) -> tuple[bool, str | None, str | None]:
    has_theme = _contains_any(_signal_text(signal), STRATEGIC_THEME_KEYWORDS)
    company_match = _signal_mentions_company(signal.get("company", ""), signal)

    if signal_type == "none":
        return False, None, "no_recent_concrete_signal"

    if signal_type == "financial_results":
        return False, None, "weak_bidmatrix_angle"

    if freshness_days is not None and freshness_days > max(lookback_days * 2, 60):
        return False, None, "too_old_for_preview"

    if not company_match:
        return False, None, "weak_company_match"

    if noise_risk >= 4:
        return False, None, "high_noise_risk"

    if marketing_value_score < 3:
        return False, None, "low_marketing_value"

    if bd_value_score < 2:
        return False, None, "low_bd_value"

    if signal_type in {"report_benchmark", "case_study", "positioning_shift"}:
        if not has_theme:
            return False, None, "weak_bidmatrix_angle"
        if freshness_days is not None and freshness_days > 30:
            return False, None, "too_old_for_strategic_signal"
        if noise_risk > 1:
            return False, None, "generic_or_evergreen_content"
    elif signal_type == "strategic_narrative":
        if freshness_days is None or freshness_days > lookback_days:
            return False, None, "too_old_for_strategic_signal"
        if marketing_value_score < 4 or bd_value_score < 3 or noise_risk > 0:
            return False, None, "vague_bidmatrix_angle"
    else:
        if not has_theme and signal_type != "funding_mna":
            return False, None, "weak_bidmatrix_angle"
        if freshness_days is not None and freshness_days > 35:
            return False, None, "too_old_for_preview"

    return True, _keep_reason(signal_type), None


def _keep_reason(signal_type: str) -> str:
    return {
        "funding_mna": "clear_market_structure_move",
        "partnership": "clear_partner_or_distribution_move",
        "integration": "clear_product_integration_signal",
        "product_launch": "clear_product_launch_signal",
        "report_benchmark": "fresh_report_with_competitive_value",
        "case_study": "clear_case_study_with_positioning_value",
        "positioning_shift": "clear_positioning_or_gtm_shift",
        "strategic_narrative": "fresh_strategic_narrative_with_clear_bidmatrix_angle",
    }.get(signal_type, "clear_competitive_signal")


def _weekly_pattern(signals: list[dict[str, Any]]) -> str:
    themes: dict[str, int] = {}
    for signal in signals:
        theme = str(signal.get("market_theme") or "").strip().lower()
        if not theme:
            continue
        themes[theme] = themes.get(theme, 0) + 1

    if not themes:
        return "Recent competitor signals are scattered across product, measurement, and growth narratives rather than one dominant theme."

    top = sorted(themes.items(), key=lambda item: (-item[1], item[0]))[:3]
    labels = [theme.replace("_", " ") for theme, _count in top]
    if len(labels) == 1:
        return f"Recent competitor signals cluster around {labels[0]}."
    if len(labels) == 2:
        return f"Recent competitor signals cluster around {labels[0]} and {labels[1]}."
    return f"Recent competitor signals cluster around {labels[0]}, {labels[1]}, and {labels[2]}."


def _sort_key(signal: dict[str, Any]) -> tuple[int, int, int, str]:
    kept_rank = 0 if signal.get("kept") else 1
    score = int(signal.get("marketing_value_score", 0)) + int(signal.get("bd_value_score", 0)) - int(signal.get("noise_risk", 0))
    freshness = signal.get("freshness_days")
    freshness_rank = freshness if isinstance(freshness, int) else 9999
    return kept_rank, -score, freshness_rank, str(signal.get("company") or "")


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def _signal_text(signal: dict[str, Any]) -> str:
    return _normalize_text(
        " ".join(
            str(signal.get(field) or "")
            for field in (
                "title",
                "what_changed",
                "why_it_matters",
                "bidmatrix_angle",
                "possible_use",
                "market_theme",
            )
        )
    )


def _has_bidmatrix_angle(signal: dict[str, Any]) -> bool:
    angle_text = _normalize_text(
        " ".join(str(signal.get(field) or "") for field in ("bidmatrix_angle", "possible_use"))
    )
    return len(angle_text) >= 40 and _contains_any(angle_text, BD_ANGLE_KEYWORDS)


def _signal_mentions_company(company: str, signal: dict[str, Any]) -> bool:
    if not company:
        return True
    normalized_company = re.sub(r"[^a-z0-9]", "", company.lower())
    if not normalized_company:
        return True
    signal_text = re.sub(r"[^a-z0-9]", "", _signal_text(signal))
    return normalized_company in signal_text


def _freshness_days(published_date: str | None) -> int | None:
    if not published_date:
        return None

    candidates: list[date] = []
    for match in re.findall(r"\d{4}-\d{2}-\d{2}", published_date):
        try:
            candidates.append(date.fromisoformat(match))
        except ValueError:
            continue

    if not candidates:
        month_year = re.search(r"([A-Za-z]+)\s+(\d{4})", published_date)
        if month_year:
            month = MONTH_NAMES.get(month_year.group(1).lower())
            year = int(month_year.group(2))
            if month:
                candidates.append(date(year, month, 1))

    if not candidates:
        return None

    freshest = max(candidates)
    return (date.today() - freshest).days


def _is_official_source(company: str, source_domain: str | None) -> bool:
    if not source_domain:
        return False
    domain_text = re.sub(r"[^a-z0-9]", "", source_domain.lower())
    company_text = re.sub(r"[^a-z0-9]", "", company.lower())
    company_tokens = [token for token in re.split(r"[^a-z0-9]+", company.lower()) if len(token) >= 4]
    if company_text and company_text in domain_text:
        return True
    return any(token in domain_text for token in company_tokens)


def _matched_company_name(value: Any, company: str) -> str | None:
    text = _optional_string(value)
    if not text:
        return None
    if _normalize_text(text) == _normalize_text(company):
        return None
    return text


def _source_domain(url: str) -> str | None:
    if not url:
        return None
    return urlparse(url).netloc.lower().removeprefix("www.") or None


def _source_name_from_url(url: str) -> str | None:
    domain = _source_domain(url)
    if not domain:
        return None
    head = domain.split(".")[0].replace("-", " ").strip()
    return head.title() if head else domain
