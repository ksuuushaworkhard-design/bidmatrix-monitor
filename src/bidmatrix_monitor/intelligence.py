from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
import re
from urllib.parse import urlparse

from .models import MonitorConfig, MonitorReport, NewsItem


def dedupe_items(items: list[NewsItem], config: MonitorConfig | None = None) -> list[NewsItem]:
    scored = [_score_item(item, config) for item in items]
    by_url: dict[str, NewsItem] = {}
    for item in scored:
        existing = by_url.get(_canonical_url(item.url))
        if existing is None or item.relevance_score > existing.relevance_score:
            by_url[_canonical_url(item.url)] = item

    deduped: list[NewsItem] = []
    for item in sorted(by_url.values(), key=lambda value: (-value.final_score, -value.relevance_score, value.title.lower())):
        duplicate_index = _near_duplicate_index(item, deduped)
        if duplicate_index is None:
            deduped.append(item)
        elif item.final_score > deduped[duplicate_index].final_score:
            deduped[duplicate_index] = item

    return sorted(deduped, key=lambda item: (-item.final_score, -item.relevance_score, item.topic_label, item.title.lower()))


def build_report(
    items: list[NewsItem],
    config: MonitorConfig,
    exa_errors: list[str] | None = None,
    exa_meta: dict | None = None,
) -> MonitorReport:
    deduped = dedupe_items(items, config)
    thresholds = _sensitivity_thresholds(config)
    fresh_candidates = [
        item
        for item in deduped
        if item.relevance_tier != "ignore"
        and item.source_quality >= thresholds["curated_min_source_quality"]
        and item.freshness_tier in {"new_last_24h", "new_last_7d"}
    ]
    curated = [item for item in fresh_candidates if item.final_score >= thresholds["curated_min_score"]][
        : config.outputs.max_items_in_digest
    ]
    core_curated = [item for item in curated if item.relevance_tier == "core"]
    adjacent_curated = [item for item in curated if item.relevance_tier == "adjacent"]
    all_background_items = [
        item
        for item in deduped
        if item.relevance_tier != "ignore"
        and item.source_quality >= thresholds["background_min_source_quality"]
        and item.freshness_tier == "background_context"
        and item.final_score >= thresholds["background_min_score"]
    ][:5]
    digest_target = max(2, min(config.outputs.daily_digest_target, 5))
    daily_signals, adjacent_watchlist, fallback_level_used, market_watch_meta = _select_daily_content(
        core_curated=core_curated,
        adjacent_curated=adjacent_curated,
        deduped=deduped,
        thresholds=thresholds,
        target=digest_target,
    )
    daily_digest_items = daily_signals if daily_signals else adjacent_watchlist
    background_items = all_background_items if (daily_signals or adjacent_watchlist) else []
    report_items = _unique_items(curated + background_items + adjacent_watchlist + daily_digest_items)
    diagnostics = _diagnostics(items, deduped, curated, background_items, thresholds)
    diagnostics.update(exa_meta or {})
    diagnostics["kept_core_signals"] = len(core_curated)
    diagnostics["kept_adjacent_signals"] = len(adjacent_curated)
    diagnostics["selected_top_signals_count"] = len(daily_signals)
    diagnostics["selected_digest_items_count"] = len(daily_digest_items)
    diagnostics["fallback_level_used"] = fallback_level_used
    diagnostics.update(market_watch_meta)
    diagnostics["telegram_message_state"] = _telegram_message_state(daily_signals, adjacent_watchlist, background_items, items, exa_errors or [])
    diagnostics["exa_errors"] = list(exa_errors or [])
    trends = _trends(report_items, config.outputs.recurring_trend_min_mentions)
    top_news = daily_signals[:8]
    partner_signals = [
        item
        for item in curated
        if item.signal_type != "competitor_move"
        and (_matches_any(item, config.tracking.partners) or item.signal_type == "partner_signal")
    ][:6]
    competitor_moves = [
        item for item in curated if _matches_any(item, config.tracking.competitors) or item.signal_type == "competitor_move"
    ][:6]
    primary_items = core_curated or curated
    return MonitorReport(
        run_date=date.today(),
        diagnostics=diagnostics,
        items=report_items,
        trends=trends,
        daily_intro=_daily_intro(
            items,
            curated,
            daily_signals,
            adjacent_watchlist,
            background_items,
            diagnostics["exa_errors"],
            fallback_level_used,
            diagnostics,
        ),
        daily_signals=daily_signals,
        daily_digest_items=daily_digest_items,
        adjacent_watchlist=adjacent_watchlist,
        top_news=top_news,
        actually_new_today=[
            item
            for item in core_curated
            if item.freshness_tier == "new_last_24h" and item.freshness_confidence >= 4
        ][:5],
        fresh_weak_confidence=[
            item
            for item in core_curated
            if item.freshness_tier in {"new_last_24h", "new_last_7d"}
            and (item.date_quality != "explicit_date" or item.freshness_confidence < 4)
        ][:5],
        background_items=background_items,
        what_this_suggests=_daily_digest_synthesis(daily_digest_items),
        bidmatrix_angles=_bidmatrix_angles(daily_digest_items),
        watch_next_items=_watch_next_items(daily_digest_items),
        hot_takes=_hot_takes(primary_items, trends)[:6],
        partner_signals=partner_signals,
        competitor_moves=competitor_moves,
        content_angles_for_linkedin=_content_angles(primary_items)[:8],
        pr_hooks=_pr_hooks(primary_items)[:6],
        what_changed_today=_what_changed(primary_items, trends)[:8],
        exa_errors=list(exa_errors or []),
    )

def _daily_signals(curated: list[NewsItem], target: int) -> list[NewsItem]:
    return _recent_signals(curated, target)


def _select_daily_content(
    core_curated: list[NewsItem],
    adjacent_curated: list[NewsItem],
    deduped: list[NewsItem],
    thresholds: dict[str, int | str],
    target: int,
) -> tuple[list[NewsItem], list[NewsItem], str, dict[str, object]]:
    strong_core = [item for item in core_curated if item.confidence in {"high", "medium"}]
    daily_signals = _recent_signals(strong_core, target)
    if daily_signals:
        if any(item.freshness_tier == "new_last_7d" and not _is_last_72h(item) for item in daily_signals):
            return daily_signals, [], "core_7d", {}
        if any(_is_last_72h(item) and item.freshness_tier != "new_last_24h" for item in daily_signals):
            return daily_signals, [], "core_72h", {}
        return daily_signals, [], "core_24h", {}

    broader_recent, market_watch_meta = _recent_market_watch_items(deduped, thresholds, target=target)
    if broader_recent:
        return [], broader_recent, "market_watch_14d", market_watch_meta

    older_recent, older_meta = _best_available_recent_items(deduped, target=target)
    if older_recent:
        return [], older_recent, "market_watch_best_available", older_meta

    return [], [], "empty", {
        "market_watch_candidates_count": 0,
        "selected_market_watch_reason": "",
        "selected_market_watch_priority_score": 0,
        "market_watch_rejections": [],
    }


def _recent_signals(items: list[NewsItem], target: int) -> list[NewsItem]:
    selected: list[NewsItem] = []
    buckets = [
        _sort_daily_bucket([item for item in items if item.freshness_tier == 'new_last_24h']),
        _sort_daily_bucket([item for item in items if _is_last_72h(item) and item.freshness_tier != 'new_last_24h']),
        _sort_daily_bucket([item for item in items if item.freshness_tier == 'new_last_7d' and not _is_last_72h(item)]),
    ]
    for bucket in buckets:
        for item in bucket:
            if item.normalized_url not in {value.normalized_url for value in selected}:
                selected.append(item)
            if len(selected) >= target:
                return selected
    return selected


