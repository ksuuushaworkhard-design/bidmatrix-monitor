from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True)
class Topic:
    id: str
    label: str
    query: str
    priority_keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class SearchSettings:
    type: str = "deep"
    category: str = "news"
    num_results_per_topic: int = 8
    max_age_hours: int | None = 24
    highlight_max_characters: int = 4000


@dataclass(frozen=True)
class OutputSettings:
    report_dir: str = "reports"
    max_items_in_digest: int = 20
    recurring_trend_min_mentions: int = 2
    min_relevance_score: int = 5
    sensitivity: str = "balanced"


@dataclass(frozen=True)
class TrackingConfig:
    partners: tuple[str, ...] = ()
    competitors: tuple[str, ...] = ()
    watchlist: tuple[str, ...] = ()
    conferences: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceConfig:
    high_signal_domains: tuple[str, ...] = ()
    fresh_priority_domains: tuple[str, ...] = ()
    background_priority_domains: tuple[str, ...] = ()
    low_value_domains: tuple[str, ...] = ()


@dataclass(frozen=True)
class DeliveryConfig:
    enabled: bool = False
    channel: str = "telegram"
    send_daily: bool = True
    send_weekly: bool = True


@dataclass(frozen=True)
class MonitorConfig:
    brand_name: str
    brand_description: str
    search: SearchSettings
    outputs: OutputSettings
    topics: tuple[Topic, ...]
    tracking: TrackingConfig = TrackingConfig()
    sources: SourceConfig = SourceConfig()
    delivery: DeliveryConfig = DeliveryConfig()


@dataclass
class NewsItem:
    topic_id: str
    topic_label: str
    title: str
    url: str
    published_date: str | None = None
    author: str | None = None
    source: str | None = None
    company_or_topic: str = ""
    summary: str = ""
    what_happened: str = ""
    why_now: str = ""
    market_context: str = ""
    why_it_matters: str = ""
    why_it_matters_for_bidmatrix: str = ""
    opportunity: str = ""
    bidmatrix_angle: str = ""
    content_angle: str = ""
    linkedin_post_angle: str = ""
    pr_angle: str = ""
    concrete_action: str = ""
    partner_or_sales_action: str = ""
    watch_next: str = ""
    source_title: str = ""
    source_domain: str = ""
    source_url: str = ""
    confidence: str = "medium"
    relevance_tier: str = "background"
    hot_topics: list[str] = field(default_factory=list)
    mentioned_companies: list[str] = field(default_factory=list)
    signal_type: str = "top_news"
    monitoring_layer: str = "strategic_background"
    page_type: str = "unknown"
    source_type: str = "unknown"
    freshness_tier: str = "background_context"
    date_quality: str = "unknown_date"
    freshness_confidence: int = 0
    citations: list[str] = field(default_factory=list)
    relevance_score: int = 0
    source_quality: int = 0
    originality_score: int = 0
    final_score: int = 0

    @property
    def normalized_url(self) -> str:
        return self.url.split("?", 1)[0].rstrip("/").replace("/amp", "")


@dataclass
class MonitorReport:
    run_date: date
    diagnostics: dict[str, Any]
    items: list[NewsItem]
    trends: list[tuple[str, int]]
    daily_intro: str
    daily_signals: list[NewsItem]
    adjacent_watchlist: list[NewsItem]
    top_news: list[NewsItem]
    actually_new_today: list[NewsItem]
    fresh_weak_confidence: list[NewsItem]
    background_items: list[NewsItem]
    hot_takes: list[str]
    partner_signals: list[NewsItem]
    competitor_moves: list[NewsItem]
    content_angles_for_linkedin: list[str]
    pr_hooks: list[str]
    what_changed_today: list[str]
    exa_errors: list[str] = field(default_factory=list)
