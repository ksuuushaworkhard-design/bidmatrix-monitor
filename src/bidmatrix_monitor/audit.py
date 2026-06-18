from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .delivery import (
    _filter_telegram_daily_items,
    _report_items,
    _select_telegram_daily_items,
    _telegram_can_relax_low_confidence,
    _telegram_date_status,
    _telegram_is_self_item,
    _telegram_is_trusted_unknown,
)
from .models import MonitorReport, NewsItem
from .render import render_markdown


def write_daily_audit_report(report: MonitorReport, report_dir: str | Path) -> Path:
    output_dir = Path(report_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"bidmatrix-monitor-{report.run_date.isoformat()}"
    audit_path = output_dir / f"{stem}-audit.json"
    audit_path.write_text(
        json.dumps(build_daily_audit_payload(report), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return audit_path


def build_daily_audit_payload(report: MonitorReport) -> dict[str, Any]:
    diagnostics = report.diagnostics or {}
    telegram_info = _telegram_audit_info(report)

    report_selected_urls = {item.normalized_url for item in report.items}
    telegram_candidate_urls = telegram_info["candidate_urls"]
    telegram_selected_urls = telegram_info["selected_urls"]
    telegram_rejections = telegram_info["rejections"]

    raw_by_url: dict[str, NewsItem] = {}
    for item in report.raw_items:
        raw_by_url.setdefault(item.normalized_url, item)

    candidate_by_url: dict[str, NewsItem] = {item.normalized_url: item for item in report.candidate_items}
    all_urls = sorted(set(raw_by_url) | set(candidate_by_url))
    entries: list[dict[str, Any]] = []

    for normalized_url in all_urls:
        raw_item = raw_by_url.get(normalized_url)
        candidate_item = candidate_by_url.get(normalized_url)
        base_item = candidate_item or raw_item
        selected_for_report = normalized_url in report_selected_urls
        selected_for_telegram = normalized_url in telegram_selected_urls
        stage_status = _stage_status(
            normalized_url=normalized_url,
            candidate_item=candidate_item,
            selected_for_report=selected_for_report,
            selected_for_telegram=selected_for_telegram,
            telegram_candidate_urls=telegram_candidate_urls,
        )
        rejection_reason = _rejection_reason(
            normalized_url=normalized_url,
            candidate_item=candidate_item,
            selected_for_report=selected_for_report,
            selected_for_telegram=selected_for_telegram,
            telegram_candidate_urls=telegram_candidate_urls,
            telegram_rejections=telegram_rejections,
        )
        entries.append(
            {
                "url": _value(base_item.url if base_item else None),
                "title": _value(base_item.title if base_item else None),
                "source": _value(_optional_attr(candidate_item, "source") or _optional_attr(raw_item, "source")),
                "source_domain": _value(
                    _optional_attr(candidate_item, "source_domain") or _optional_attr(raw_item, "source_domain")
                ),
                "topic_id": _value(_optional_attr(candidate_item, "topic_id") or _optional_attr(raw_item, "topic_id")),
                "monitoring_layer": _value(
                    _optional_attr(candidate_item, "monitoring_layer") or _optional_attr(raw_item, "monitoring_layer")
                ),
                "published_date": _value(
                    _optional_attr(candidate_item, "published_date") or _optional_attr(raw_item, "published_date")
                ),
                "date_quality": _value(_optional_attr(candidate_item, "date_quality")),
                "freshness_tier": _value(_optional_attr(candidate_item, "freshness_tier")),
                "source_quality": _numeric_or_none(candidate_item, "source_quality"),
                "relevance_tier": _value(_optional_attr(candidate_item, "relevance_tier")),
                "final_score": _numeric_or_none(candidate_item, "final_score"),
                "confidence": _value(_optional_attr(candidate_item, "confidence")),
                "stage_status": stage_status,
                "rejection_reason": rejection_reason,
                "selected_for_report": selected_for_report,
                "selected_for_telegram": selected_for_telegram,
            }
        )

    return {
        "run_date": report.run_date.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "exa_total_queries": diagnostics.get("exa_total_queries"),
        "exa_total_raw_results": diagnostics.get("exa_total_raw_results"),
        "exa_unique_results": diagnostics.get("exa_unique_results"),
        "exa_errors_count": diagnostics.get("exa_errors_count"),
        "exa_timeouts_count": diagnostics.get("exa_timeouts_count"),
        "raw_results_count": diagnostics.get("raw_items_found"),
        "parsed_signals_count": diagnostics.get("parsed_signals_count"),
        "selected_top_signals_count": diagnostics.get("selected_top_signals_count"),
        "selected_digest_items_count": diagnostics.get("selected_digest_items_count"),
        "curated_signals_kept": diagnostics.get("curated_items_kept"),
        "telegram_message_state": diagnostics.get("telegram_message_state"),
        "fallback_level_used": diagnostics.get("fallback_level_used"),
        "candidates": entries,
    }


def _telegram_audit_info(report: MonitorReport) -> dict[str, Any]:
    markdown = render_markdown(report)
    parsed = _report_items(markdown)
    top_items = [item for item in parsed if item.get("section") == "top"]
    adjacent_items = [item for item in parsed if item.get("section") == "adjacent"]
    filtered_top, _top_stats = _filter_telegram_daily_items(top_items, report.run_date)
    filtered_adjacent, _adjacent_stats = _filter_telegram_daily_items(adjacent_items, report.run_date)
    selected, _selection_meta = _select_telegram_daily_items(
        filtered_top,
        filtered_adjacent,
        target=3,
        limit=4,
    )

    candidate_urls = {_normalized_url(item.get("url")) for item in top_items + adjacent_items if item.get("url")}
    selected_urls = {_normalized_url(item.get("url")) for item in selected if item.get("url")}
    rejections: dict[str, str] = {}
    for item in top_items + adjacent_items:
        url = _normalized_url(item.get("url"))
        if not url or url in selected_urls:
            continue
        rejections[url] = _telegram_rejection_reason(item, report.run_date)

    return {
        "candidate_urls": candidate_urls,
        "selected_urls": selected_urls,
        "rejections": rejections,
    }


def _telegram_rejection_reason(item: dict[str, str], run_date) -> str:
    if _telegram_is_self_item(item):
        return "telegram_self_item"
    status = _telegram_date_status(item, run_date)
    quality = status["quality"]
    if quality == "future_invalid":
        return "telegram_future_invalid"
    if quality == "old_2025_or_earlier":
        return "telegram_old_2025_or_earlier"
    if quality == "older_than_30d":
        return "telegram_older_than_30d"
    if quality == "missing_or_unknown_date":
        return "telegram_missing_or_unknown_date"
    if item.get("confidence") == "low" and not _telegram_can_relax_low_confidence(item, quality):
        return "telegram_low_confidence"
    if quality == "unknown_trusted" and not _telegram_is_trusted_unknown(item):
        return "telegram_unknown_untrusted"
    return "telegram_selection_limit_or_diversity"


def _stage_status(
    *,
    normalized_url: str,
    candidate_item: NewsItem | None,
    selected_for_report: bool,
    selected_for_telegram: bool,
    telegram_candidate_urls: set[str],
) -> str:
    if selected_for_telegram:
        return "selected_for_telegram"
    if selected_for_report and normalized_url in telegram_candidate_urls:
        return "rejected_by_telegram"
    if selected_for_report:
        return "selected_for_report"
    if candidate_item is not None:
        return "rejected"
    return "raw_found"


def _rejection_reason(
    *,
    normalized_url: str,
    candidate_item: NewsItem | None,
    selected_for_report: bool,
    selected_for_telegram: bool,
    telegram_candidate_urls: set[str],
    telegram_rejections: dict[str, str],
) -> str | None:
    if selected_for_telegram:
        return None
    if selected_for_report and normalized_url in telegram_candidate_urls:
        return telegram_rejections.get(normalized_url)
    if selected_for_report:
        return None
    if candidate_item is None:
        return "deduped_out_before_scoring"
    if candidate_item.relevance_tier == "ignore":
        return "relevance_tier_ignore"
    if candidate_item.freshness_tier == "background_context":
        return "freshness_not_fresh"
    return "not_selected_for_report"


def _value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return value


def _numeric_or_none(item: NewsItem | None, attribute: str) -> int | None:
    if item is None:
        return None
    value = getattr(item, attribute, None)
    return value if isinstance(value, int) else None


def _optional_attr(item: NewsItem | None, attribute: str) -> Any:
    if item is None:
        return None
    return getattr(item, attribute, None)


def _normalized_url(url: str | None) -> str:
    if not url:
        return ""
    return str(url).split("?", 1)[0].rstrip("/").replace("/amp", "")