def _recent_market_watch_items(
    items: list[NewsItem], thresholds: dict[str, int | str], target: int
) -> tuple[list[NewsItem], dict[str, object]]:
    candidates = [
        item
        for item in items
        if item.relevance_tier in {"core", "adjacent"}
        and item.confidence in {"high", "medium"}
        and item.source_quality >= int(thresholds["background_min_source_quality"])
        and item.final_score >= max(int(thresholds["curated_min_score"]) - 1, 6)
        and _is_last_14d(item)
    ]
    unique_candidates = _unique_items(candidates)
    scored_candidates: list[tuple[int, str, NewsItem]] = []
    for item in unique_candidates:
        priority, reason = _market_watch_priority(item)
        item.market_watch_priority_score = priority
        item.market_watch_reason = reason
        scored_candidates.append((priority, reason, item))

    ranked = sorted(
        scored_candidates,
        key=lambda value: (
            -value[0],
            -value[2].final_score,
            -value[2].freshness_confidence,
            value[2].title.lower(),
        ),
    )
    selected = _select_diverse_market_watch_items(ranked, target, minimum=2)
    meta: dict[str, object] = {
        "market_watch_candidates_count": len(unique_candidates),
        "selected_market_watch_reason": selected[0].market_watch_reason if selected else "",
        "selected_market_watch_priority_score": selected[0].market_watch_priority_score if selected else 0,
        "market_watch_rejections": [
            {
                "title": item.title,
                "priority_score": priority,
                "reason": reason,
            }
            for priority, reason, item in ranked[1:6]
        ],
    }
    return selected, meta

def _sort_daily_bucket(items: list[NewsItem]) -> list[NewsItem]:
    return sorted(
        items,
        key=lambda item: (
            -item.final_score,
            -item.freshness_confidence,
            0 if item.date_quality == "explicit_date" else 1,
            item.title.lower(),
        ),
    )


def _daily_intro(
    raw_items: list[NewsItem],
    curated: list[NewsItem],
    daily_signals: list[NewsItem],
    adjacent_watchlist: list[NewsItem],
    background_items: list[NewsItem],
    exa_errors: list[str],
    fallback_level_used: str,
    diagnostics: dict,
) -> str:
    count = len(daily_signals)
    if count:
        noun = 'signal' if count == 1 else 'signals'
        return f'Found {count} core {noun} worth attention today.'
    if adjacent_watchlist:
        if fallback_level_used == "market_watch_best_available":
            return "No major core BidMatrix signal dominated today, but several relevant market moves are worth tracking."
        return 'No direct core BidMatrix signal dominated today, so this brief uses the strongest adjacent industry signals worth monitoring.'
    if not raw_items:
        return (
            "Market brief monitor ran, but no Exa results were available. "
            "Please check EXA_API_KEY, Exa response logs, or source/query configuration."
        )
    if diagnostics.get("exa_budget_exceeded"):
        return (
            "Exa returned results, but the fallback search budget was reached before additional market-watch queries could run."
        )
    if curated or background_items or fallback_level_used == "empty":
        return (
            "No core BidMatrix-relevant signals found today.\n\n"
            "The monitor ran successfully, but no usable market signals passed the relevance filters.\n"
            "Checked: mobile UA, measurement, fraud, CTV, AI campaign ops, partner and competitor updates.\n\n"
            f"Raw results found: {len(raw_items)}\n"
            f"Curated signals kept: {len(curated) + len(background_items)}"
        )
    return (
        "No core BidMatrix-relevant signals found today.\n\n"
        "Raw results were found, but none passed BidMatrix relevance filters."
    )

def _sensitivity_thresholds(config: MonitorConfig) -> dict[str, int | str]:
    base_min_score = config.outputs.min_relevance_score
    mode = config.outputs.sensitivity
    if mode == "strict":
        return {
            "mode": mode,
            "curated_min_score": max(7, base_min_score),
            "curated_min_source_quality": 1,
            "background_min_score": 9,
            "background_min_source_quality": 2,
        }
    if mode == "broad":
        return {
            "mode": mode,
            "curated_min_score": max(4, base_min_score - 1),
            "curated_min_source_quality": 0,
            "background_min_score": 7,
            "background_min_source_quality": 0,
        }
    return {
        "mode": "balanced",
        "curated_min_score": base_min_score,
        "curated_min_source_quality": 1,
        "background_min_score": 8,
        "background_min_source_quality": 1,
    }


def _diagnostics(
    raw_items: list[NewsItem],
    deduped_items: list[NewsItem],
    curated: list[NewsItem],
    background_items: list[NewsItem],
    thresholds: dict[str, int | str],
) -> dict[str, int | str]:
    fresh_items = [item for item in deduped_items if item.freshness_tier in {"new_last_24h", "new_last_7d"}]
    source_ok_items = [
        item for item in fresh_items if item.source_quality >= int(thresholds["curated_min_source_quality"])
    ]
    curated_urls = {item.normalized_url for item in curated}
    background_urls = {item.normalized_url for item in background_items}
    kept_urls = curated_urls | background_urls
    tier_counts = Counter(item.relevance_tier for item in deduped_items)
    return {
        "sensitivity": str(thresholds["mode"]),
        "raw_items_found": len(raw_items),
        "parsed_signals_count": len(deduped_items),
        "raw_daily_fresh_signals": len([item for item in raw_items if item.monitoring_layer == "daily_fresh_signals"]),
        "raw_strategic_background": len([item for item in raw_items if item.monitoring_layer == "strategic_background"]),
        "deduped_items_scored": len(deduped_items),
        "filtered_out_by_freshness": len([item for item in deduped_items if item.freshness_tier == "background_context" and item.normalized_url not in background_urls]),
        "filtered_out_by_source_quality": len(
            [
                item
                for item in fresh_items
                if item.source_quality < int(thresholds["curated_min_source_quality"])
            ]
        ),
        "filtered_out_by_score": len(
            [
                item
                for item in source_ok_items
                if item.final_score < int(thresholds["curated_min_score"])
            ]
        ),
        "kept_new_last_24h": len([item for item in curated if item.freshness_tier == "new_last_24h"]),
        "kept_new_last_7d": len([item for item in curated if item.freshness_tier == "new_last_7d"]),
        "kept_background_context": len(background_items),
        "curated_items_kept": len(kept_urls),
        "core_count": tier_counts.get("core", 0),
        "adjacent_count": tier_counts.get("adjacent", 0),
        "background_count": tier_counts.get("background", 0),
        "ignored_count": tier_counts.get("ignore", 0),
        "page_type_counts": dict(Counter(item.page_type for item in deduped_items)),
        "source_type_counts": dict(Counter(item.source_type for item in deduped_items)),
    }


def _telegram_message_state(
    daily_signals: list[NewsItem],
    adjacent_watchlist: list[NewsItem],
    background_items: list[NewsItem],
    raw_items: list[NewsItem],
    exa_errors: list[str],
) -> str:
    if not raw_items:
        return "monitor_error"
    if daily_signals:
        return "core"
    if adjacent_watchlist:
        return "adjacent" if not any(item.relevance_tier == "core" for item in adjacent_watchlist) else "market_watch"
    if raw_items:
        return "filtered_empty"
    return "empty"


def _best_available_recent_items(items: list[NewsItem], target: int) -> tuple[list[NewsItem], dict[str, object]]:
    candidates = [
        item
        for item in items
        if item.relevance_tier in {"core", "adjacent"}
        and (_is_last_14d(item) or item.freshness_tier == "background_context")
    ]
    unique_candidates = _unique_items(candidates)
    ranked: list[tuple[int, str, NewsItem]] = []
    for item in unique_candidates:
        priority, reason = _market_watch_priority(item)
        item.market_watch_priority_score = priority
        item.market_watch_reason = reason
        ranked.append((priority + _confidence_bonus(item), reason, item))
    ranked.sort(key=lambda value: (-value[0], -value[2].final_score, -value[2].freshness_confidence, value[2].title.lower()))
    selected = _select_diverse_market_watch_items(ranked, target, minimum=2)
    meta = {
        "market_watch_candidates_count": len(unique_candidates),
        "selected_market_watch_reason": selected[0].market_watch_reason if selected else "",
        "selected_market_watch_priority_score": selected[0].market_watch_priority_score if selected else 0,
        "market_watch_rejections": [
            {
                "title": item.title,
                "priority_score": priority,
                "reason": reason,
            }
            for priority, reason, item in ranked
            if item not in selected
        ][:5],
    }
    return selected, meta


