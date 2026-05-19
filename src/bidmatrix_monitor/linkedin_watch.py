from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse


RELEVANCE_KEYWORDS = {
    "mmp",
    "attribution",
    "measurement",
    "skan",
    "privacy sandbox",
    "user acquisition",
    "app growth",
    "mobile growth",
    "aso",
    "fraud",
    "traffic quality",
    "brand safety",
    "ivt",
    "ctv",
    "streaming",
    "programmatic",
    "in-app supply",
    "media buying",
    "agentic workflows",
    "ai",
    "analytics",
    "incrementality",
    "deep linking",
    "apple ads",
    "subscriptions",
}

ACTIONABLE_USES = {
    "content idea",
    "BD outreach",
    "partner monitoring",
    "competitor monitoring",
    "sales talking point",
    "market trend",
    "PR/commentary",
    "deck/positioning angle",
}


def build_linkedin_watch_preview(
    input_path: str | Path,
    watchlist_path: str | Path = "config/linkedin_watchlist.json",
    report_dir: str | Path = "reports",
    run_date: date | None = None,
) -> Path:
    effective_run_date = run_date or date.today()
    watchlist = load_linkedin_watchlist(watchlist_path)
    posts = load_linkedin_posts_input(input_path, watchlist)
    scored = score_linkedin_posts(posts, watchlist, run_date=effective_run_date)
    markdown = render_linkedin_watch_markdown(scored, run_date=effective_run_date)

    output_dir = Path(report_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"linkedin-watch-preview-{effective_run_date.isoformat()}.md"
    output_path.write_text(markdown, encoding="utf-8")
    return output_path


def load_linkedin_watchlist(path: str | Path) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    expected_keys = {"experts", "companies", "communities", "mvp_shortlist"}
    if set(payload.keys()) != expected_keys:
        raise ValueError("linkedin_watchlist.json has an unexpected top-level structure.")
    return payload


def load_linkedin_posts_input(path: str | Path, watchlist: dict) -> list[dict]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    posts = payload.get("posts")
    if not isinstance(posts, list):
        raise ValueError("linkedin_posts_input.json must contain a 'posts' list.")

    source_lookup = _watch_source_lookup(watchlist)
    normalized: list[dict] = []

    for index, raw in enumerate(posts, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"Post {index} must be an object.")
        source_name = _required_text(raw, "source_name", index)
        post_url = _required_text(raw, "post_url", index)
        if not _looks_like_url(post_url):
            raise ValueError(f"Post {index} field 'post_url' must be a valid URL.")
        post_text = _required_text(raw, "post_text", index)
        published_at = _required_text(raw, "published_at", index)
        if not _parse_date(published_at):
            raise ValueError(f"Post {index} field 'published_at' must be a supported date format.")
        collected_at = _required_text(raw, "collected_at", index)
        if not _parse_date(collected_at):
            raise ValueError(f"Post {index} field 'collected_at' must be a supported date format.")

        topic_tags = raw.get("topic_tags", [])
        if not isinstance(topic_tags, list):
            raise ValueError(f"Post {index} field 'topic_tags' must be a list.")

        needs_verification = raw.get("needs_verification", False)
        if not isinstance(needs_verification, bool):
            raise ValueError(f"Post {index} field 'needs_verification' must be true or false.")

        source = source_lookup.get(source_name.lower())
        if not source and not needs_verification:
            raise ValueError(
                f"Post {index} source_name '{source_name}' was not found in config/linkedin_watchlist.json. "
                "Use a configured source name or set needs_verification=true for an explicit manual exception."
            )
        source_url = _clean_text(raw.get("source_url"))
        if source_url and not _looks_like_url(source_url):
            raise ValueError(f"Post {index} field 'source_url' must be a valid URL when provided.")
        if not source_url and source:
            source_url = source.get("linkedin_url")

        normalized.append(
            {
                "source_name": source_name,
                "source_url": source_url,
                "post_url": post_url,
                "post_text": _clean_text(post_text),
                "published_at": published_at,
                "collected_at": collected_at,
                "topic_tags": _normalize_tags(topic_tags),
                "needs_verification": needs_verification,
                "source_config": source,
            }
        )
    return normalized


def score_linkedin_posts(posts: list[dict], watchlist: dict, run_date: date | None = None) -> list[dict]:
    effective_run_date = run_date or date.today()
    scored: list[dict] = []
    seen_tag_sets: dict[tuple[str, ...], int] = {}

    for post in posts:
        tags = _normalize_tags(post.get("topic_tags", []))
        text = " ".join([post.get("post_text", ""), " ".join(tags)]).lower()
        source = post.get("source_config") or {}
        expected_use = source.get("expected_use", [])

        relevance = min(10, 2 + sum(1 for key in RELEVANCE_KEYWORDS if key in text))
        source_priority = _source_priority_score(source, watchlist)
        freshness = _freshness_score(post.get("published_at"), effective_run_date)
        insight_quality = _insight_quality_score(text)
        actionability = _actionability_score(expected_use, text)

        tag_signature = tuple(sorted(tags))
        novelty = 8 if not seen_tag_sets.get(tag_signature) else 4
        seen_tag_sets[tag_signature] = seen_tag_sets.get(tag_signature, 0) + 1

        noise_risk = _noise_risk_score(text, source)
        total = relevance + source_priority + freshness + insight_quality + actionability + novelty - noise_risk

        scored.append(
            {
                **post,
                "short_insight": _short_insight(post.get("post_text", "")),
                "why_it_matters_for_bidmatrix": _why_it_matters(source, text),
                "possible_use": _possible_use(expected_use, text),
                "scores": {
                    "relevance_to_bidmatrix": relevance,
                    "source_priority": source_priority,
                    "freshness": freshness,
                    "insight_quality": insight_quality,
                    "marketing_bd_actionability": actionability,
                    "novelty": novelty,
                    "noise_risk": noise_risk,
                    "total_score": total,
                },
            }
        )

    return sorted(scored, key=lambda item: (-item["scores"]["total_score"], item["source_name"].lower()))


def render_linkedin_watch_markdown(scored_posts: list[dict], run_date: date) -> str:
    title = f"BidMatrix LinkedIn Watch — {run_date.isoformat()}"
    lines = [title, ""]
    strongest = scored_posts[:5]

    if not strongest:
        lines.append("No LinkedIn Watch posts were available for preview.")
        lines.append("")
        return "\n".join(lines)

    for index, post in enumerate(strongest, start=1):
        insight = post.get("short_insight") or _short_insight(post.get("post_text", ""))
        lines.extend(
            [
                f"{index}. {post['source_name']} — {insight}",
                post["post_url"],
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _watch_source_lookup(watchlist: dict) -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    for section in ("experts", "companies", "communities"):
        for row in watchlist.get(section, []):
            row_with_section = {**row, "source_section": section}
            lookup[row["name"].lower()] = row_with_section
    return lookup


def _required_text(raw: dict, key: str, index: int) -> str:
    value = _clean_text(raw.get(key))
    if not value:
        raise ValueError(f"Post {index} field '{key}' is required.")
    return value


def _clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_tags(values: list[object]) -> list[str]:
    tags: list[str] = []
    for value in values:
        cleaned = _clean_text(value).lower()
        if cleaned and cleaned not in tags:
            tags.append(cleaned)
    return tags


def _parse_date(value: str) -> date | None:
    text = _clean_text(value)
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _freshness_score(published_at: str, run_date: date) -> int:
    published = _parse_date(published_at)
    if not published:
        return 2
    age = (run_date - published).days
    if age <= 2:
        return 10
    if age <= 7:
        return 8
    if age <= 14:
        return 5
    if age <= 30:
        return 2
    return 0


def _source_priority_score(source: dict, watchlist: dict) -> int:
    base = {"high": 10, "medium": 6, "low": 2}.get(source.get("priority"), 4)
    name = source.get("name", "")
    shortlist = watchlist.get("mvp_shortlist", {})
    if name in shortlist.get("daily", []):
        return min(12, base + 2)
    if name in shortlist.get("twice_weekly", []):
        return min(11, base + 1)
    return base


def _insight_quality_score(text: str) -> int:
    strong_markers = ("launched", "announced", "released", "expanded", "integrated", "partnership", "report", "benchmark", "postbacks", "measurement")
    weak_markers = ("happening next week", "join us", "register now", "speaker lineup", "see you at")
    score = 4
    if any(marker in text for marker in strong_markers):
        score += 4
    if any(marker in text for marker in weak_markers):
        score -= 2
    return max(1, min(score, 10))


def _actionability_score(expected_use: list[str], text: str) -> int:
    score = min(6, len(expected_use))
    if any(key in text for key in ("partnership", "outreach", "sales", "measurement", "fraud", "benchmark", "trend")):
        score += 2
    return min(score, 10)


def _noise_risk_score(text: str, source: dict) -> int:
    score = 1
    if source.get("source_section") == "communities":
        score += 1
    if any(marker in text for marker in ("happening next week", "register now", "join us", "speaker lineup")):
        score += 3
    if len(text) < 60:
        score += 1
    return min(score, 8)


def _looks_like_url(value: str) -> bool:
    parsed = urlparse(_clean_text(value))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _short_insight(post_text: str) -> str:
    cleaned = _clean_insight_text(post_text)
    if not cleaned:
        return "No usable insight extracted."
    synthesized = _synthesized_insight(cleaned)
    if synthesized:
        return synthesized

    sentences = _split_sentences(cleaned)
    chosen = ""
    for sentence in sentences:
        if _is_hype_or_hook(sentence):
            continue
        chosen = sentence
        break
    if not chosen and sentences:
        chosen = sentences[0]
    chosen = chosen.rstrip(":,;")
    if len(chosen) > 170:
        chosen = chosen[:167].rstrip() + "..."
    return chosen or "No usable insight extracted."


def _why_it_matters(source: dict, text: str) -> str:
    if "fraud" in text or "traffic quality" in text:
        return "Useful for BidMatrix messaging around verified traffic, cleaner supply, and fraud-aware acquisition."
    if "ctv" in text:
        return "Useful for BidMatrix positioning around measurable cross-screen performance and verified CTV execution."
    if "measurement" in text or "attribution" in text or "mmp" in text:
        return "Useful for BidMatrix messaging around attribution clarity, cleaner measurement, and performance accountability."
    if "programmatic" in text or "in-app supply" in text:
        return "Useful for BidMatrix conversations about supply quality, adtech workflow changes, and buying efficiency."
    uses = source.get("expected_use", [])
    if "BD outreach" in uses:
        return "Useful for BD outreach and partner conversations around current market themes."
    return "Useful as a practical market signal for BidMatrix marketing and BD review."


def _possible_use(expected_use: list[str], text: str) -> str:
    for item in expected_use:
        if item in ACTIONABLE_USES:
            return item
    if "fraud" in text or "traffic quality" in text:
        return "sales talking point"
    if "partnership" in text:
        return "BD outreach"
    return "market trend"


def _clean_insight_text(value: str) -> str:
    cleaned = _clean_text(value)
    cleaned = re.sub(r"[\U0001F300-\U0001FAFF]+", " ", cleaned)
    cleaned = cleaned.replace("“", '"').replace("”", '"').replace("’", "'")
    cleaned = re.sub(r"\s*[-–—]\s*", " - ", cleaned)
    cleaned = re.sub(r"[!]{2,}", "!", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [part.strip() for part in parts if part.strip()]


def _is_hype_or_hook(sentence: str) -> bool:
    lowered = sentence.lower().strip()
    hype_markers = (
        "major announcement",
        "link in the comments",
        "link in comments",
        "join us",
        "register now",
        "happening next week",
    )
    if any(marker in lowered for marker in hype_markers):
        return True
    if lowered.startswith("performance advertising today boils down to trust"):
        return True
    if len(lowered) < 45 and ("announcement" in lowered or "trust" in lowered):
        return True
    return False


def _synthesized_insight(text: str) -> str:
    lowered = text.lower()
    if "singular ai" in lowered and ("marketing agents" in lowered or "ai agents" in lowered):
        return (
            "Singular is positioning AI agents as a way for marketers to turn granular attribution data "
            "into autonomous campaign workflows."
        )
    if "opacity disguised as performance" in lowered or (
        "advertisers need visibility" in lowered and "automation and ai" in lowered
    ):
        return "Performance platforms are being pushed to make AI-driven optimization more transparent, not just more automated."
    if "subscription" in lowered and "adjust" in lowered and "integration" in lowered:
        return "Adjust is framing subscription lifecycle measurement as a more direct optimization input across mobile growth workflows."
    return ""
