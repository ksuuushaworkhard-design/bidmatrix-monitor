from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import DeliveryConfig, MonitorConfig, OutputSettings, SearchSettings, SourceConfig, Topic, TrackingConfig


def load_config(path: str | Path) -> MonitorConfig:
    config_path = Path(path)
    raw = _read_config(config_path)
    config_files = raw.get("config_files", {})

    brand = raw.get("brand", {})
    search = raw.get("search", {})
    highlights = search.get("highlights", {})
    outputs = raw.get("outputs", {})
    delivery = raw.get("delivery", {})

    topics_raw = _read_optional_config(config_path, config_files.get("topics"), raw.get("topics", []))
    companies_raw = _read_optional_config(config_path, config_files.get("companies"), {})
    competitors_raw = _read_optional_config(config_path, config_files.get("competitors"), companies_raw.get("competitors", []))
    conferences_raw = _read_optional_config(config_path, config_files.get("conferences"), [])
    sources_raw = _read_optional_config(
        config_path,
        config_files.get("priority_sources") or config_files.get("sources"),
        {},
    )

    topics = tuple(_topic_from_dict(item) for item in topics_raw)
    if not topics:
        raise ValueError("Config must define at least one topic.")

    return MonitorConfig(
        brand_name=brand.get("name", "BidMatrix"),
        brand_description=brand.get("description", ""),
        search=SearchSettings(
            type=search.get("type", "deep"),
            category=search.get("category", "news"),
            num_results_per_topic=int(search.get("num_results_per_topic", 8)),
            max_age_hours=search.get("max_age_hours"),
            highlight_max_characters=int(highlights.get("max_characters", 4000)),
            request_timeout_seconds=int(search.get("request_timeout_seconds", 30)),
            market_watch_timeout_seconds=int(search.get("market_watch_timeout_seconds", 12)),
            strategic_background_timeout_seconds=int(search.get("strategic_background_timeout_seconds", 10)),
            daily_total_budget_seconds=int(search.get("daily_total_budget_seconds", 240)),
            max_queries_per_topic_layer=int(search.get("max_queries_per_topic_layer", 10)),
            max_strategic_background_queries=int(search.get("max_strategic_background_queries", 3)),
            max_market_watch_queries=int(search.get("max_market_watch_queries", 7)),
            max_results_per_market_watch_query=int(search.get("max_results_per_market_watch_query", 5)),
            max_total_results_per_layer=int(search.get("max_total_results_per_layer", 24)),
            max_total_results_per_market_watch=int(search.get("max_total_results_per_market_watch", 18)),
            max_total_results_per_topic=int(search.get("max_total_results_per_topic", 10)),
        ),
        outputs=OutputSettings(
            report_dir=outputs.get("report_dir", "reports"),
            max_items_in_digest=int(outputs.get("max_items_in_digest", 20)),
            recurring_trend_min_mentions=int(outputs.get("recurring_trend_min_mentions", 2)),
            min_relevance_score=int(outputs.get("min_relevance_score", 5)),
            sensitivity=_sensitivity(outputs.get("sensitivity", "balanced")),
        ),
        topics=topics,
        tracking=TrackingConfig(
            partners=_tuple(companies_raw.get("partners", [])),
            competitors=_tuple(competitors_raw),
            watchlist=_tuple(companies_raw.get("watchlist", [])),
            conferences=_tuple(conferences_raw),
        ),
        sources=SourceConfig(
            high_signal_domains=_tuple(sources_raw.get("high_signal_domains", [])),
            fresh_priority_domains=_tuple(sources_raw.get("fresh_priority_sources", [])),
            background_priority_domains=_tuple(sources_raw.get("background_priority_sources", [])),
            low_value_domains=_tuple(sources_raw.get("low_value_domains", [])),
        ),
        delivery=DeliveryConfig(
            enabled=_bool(delivery.get("enabled", False)),
            channel=str(delivery.get("channel", "telegram")).strip().lower() or "telegram",
            send_daily=_bool(delivery.get("send_daily", True)),
            send_weekly=_bool(delivery.get("send_weekly", True)),
        ),
    )


def _read_config(config_path: Path) -> dict[str, Any]:
    text = config_path.read_text(encoding="utf-8")
    if config_path.suffix.lower() == ".json":
        return json.loads(text)

    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "YAML config requires PyYAML. Use config/monitoring.json or install the project dependencies."
        ) from exc
    return yaml.safe_load(text)


def _read_optional_config(parent_path: Path, value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    path = Path(value)
    if not path.is_absolute():
        path = parent_path.parent / path
    return _read_config(path)


def _topic_from_dict(raw: dict[str, Any]) -> Topic:
    required = ("id", "label", "query")
    missing = [key for key in required if not raw.get(key)]
    if missing:
        raise ValueError(f"Topic is missing required field(s): {', '.join(missing)}")

    return Topic(
        id=str(raw["id"]),
        label=str(raw["label"]),
        query=str(raw["query"]),
        priority_keywords=tuple(str(value) for value in raw.get("priority_keywords", [])),
    )


def _tuple(values: Any) -> tuple[str, ...]:
    return tuple(str(value).strip() for value in values if str(value).strip())


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _sensitivity(value: Any) -> str:
    text = str(value).strip().lower()
    if text not in {"strict", "balanced", "broad"}:
        return "balanced"
    return text