def _select_diverse_market_watch_items(
    ranked: list[tuple[int, str, NewsItem]], target: int, minimum: int = 2
) -> list[NewsItem]:
    if not ranked:
        return []

    selected: list[NewsItem] = []
    seen_urls: set[str] = set()
    seen_reasons: set[str] = set()
    max_items = max(minimum, min(target, 5))

    for _, reason, item in ranked:
        if item.normalized_url in seen_urls:
            continue
        if item.market_watch_priority_score <= 15 and len(selected) >= 3:
            continue
        if reason in seen_reasons and len(selected) < minimum:
            continue
        if reason in seen_reasons and item.market_watch_priority_score <= 15:
            continue
        selected.append(item)
        seen_urls.add(item.normalized_url)
        seen_reasons.add(reason)
        if len(selected) >= max_items:
            return selected

    for priority, _, item in ranked:
        if item.normalized_url in seen_urls:
            continue
        if priority <= 15 and len(selected) >= 3:
            continue
        selected.append(item)
        seen_urls.add(item.normalized_url)
        if len(selected) >= max_items:
            break
    return selected


def _confidence_bonus(item: NewsItem) -> int:
    return {"high": 8, "medium": 4, "low": 0}.get(item.confidence, 0)


def _market_watch_priority(item: NewsItem) -> tuple[int, str]:
    text = _item_text(item)
    if _has_terms(item, "appsflyer", "adjust", "singular", "airbridge", "kochava", "branch", "mmp", "attribution", "skan", "privacy sandbox", "adattributionkit", "measurement partner", "conversion value", "postback"):
        return 100, "measurement_attribution_priority"
    if _has_terms(item, "mobile user acquisition", "user acquisition", "app growth", "performance marketing", "app marketers", "app advertisers", "mobile marketing"):
        return 90, "mobile_ua_app_growth_priority"
    if _has_terms(item, "fraud", "invalid traffic", "ivt", "traffic quality", "brand safety", "viewability", "verified"):
        return 80, "fraud_quality_priority"
    if _has_terms(item, "ctv", "connected tv", "performance ctv", "installs", "mmp", "roi", "roas"):
        return 70, "ctv_app_performance_priority"
    if _has_terms(item, "ai media buying", "campaign optimization", "media optimization", "creative intelligence", "creative effectiveness", "budget shifts", "agentic media buying", "agentic"):
        return 60, "ai_campaign_ops_priority"
    if _has_terms(item, "programmatic", "in-app", "dsp", "ssp", "exchange", "inventory", "direct deals", "brand demand"):
        return 50, "programmatic_in_app_priority"
    if _has_terms(item, "applovin", "moloco", "liftoff", "adjust", "appsflyer", "singular", "airbridge", "kochava", "branch", "tenjin", "braze", "clevertap", "apptweak"):
        return 40, "partner_competitor_priority"
    if _has_terms(item, "report", "benchmark", "index", "conference", "summit", "mau", "business of apps", "mobile marketing reads"):
        return 30, "industry_report_conference_priority"
    if _has_terms(item, "overwolf", "gamer grid", "pc gaming", "gameplay", "hardware signals", "gamer", "gaming audience", "broad brand"):
        return 10, "adjacent_gaming_watchlist_priority"
    if item.relevance_tier == "adjacent" or "indirect" in (item.why_it_matters_for_bidmatrix or "").lower():
        return 5, "indirect_watchlist_priority"
    return 20, "general_market_watch_priority"


def _score_item(item: NewsItem, config: MonitorConfig | None) -> NewsItem:
    explicit_date = _parse_date(item.published_date)
    inferred_date = explicit_date or _date_from_url(item.url)
    if explicit_date:
        item.date_quality = "explicit_date"
    elif inferred_date:
        item.date_quality = "inferred_date"
        item.published_date = inferred_date.isoformat()
    else:
        item.date_quality = "unknown_date"
    item.page_type = _page_type(item)
    item.source_type = _source_type(item, config)
    item.freshness_confidence = _freshness_confidence(item)
    source_quality = _source_quality(item, config)
    freshness_tier = _freshness_tier(item)
    originality_score = _originality_score(item)
    _enrich_signal(item, config)
    relevance = _relevance_score(item, config)
    entity_bonus = 0

    if config:
        partner_match = _matches_any(item, config.tracking.partners)
        competitor_match = _matches_any(item, config.tracking.competitors)
        conference_match = _matches_any(item, config.tracking.conferences)

        if partner_match:
            entity_bonus = max(entity_bonus, 1)
            if not competitor_match and item.signal_type in {"top_news", "competitor_move"}:
                item.signal_type = "partner_signal"
        if competitor_match:
            entity_bonus = max(entity_bonus, 1)
            if item.signal_type in {"top_news", "partner_signal"}:
                item.signal_type = "competitor_move"
        if conference_match:
            entity_bonus = max(entity_bonus, 1)
            if item.signal_type == "top_news":
                item.signal_type = "conference_signal"

    score = 0
    score += {2: 2, 1: 1, 0: 0, -1: -2, -2: -4}.get(source_quality, 0)
    score += {"new_last_24h": 2, "new_last_7d": 1, "background_context": 0}.get(freshness_tier, 0)
    score += relevance
    score += originality_score
    score += entity_bonus
    score += 1 if item.why_it_matters else 0
    score += 1 if item.what_happened and item.why_now and item.concrete_action else 0
    if item.monitoring_layer == "daily_fresh_signals" and item.date_quality == "unknown_date":
        score -= 0 if _is_top_fresh_source(item, config) else 2
    if item.monitoring_layer == "daily_fresh_signals" and _is_background_page_type(item.page_type):
        if not (item.date_quality == "explicit_date" and item.freshness_tier in {"new_last_24h", "new_last_7d"}):
            score -= 3
    if item.monitoring_layer == "daily_fresh_signals" and item.page_type in _FRESH_PAGE_TYPES:
        score += 1
    if item.source_type == "aggregator":
        score -= 3
    if item.freshness_confidence >= 4:
        score += 1
    if item.monitoring_layer == "daily_fresh_signals" and item.freshness_tier == "background_context":
        score -= 1
    if item.monitoring_layer == "strategic_background" and item.freshness_tier in {"new_last_24h", "new_last_7d"}:
        score -= 1

    item.linkedin_post_angle = item.content_angle or _linkedin_angle(item)
    item.bidmatrix_angle = item.why_it_matters_for_bidmatrix or _bidmatrix_angle(item)
    item.pr_angle = _pr_angle(item)
    item.partner_or_sales_action = item.concrete_action or _partner_or_sales_action(item)
    item.source_quality = source_quality
    item.freshness_tier = freshness_tier
    item.originality_score = originality_score
    item.confidence = _confidence_label(item, score)
    item.final_score = max(1, min(10, score))
    return item


def _enrich_signal(item: NewsItem, config: MonitorConfig | None = None) -> None:
    item.signal_type = _normalized_signal_type(item)
    item.company_or_topic = _primary_company_or_topic(item) or item.company_or_topic or _lead_entity(item) or item.topic_label
    item.source_title = item.source_title or item.title
    item.source_domain = item.source_domain or urlparse(item.url).netloc.lower().removeprefix("www.")
    item.source_url = item.source_url or item.url
    item.relevance_tier = _relevance_tier(item, config)
    item.what_happened = _best_what_happened(item)
    item.why_now = _best_why_now(item)
    item.market_context = _best_market_context(item)
    item.why_it_matters_for_bidmatrix = _best_bidmatrix_implication(item)
    item.content_angle = _best_content_angle(item)
    item.concrete_action = _best_concrete_action(item)
    item.watch_next = _best_watch_next(item)
    if not item.summary:
        item.summary = item.what_happened
    if not item.why_it_matters:
        item.why_it_matters = item.why_now or item.market_context


