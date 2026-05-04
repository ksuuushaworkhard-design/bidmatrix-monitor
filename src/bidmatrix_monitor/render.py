from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

from .models import MonitorReport, NewsItem


def write_report(report: MonitorReport, report_dir: str | Path) -> tuple[Path, Path, Path]:
    output_dir = Path(report_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    stem = f"bidmatrix-monitor-{report.run_date.isoformat()}"
    markdown_path = output_dir / f"{stem}.md"
    json_path = output_dir / f"{stem}.json"
    curated_json_path = output_dir / f"{stem}-curated.json"

    markdown_path.write_text(_strip_diagnostics(render_markdown(report)), encoding="utf-8")
    json_path.write_text(json.dumps(_report_to_dict(report), indent=2, ensure_ascii=False), encoding="utf-8")
    curated_json_path.write_text(json.dumps(_curated_report_to_dict(report), indent=2, ensure_ascii=False), encoding="utf-8")
    return markdown_path, json_path, curated_json_path


def render_markdown(report: MonitorReport) -> str:
    lines = [
        f"# BidMatrix Daily Brief - {report.run_date.isoformat()}",
        "",
        "## Today's Useful Signal" if len(report.daily_signals) == 1 else "## Today's Useful Signals",
        report.daily_intro,
    ]
    if report.daily_signals:
        lines.extend(["", "## Top Signal" if len(report.daily_signals) == 1 else "## Top Signals"])
        lines.extend(_daily_signal_cards(report.daily_signals))
    elif report.adjacent_watchlist:
        lines.extend(["", "## Market Watch"])
        lines.extend(_adjacent_watchlist_cards(report.adjacent_watchlist))
    background_lines = _background_context(report)
    if background_lines and (report.daily_signals or report.adjacent_watchlist):
        lines.extend([
            "",
            "## Strategic Context",
        ])
        lines.extend(background_lines)

    lines.append("")
    return "\n".join(lines)


def _strip_diagnostics(markdown: str) -> str:
    lines = markdown.splitlines()
    try:
        index = lines.index("## Diagnostic Summary")
    except ValueError:
        return markdown
    cleaned = lines[:index]
    while cleaned and cleaned[-1] == "":
        cleaned.pop()
    cleaned.append("")
    return "\n".join(cleaned)


def _diagnostic_summary(report: MonitorReport) -> list[str]:
    diagnostics = report.diagnostics
    return [
        f"- Sensitivity: {diagnostics.get('sensitivity', 'balanced')}",
        f"- Total raw signals found: {diagnostics.get('raw_items_found', 0)}",
        f"- Raw daily fresh signals: {diagnostics.get('raw_daily_fresh_signals', 0)}",
        f"- Raw strategic background signals: {diagnostics.get('raw_strategic_background', 0)}",
        f"- Total curated signals kept: {diagnostics.get('curated_items_kept', 0)}",
        f"- New today count: {diagnostics.get('kept_new_last_24h', 0)}",
        f"- New this week count: {diagnostics.get('kept_new_last_7d', 0)}",
        f"- Background count: {diagnostics.get('kept_background_context', 0)}",
        f"- Page types: {_counts_label(diagnostics.get('page_type_counts', {}))}",
        f"- Source types: {_counts_label(diagnostics.get('source_type_counts', {}))}",
    ]


def _counts_label(value) -> str:
    if not isinstance(value, dict) or not value:
        return "none"
    return ", ".join(f"{key}={count}" for key, count in sorted(value.items()))


def _item_cards(items: list[NewsItem], empty: str = "No items found.") -> list[str]:
    if not items:
        return [f"- {empty}"]

    lines: list[str] = []
    for item in items:
        meta = " | ".join(
            value
            for value in [
                f"Source: {_source_label(item)}",
                f"Score: {item.final_score}/10 ({_score_band(item.final_score)})",
                f"Freshness: {_freshness_label(item.freshness_tier)}",
                f"Date quality: {_date_quality_label(item.date_quality)}",
                f"Page type: {_label_signal(item.page_type)}",
                f"Source type: {_label_signal(item.source_type)}",
                f"Freshness confidence: {item.freshness_confidence}/5",
                f"Published: {item.published_date or 'unknown'}",
                item.topic_label,
            ]
            if value
        )
        lines.extend(
            [
                "",
                f"### [{item.title}]({item.url})",
            ]
        )
        lines.append(f"_{meta}_")
        lines.extend(
            [
                f"- Signal: {_label_signal(item.signal_type)}",
                f"- Market move: {_clean_text(item.summary or item.why_it_matters)}",
                f"- LinkedIn angle: {_clean_text(item.linkedin_post_angle)}",
                f"- PR angle: {_clean_text(item.pr_angle) or 'No immediate PR hook.'}",
                f"- Partner/sales action: {_clean_text(item.partner_or_sales_action) or 'No immediate partner or sales action.'}",
            ]
        )
        if item.hot_topics:
            lines.append(f"- Tags: {', '.join(item.hot_topics[:5])}")
        if item.mentioned_companies:
            lines.append(f"- Companies: {', '.join(item.mentioned_companies[:5])}")
    return lines


def _daily_signal_cards(items: list[NewsItem]) -> list[str]:
    lines: list[str] = []
    for index, item in enumerate(items, start=1):
        entity = _lead_entity(item)
        title = _event_line(item, entity)
        lines.extend(
            [
                f"### {index}. {title}",
                f"- What happened: {_sentence(item.what_happened or _what_happened(item))}",
                f"- Why it matters: {_sentence(item.why_now or _why_it_matters(item))}",
                f"- Market context: {_sentence(_market_context_line(item))}",
                f"- BidMatrix angle: {_sentence(item.why_it_matters_for_bidmatrix or item.bidmatrix_angle or item.why_it_matters)}",
                f"- Content angle: {_sentence(item.content_angle or item.linkedin_post_angle)}",
                f"- Action: {_sentence(item.concrete_action or item.partner_or_sales_action)}",
                f"- Watch next: {_sentence(item.watch_next)}",
                f"- Source: [{item.source_title or item.title}]({item.source_url or item.url}) - {_source_label(item)} - Date: {item.published_date or 'unknown'} - confidence: {item.confidence}",
                "",
            ]
        )
    return lines[:-1] if lines else ["- No usable signal cards were generated."]



def _adjacent_watchlist_cards(items: list[NewsItem]) -> list[str]:
    lines: list[str] = []
    for index, item in enumerate(items, start=1):
        entity = _lead_entity(item)
        title = _event_line(item, entity)
        lines.extend(
            [
                f"### {index}. {title}",
                f"- Why it may matter: {_sentence(item.why_now or item.market_context or item.why_it_matters)}",
                f"- BidMatrix use: {_sentence(item.why_it_matters_for_bidmatrix or item.bidmatrix_angle or 'Relevance to BidMatrix is indirect; keep as watchlist only.')}",
                f"- Source: [{item.source_title or item.title}]({item.source_url or item.url}) - {_source_label(item)} - Date: {item.published_date or 'unknown'}",
                "",
            ]
        )
    return lines[:-1] if lines else ["- No adjacent watchlist items were kept."]

def _background_context(report: MonitorReport) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for item in report.background_items:
        text = _clean_text(item.market_context or item.why_now or item.why_it_matters or item.summary)
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        date_label = item.published_date or "unknown"
        values.append(
            f"- {text} Source: [{item.title}]({item.url}) | Date: {date_label}"
        )
        if len(values) >= 2:
            break
    return values


def _bullets(values: list[str], empty: str) -> list[str]:
    if not values:
        return [f"- {empty}"]
    return [f"- {_clean_text(value)}" for value in values if _clean_text(value)]


def _label_signal(value: str) -> str:
    return value.replace("_", " ").title()


def _freshness_label(value: str) -> str:
    labels = {
        "new_last_24h": "new last 24h",
        "new_last_7d": "new last 7d",
        "background_context": "background context",
    }
    return labels.get(value, value.replace("_", " "))


def _date_quality_label(value: str) -> str:
    return value.replace("_", " ")


def _score_band(score: int) -> str:
    if score >= 9:
        return "must read"
    if score >= 7:
        return "useful"
    return "optional"


def _merge_items(first: list[NewsItem], second: list[NewsItem], limit: int) -> list[NewsItem]:
    seen = set()
    merged = []
    for item in first + second:
        key = item.normalized_url
        if key not in seen:
            seen.add(key)
            merged.append(item)
    return sorted(merged, key=lambda item: (-item.final_score, item.title.lower()))[:limit]


def _source_label(item: NewsItem) -> str:
    label = item.source or urlparse(item.url).netloc.lower().removeprefix("www.") or "unknown"
    if item.source_quality > 0:
        return f"{label} (high-signal)"
    if item.source_quality < 0:
        return f"{label} (lower-priority)"
    return label


def _event_line(item: NewsItem, entity: str) -> str:
    prefix = entity or item.topic_label
    event = _clean_text(item.summary or item.title)
    if entity and event.lower().startswith(entity.lower()):
        event = event[len(entity):].lstrip(" -,:")
    return f"{prefix} — {event}"


def _what_happened(item: NewsItem) -> str:
    parts = [_sentence(item.what_happened or item.summary), _sentence(_concrete_detail(item))]
    return " ".join(value for value in parts if value)


def _market_context_line(item: NewsItem) -> str:
    candidate = item.market_context or item.why_it_matters or item.why_now or item.summary
    if _same_meaning(candidate, item.what_happened or item.summary):
        return item.why_now or item.why_it_matters or candidate
    return candidate


def _why_it_matters(item: NewsItem) -> str:
    return _sentence(item.why_now or item.why_it_matters or item.pr_angle or item.summary)


def _concrete_detail(item: NewsItem) -> str:
    details = []
    if item.published_date:
        details.append(f"The source dates it to {item.published_date}.")
    if item.mentioned_companies:
        details.append(f"Named entities include {', '.join(item.mentioned_companies[:4])}.")
    if item.hot_topics:
        details.append(f"It touches {', '.join(item.hot_topics[:3])}.")
    return " ".join(details[:2])


def _sentence(value: str) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    if text[-1] not in ".!?":
        text += "."
    return text[0].upper() + text[1:]


def _lead_entity(item: NewsItem) -> str:
    if item.company_or_topic:
        return item.company_or_topic
    if item.mentioned_companies:
        return item.mentioned_companies[0]
    return item.title.split(":", 1)[0].split("-", 1)[0].strip()


def _why_advertisers_care(report: MonitorReport) -> list[str]:
    implications = []
    for item in report.items:
        text = item.why_it_matters or item.summary
        if not text:
            continue
        if any(term in text.lower() for term in ("advertiser", "campaign", "ua", "user acquisition", "measurement", "creative", "fraud", "privacy", "roas", "retention")):
            implications.append(text)
    if not implications:
        implications = [item.why_it_matters or item.summary for item in report.top_news if item.why_it_matters or item.summary]
    return _unique_clean(implications)[:6]


def _same_meaning(first: str, second: str) -> bool:
    left = re.sub(r"[^a-z0-9]+", " ", str(first).lower()).split()
    right = re.sub(r"[^a-z0-9]+", " ", str(second).lower()).split()
    if not left or not right:
        return False
    left_set = set(left)
    right_set = set(right)
    overlap = len(left_set & right_set) / max(1, min(len(left_set), len(right_set)))
    return overlap >= 0.75


def _clean_text(value: str) -> str:
    text = " ".join(str(value).split())
    replacements = {
        "No immediate angle identified.": "",
        "No summary available.": "",
        "worth treating as a live market narrative": "a live market narrative",
        "Leverage BidMatrix intelligence to": "Use BidMatrix data to",
        "Position BidMatrix as": "Frame BidMatrix as",
        "LinkedIn post on": "Post about",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.strip(" ;.-")


def _unique_clean(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        text = _clean_text(value)
        if text and text.lower() not in seen:
            seen.add(text.lower())
            result.append(text)
    return result


def _legacy_render_markdown(report: MonitorReport) -> str:
    lines = [
        f"# BidMatrix Market Intelligence - {report.run_date.isoformat()}",
        "",
        "## What Changed",
    ]
    if report.items:
        for item in report.items:
            lines.extend(_item_lines(item))
    else:
        lines.append("No relevant developments found.")

    lines.extend(["", "## Recurring Trends"])
    if report.trends:
        lines.extend(f"- {trend} ({count} mentions)" for trend, count in report.trends)
    else:
        lines.append("- No recurring trend crossed the mention threshold today.")

    lines.extend(_section("LinkedIn Angles", report.content_angles_for_linkedin))
    lines.extend(_section("PR Opportunities", report.pr_hooks))
    lines.extend(_section("Positioning Ideas", report.hot_takes))
    lines.append("")
    return "\n".join(lines)


def _item_lines(item: NewsItem) -> list[str]:
    meta = " | ".join(value for value in [item.source, item.published_date, item.topic_label] if value)
    lines = [
        "",
        f"### [{item.title}]({item.url})",
    ]
    if meta:
        lines.append(f"_{meta}_")
    lines.extend(
        [
            f"- Summary: {item.summary or 'No summary available.'}",
            f"- Why it matters: {item.why_it_matters or 'Not specified.'}",
            f"- Opportunity: {item.opportunity or 'Not specified.'}",
            f"- Hot topics: {', '.join(item.hot_topics) if item.hot_topics else 'None'}",
            f"- Relevance: {item.final_score or item.relevance_score}/10",
        ]
    )
    return lines


def _section(title: str, values: list[str]) -> list[str]:
    lines = ["", f"## {title}"]
    if values:
        lines.extend(f"- {value}" for value in values)
    else:
        lines.append("- None identified.")
    return lines


def _report_to_dict(report: MonitorReport) -> dict:
    return {
        "run_date": report.run_date.isoformat(),
        "diagnostics": report.diagnostics,
        "items": [_item_to_dict(item) for item in report.items],
        "trends": [{"topic": trend, "mentions": count} for trend, count in report.trends],
        "daily_intro": report.daily_intro,
        "daily_signals": [_item_to_dict(item) for item in report.daily_signals],
        "adjacent_watchlist": [_item_to_dict(item) for item in report.adjacent_watchlist],
        "top_news": [_item_to_dict(item) for item in report.top_news],
        "actually_new_today": [_item_to_dict(item) for item in report.actually_new_today],
        "fresh_weak_confidence": [_item_to_dict(item) for item in report.fresh_weak_confidence],
        "background_items": [_item_to_dict(item) for item in report.background_items],
        "hot_takes": report.hot_takes,
        "partner_signals": [_item_to_dict(item) for item in report.partner_signals],
        "competitor_moves": [_item_to_dict(item) for item in report.competitor_moves],
        "content_angles_for_linkedin": report.content_angles_for_linkedin,
        "pr_hooks": report.pr_hooks,
        "what_changed_today": report.what_changed_today,
    }


def _curated_report_to_dict(report: MonitorReport) -> dict:
    return {
        "run_date": report.run_date.isoformat(),
        "diagnostics": report.diagnostics,
        "daily_intro": report.daily_intro,
        "daily_signals": [_curated_item(item) for item in report.daily_signals],
        "adjacent_watchlist": [_curated_item(item) for item in report.adjacent_watchlist],
        "top_news": [_curated_item(item) for item in report.top_news],
        "actually_new_today": [_curated_item(item) for item in report.actually_new_today],
        "fresh_weak_confidence": [_curated_item(item) for item in report.fresh_weak_confidence],
        "background_items": [_curated_item(item) for item in report.background_items],
        "hot_takes": report.hot_takes,
        "partner_signals": [_curated_item(item) for item in report.partner_signals],
        "competitor_moves": [_curated_item(item) for item in report.competitor_moves],
        "content_angles_for_linkedin": report.content_angles_for_linkedin,
        "pr_hooks": report.pr_hooks,
        "what_changed_today": report.what_changed_today,
    }


def _item_to_dict(item: NewsItem) -> dict:
    return {
        "topic_id": item.topic_id,
        "topic_label": item.topic_label,
        "title": item.title,
        "url": item.url,
        "published_date": item.published_date,
        "author": item.author,
        "source": item.source,
        "company_or_topic": item.company_or_topic,
        "summary": item.summary,
        "what_happened": item.what_happened,
        "why_now": item.why_now,
        "market_context": item.market_context,
        "why_it_matters": item.why_it_matters,
        "why_it_matters_for_bidmatrix": item.why_it_matters_for_bidmatrix,
        "opportunity": item.opportunity,
        "bidmatrix_angle": item.bidmatrix_angle,
        "content_angle": item.content_angle,
        "linkedin_post_angle": item.linkedin_post_angle,
        "pr_angle": item.pr_angle,
        "concrete_action": item.concrete_action,
        "partner_or_sales_action": item.partner_or_sales_action,
        "watch_next": item.watch_next,
        "source_title": item.source_title,
        "source_domain": item.source_domain,
        "source_url": item.source_url,
        "confidence": item.confidence,
        "relevance_tier": item.relevance_tier,
        "hot_topics": item.hot_topics,
        "mentioned_companies": item.mentioned_companies,
        "signal_type": item.signal_type,
        "monitoring_layer": item.monitoring_layer,
        "page_type": item.page_type,
        "source_type": item.source_type,
        "freshness_tier": item.freshness_tier,
        "date_quality": item.date_quality,
        "freshness_confidence": item.freshness_confidence,
        "citations": item.citations,
        "relevance_score": item.relevance_score,
        "source_quality": item.source_quality,
        "originality_score": item.originality_score,
        "final_score": item.final_score,
        "score_band": _score_band(item.final_score),
    }


def _curated_item(item: NewsItem) -> dict:
    return {
        "title": item.title,
        "url": item.url,
        "source": item.source,
        "source_label": _source_label(item),
        "company_or_topic": item.company_or_topic,
        "published_date": item.published_date,
        "signal_type": item.signal_type,
        "monitoring_layer": item.monitoring_layer,
        "page_type": item.page_type,
        "source_type": item.source_type,
        "freshness_tier": item.freshness_tier,
        "date_quality": item.date_quality,
        "freshness_confidence": item.freshness_confidence,
        "summary": item.summary,
        "what_happened": item.what_happened,
        "why_now": item.why_now,
        "market_context": item.market_context,
        "why_it_matters": item.why_it_matters,
        "why_it_matters_for_bidmatrix": item.why_it_matters_for_bidmatrix,
        "bidmatrix_angle": item.bidmatrix_angle,
        "content_angle": item.content_angle,
        "linkedin_post_angle": item.linkedin_post_angle,
        "pr_angle": item.pr_angle,
        "concrete_action": item.concrete_action,
        "partner_or_sales_action": item.partner_or_sales_action,
        "watch_next": item.watch_next,
        "source_title": item.source_title,
        "source_domain": item.source_domain,
        "source_url": item.source_url,
        "confidence": item.confidence,
        "relevance_tier": item.relevance_tier,
        "hot_topics": item.hot_topics,
        "mentioned_companies": item.mentioned_companies,
        "score": item.final_score,
        "score_band": _score_band(item.final_score),
    }
