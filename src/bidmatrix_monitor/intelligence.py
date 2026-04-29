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


def build_report(items: list[NewsItem], config: MonitorConfig) -> MonitorReport:
    deduped = dedupe_items(items, config)
    thresholds = _sensitivity_thresholds(config)
    curated = [
        item
        for item in deduped
        if item.final_score >= thresholds["curated_min_score"]
        and item.source_quality >= thresholds["curated_min_source_quality"]
        and item.freshness_tier in {"new_last_24h", "new_last_7d"}
    ][: config.outputs.max_items_in_digest]
    background_items = [
        item
        for item in deduped
        if item.source_quality >= thresholds["background_min_source_quality"]
        and item.freshness_tier == "background_context"
        and item.final_score >= thresholds["background_min_score"]
    ][:5]
    report_items = curated + background_items
    diagnostics = _diagnostics(items, deduped, curated, background_items, thresholds)
    trends = _trends(report_items, config.outputs.recurring_trend_min_mentions)
    top_news = curated[:8]
    partner_signals = [
        item
        for item in curated
        if item.signal_type != "competitor_move"
        and (_matches_any(item, config.tracking.partners) or item.signal_type == "partner_signal")
    ][:6]
    competitor_moves = [
        item for item in curated if _matches_any(item, config.tracking.competitors) or item.signal_type == "competitor_move"
    ][:6]
    return MonitorReport(
        run_date=date.today(),
        diagnostics=diagnostics,
        items=report_items,
        trends=trends,
        top_news=top_news,
        actually_new_today=[
            item
            for item in curated
            if item.freshness_tier == "new_last_24h" and item.freshness_confidence >= 4
        ][:5],
        fresh_weak_confidence=[
            item
            for item in curated
            if item.freshness_tier in {"new_last_24h", "new_last_7d"}
            and (item.date_quality != "explicit_date" or item.freshness_confidence < 4)
        ][:5],
        background_items=background_items,
        hot_takes=_hot_takes(curated, trends)[:6],
        partner_signals=partner_signals,
        competitor_moves=competitor_moves,
        content_angles_for_linkedin=_content_angles(curated)[:8],
        pr_hooks=_pr_hooks(curated)[:6],
        what_changed_today=_what_changed(curated, trends)[:8],
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
    return {
        "sensitivity": str(thresholds["mode"]),
        "raw_items_found": len(raw_items),
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
        "page_type_counts": dict(Counter(item.page_type for item in deduped_items)),
        "source_type_counts": dict(Counter(item.source_type for item in deduped_items)),
    }


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

    item.linkedin_post_angle = _linkedin_angle(item)
    item.pr_angle = _pr_angle(item)
    item.partner_or_sales_action = _partner_or_sales_action(item)
    item.source_quality = source_quality
    item.freshness_tier = freshness_tier
    item.originality_score = originality_score
    item.final_score = max(1, min(10, score))
    return item


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
    return min(3, score)


def _linkedin_angle(item: NewsItem) -> str:
    if "linkedin" in item.opportunity.lower():
        return item.opportunity
    if item.hot_topics:
        return f"Explain what {', '.join(item.hot_topics[:2])} changes for mobile growth teams, using {item.title} as the hook."
    return f"Use {item.title} to frame a short BidMatrix point of view for app growth teams."


def _pr_angle(item: NewsItem) -> str:
    text = _item_text(item)
    if any(term in text for term in ("report", "benchmark", "index", "fraud", "privacy", "measurement", "ai", "launch")):
        return item.why_it_matters or item.summary
    return ""


def _partner_or_sales_action(item: NewsItem) -> str:
    companies = ", ".join(item.mentioned_companies[:3])
    if companies:
        return f"Use this as a sales or partner conversation starter with {companies}."
    if item.signal_type in {"partner_signal", "competitor_move"}:
        return item.why_it_matters or item.summary
    return ""


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


def _unique_nonempty(values) -> list[str]:
    seen = set()
    result = []
    for value in values:
        text = str(value).strip()
        if text and text.lower() not in seen:
            seen.add(text.lower())
            result.append(text)
    return result