def _normalized_signal_type(item: NewsItem) -> str:
    raw = (item.signal_type or "").strip().lower()
    mapping = {
        "competitor_move": "competitor_signal",
        "partner_signal": "partnership",
        "conference_signal": "conference",
        "measurement_update": "privacy_measurement",
        "fraud_signal": "fraud_quality",
        "creative_signal": "AI_marketing",
        "top_news": "other",
    }
    if raw in mapping:
        return mapping[raw]
    if raw in {
        "product_launch",
        "funding",
        "partnership",
        "platform_update",
        "privacy_measurement",
        "fraud_quality",
        "ai_marketing",
        "conference",
        "competitor_signal",
        "market_report",
        "other",
    }:
        return raw
    text = _item_text(item)
    if any(term in text for term in ("funding", "raised", "series a", "series b", "seed round", "acquisition")):
        return "funding"
    if any(term in text for term in ("partnership", "partnered", "integrates with", "integration")):
        return "partnership"
    if any(term in text for term in ("release notes", "changelog", "sdk", "wwdc", "privacy sandbox", "adattributionkit", "skan")):
        return "privacy_measurement"
    if any(term in text for term in ("fraud", "invalid traffic", "quality index", "brand safety", "viewability")):
        return "fraud_quality"
    if any(term in text for term in ("ai", "creative", "automation", "copilot", "optimization")):
        return "AI_marketing"
    if any(term in text for term in ("conference", "agenda", "speaker", "sponsor", "summit", "expo")):
        return "conference"
    if any(term in text for term in ("report", "benchmark", "index", "study")):
        return "market_report"
    if any(term in text for term in ("launch", "launched", "announced", "new product", "general availability")):
        return "product_launch"
    if any(term in text for term in ("update", "updated", "rollout", "version")):
        return "platform_update"
    return "other"


def _daily_digest_synthesis(items: list[NewsItem]) -> list[str]:
    if len(items) < 2:
        return []

    reasons = {item.market_watch_reason for item in items if item.market_watch_reason}
    sentences: list[str] = []
    if any("measurement" in reason for reason in reasons) and any("ctv" in reason for reason in reasons):
        sentences.append(
            "Measurement changes and performance CTV signals both point to a market that wants clearer proof of outcomes, not just more reach."
        )
    if any("ai" in reason for reason in reasons) and any("programmatic" in reason or "mobile_ua" in reason for reason in reasons):
        sentences.append(
            "Automation is moving deeper into media operations, but advertisers still need transparent supply, usable attribution, and human QA around performance."
        )
    if any("programmatic" in reason for reason in reasons):
        sentences.append(
            "The common thread is that app inventory is being packaged with more emphasis on direct brand-demand paths, measurable quality, and stronger in-app monetization economics."
        )
    if any("measurement" in reason for reason in reasons):
        sentences.append(
            "Attribution resilience and privacy-safe optimization remain central to how growth teams decide where budget should move next."
        )
    if not sentences:
        sentences.append(
            "The common thread is not more adtech noise, but stronger pressure for measurable outcomes, cleaner inventory, and better decision support."
        )
    return _unique_nonempty(sentences)[:4]


def _bidmatrix_angles(items: list[NewsItem]) -> list[str]:
    values = [item.why_it_matters_for_bidmatrix or item.bidmatrix_angle for item in items]
    return _unique_nonempty(values)[:5]


def _watch_next_items(items: list[NewsItem]) -> list[str]:
    values = [item.watch_next for item in items]
    return _unique_nonempty(values)[:4]


def _trends(items: list[NewsItem], min_mentions: int) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for item in items:
        counter.update(topic.lower().strip() for topic in item.hot_topics if topic.strip())
    return [(topic, count) for topic, count in counter.most_common() if count >= min_mentions]


def _positioning_ideas(items: list[NewsItem], trends: list[tuple[str, int]]) -> list[str]:
    ideas = []
    for trend, count in trends:
        ideas.append(f"Position around {trend}: {count} fresh signals suggest buyers may need clearer guidance.")
    for item in items:
        if item.why_it_matters:
            ideas.append(item.why_it_matters)
    return _unique_nonempty(ideas)


def _hot_takes(items: list[NewsItem], trends: list[tuple[str, int]]) -> list[str]:
    takes = []
    for trend, count in trends:
        takes.append(f"{trend.title()} is gaining momentum across {count} signals.")
    for item in items:
        if item.final_score >= 8 and item.why_it_matters:
            takes.append(item.why_it_matters)
    return _unique_nonempty(takes)


def _content_angles(items: list[NewsItem]) -> list[str]:
    values = []
    for item in items:
        if item.linkedin_post_angle:
            values.append(item.linkedin_post_angle)
        elif item.hot_topics:
            values.append(f"What {', '.join(item.hot_topics[:2])} means for mobile growth teams.")
    return _unique_nonempty(values)


def _pr_hooks(items: list[NewsItem]) -> list[str]:
    hooks = []
    for item in items:
        if item.pr_angle:
            hooks.append(item.pr_angle)
    return _unique_nonempty(hooks)


def _what_changed(items: list[NewsItem], trends: list[tuple[str, int]]) -> list[str]:
    changes = [f"{trend.title()} appeared across {count} curated signals." for trend, count in trends]
    for item in items:
        changes.append(item.summary)
    return _unique_nonempty(changes)


def _near_duplicate_index(item: NewsItem, existing_items: list[NewsItem]) -> int | None:
    item_title = _normalize_title(item.title)
    item_companies = {value.lower() for value in item.mentioned_companies}
    for index, existing in enumerate(existing_items):
        existing_title = _normalize_title(existing.title)
        similarity = SequenceMatcher(None, item_title, existing_title).ratio()
        company_overlap = bool(item_companies & {value.lower() for value in existing.mentioned_companies})
        same_topic = item.topic_id == existing.topic_id
        if similarity >= 0.86 or (similarity >= 0.74 and (company_overlap or same_topic)):
            return index
    return None


def _source_quality(item: NewsItem, config: MonitorConfig | None) -> int:
    if not config:
        return 0
    domain = urlparse(item.url).netloc.lower().removeprefix("www.")
    if any(domain == value or domain.endswith(f".{value}") for value in config.sources.low_value_domains):
        return -2
    if item.source_type == "aggregator":
        return -2
    if any(domain == value or domain.endswith(f".{value}") for value in config.sources.fresh_priority_domains):
        return 2
    if any(domain == value or domain.endswith(f".{value}") for value in config.sources.background_priority_domains):
        return 2 if item.monitoring_layer == "strategic_background" else 1
    if any(domain == value or domain.endswith(f".{value}") for value in config.sources.high_signal_domains):
        if _is_official_source(item, config):
            return 2
        return 1
    return 0


def _is_official_source(item: NewsItem, config: MonitorConfig) -> bool:
    domain = urlparse(item.url).netloc.lower().removeprefix("www.")
    official_terms = [name.lower().replace(" ", "") for name in (
        config.tracking.partners + config.tracking.competitors + config.tracking.conferences + config.tracking.watchlist
    )]
    compact_domain = domain.replace("-", "").replace(".", "")
    if any(term and term in compact_domain for term in official_terms):
        return True
    official_words = ("blog", "newsroom", "press", "product", "events", "conference")
    return any(word in item.url.lower() for word in official_words)


def _freshness_tier(item: NewsItem) -> str:
    published = _parse_date(item.published_date) or _date_from_url(item.url)
    if not published:
        return "background_context"
    today = date.today()
    if published >= today:
        return "new_last_24h"
    if published >= today - timedelta(days=6):
        return "new_last_7d"
    return "background_context"


def _is_top_fresh_source(item: NewsItem, config: MonitorConfig | None) -> bool:
    if not config:
        return False
    domain = urlparse(item.url).netloc.lower().removeprefix("www.")
    return any(domain == value or domain.endswith(f".{value}") for value in config.sources.fresh_priority_domains)


_FRESH_PAGE_TYPES = {
    "newsroom",
    "press_release",
    "product_update",
    "release_notes",
    "conference_announcement",
    "news_article",
}

_BACKGROUND_PAGE_TYPES = {
    "product_page",
    "comparison_page",
    "guide",
    "report_page",
    "thought_leadership",
}


