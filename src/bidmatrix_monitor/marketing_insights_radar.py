from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from .competitor_radar import (
    collect_competitor_radar_payload,
    load_competitor_radar_settings,
)


MAX_WATCHLIST_ITEMS = 3

MALFORMED_SUBJECT_PREFIXES = (
    "ad tech",
    "agentic ad-tech",
    "how ",
    "retail media",
    "the ",
    "what ",
    "why ",
)

MALFORMED_SUBJECT_SUFFIXES = (
    "ad",
    "ads",
    "first-party",
    "hidden",
    "market",
    "media",
    "next",
    "performance",
    "report",
    "study",
)

SUBJECT_ACTION_FRAGMENTS = (
    " announces ",
    " expands ",
    " introduces ",
    " launches ",
    " releases ",
    " rolls out ",
    " unveils ",
)

CONTENT_IDEA_VARIANTS = {
    "ai_campaign_operations": (
        "BD talking point: “Can your UA setup connect creative performance, traffic quality, and budget decisions automatically?”",
        "LinkedIn post: explain why AI buying needs measurable optimization loops, not just faster campaign changes.",
        "Sales deck note: show how AI campaign operations connect testing, spend control, and performance proof.",
    ),
    "measurement_proof": (
        "LinkedIn post: “Why mobile growth teams need performance proof beyond last-click attribution.”",
        "BD talking point: “Can your attribution setup prove lift across app, web, and partner channels?”",
        "Website message: connect transparent ROAS, incrementality, and user quality in one measurement story.",
    ),
    "traffic_quality": (
        "Website message: strengthen language around verified supply, fraud-resistant growth, and budget protection.",
        "BD talking point: “How are you validating traffic quality before scaling spend?”",
        "Sales deck note: add a budget-safety slide around anti-fraud checks and verified inventory.",
    ),
    "market_structure": (
        "Counter-positioning angle: contrast BidMatrix’s focused growth story with broader platform-consolidation claims.",
        "BD talking point: “How much platform consolidation do you actually need to improve growth quality?”",
        "Sales deck note: use this as context for independent, measurable mobile growth alternatives.",
    ),
    "creative_intelligence": (
        "LinkedIn post: “Creative is becoming a performance system, not just an asset pipeline.”",
        "BD talking point: “Can your creative testing data influence bidding and budget decisions?”",
        "Partner outreach angle: ask creative partners how performance feedback should flow back into UA decisions.",
    ),
    "partnership_integration": (
        "Partner outreach angle: use this move to ask where shared data or workflow connections could reduce campaign friction.",
        "BD talking point: “Which parts of your growth stack still require manual handoffs?”",
        "Website message: show how connected workflows improve speed, measurement, and campaign control.",
    ),
}


def build_marketing_insights_radar_preview(
    config_path: str | Path = "config/marketing_insights_radar_sources.json",
    *,
    max_companies: int | None = None,
    report_dir: str | Path = "reports",
) -> tuple[Path, Path, dict[str, Any]]:
    settings = load_competitor_radar_settings(config_path)
    payload = collect_marketing_insights_radar_payload(settings, max_companies=max_companies)
    return write_marketing_insights_radar_preview(payload, report_dir)


def collect_marketing_insights_radar_payload(
    settings: dict[str, Any],
    *,
    max_companies: int | None = None,
) -> dict[str, Any]:
    source_payload = collect_competitor_radar_payload(settings, max_companies=max_companies)
    signals = [_marketing_signal(item) for item in source_payload.get("signals", [])]
    signals = _apply_subject_gate(signals)
    signals = _dedupe_marketing_signals(signals)
    signals = _calibrate_signal_copy(signals)
    kept = [signal for signal in signals if signal.get("kept")]
    watchlist = _watchlist(signals)
    skipped_count = len([signal for signal in signals if not signal.get("kept")])

    payload = {
        "run_date": source_payload.get("run_date") or date.today().isoformat(),
        "generated_at": source_payload.get("generated_at"),
        "preview_only": True,
        "companies_total": source_payload.get("companies_total", 0),
        "companies_checked": source_payload.get("companies_checked", 0),
        "max_companies_per_run": source_payload.get("max_companies_per_run", 0),
        "lookback_days": source_payload.get("lookback_days", 30),
        "exa_total_queries": source_payload.get("exa_total_queries", 0),
        "exa_errors_count": source_payload.get("exa_errors_count", 0),
        "exa_timeouts_count": source_payload.get("exa_timeouts_count", 0),
        "companies_with_useful_signals": len(kept),
        "companies_skipped": skipped_count,
        "watchlist_signals_count": len(watchlist),
        "signals": signals,
        "watchlist": watchlist,
        "errors": source_payload.get("errors", []),
        "today_marketing_pattern": _today_marketing_pattern(kept),
    }
    return payload


