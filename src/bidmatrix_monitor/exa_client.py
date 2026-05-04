from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from exa_py import Exa
from exa_py.api import ExaJSONEncoder

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


MARKET_WATCH_QUERIES: tuple[tuple[str, str], ...] = (
    ("market_watch_mobile_marketing", "mobile app marketing news"),
    ("market_watch_mobile_ua", "mobile user acquisition app growth"),
    ("market_watch_measurement", "mobile attribution SKAN Privacy Sandbox"),
    ("market_watch_fraud", "mobile ad fraud IVT traffic quality"),
    ("market_watch_ctv", "CTV app marketing performance"),
    ("market_watch_ai_buying", "AI media buying performance marketing"),
    ("market_watch_programmatic", "programmatic in-app advertising"),
)


@dataclass
class ExaCollectionStats:
    total_queries: int = 0
    total_raw_results: int = 0
    unique_results: int = 0
    errors_count: int = 0
    timeouts_count: int = 0
    total_duration_seconds: float = 0.0
    market_watch_queries_run: int = 0
    market_watch_results: int = 0
    budget_exceeded: bool = False


class TimeoutExa(Exa):
    def __init__(self, api_key: str, *, request_timeout_seconds: int) -> None:
        super().__init__(api_key=api_key)
        self._request_timeout_seconds = request_timeout_seconds

    def set_request_timeout(self, seconds: int) -> None:
        self._request_timeout_seconds = max(1, int(seconds))

    def request(
        self,
        endpoint: str,
        data: dict[str, Any] | str | None = None,
        method: str = "POST",
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any] | requests.Response:
        if isinstance(data, str):
            json_data = data
        else:
            json_data = json.dumps(data, cls=ExaJSONEncoder) if data else None

        needs_streaming = (data and isinstance(data, dict) and data.get("stream")) or (
            params and params.get("stream") == "true"
        )

        request_headers = {**self.headers}
        if headers:
            request_headers.update(headers)

        timeout = self._request_timeout_seconds
        if method.upper() == "GET":
            if needs_streaming:
                res = requests.get(
                    self.base_url + endpoint,
                    headers=request_headers,
                    params=params,
                    stream=True,
                    timeout=timeout,
                )
                return res
            res = requests.get(
                self.base_url + endpoint,
                headers=request_headers,
                params=params,
                timeout=timeout,
            )
        elif method.upper() == "POST":
            if needs_streaming:
                res = requests.post(
                    self.base_url + endpoint,
                    data=json_data,
                    headers=request_headers,
                    stream=True,
                    timeout=timeout,
                )
                return res
            res = requests.post(
                self.base_url + endpoint,
                data=json_data,
                headers=request_headers,
                timeout=timeout,
            )
        elif method.upper() == "PATCH":
            res = requests.patch(
                self.base_url + endpoint,
                data=json_data,
                headers=request_headers,
                timeout=timeout,
            )
        elif method.upper() == "DELETE":
            res = requests.delete(self.base_url + endpoint, headers=request_headers, timeout=timeout)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        if res.status_code >= 400:
            raise ValueError(f"Request failed with status code {res.status_code}: {res.text}")
        return res.json()