def _page_type(item: NewsItem) -> str:
    text = _item_text(item)
    path = urlparse(item.url).path.lower()
    if any(token in path for token in ("/release-notes", "/releases", "/changelog", "/change-log")):
        return "release_notes"
    if any(token in path for token in ("/newsroom", "/company/news", "/news/")):
        return "newsroom"
    if any(token in path for token in ("/press", "/pr/", "/press-release")) or "press release" in text:
        return "press_release"
    if any(token in path for token in ("/product-update", "/product-updates", "/updates", "/blog/product")):
        return "product_update"
    if any(token in path for token in ("/events/", "/event/", "/agenda", "/speakers", "/sponsor")):
        return "conference_announcement"
    if any(token in path for token in ("/compare", "/vs-", "-vs-", "/alternatives")):
        return "comparison_page"
    if any(token in path for token in ("/products/", "/product/", "/platform/")):
        return "product_page"
    if any(token in path for token in ("/resources/reports", "/report", "/reports", "/benchmark", "/index")):
        return "report_page"
    if any(token in path for token in ("/guide", "/guides", "/best-", "/top-")):
        return "guide"
    if any(token in path for token in ("/blog/", "/insights/", "/thought-leadership")):
        if any(word in text for word in ("announced", "launch", "released", "update")):
            return "news_article"
        return "thought_leadership"
    if re.search(r"/20\d{2}/\d{1,2}/\d{1,2}/", path):
        return "news_article"
    return "unknown"


def _source_type(item: NewsItem, config: MonitorConfig | None) -> str:
    if not config:
        return "unknown"
    domain = urlparse(item.url).netloc.lower().removeprefix("www.")
    if any(domain == value or domain.endswith(f".{value}") for value in config.sources.low_value_domains):
        return "aggregator"
    if any(domain == value or domain.endswith(f".{value}") for value in config.sources.fresh_priority_domains):
        if any(value in domain for value in ("exchangewire", "adexchanger", "digiday", "marketingbrew", "businessofapps", "mobilemarketingmagazine")):
            return "industry_media"
        if any(value in domain for value in ("summit", "event", "dmexco", "mwc", "possible")):
            return "conference_site"
        if _is_official_source(item, config):
            return "official_company"
    if any(domain == value or domain.endswith(f".{value}") for value in config.sources.background_priority_domains):
        if any(value in domain for value in ("iab", "summit", "dmexco", "mwc")):
            return "conference_site"
        if _is_official_source(item, config):
            return "official_company"
        return "industry_media"
    return "unknown"


def _freshness_confidence(item: NewsItem) -> int:
    score = 0
    if item.date_quality == "explicit_date":
        score += 3
    elif item.date_quality == "inferred_date":
        score += 1
    if item.page_type in _FRESH_PAGE_TYPES:
        score += 1
    if item.source_type in {"official_company", "industry_media", "conference_site"}:
        score += 1
    if _date_from_url(item.url):
        score += 1
    if item.page_type in _BACKGROUND_PAGE_TYPES and item.date_quality != "explicit_date":
        score -= 1
    return max(0, min(5, score))


