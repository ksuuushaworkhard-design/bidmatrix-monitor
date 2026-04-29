from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from exa_py import Exa

from .models import MonitorConfig, NewsItem, Topic


OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "Market intelligence extracted from fresh news for a mobile ad tech company.",
    "required": ["developments"],
    "properties": {
        "developments": {
            "type": "array",
            "description": "Relevant developments discovered in the search results.",
            "items": {
                "type": "object",
                "required": ["title", "url", "summary", "why_it_matters", "opportunity", "hot_topics"],
                "properties": {
                    "title": {"type": "string", "description": "Article or announcement title."},
                    "url": {"type": "string", "description": "Canonical source URL."},
                    "published_date": {"type": "string", "description": "Publication date in YYYY-MM-DD if available from the source."},
                    "summary": {"type": "string", "description": "Compact factual summary in one sentence."},
                    "why_it_matters": {"type": "string", "description": "Why this matters to mobile adtech, app growth, marketing, or BidMatrix positioning."},
                    "opportunity": {"type": "string", "description": "Actionable LinkedIn, PR, sales, partner, or positioning opportunity."},
                    "signal_type": {
                        "type": "string",
                        "description": "One of top_news, partner_signal, competitor_move, conference_signal, measurement_update, fraud_signal, creative_signal.",
                    },
                    "mentioned_companies": {
                        "type": "array",
                        "description": "Companies, platforms, MMPs, competitors, partners, or conferences named in the development.",
                        "items": {"type": "string"},
                    },
                    "hot_topics": {
                        "type": "array",
                        "description": "Short normalized themes such as SKAN, fraud, creative AI, incrementality, privacy.",
                        "items": {"type": "string"},
                    },
                },
            },
        }
    },
}


class ExaMonitorClient:
    def __init__(self, config: MonitorConfig) -> None:
        load_dotenv()
        api_key = os.environ.get("EXA_API_KEY")
        if not api_key:
            raise RuntimeError("EXA_API_KEY is not set. Add it to your environment or a local .env file.")
        self._exa = Exa(api_key=api_key)
        self._config = config

    def search_topic(self, topic: Topic) -> list[NewsItem]:
        return self.search_topic_layer(topic, "daily_fresh_signals") + self.search_topic_layer(
            topic,
            "strategic_background",
        )

    def search_topic_layer(self, topic: Topic, layer: str) -> list[NewsItem]:
        settings = self._config.search
        query = self._build_query(topic, layer)
        response = self._exa.search(
            query,
            type=settings.type,
            category=settings.category,
            num_results=settings.num_results_per_topic,
            output_schema=OUTPUT_SCHEMA,
            contents={
                "highlights": {
                    "max_characters": settings.highlight_max_characters,
                }
            },
        )
        return _items_from_response(response, topic, layer)

    def _build_query(self, topic: Topic, layer: str) -> str:
        tracking = self._config.tracking
        sources = self._config.sources
        tracked_entities = ", ".join(
            tracking.partners + tracking.competitors + tracking.watchlist + tracking.conferences
        )
        source_domains = ", ".join(_layer_domains(sources, layer))
        low_value_domains = ", ".join(sources.low_value_domains)
        priority_keywords = ", ".join(topic.priority_keywords)

        shared = (
            f"{topic.query}. {self._config.brand_name}: {self._config.brand_description}. "
            "Focus only on mobile marketing, adtech, app growth, attribution, measurement, fraud, "
            "AI for marketing, creative strategy, MMPs, conferences, partners, and competitors. "
            f"Priority domains: {source_domains}. Tracked entities: {tracked_entities}. "
            f"Topic priority terms: {priority_keywords}. Deprioritize generic syndicated PR/newswire "
            f"content and thin reposts, especially: {low_value_domains}. Return published_date when the "
            "page or article clearly provides it. Return only developments with a clear business implication."
        )
        if layer == "daily_fresh_signals":
            return (
                f"{shared} Search layer: daily_fresh_signals. Prioritize content published in the last "
                "24 to 72 hours, today, yesterday, this week, or since the last business day. Look for official "
                "company newsroom posts, product update blogs, release notes, changelogs, conference news and "
                "announcement pages, agenda/speaker/sponsor updates, and trusted adtech/app-growth media with "
                "frequent updates. Avoid evergreen product pages, generic lists, old reports, and long-form "
                "background explainers unless they contain a dated announcement in the last 72 hours."
            )
        return (
            f"{shared} Search layer: strategic_background. Include evergreen reports, benchmark pages, "
            "thought leadership, product pages, and long-form explainers only when they provide strategic "
            "context for market positioning, partner/competitor tracking, or recurring trends. Do not treat "
            "undated evergreen content as daily news."
        )


def _layer_domains(sources, layer: str) -> tuple[str, ...]:
    if layer == "daily_fresh_signals":
        return sources.fresh_priority_domains or sources.high_signal_domains
    return sources.background_priority_domains or sources.high_signal_domains


def _items_from_response(response: Any, topic: Topic, layer: str) -> list[NewsItem]:
    content = getattr(getattr(response, "output", None), "content", None) or {}
    developments = content.get("developments", []) if isinstance(content, dict) else []
    grounding = getattr(getattr(response, "output", None), "grounding", []) or []

    items: list[NewsItem] = []
    for raw in developments:
        if not isinstance(raw, dict) or not raw.get("url") or not raw.get("title"):
            continue
        items.append(
            NewsItem(
                topic_id=topic.id,
                topic_label=topic.label,
                title=str(raw.get("title", "")).strip(),
                url=str(raw.get("url", "")).strip(),
                published_date=_optional_string(raw.get("published_date")),
                source=_optional_string(raw.get("source")),
                summary=str(raw.get("summary", "")).strip(),
                why_it_matters=str(raw.get("why_it_matters", "")).strip(),
                opportunity=str(raw.get("opportunity", "")).strip(),
                hot_topics=[str(value).strip() for value in raw.get("hot_topics", []) if str(value).strip()],
                mentioned_companies=[
                    str(value).strip() for value in raw.get("mentioned_companies", []) if str(value).strip()
                ],
                signal_type=str(raw.get("signal_type", "top_news")).strip() or "top_news",
                monitoring_layer=layer,
                citations=_citations_for_url(grounding, str(raw.get("url", ""))),
                relevance_score=_int_score(raw.get("relevance_score")),
            )
        )
    return items


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_score(value: Any) -> int:
    try:
        return max(1, min(5, int(float(value))))
    except (TypeError, ValueError):
        return 3


def _citations_for_url(grounding: list[Any], url: str) -> list[str]:
    citations: list[str] = []
    for field in grounding:
        for citation in _field_citations(field):
            citation_url = citation.get("url") if isinstance(citation, dict) else getattr(citation, "url", None)
            if citation_url and (citation_url == url or not citations):
                citations.append(str(citation_url))
    return sorted(set(citations))


def _field_citations(field: Any) -> list[Any]:
    if isinstance(field, dict):
        return list(field.get("citations", []) or [])
    return list(getattr(field, "citations", []) or [])