class ExaMonitorClient:
    def __init__(self, config: MonitorConfig, *, debug_exa: bool = False) -> None:
        load_dotenv()
        api_key = os.environ.get("EXA_API_KEY")
        if not api_key:
            raise RuntimeError("EXA_API_KEY is not set. Add it to your environment or a local .env file.")
        self._config = config
        self._debug_exa = debug_exa
        self._exa = TimeoutExa(api_key=api_key, request_timeout_seconds=config.search.request_timeout_seconds)
        self._last_errors: list[str] = []
        self._stats = ExaCollectionStats()
        self._collection_started_at = time.monotonic()
        self._query_counts: dict[str, int] = {}
        self._layer_result_counts: dict[str, int] = {}
        self._seen_raw_urls: set[str] = set()
        self._fresh_items_collected = 0

    def search_topic(self, topic: Topic) -> list[NewsItem]:
        items: list[NewsItem] = []
        for layer in ("daily_fresh_signals", "strategic_background"):
            if self._budget_exceeded():
                break
            if not self._can_run_layer(layer):
                continue
            try:
                layer_items = self.search_topic_layer(topic, layer)
            except Exception as exc:
                self._record_layer_error(topic.label, layer, exc)
                continue
            items.extend(layer_items)
            if layer == "daily_fresh_signals":
                self._fresh_items_collected += len(layer_items)
            if len(items) >= self._config.search.max_total_results_per_topic:
                break
        return items[: self._config.search.max_total_results_per_topic]

    def search_market_watch_recent(self) -> list[NewsItem]:
        settings = self._config.search
        collected: list[NewsItem] = []
        if self._budget_exceeded():
            return collected

        for query_id, query in MARKET_WATCH_QUERIES[: settings.max_market_watch_queries]:
            if self._budget_exceeded():
                break
            if len(collected) >= settings.max_total_results_per_market_watch:
                break
            topic = Topic(
                id=query_id,
                label=f"Market Watch: {query}",
                query=query,
                priority_keywords=tuple(query.split()[:4]),
            )
            try:
                items = self.search_topic_layer(
                    topic,
                    "market_watch_recent",
                    num_results=settings.max_results_per_market_watch_query,
                )
            except Exception as exc:
                self._record_layer_error(topic.label, "market_watch_recent", exc)
                if isinstance(exc, (TimeoutError, requests.Timeout)):
                    print(f"MARKET_WATCH_TIMEOUT topic={topic.label}")
                continue

            self._stats.market_watch_queries_run += 1
            self._stats.market_watch_results += len(items)
            collected.extend(items)

        return collected[: settings.max_total_results_per_market_watch]

    def should_run_market_watch_recent(self) -> bool:
        return self._query_counts.get("market_watch_recent", 0) == 0 and not self._budget_exceeded()

    def pop_errors(self) -> list[str]:
        errors = list(self._last_errors)
        self._last_errors.clear()
        return errors

    def collection_stats(self) -> dict[str, Any]:
        self._stats.unique_results = len(self._seen_raw_urls)
        self._stats.total_duration_seconds = round(time.monotonic() - self._collection_started_at, 2)
        return {
            "exa_total_queries": self._stats.total_queries,
            "exa_total_raw_results": self._stats.total_raw_results,
            "exa_unique_results": self._stats.unique_results,
            "exa_errors_count": self._stats.errors_count,
            "exa_timeouts_count": self._stats.timeouts_count,
            "exa_total_duration_seconds": self._stats.total_duration_seconds,
            "exa_market_watch_queries_run": self._stats.market_watch_queries_run,
            "exa_market_watch_results": self._stats.market_watch_results,
            "exa_budget_exceeded": self._stats.budget_exceeded,
        }

    def print_collection_summary(self) -> None:
        stats = self.collection_stats()
        print(f"EXA_TOTAL_QUERIES={stats['exa_total_queries']}")
        print(f"EXA_TOTAL_RAW_RESULTS={stats['exa_total_raw_results']}")
        print(f"EXA_UNIQUE_RESULTS={stats['exa_unique_results']}")
        print(f"EXA_ERRORS_COUNT={stats['exa_errors_count']}")
        print(f"EXA_TIMEOUTS_COUNT={stats['exa_timeouts_count']}")
        print(f"EXA_TOTAL_DURATION_SECONDS={stats['exa_total_duration_seconds']}")

    def search_topic_layer(self, topic: Topic, layer: str, *, num_results: int | None = None) -> list[NewsItem]:
        settings = self._config.search
        if self._budget_exceeded():
            return []

        timeout_seconds = _layer_timeout_seconds(settings, layer)
        query = self._build_query(topic, layer)
        query_label = topic.label if layer != "market_watch_recent" else topic.query
        start = time.monotonic()
        self._stats.total_queries += 1
        self._query_counts[layer] = self._query_counts.get(layer, 0) + 1
        self._exa.set_request_timeout(timeout_seconds)
        print(f"EXA_QUERY_START layer={layer} topic={query_label} timeout={timeout_seconds}")
        try:
            response = self._exa.search(
                query,
                type=settings.type,
                category=settings.category,
                num_results=num_results or settings.num_results_per_topic,
                output_schema=OUTPUT_SCHEMA,
                contents={
                    "highlights": {
                        "max_characters": settings.highlight_max_characters,
                    }
                },
            )
            items = _items_from_response(response, topic, layer)
            duration = round(time.monotonic() - start, 2)
            self._stats.total_raw_results += len(items)
            self._layer_result_counts[layer] = self._layer_result_counts.get(layer, 0) + len(items)
            for item in items:
                self._seen_raw_urls.add(item.normalized_url)
            print(f"EXA_QUERY_DONE layer={layer} result_count={len(items)} duration={duration}")
            return items[: _layer_result_cap(settings, layer)]
        except Exception as exc:
            duration = round(time.monotonic() - start, 2)
            self._stats.errors_count += 1
            if isinstance(exc, (TimeoutError, requests.Timeout)):
                self._stats.timeouts_count += 1
            print(
                f"EXA_QUERY_ERROR layer={layer} error_type={type(exc).__name__} duration={duration}"
            )
            raise

    def _record_layer_error(self, topic_label: str, layer: str, exc: Exception) -> None:
        message = f"{topic_label} [{layer}]: {exc}"
        self._last_errors.append(message)

    def _can_run_layer(self, layer: str) -> bool:
        settings = self._config.search
        if layer == "market_watch_recent":
            return (
                self._query_counts.get(layer, 0) < settings.max_market_watch_queries
                and self._layer_result_counts.get(layer, 0) < settings.max_total_results_per_market_watch
            )
        if layer == "strategic_background":
            return (
                self._query_counts.get(layer, 0) < settings.max_strategic_background_queries
                and self._layer_result_counts.get(layer, 0) < settings.max_total_results_per_layer
            )
        return (
            self._query_counts.get(layer, 0) < settings.max_queries_per_topic_layer
            and self._layer_result_counts.get(layer, 0) < settings.max_total_results_per_layer
        )

    def _budget_exceeded(self) -> bool:
        elapsed = time.monotonic() - self._collection_started_at
        if elapsed >= self._config.search.daily_total_budget_seconds:
            if not self._stats.budget_exceeded:
                print(
                    "EXA_BUDGET_EXCEEDED "
                    f"elapsed={round(elapsed, 2)} budget={self._config.search.daily_total_budget_seconds}"
                )
            self._stats.budget_exceeded = True
            return True
        return False

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
                f"{shared} Search layer: market_watch_recent. Search only the last 7 to 14 days for the strongest "
                "adjacent or broader market signals worth a concise mobile adtech Market Watch. Prefer concrete "
                "product launches, measurement changes, AI buying moves, fraud/quality developments, CTV-for-apps "
                "performance updates, and programmatic in-app shifts from trusted sources."
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


def _layer_timeout_seconds(settings, layer: str) -> int:
    if layer == "market_watch_recent":
        return max(10, settings.market_watch_timeout_seconds)
    if layer == "strategic_background":
        return max(6, settings.strategic_background_timeout_seconds)
    return max(8, settings.request_timeout_seconds)


def _layer_result_cap(settings, layer: str) -> int:
    if layer == "market_watch_recent":
        return min(settings.max_results_per_market_watch_query, settings.max_total_results_per_layer)
    return min(settings.num_results_per_topic, settings.max_total_results_per_layer)


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


def _citations_for_url(grounding: list[dict[str, Any]], url: str) -> list[str]:
    citations: list[str] = []
    for item in grounding:
        if not isinstance(item, dict):
            continue
        if str(item.get("url", "")).strip() != url:
            continue
        snippet = str(item.get("snippet", "")).strip()
        if snippet:
            citations.append(snippet)
    return citations[:3]