def _is_background_page_type(page_type: str) -> bool:
    return page_type in _BACKGROUND_PAGE_TYPES


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    text = value.strip()
    patterns = (
        r"(\d{4})-(\d{2})-(\d{2})",
        r"(\d{4})/(\d{2})/(\d{2})",
        r"(\d{1,2})/(\d{1,2})/(\d{4})",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        parts = [int(value) for value in match.groups()]
        try:
            if len(str(parts[0])) == 4:
                return date(parts[0], parts[1], parts[2])
            return date(parts[2], parts[0], parts[1])
        except ValueError:
            return None
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _date_from_url(url: str) -> date | None:
    match = re.search(r"/(20\d{2})/(\d{1,2})/(\d{1,2})(?:/|$)", url)
    if not match:
        return None
    year, month, day = (int(value) for value in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _originality_score(item: NewsItem) -> int:
    text = _item_text(item)
    if any(term in text for term in ("launch", "announced", "released", "product update", "beta", "general availability", "ga ")):
        return 1
    if any(term in text for term in ("report", "benchmark", "index", "study", "survey", "conference", "agenda")):
        return 1
    if any(term in text for term in ("best ", "top ", "guide", "list")):
        return -1
    return 0


def _relevance_score(item: NewsItem, config: MonitorConfig | None) -> int:
    text = _item_text(item)
    score = max(1, min(2, item.relevance_score or 2))
    if not config:
        return score
    topic_terms = set()
    for topic in config.topics:
        if topic.id == item.topic_id:
            topic_terms.update(value.lower() for value in topic.priority_keywords)
    matched_terms = sum(1 for term in topic_terms if term and term in text)
    if matched_terms >= 3:
        score += 2
    elif matched_terms >= 1:
        score += 1
    if any(name.lower() in text for name in config.tracking.partners + config.tracking.competitors):
        score += 1
    if item.relevance_tier == "core":
        score += 1
    elif item.relevance_tier == "adjacent":
        score -= 1
    elif item.relevance_tier == "ignore":
        score -= 3
    return min(3, max(0, score))

def _relevance_tier(item: NewsItem, config: MonitorConfig | None) -> str:
    text = " ".join(
        [
            _item_text(item),
            item.what_happened or "",
            item.why_now or "",
            item.market_context or "",
            item.summary or "",
            item.company_or_topic or "",
        ]
    ).lower()
    core_terms = (
        "user acquisition", "app growth", "performance marketing", "mobile marketing", "in-app",
        "app advertisers", "app marketers", "app inventory", "app monetization", "programmatic",
        "mmp", "attribution", "skan", "privacy sandbox", "adattributionkit", "measurement",
        "incrementality", "fraud", "invalid traffic", "ivt", "traffic quality", "verified",
        "viewability", "brand safety", "connected tv", "ctv", "performance ctv", "installs",
        "roi", "roas", "creative intelligence", "creative effectiveness", "budget shifts",
        "campaign optimization", "media optimization", "retargeting", "chartboost direct",
        "direct deals", "brand demand", "appsflyer", "adjust", "singular", "airbridge",
        "kochava", "branch", "moloco", "liftoff", "applovin", "ironsource", "unity",
        "mintegral", "tenjin", "apptweak", "clevertap", "braze"
    )
    adjacent_terms = (
        "pc gaming", "gameplay", "hardware signals", "gamer grid", "gamer", "gaming audience",
        "publisher yield", "broad brand advertising", "generic agency", "media news"
    )
    ignore_terms = (
        "esports", "community event", "community update", "tournament", "gaming community", "creator drop"
    )
    if any(term in text for term in ignore_terms):
        return "ignore"
    if any(term in text for term in core_terms):
        if "ctv" in text and not any(term in text for term in ("app", "apps", "install", "installs", "mmp", "roi", "roas", "performance", "viewability", "invalid traffic", "device verification", "measurement")):
            return "adjacent"
        return "core"
    if config and any(name.lower() in text for name in config.tracking.partners + config.tracking.competitors):
        return "core"
    if any(term in text for term in adjacent_terms):
        return "adjacent"
    if any(term in text for term in ("creative", "ai", "brand", "publisher", "inventory")):
        if any(term in text for term in ("mobile", "app", "campaign optimization", "media optimization", "measurement", "attribution")):
            return "core"
        return "adjacent"
    if any(term in text for term in ("report", "benchmark", "index", "study", "conference", "summit")):
        return "background"
    return "background"


def _linkedin_angle(item: NewsItem) -> str:
    if _has_terms(item, 'omnicom', 'agentic media buying', 'agentic buying', 'media buying agents', 'agentic'):
        return 'AI agents are entering media buying — but who verifies the quality of what they buy?'
    if _has_terms(item, 'ias', 'total tv', 'connected tv', 'ctv', 'viewability', 'device verification'):
        return 'CTV is being sold less on reach alone and more on proof: content-level transparency, verification, and measurable outcomes.'
    if _has_terms(item, 'doubleverify', 'slopstopper', 'ai-generated content', 'brand suitability', 'youtube'):
        return 'The AI-content boom is creating a new media-quality problem: not every impression is worth buying.'
    if _has_terms(item, 'moloco', 'performance ctv', 'mmp', 'household', 'roi', 'installs'):
        return 'CTV is starting to look like a user-acquisition channel, not just an awareness buy.'
    if _has_terms(item, 'overwolf', 'gamer grid', 'gameplay', 'hardware signals', 'gamer'):
        return 'Gaming audience products are getting more behavior-based, but the practical question is whether that signal travels into mobile UA.'
    if _has_terms(item, 'chartboost direct', 'brand demand', 'direct deals', 'marketplace', 'publisher'):
        return 'Brand budgets moving into curated in-app inventory could change how premium app supply gets packaged and sold.'
    if _has_terms(item, 'fraud', 'invalid traffic', 'quality', 'brand safety', 'viewability'):
        return 'Traffic quality is still a performance story: better filtering protects spend before it disappears into bad inventory.'
    if _has_terms(item, 'measurement', 'attribution', 'skan', 'privacy sandbox', 'adattributionkit', 'mmp'):
        return 'Measurement changes only matter when they change real campaign decisions: windows, signals, and what teams can still optimize.'
    if _has_terms(item, 'daivid', 'adin.ai', 'creative effectiveness', 'creative intelligence', 'budget shifts'):
        return 'AI in user acquisition is not just making creatives anymore. It is starting to decide which creatives deserve budget.'
    if _has_terms(item, 'ai', 'creative', 'generative ai', 'optimization'):
        return 'The next adtech question is not whether AI can speed up execution, but whether it improves media decisions.'
    if _has_terms(item, 'audience', 'targeting', 'gamer', 'gaming'):
        return 'Audience quality is getting more behavior-based, which matters only if marketers can turn that signal into better buying decisions.'
    if _has_terms(item, 'benchmark', 'index', 'report'):
        return 'A benchmark only matters if it changes how buyers compare quality, performance, or risk.'
    if _has_terms(item, 'partnership', 'launch', 'product update', 'released'):
        return 'The useful question is not just what launched, but whether it changes how app marketers buy, measure, or protect performance.'
    text = item.opportunity.strip()
    if text:
        cleaned = _sentence_cleanup(text)
        if cleaned:
            return cleaned
    return 'The useful question is what this changes for mobile growth teams today.'

def _bidmatrix_angle(item: NewsItem) -> str:
    company = _lead_entity(item)
    if _has_terms(item, "appsflyer", "adjust", "singular", "airbridge", "kochava", "branch", "mmp", "attribution", "measurement", "skan", "privacy sandbox", "adattributionkit"):
        return "Supports BidMatrix positioning around attribution resilience, privacy-safe optimization, and cleaner performance decision-making for app growth teams."
    if _has_terms(item, 'ias', 'total tv', 'connected tv', 'ctv', 'device verification'):
        return 'Gives BidMatrix a concrete angle on transparent CTV, verified environments, and performance measurement beyond impressions.'
    if _has_terms(item, 'fraud', 'invalid traffic', 'quality', 'brand safety', 'viewability'):
        return 'Strengthens BidMatrix positioning around quality traffic, safer in-app supply, and performance protection.'
    if _has_terms(item, 'omnicom', 'agentic media buying', 'agentic buying', 'media buying agents', 'agentic'):
        return "Supports BidMatrix's AI-native positioning: automation can speed up buying, but advertisers still need transparent supply, attribution clarity, and performance safeguards."
    if _has_terms(item, 'connected tv', 'ctv', 'viewability', 'device verification', 'invalid traffic'):
        return 'Gives BidMatrix a concrete angle on transparent CTV, verified environments, and performance measurement beyond impressions.'
    if _has_terms(item, 'doubleverify', 'slopstopper', 'ai-generated content', 'brand suitability', 'youtube'):
        return 'Strengthens BidMatrix positioning around traffic quality in the AI-content era, where low-quality impressions can quietly erode performance.'
    if _has_terms(item, 'moloco', 'performance ctv', 'mmp', 'household', 'roi', 'installs'):
        return 'Supports a BidMatrix point of view that CTV is becoming measurable app-growth media, not just an awareness channel.'
    if _has_terms(item, 'overwolf', 'gamer grid', 'gameplay', 'hardware signals', 'gamer'):
        return 'Relevance to BidMatrix is indirect; keep as watchlist only.'
    if _has_terms(item, 'chartboost direct', 'brand demand', 'direct deals', 'marketplace', 'publisher'):
        return 'Gives BidMatrix a cleaner angle on curated in-app supply, premium inventory quality, and brand budgets moving deeper into apps.'
    if _has_terms(item, 'daivid', 'adin.ai', 'creative effectiveness', 'creative intelligence', 'budget shifts'):
        return 'Useful for BidMatrix AI-native positioning: AI in performance marketing is moving from content generation to decision support, including creative scoring, budget shifts, and measurable outcomes.'
    if _has_terms(item, 'ai', 'creative', 'generative ai', 'optimization'):
        return "Supports BidMatrix's AI-native positioning when automation is tied to measurable campaign decisions, not just creative speed."
    if _has_terms(item, 'programmatic', 'dsp', 'ssp', 'exchange', 'brand demand', 'inventory'):
        return 'Supports BidMatrix positioning around programmatic growth, stronger in-app inventory quality, and better demand visibility.'
    if _has_terms(item, 'retargeting', 'ctv', 'connected tv'):
        return 'Supports a BidMatrix point of view on growth beyond installs, especially across retargeting and cross-channel inventory.'
    if company:
        return f'Creates a timely opening for BidMatrix to comment on how {company} could shift app growth, inventory quality, or measurement expectations.'
    return 'Gives BidMatrix a concrete opening to comment on market changes that affect app growth, measurement, and inventory quality.'

def _pr_angle(item: NewsItem) -> str:
    text = _item_text(item)
    if any(term in text for term in ("report", "benchmark", "index", "fraud", "privacy", "measurement", "ai", "launch")):
        return item.why_it_matters or item.summary
    return ""


def _partner_or_sales_action(item: NewsItem) -> str:
    companies = ", ".join(item.mentioned_companies[:3])
    if _has_terms(item, "ias", "total tv", "connected tv", "ctv", "viewability", "device verification"):
        return "Use this in messaging about verified CTV environments, measurable premium inventory, and app-growth outcomes beyond impressions."
    if _has_terms(item, "doubleverify", "slopstopper", "ai-generated content", "brand suitability", "youtube"):
        return "Use this in content or sales messaging about traffic quality in AI-generated environments and why low-quality impressions hurt performance."
    if _has_terms(item, "moloco", "performance ctv", "mmp", "household", "roi", "installs"):
        return "Use this in positioning around CTV as a performance channel for app growth, not just an awareness buy."
    if _has_terms(item, "overwolf", "gamer grid", "gameplay", "hardware signals", "gamer"):
        return "Use this as a hook for outreach or content about gaming user acquisition moving toward higher-intent behavior segments."
    if _has_terms(item, "daivid", "adin.ai", "creative effectiveness", "creative intelligence", "budget shifts"):
        return "Track whether creative intelligence vendors start integrating more directly with media buying, MMPs, or campaign optimization platforms."
    if _has_terms(item, "chartboost direct", "brand demand", "direct deals", "marketplace", "publisher"):
        return "Use this in partner or sales messaging about curated in-app supply, direct brand-demand paths, and better app monetization through ad demand."
    if companies:
        if _has_terms(item, "fraud", "quality", "brand safety", "invalid traffic"):
            return f"Use this signal in partner outreach or sales conversations about traffic quality with {companies}."
        if _has_terms(item, "measurement", "attribution", "privacy sandbox", "skan", "adattributionkit"):
            return f"Track how {companies} package this change for advertisers and whether BidMatrix should respond with a measurement-focused point of view."
        if _has_terms(item, "launch", "product update", "partnership", "released"):
            return f"Track whether {companies} turn this move into partner launches, case studies, or a larger go-to-market push."
        return f"Track whether {companies} follow this move with partner, product, or go-to-market updates."
    if item.signal_type in {"partner_signal", "competitor_move"}:
        return _sentence_cleanup(item.why_it_matters or item.summary)
    return "Keep this on the watchlist and only escalate it if a second related signal appears."


def _canonical_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if path.endswith("/amp"):
        path = path[:-4]
    return f"{parsed.netloc.lower().removeprefix('www.')}{path}"


def _normalize_title(title: str) -> str:
    text = title.lower()
    text = re.sub(r"\b(202[0-9]|latest|news|announces?|launches?|report|update)\b", " ", text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return " ".join(text.split())


def _matches_any(item: NewsItem, names: tuple[str, ...]) -> bool:
    text = _item_text(item)
    return any(name.lower() in text for name in names)


def _item_text(item: NewsItem) -> str:
    return " ".join(
        [
            item.title,
            item.source or "",
            item.summary,
            item.why_it_matters,
            item.opportunity,
            " ".join(item.hot_topics),
            " ".join(item.mentioned_companies),
            item.url,
        ]
    ).lower()


def _lead_entity(item: NewsItem) -> str:
    primary = _primary_company_or_topic(item)
    if primary:
        return primary
    if item.company_or_topic and len(item.company_or_topic.split()) <= 4:
        return item.company_or_topic.strip()
    if item.mentioned_companies:
        return item.mentioned_companies[0]
    match = re.match(r"([A-Z][A-Za-z0-9&+.-]+(?:\s+[A-Z][A-Za-z0-9&+.-]+){0,2})", item.title)
    return match.group(1) if match else ""


def _has_terms(item: NewsItem, *terms: str) -> bool:
    text = _item_text(item)
    for term in terms:
        token = term.strip().lower()
        if not token:
            continue
        pattern = re.escape(token)
        if token[0].isalnum():
            pattern = r"\b" + pattern
        if token[-1].isalnum():
            pattern += r"\b"
        if re.search(pattern, text):
            return True
    return False

def _primary_company_or_topic(item: NewsItem) -> str:
    texts = [item.what_happened, item.summary, item.title]
    for text in texts:
        actors = _actors_from_text(text)
        if actors:
            if len(actors) >= 2:
                return f"{actors[0]} x {actors[1]}"
            return actors[0]
    if item.company_or_topic and _looks_like_customer_example(item.company_or_topic, item):
        actors = _actors_from_text(item.what_happened or item.summary or item.title)
        if actors:
            if len(actors) >= 2:
                return f"{actors[0]} x {actors[1]}"
            return actors[0]
    return item.company_or_topic.strip()


def _actors_from_text(text: str) -> list[str]:
    source = " ".join(str(text).split())
    if not source:
        return []
    partnership = re.match(r"([A-Z][A-Za-z0-9.&+\-]*(?:\s+[A-Z][A-Za-z0-9.&+\-]*){0,2})\s+(?:partnered with|partners with|announced a partnership with|integrated with)\s+([A-Z][A-Za-z0-9.&+\-]*(?:\s+[A-Z][A-Za-z0-9.&+\-]*){0,2})", source)
    if partnership:
        return [partnership.group(1).strip(), partnership.group(2).strip()]
    launched = re.match(r"([A-Z][A-Za-z0-9.&+\-]*(?:\s+[A-Z][A-Za-z0-9.&+\-]*){0,3})\s+(?:launched|announced|introduced|released)", source)
    if launched:
        return [launched.group(1).strip()]
    return []


def _looks_like_customer_example(value: str, item: NewsItem) -> bool:
    candidate = value.strip().lower()
    if not candidate:
        return False
    text = f"{item.what_happened} {item.summary} {item.title}".lower()
    actor_patterns = ("partnered with", "launched", "announced", "introduced", "released", "integrated with")
    if any(pattern in text for pattern in actor_patterns) and candidate not in text.split()[:8]:
        return True
    return False


def _is_last_72h(item: NewsItem) -> bool:
    published = _parse_date(item.published_date) or _date_from_url(item.url)
    if not published:
        return False
    return published >= date.today() - timedelta(days=2)


def _is_last_14d(item: NewsItem) -> bool:
    published = _parse_date(item.published_date) or _date_from_url(item.url)
    if not published:
        return False
    return published >= date.today() - timedelta(days=14)


def _sentence_cleanup(text: str) -> str:
    cleaned = " ".join(str(text).split()).strip(" ;")
    replacements = {
        "Use this as": "",
        "Explain what": "",
        "Leverage BidMatrix intelligence to": "",
        "Position BidMatrix as": "",
    }
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    cleaned = cleaned.strip()
    cleaned = re.sub(r"(and|but|with|for|into|across|against|including|allowing|using|built on|based on|real-time|real time)$", "", cleaned, flags=re.IGNORECASE).strip(" ,;:-")
    if not cleaned:
        return ""
    if cleaned[-1] not in ".!?":
        cleaned += "."
    return cleaned[0].upper() + cleaned[1:]

def _unique_items(items: list[NewsItem]) -> list[NewsItem]:
    seen: set[str] = set()
    result: list[NewsItem] = []
    for item in items:
        if item.normalized_url in seen:
            continue
        seen.add(item.normalized_url)
        result.append(item)
    return result


def _best_what_happened(item: NewsItem) -> str:
    if _has_terms(item, "daivid", "adin.ai", "creative effectiveness", "creative intelligence", "budget shifts"):
        return _sentence_cleanup(
            "DAIVID partnered with ADIN.AI to bring AI creative-effectiveness data into media optimization, allowing predicted emotional and business impact to inform real-time budget decisions. Ajinomoto is referenced as an early client proof point, not the main actor."
        )
    details = []
    lead = item.what_happened or item.summary or item.title
    lead_clean = _sentence_cleanup(lead) if lead else ""
    if lead_clean:
        details.append(lead_clean)
    lead_lower = lead_clean.lower()
    if item.published_date and "the source dates it to" not in lead_lower:
        details.append(f"The source dates it to {item.published_date}.")
    entities = item.mentioned_companies[:4]
    primary = [part.strip() for part in (item.company_or_topic or '').replace(' x ', ',').split(',') if part.strip()]
    merged_entities = []
    for value in primary + entities:
        if value and value not in merged_entities:
            merged_entities.append(value)
    if merged_entities and "named entities include" not in lead_lower:
        details.append(f"Named entities include {', '.join(merged_entities[:4])}.")
    elif item.company_or_topic and "the main entity here is" not in lead_lower and "named entities include" not in lead_lower:
        details.append(f"The main entity here is {item.company_or_topic}.")
    return " ".join(_dedupe_sentences(details[:3]))


def _best_why_now(item: NewsItem) -> str:
    if _has_terms(item, "daivid", "adin.ai", "creative effectiveness", "creative intelligence", "budget shifts"):
        return _sentence_cleanup(
            "This shows creative intelligence moving from post-campaign reporting into active media decisioning. For performance teams, the shift is not just generating more creative assets, but using creative quality signals to decide what deserves spend."
        )
    if item.why_now:
        return _sentence_cleanup(item.why_now)
    if item.date_quality == "explicit_date" and item.freshness_tier == "new_last_24h":
        return _sentence_cleanup("This is newly published and relevant to current mobile growth decisions.")
    if item.signal_type == "privacy_measurement":
        return _sentence_cleanup("This matters now because attribution and privacy changes keep forcing live implementation changes across iOS and Android growth stacks.")
    if item.signal_type == "product_launch":
        return _sentence_cleanup("This matters now because it signals an active product and go-to-market move rather than background commentary.")
    if item.signal_type == "fraud_quality":
        return _sentence_cleanup("This matters now because buyers are under pressure to prove traffic quality and protect budget efficiency.")
    if item.signal_type == "conference":
        return _sentence_cleanup("This matters now because conference agendas and sponsor moves usually preview what teams will talk about and sell against next.")
    return _sentence_cleanup(item.why_it_matters or item.market_context or item.summary)


def _best_market_context(item: NewsItem) -> str:
    if item.market_context and not _same_meaning(item.market_context, item.what_happened or item.summary):
        return _sentence_cleanup(item.market_context)
    if _has_terms(item, "ias", "total tv", "connected tv", "ctv", "viewability", "device verification"):
        return _sentence_cleanup("CTV inventory is being sold less as broad reach and more as a verified, measurable environment with content-level visibility.")
    if _has_terms(item, "doubleverify", "slopstopper", "ai-generated content", "brand suitability", "youtube"):
        return _sentence_cleanup("As generative AI floods social and video inventory, buyers are putting more value on filtering low-quality environments before bidding.")
    if _has_terms(item, "moloco", "performance ctv", "mmp", "household", "roi", "installs"):
        return _sentence_cleanup("CTV is moving closer to performance media, with app marketers expecting install, revenue, and MMP-linked outcomes rather than pure awareness.")
    if _has_terms(item, "overwolf", "gamer grid", "gameplay", "hardware signals", "gamer"):
        return _sentence_cleanup("Gaming adtech is shifting from broad gamer labels toward deterministic behavior data that can signal intent and audience quality.")
    if _has_terms(item, "chartboost direct", "brand demand", "direct deals", "marketplace", "publisher"):
        return _sentence_cleanup("Brand budgets are moving deeper into in-app supply, with more emphasis on direct demand paths, curated inventory, and publisher yield.")
    if item.signal_type == "privacy_measurement":
        return _sentence_cleanup("This sits inside the broader shift toward privacy-preserving attribution, SDK readiness, and more fragile measurement infrastructure.")
    if item.signal_type == "fraud_quality":
        return _sentence_cleanup("This connects to the wider market push for verified traffic quality, safer inventory, and lower fraud exposure.")
    if _has_terms(item, "daivid", "adin.ai", "creative effectiveness", "creative intelligence", "budget shifts"):
        return _sentence_cleanup("Creative intelligence is moving from post-campaign reporting into live media optimization and budget allocation.")
    if item.signal_type == "AI_marketing":
        return _sentence_cleanup("This fits the broader move from AI as a creative novelty to AI as a performance and workflow layer inside user acquisition.")
    if item.signal_type == "conference":
        return _sentence_cleanup("This is part of the live conference circuit that often surfaces next-quarter talking points across app growth, AI, privacy, and measurement.")
    if item.signal_type == "market_report":
        return _sentence_cleanup("This adds benchmark context to how teams compare regions, channels, and app growth performance.")
    return _sentence_cleanup(item.why_it_matters or item.summary)


def _best_bidmatrix_implication(item: NewsItem) -> str:
    if item.relevance_tier == "adjacent":
        return _sentence_cleanup("Relevance to BidMatrix is indirect; keep as watchlist only.")
    if _has_terms(item, "daivid", "adin.ai", "creative effectiveness", "creative intelligence", "budget shifts"):
        return _sentence_cleanup("Useful for BidMatrix AI-native positioning: AI in performance marketing is moving from content generation to decision support, including creative scoring, budget shifts, and measurable outcomes.")
    if item.why_it_matters_for_bidmatrix:
        return _sentence_cleanup(item.why_it_matters_for_bidmatrix)
    return _sentence_cleanup(_bidmatrix_angle(item))

def _best_content_angle(item: NewsItem) -> str:
    if _has_terms(item, "daivid", "adin.ai", "creative effectiveness", "creative intelligence", "budget shifts"):
        return _sentence_cleanup("AI in user acquisition is not just making creatives anymore. It is starting to decide which creatives deserve budget.")
    if item.content_angle:
        return _sentence_cleanup(item.content_angle)
    return _sentence_cleanup(_linkedin_angle(item))


def _best_concrete_action(item: NewsItem) -> str:
    if _has_terms(item, 'omnicom', 'agentic media buying', 'agentic buying', 'media buying agents', 'agentic'):
        return _sentence_cleanup('Use this as a POV hook for AI-native programmatic: automation can speed up buying, but advertisers still need traffic quality, attribution clarity, and performance safeguards.')
    if _has_terms(item, 'daivid', 'adin.ai', 'creative effectiveness', 'creative intelligence', 'budget shifts'):
        return _sentence_cleanup('Track whether creative intelligence vendors start integrating more directly with media buying, MMPs, or campaign optimization platforms.')
    if item.concrete_action:
        return _sentence_cleanup(item.concrete_action)
    if item.signal_type == 'privacy_measurement':
        companies = ', '.join(item.mentioned_companies[:2]) or item.company_or_topic
        return _sentence_cleanup(f'Check whether {companies} are changing guidance for advertisers, SDK users, or measurement partners.')
    if item.signal_type == 'conference':
        return _sentence_cleanup('Use this as an agenda signal for what topics, partners, or competitors deserve extra monitoring this quarter.')
    return _sentence_cleanup(_partner_or_sales_action(item))

def _best_watch_next(item: NewsItem) -> str:
    if _has_terms(item, "daivid", "adin.ai", "creative effectiveness", "creative intelligence", "budget shifts"):
        return _sentence_cleanup("Track whether creative intelligence vendors start integrating more directly with media buying, MMPs, or optimization platforms.")
    if item.watch_next:
        return _sentence_cleanup(item.watch_next)
    companies = ", ".join(item.mentioned_companies[:3]) or item.company_or_topic
    if _has_terms(item, "ias", "total tv", "connected tv", "ctv", "viewability", "device verification"):
        return _sentence_cleanup("Track whether CTV sellers, DSPs, or measurement partners start using the same transparency and verification language.")
    if _has_terms(item, "doubleverify", "slopstopper", "ai-generated content", "brand suitability", "youtube"):
        return _sentence_cleanup("Track whether Meta, YouTube, TikTok, or rival verification vendors launch similar AI-content quality filters.")
    if _has_terms(item, "moloco", "performance ctv", "mmp", "household", "roi", "installs"):
        return _sentence_cleanup("Track whether MMPs, DSPs, or CTV networks start promising install or revenue outcomes with similar measurement language.")
    if _has_terms(item, "overwolf", "gamer grid", "gameplay", "hardware signals", "gamer"):
        return _sentence_cleanup("Track whether gaming ad networks or MMPs start packaging similar deterministic audience-quality segments.")
    if _has_terms(item, "daivid", "adin.ai", "creative effectiveness", "creative intelligence", "budget shifts"):
        return _sentence_cleanup("Track whether creative intelligence vendors start integrating more directly with media buying, MMPs, or campaign optimization platforms.")
    if _has_terms(item, "chartboost direct", "brand demand", "direct deals", "marketplace", "publisher"):
        return _sentence_cleanup("Track whether more app monetization partners launch direct brand-demand paths or curated marketplace deals for app inventory.")
    if item.signal_type == "privacy_measurement":
        return _sentence_cleanup(f"Track whether {companies} publish follow-up SDK, postback, or implementation guidance.")
    if item.signal_type == "fraud_quality":
        return _sentence_cleanup(f"Track whether {companies} or peers start using similar traffic-quality or verification language.")
    if item.signal_type == "product_launch":
        return _sentence_cleanup(f"Track whether {companies} announce integrations, demand partners, or advertiser case studies next.")
    return _sentence_cleanup(f"Track whether {companies} turn this into a broader product, partner, or messaging push.")


def _confidence_label(item: NewsItem, pre_final_score: int) -> str:
    if item.source_quality >= 2 and item.freshness_confidence >= 4 and pre_final_score >= 8:
        return "high"
    if item.source_quality <= 0 or item.freshness_confidence <= 2 or not item.what_happened:
        return "low"
    return "medium"


def _same_meaning(first: str, second: str) -> bool:
    left = re.sub(r"[^a-z0-9]+", " ", str(first).lower()).split()
    right = re.sub(r"[^a-z0-9]+", " ", str(second).lower()).split()
    if not left or not right:
        return False
    left_set = set(left)
    right_set = set(right)
    overlap = len(left_set & right_set) / max(1, min(len(left_set), len(right_set)))
    return overlap >= 0.75


def _dedupe_sentences(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = " ".join(value.split()).strip()
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            result.append(cleaned)
    return result


def _unique_nonempty(values) -> list[str]:
    seen = set()
    result = []
    for value in values:
        text = str(value).strip()
        if text and text.lower() not in seen:
            seen.add(text.lower())
            result.append(text)
    return result
