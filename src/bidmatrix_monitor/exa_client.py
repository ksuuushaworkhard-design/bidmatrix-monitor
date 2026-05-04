from __future__ import annotations

import os
import signal
import threading
from contextlib import contextmanager
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv
from exa_py import Exa

from .models import MonitorConfig, NewsItem, Topic


OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "Market intelligence extracted from fresh news for a mobile ad tech company. Every development must be concrete, named, source-grounded, and useful for a market intelligence brief.",
    "required": ["developments"],
    "properties": {
        "developments": {
            "type": "array",
            "description": "Relevant developments discovered in the search results.",
            "items": {
                "type": "object",
                "required": [
                    "title",
                    "url",
                    "company_or_topic",
                    "signal_type",
                    "what_happened",
                    "why_now",
                    "mentioned_companies",
                    "hot_topics",
                ],
                "properties": {
                    "title": {"type": "string", "description": "Article or announcement title."},
                    "url": {"type": "string", "description": "Canonical source URL."},
                    "published_date": {"type": "string", "description": "Publication date in YYYY-MM-DD if available from the source."},
                    "company_or_topic": {"type": "string", "description": "The main company, platform, product, report, or conference this signal is about."},
                    "signal_type": {
                        "type": "string",
                        "description": "One of product_launch, funding, partnership, platform_update, privacy_measurement, fraud_quality, AI_marketing, conference, competitor_signal, market_report, other.",
                    },
                    "what_happened": {
                        "type": "string",
                        "description": "Concrete 2-3 sentence summary with named entities and specific details. Avoid generic filler.",
                    },
                    "why_now": {
                        "type": "string",
                        "description": "Why this matters right now, tied to recency, a launch, a market shift, a regulatory change, or a live go-to-market move.",
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
        self._last_errors: list[str] = []

    def search_topic(self, topic: Topic) -> list[NewsItem]:
        items: list[NewsItem] = []
        for layer in ("daily_fresh_signals", "market_watch_recent", "strategic_background"):
            try:
                items.extend(self.search_topic_layer(topic, layer))
            except Exception as exc:
                self._last_errors.append(f"{topic.label} [{layer}]: {exc}")
        return items

    def pop_errors(self) -> list[str]:
        errors = list(self._last_errors)
        self._last_errors.clear()
        return errors

    def search_topic_layer(self, topic: Topic, layer: str) -> list[NewsItem]:
        settings = self._config.search
        query = self._build_query(topic, layer)
        with _time_limit(_layer_timeout_seconds(settings.request_timeout_seconds, layer), f"Exa search timed out for {layer}"):
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
            "page or article clearly provides it. Return only developments with a clear business implication. "
            "Do not return generic filler such as 'supports privacy-safe growth' or 'watch follow-up moves' unless you add specifics. "
            "Every development must answer: what happened, why now, and what BidMatrix can do with it."
        )
        if layer == "daily_fresh_signals":
            return (
                f"{shared} Search layer: daily_fresh_signals. Prioritize content published in the last "
                "24 to 72 hours, today, yesterday, this week, or since the last business day. Look for official "
                "company newsroom posts, product update blogs, release notes, changelogs, conference news and "
                "announcement pages, agenda/speaker/sponsor updates, and trusted adtech/app-growth media with "
                "frequent updates. Avoid evergreen product pages, generic lists, old reports, and long-form "
                "background explainers unless they contain a dated announcement in the last 72 hours. "
                "Prefer named companies, products, conferences, reports, and platforms over broad themes."
            )
        if layer == "market_watch_recent":
            return (
                f"{shared} Search layer: market_watch_recent. If strict daily news is thin, broaden into the last 7 to 14 days "
                "across trusted sources and look for the best useful industry signals available. Include mobile app marketing news, "
                "mobile user acquisition, app growth marketing, mobile attribution, SKAN, Privacy Sandbox, AppsFlyer, Adjust, "
                "Singular, Airbridge, mobile ad fraud, IVT, traffic quality, programmatic in-app advertising, CTV for app marketing, "
                "AI creative testing, AI media buying, app monetization, mobile adtech funding, partnerships, product launches, MAU "
                "Vegas, Business of Apps, Mobile Marketing Reads, ExchangeWire, AdExchanger, and Digiday. Prefer trusted sources and "
                "named companies over vague market commentary. Return only concrete developments that could support a Market Watch brief."
            )
        return (
            f"{shared} Search layer: strategic_background. Include evergreen reports, benchmark pages, "
            "thought leadership, product pages, and long-form explainers only when they provide strategic "
            "context for market positioning, partner/competitor tracking, or recurring trends. Do not treat "
            "undated evergreen content as daily news. Prefer concrete named signals over abstract thought leadership."
        )


def _layer_domains(sources, layer: str) -> tuple[str, ...]:
    if layer == "daily_fresh_signals":
        return sources.fresh_priority_domains or sources.high_signal_domains
    if layer == "market_watch_recent":
        return sources.high_signal_domains or sources.fresh_priority_domains
    return sources.background_priority_domains or sources.high_signal_domains


def _layer_timeout_seconds(base_timeout: int, layer: str) -> int:
    if layer == "market_watch_recent":
        return max(12, min(base_timeout, 20))
    if layer == "strategic_background":
        return max(15, min(base_timeout, 25))
    return max(15, base_timeout)


@contextmanager
def _time_limit(seconds: int, message: str):
    if seconds <= 0 or threading.current_thread() is not threading.main_thread() or not hasattr(signal, "SIGALRM"):
        yield
        return

    def _handler(signum, frame):  # type: ignore[unused-argument]
        raise TimeoutError(message)

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    signal.signal(signal.SIGALRM, _handler)
    signal.setitimer(signal.ITIMER_REAL, float(seconds))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer != (0.0, 0.0):
            signal.setitimer(signal.ITIMER_REAL, *previous_timer)


def _items_from_response(response: Any, topic: Topic, layer: str) -> list[NewsItem]:
    content = getattr(getattr(response, "output", None), "content", None) or {}
    developments = content.get("developments", []) if isinstance(content, dict) else []
    grounding = getattr(getattr(response, "output", None), "grounding", []) or []

    items: list[NewsItem] = []
    for raw in developments:
        if not isinstance(raw, dict) or not raw.get("url") or not raw.get("title"):
            continue
        url = str(raw.get("url", "")).strip()
        items.append(
            NewsItem(
                topic_id=topic.id,
                topic_label=topic.label,
                title=str(raw.get("title", "")).strip(),
                url=url,
                published_date=_optional_string(raw.get("published_date")),
                source=_optional_string(raw.get("source")),
                company_or_topic=str(raw.get("company_or_topic", "")).strip(),
                summary=str(raw.get("what_happened", "")).strip(),
                what_happened=str(raw.get("what_happened", "")).strip(),
                why_now=str(raw.get("why_now", "")).strip(),
                hot_topics=[str(value).strip() for value in raw.get("hot_topics", []) if str(value).strip()],
                mentioned_companies=[
                    str(value).strip() for value in raw.get("mentioned_companies", []) if str(value).strip()
                ],
                signal_type=str(raw.get("signal_type", "other")).strip() or "other",
                source_title=str(raw.get("title", "")).strip(),
                source_domain=urlparse(url).netloc.lower().removeprefix("www."),
                source_url=url,
                monitoring_layer=layer,
                citations=_citations_for_url(grounding, url),
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