def write_marketing_insights_radar_preview(
    payload: dict[str, Any],
    report_dir: str | Path,
) -> tuple[Path, Path, dict[str, Any]]:
    output_dir = Path(report_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"marketing-insights-radar-{payload['run_date']}"
    markdown_path = output_dir / f"{stem}.md"
    json_path = output_dir / f"{stem}.json"

    markdown_path.write_text(render_marketing_insights_radar_markdown(payload), encoding="utf-8")
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return markdown_path, json_path, payload


def render_marketing_insights_radar_markdown(payload: dict[str, Any]) -> str:
    signals = _calibrate_signal_copy(payload.get("signals", []))
    watchlist = _watchlist(signals)
    lines = [f"# Marketing Insights Radar — {payload['run_date']}", ""]
    lines.extend(["## Today’s marketing pattern", payload.get("today_marketing_pattern") or _today_marketing_pattern(signals), ""])
    lines.extend(["## What companies are doing", ""])

    kept_signals = [signal for signal in signals if signal.get("kept")]
    if not kept_signals:
        lines.extend(["No strong marketing insight signals passed the preview quality gate.", ""])
    else:
        for index, signal in enumerate(kept_signals, start=1):
            lines.extend(
                [
                    f"{index}. {_company_action_sentence(signal)}",
                    "",
                    f"Marketing insight: {signal.get('marketing_insight') or _marketing_insight(signal)}",
                    "",
                    f"What BidMatrix can use: {signal.get('bidmatrix_use') or _bidmatrix_use(signal)}",
                    "",
                    f"Content / BD idea: {signal.get('content_bd_idea') or _content_bd_idea(signal)}",
                    "",
                ]
            )

    lines.append("## Watchlist")
    watchlist = payload.get("watchlist") or watchlist
    if watchlist:
        for item in watchlist:
            lines.append(f"- {_watchlist_sentence(item)}")
    else:
        lines.append("- No watchlist items in this preview run.")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _marketing_signal(signal: dict[str, Any]) -> dict[str, Any]:
    item = {
        "company": signal.get("company"),
        "title": signal.get("title"),
        "url": signal.get("url"),
        "source_domain": signal.get("source_domain"),
        "published_date": signal.get("published_date"),
        "signal_type": signal.get("signal_type"),
        "marketing_value_score": signal.get("marketing_value_score", 0),
        "bd_value_score": signal.get("bd_value_score", 0),
        "noise_risk": signal.get("noise_risk", 0),
        "kept": bool(signal.get("kept")),
        "keep_reason": signal.get("keep_reason"),
        "skip_reason": signal.get("skip_reason"),
        "what_changed": signal.get("what_changed"),
        "why_it_matters": signal.get("why_it_matters"),
        "bidmatrix_angle": signal.get("bidmatrix_angle"),
        "possible_use": signal.get("possible_use"),
        "market_theme": signal.get("market_theme"),
    }
    item["marketing_insight"] = _marketing_insight(item)
    item["bidmatrix_use"] = _bidmatrix_use(item)
    item["content_bd_idea"] = _content_bd_idea(item)
    return item


def _apply_subject_gate(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    gated: list[dict[str, Any]] = []
    for signal in signals:
        item = dict(signal)
        subject = _clean_company_subject(item)
        if not subject:
            item["kept"] = False
            item["skip_reason"] = "malformed_subject"
        else:
            item["company"] = subject
        gated.append(item)
    return gated


def _dedupe_marketing_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for signal in signals:
        item = dict(signal)
        if not item.get("kept"):
            deduped.append(item)
            continue
        key = (_slug(item.get("company")), _theme_key(item))
        if key in seen:
            item["kept"] = False
            item["skip_reason"] = "duplicate_company_theme"
            deduped.append(item)
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _watchlist(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for signal in signals:
        if signal.get("kept"):
            continue
        if signal.get("skip_reason") in {"malformed_subject", "duplicate_company_theme", "high_noise_risk"}:
            continue
        score = int(signal.get("marketing_value_score") or 0) + int(signal.get("bd_value_score") or 0) - int(signal.get("noise_risk") or 0)
        if score < 3:
            continue
        sentence = _watchlist_sentence(signal)
        key = _slug(sentence)
        if key in seen:
            continue
        seen.add(key)
        items.append(signal)
        if len(items) >= MAX_WATCHLIST_ITEMS:
            break
    return items


def _calibrate_signal_copy(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    calibrated: list[dict[str, Any]] = []
    idea_counts: dict[str, int] = {}
    for signal in signals:
        item = dict(signal)
        family = _theme_family(item)
        item["theme_family"] = family
        item["marketing_insight"] = _marketing_insight_for_family(family)
        item["bidmatrix_use"] = _bidmatrix_use_for_family(family)
        idea = _content_bd_idea_for_family(family, idea_counts.get(family, 0))
        idea_counts[family] = idea_counts.get(family, 0) + 1
        item["content_bd_idea"] = idea
        calibrated.append(item)
    return calibrated


def _today_marketing_pattern(signals: list[dict[str, Any]]) -> str:
    kept = [signal for signal in signals if signal.get("kept")]
    if not kept:
        return "No strong competitor marketing pattern passed the preview quality gate."
    themes = [_theme_label(signal) for signal in kept]
    counts = {theme: themes.count(theme) for theme in set(themes)}
    leading = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:2]
    labels = [label for label, _count in leading]
    if len(labels) == 1:
        return f"Competitors are using {labels[0]} as the clearest marketing narrative in this run. BidMatrix can turn that into sharper content, BD, and positioning angles."
    return f"Competitors are clustering around {labels[0]} and {labels[1]}. BidMatrix can use these narratives for LinkedIn, website messaging, BD hooks, and partner conversations."


def _company_action_sentence(signal: dict[str, Any]) -> str:
    company = _clean_company_subject(signal) or str(signal.get("company") or "A company")
    family = _theme_family(signal)
    if family == "market_structure":
        return f"{company} is using a market-structure move to strengthen its platform positioning."
    if family == "ai_campaign_operations":
        return f"{company} is positioning around AI-led campaign operations."
    if family == "measurement_proof":
        return f"{company} is expanding the measurement-proof narrative for growth teams."
    if family == "traffic_quality":
        return f"{company} is using fraud or inventory-quality signals to strengthen its verification story."
    if family == "creative_intelligence":
        return f"{company} is positioning creative intelligence as part of performance growth."
    if family == "partnership_integration":
        return f"{company} is using partnerships or integrations to reduce growth-workflow friction."
    return f"{company} is pushing a clearer positioning narrative."


def _marketing_insight(signal: dict[str, Any]) -> str:
    return _marketing_insight_for_family(_theme_family(signal))


def _bidmatrix_use(signal: dict[str, Any]) -> str:
    return _bidmatrix_use_for_family(_theme_family(signal))


def _content_bd_idea(signal: dict[str, Any]) -> str:
    return _content_bd_idea_for_family(_theme_family(signal), 0)


def _watchlist_sentence(signal: dict[str, Any]) -> str:
    company = _clean_company_subject(signal) or str(signal.get("company") or "A company")
    return f"{company} is worth watching for a clearer {_theme_label(signal)} move."


def _theme_label(signal: dict[str, Any]) -> str:
    return {
        "ai_campaign_operations": "AI campaign operations",
        "measurement_proof": "measurement proof",
        "traffic_quality": "traffic quality",
        "market_structure": "market credibility",
        "creative_intelligence": "creative intelligence",
        "partnership_integration": "partner ecosystem expansion",
    }.get(_theme_family(signal), "positioning")


def _theme_family(signal: dict[str, Any]) -> str:
    if signal.get("theme_family"):
        return str(signal["theme_family"])
    text = _signal_text(signal)
    signal_type = str(signal.get("signal_type") or "")
    if signal_type == "funding_mna" or _has_any(text, ("ipo", "funding", "acquisition", "acquires", "merger", "market structure", "platform consolidation")):
        return "market_structure"
    if _has_any(text, ("fraud", "traffic quality", "invalid traffic", "ivt", "verification", "brand safety", "inventory quality")):
        return "traffic_quality"
    if _has_any(text, ("creative intelligence", "creative analytics", "ugc", "ad concept", "ad concepts", "ad format", "creative testing")):
        return "creative_intelligence"
    if _has_any(text, ("ai", "agentic", "automation", "optimization", "bidding", "campaign management", "dsp optimization", "ml")):
        return "ai_campaign_operations"
    if _has_any(text, ("measurement", "attribution", "incrementality", "mmp", "roas", "ltv", "skan", "privacy sandbox", "analytics", "reporting", "benchmark")):
        return "measurement_proof"
    if signal_type in {"partnership", "integration"} or _has_any(text, ("partnership", "integration", "partner", "marketplace", "data connection")):
        return "partnership_integration"
    return "positioning"


def _marketing_insight_for_family(family: str) -> str:
    return {
        "ai_campaign_operations": "AI is being positioned less as a feature and more as an operating layer for planning, testing, and optimizing growth.",
        "measurement_proof": "Measurement companies are trying to own more of the growth conversation by connecting attribution, ROAS, and performance proof.",
        "traffic_quality": "Verification and traffic-quality narratives are becoming a sales argument for safer media buying and stronger budget protection.",
        "market_structure": "Companies are using market-structure moves to look bigger, more integrated, and harder to replace in the growth stack.",
        "creative_intelligence": "Creative is being positioned as a performance system, not just an asset-production function.",
        "partnership_integration": "Partnerships and integrations are being used to show ecosystem relevance and reduce perceived workflow friction.",
    }.get(family, "The signal shows a company trying to turn a public move into a sharper market position.")


def _bidmatrix_use_for_family(family: str) -> str:
    return {
        "ai_campaign_operations": "BidMatrix can frame AI around real UA workflows: creative testing, budget control, traffic quality, and measurable optimization.",
        "measurement_proof": "BidMatrix can connect this to transparent ROAS, user quality, incrementality, and partner-neutral performance proof.",
        "traffic_quality": "BidMatrix can strengthen messaging around verified traffic, anti-fraud protection, inventory quality, and budget safety.",
        "market_structure": "BidMatrix can use this for counter-positioning against broad platform claims and for sharper independent-growth messaging.",
        "creative_intelligence": "BidMatrix can connect creative testing to media-buying decisions, performance feedback, and campaign optimization.",
        "partnership_integration": "BidMatrix can use this as a partner outreach hook and a message about reducing growth-stack friction.",
    }.get(family, "BidMatrix can use this as a timely content, BD, or counter-positioning hook.")


def _content_bd_idea_for_family(family: str, index: int) -> str:
    variants = CONTENT_IDEA_VARIANTS.get(
        family,
        (
            "Counter-positioning angle: contrast BidMatrix’s measurable growth story with generic platform-expansion claims.",
            "LinkedIn post: turn this signal into a practical positioning note for app growth teams.",
            "BD talking point: ask how the buyer is evaluating this kind of market move.",
        ),
    )
    return variants[index % len(variants)]


def _theme_key(signal: dict[str, Any]) -> str:
    return _slug(f"{signal.get('signal_type')} {_theme_label(signal)} {_company_action_sentence(signal)}")


def _clean_company_subject(signal: dict[str, Any]) -> str | None:
    company = _optional_string(signal.get("company"))
    if company and not _is_malformed_subject(company):
        return company
    if company and _is_malformed_subject(company):
        return None
    text = " ".join(str(signal.get(field) or "") for field in ("title", "what_changed", "market_theme"))
    recovered = _recover_company(text)
    if recovered and not _is_malformed_subject(recovered):
        return recovered
    return None


def _recover_company(text: str) -> str | None:
    known_names = (
        "AppsFlyer",
        "Adjust",
        "Singular",
        "Branch",
        "Kochava",
        "Airbridge",
        "AppMetrica",
        "AppTweak",
        "Moloco",
        "AppLovin",
        "Liftoff",
        "Digital Turbine",
        "Pixalate",
        "HUMAN",
        "DoubleVerify",
        "Integral Ad Science",
        "TrafficGuard",
        "Braze",
        "CleverTap",
        "OneSignal",
        "RevenueCat",
        "Amplitude",
        "SplitMetrics",
        "Business of Apps",
        "Mobile Dev Memo",
    )
    normalized_text = _slug(text)
    for name in known_names:
        if _slug(name) in normalized_text:
            return name
    return None


def _is_malformed_subject(subject: str) -> bool:
    text = re.sub(r"\s+", " ", str(subject or "").strip())
    normalized = text.lower()
    if not text:
        return True
    if any(normalized.startswith(prefix) for prefix in MALFORMED_SUBJECT_PREFIXES):
        return True
    if any(normalized.endswith(f" {suffix}") or normalized == suffix for suffix in MALFORMED_SUBJECT_SUFFIXES):
        return True
    if any(fragment in f" {normalized} " for fragment in SUBJECT_ACTION_FRAGMENTS):
        return True
    if ":" in text:
        return True
    if len(text.split()) > 4:
        return True
    return False


def _signal_text(signal: dict[str, Any]) -> str:
    return _normalize(
        " ".join(
            str(signal.get(field) or "")
            for field in (
                "company",
                "title",
                "what_changed",
                "why_it_matters",
                "bidmatrix_angle",
                "possible_use",
                "market_theme",
            )
        )
    )


def _has_any(text: str, needles: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(needle in lowered for needle in needles)


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
