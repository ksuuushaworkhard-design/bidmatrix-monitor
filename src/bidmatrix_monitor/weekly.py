from __future__ import annotations

from datetime import date, datetime, timedelta
import json
from pathlib import Path
import re
from typing import Any


def write_weekly_digest(report_dir: str | Path, days: int = 7) -> tuple[Path, Path]:
    output_dir = Path(report_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    digest = build_weekly_digest(output_dir, days)
    stem = f"bidmatrix-weekly-digest-{date.today().isoformat()}"
    markdown_path = output_dir / f"{stem}.md"
    json_path = output_dir / f"{stem}.json"

    markdown_path.write_text(render_weekly_markdown(digest), encoding="utf-8")
    json_path.write_text(json.dumps(digest, indent=2, ensure_ascii=False), encoding="utf-8")
    return markdown_path, json_path


def build_weekly_digest(report_dir: Path, days: int = 7) -> dict[str, Any]:
    reports = _load_recent_curated_reports(report_dir, days)
    items = _dedupe_items(_collect_items(reports))
    low_volume = len(reports) < 3 or len(items) < 5
    development_limit = 2 if low_volume else 3
    developments = _concrete_developments(items[:development_limit])

    return {
        "run_date": date.today().isoformat(),
        "window_days": days,
        "source_reports": [report["path"] for report in reports],
        "report_count": len(reports),
        "item_count": len(items),
        "limited_signal_volume": low_volume,
        "week_in_one_line": _week_in_one_line(developments, low_volume),
        "what_actually_happened": developments,
        "what_this_suggests": _what_this_suggests(developments),
        "why_it_matters_for_bidmatrix": _why_it_matters_for_bidmatrix(developments),
        "best_content_angles": _best_content_angles(developments, reports),
        "best_pr_positioning_angles": _best_pr_positioning_angles(developments, reports),
        "watch_next_week": _watch_next_week(developments),
        "evidence": _evidence_block(developments),
    }


def render_weekly_markdown(digest: dict[str, Any]) -> str:
    lines = [f"# BidMatrix Weekly Market Brief - {digest['run_date']}", ""]

    if digest.get("limited_signal_volume"):
        lines.extend(
            [
                f"Signal volume was light this week, based on {digest['report_count']} curated daily report(s).",
                "",
            ]
        )

    lines.extend(["## 1. Week In One Line", f"- {digest['week_in_one_line']}", ""])

    lines.append("## 2. What Actually Happened This Week")
    if digest["what_actually_happened"]:
        for item in digest["what_actually_happened"]:
            lines.extend(
                [
                    f"- **{item['company']}**: {item['event']}",
                    f"  Source: {item['source']}" + (f" | Date: {item['date']}" if item["date"] else ""),
                ]
            )
    else:
        lines.append("- No strong weekly developments were found.")

    lines.extend(["", "## 3. What This Suggests"])
    lines.extend(_bullets(digest["what_this_suggests"], "There was not enough evidence this week to support a broader conclusion."))

    lines.extend(["", "## 4. Why It Matters For BidMatrix"])
    lines.extend(_bullets(digest["why_it_matters_for_bidmatrix"], "The best use of this week's signals is narrow positioning rather than a broad market claim."))

    lines.extend(["", "## 5. Best Content Angles"])
    lines.extend(_bullets(digest["best_content_angles"], "No strong content angle stood out this week."))

    lines.extend(["", "## 6. Best PR / Positioning Angles"])
    lines.extend(_bullets(digest["best_pr_positioning_angles"], "No strong PR angle stood out this week."))

    lines.extend(["", "## 7. Watch Next Week"])
    lines.extend(_bullets(digest["watch_next_week"], "Watch for stronger follow-up moves next week."))

    if digest["evidence"]:
        lines.extend(["", "## Evidence"])
        for item in digest["evidence"]:
            lines.extend(
                [
                    f"- Company: {item['company']}",
                    f"  Event: {item['event']}",
                    f"  Source: {item['source']}",
                    f"  Date: {item['date'] or 'unknown'}",
                ]
            )

    lines.append("")
    return "\n".join(lines)


def _load_recent_curated_reports(report_dir: Path, days: int) -> list[dict[str, Any]]:
    cutoff = date.today() - timedelta(days=days - 1)
    reports = []
    for path in sorted(report_dir.glob("bidmatrix-monitor-*-curated.json")):
        report_date = _date_from_daily_filename(path)
        if report_date and report_date >= cutoff:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["path"] = str(path)
            reports.append(data)
    return reports


def _date_from_daily_filename(path: Path) -> date | None:
    prefix = "bidmatrix-monitor-"
    suffix = "-curated.json"
    name = path.name
    if not name.startswith(prefix) or not name.endswith(suffix):
        return None
    value = name[len(prefix) : -len(suffix)]
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _collect_items(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = []
    for report in reports:
        for key in ("top_news", "partner_signals", "competitor_moves", "background_items"):
            items.extend(report.get(key, []))
    return items


def _dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_url: dict[str, dict[str, Any]] = {}
    for item in items:
        url = str(item.get("url", "")).split("?", 1)[0].rstrip("/")
        if not url:
            continue
        existing = by_url.get(url)
        if existing is None or int(item.get("score", 0)) > int(existing.get("score", 0)):
            by_url[url] = item
    return sorted(by_url.values(), key=lambda item: (-int(item.get("score", 0)), str(item.get("title", "")).lower()))


def _concrete_developments(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    developments = []
    for item in items:
        company = _primary_company(item)
        developments.append(
            {
                "company": company,
                "event": _event_line(item, company),
                "source": _source_name(item),
                "date": str(item.get("published_date") or "").strip() or None,
                "summary": _plain_sentence(item.get("summary") or item.get("why_it_matters") or item.get("title", ""), 170),
                "why_it_matters": _plain_sentence(item.get("why_it_matters") or item.get("summary") or item.get("title", ""), 170),
                "content_angle": _content_angle(item, company),
                "pr_angle": _pr_angle(item, company),
                "watch": _watch_line(item, company),
            }
        )
    return developments


def _week_in_one_line(developments: list[dict[str, str]], low_volume: bool) -> str:
    if not developments:
        return "This was a quiet week, with no strong developments worth carrying into a weekly brief."
    if low_volume:
        companies = ", ".join(item["company"] for item in developments[:2])
        return f"This was a light week, and the clearest developments came from {companies}."
    lead = developments[0]
    return f"The week was led by {lead['company']}, with follow-on signals that support a concrete shift rather than a broad market reset."


def _what_this_suggests(developments: list[dict[str, str]]) -> list[str]:
    if not developments:
        return []

    values = []
    text = " ".join(f"{item['company']} {item['event']} {item['why_it_matters']}" for item in developments).lower()

    if any(term in text for term in ["ad quality", "safety", "fraud", "harmful ads"]):
        values.append("Ad quality is becoming a more visible buying and performance issue, not just a back-end ops problem.")
    if any(term in text for term in ["brand demand", "brand spend", "mobile apps", "chartboost direct"]):
        values.append("Brand budgets are moving more directly into mobile apps, which could change how premium app inventory is sold.")
    if any(term in text for term in ["privacy", "transparency", "measurement", "ai"]):
        values.append("Measurement and transparency are becoming harder to separate from AI adoption and privacy changes.")

    if not values:
        values = [_plain_sentence(item["why_it_matters"], 150) for item in developments[:2]]
    return _unique_text(values)[:3]


def _why_it_matters_for_bidmatrix(developments: list[dict[str, str]]) -> list[str]:
    values = []
    text = " ".join(f"{item['company']} {item['event']} {item['why_it_matters']}" for item in developments).lower()

    if any(term in text for term in ["ad quality", "safety", "fraud", "harmful ads"]):
        values.append("BidMatrix has a stronger opening to talk about traffic quality, safer inventory, and performance protection.")
    if any(term in text for term in ["brand demand", "brand spend", "mobile apps", "chartboost direct"]):
        values.append("BidMatrix can frame how more brand budgets in apps could affect growth strategy, inventory quality, and partner conversations.")
    if any(term in text for term in ["privacy", "transparency", "measurement", "ai"]):
        values.append("BidMatrix can take a clearer position on reliable measurement, transparency, and privacy-safe growth.")

    if not values:
        values = [_plain_sentence(item["why_it_matters"], 145) for item in developments[:2]]
    return _unique_text(values)[:3]


def _best_content_angles(developments: list[dict[str, str]], reports: list[dict[str, Any]]) -> list[str]:
    values = [item["content_angle"] for item in developments if item.get("content_angle")]
    if len(values) < 3 and len(developments) >= 2:
        values.append("Together, these signals create a timely story about safer growth and better-quality demand in mobile apps.")
    return _unique_text([value for value in values if value])[:3]


def _best_pr_positioning_angles(developments: list[dict[str, str]], reports: list[dict[str, Any]]) -> list[str]:
    values = [item["pr_angle"] for item in developments if item.get("pr_angle")]
    if len(values) < 3 and len(developments) >= 2:
        values.append("BidMatrix can link cleaner traffic quality and stronger brand demand to better business outcomes for app advertisers.")
    return _unique_text([value for value in values if value])[:3]


def _watch_next_week(developments: list[dict[str, str]]) -> list[str]:
    return _unique_text([item["watch"] for item in developments if item.get("watch")])[:2]


def _evidence_block(developments: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "company": item["company"],
            "event": item["event"],
            "source": item["source"],
            "date": item["date"],
        }
        for item in developments
    ]


def _primary_company(item: dict[str, Any]) -> str:
    companies = [str(value).strip() for value in item.get("mentioned_companies", []) if str(value).strip()]
    if companies:
        return companies[0]
    title = str(item.get("title", "")).strip()
    if title:
        return title.split(" ", 1)[0]
    return "Unknown"


def _event_line(item: dict[str, Any], company: str) -> str:
    title = str(item.get("title", "")).lower()
    summary = str(item.get("summary", "")).strip()
    why = str(item.get("why_it_matters", "")).strip()

    if "quality index" in title or "ad quality" in title:
        return f"{company} launched an ad quality ranking that compares how safe and user-friendly major ad networks are."
    if "chartboost direct" in title or "loopme" in title:
        return f"{company} launched Chartboost Direct to bring more brand demand into mobile apps."
    if "transparency" in title or "arf" in title:
        return f"{company} highlighted growing pressure on marketers to prove AI and measurement are more transparent."
    if "dmexco" in title:
        return f"{company} used its 2026 conference update to signal stronger interest in AI-led marketing and measurement."
    return _plain_sentence(summary or why or str(item.get("title", "")), 160)


def _content_angle(item: dict[str, Any], company: str) -> str:
    title = str(item.get("title", "")).lower()
    if "quality index" in title or "ad quality" in title:
        return f"{company}'s ranking is a strong content hook for a post about safer ad inventory and cleaner growth."
    if "chartboost direct" in title or "loopme" in title:
        return f"{company}'s move is a strong content hook for a post about more brand money flowing into mobile apps."
    if "transparency" in title or "arf" in title:
        return f"{company}'s signal is a strong content hook for a post about clearer measurement and AI transparency."
    return _plain_sentence(item.get("linkedin_post_angle") or item.get("summary") or item.get("why_it_matters") or item.get("title", ""), 135)


def _pr_angle(item: dict[str, Any], company: str) -> str:
    title = str(item.get("title", "")).lower()
    if "quality index" in title or "ad quality" in title:
        return "BidMatrix can speak credibly about helping teams reduce low-quality traffic and protect performance."
    if "chartboost direct" in title or "loopme" in title:
        return "BidMatrix can comment on how more brand demand in apps may change mobile growth strategy."
    if "transparency" in title or "arf" in title:
        return "BidMatrix can take a clear position on transparent, privacy-safe measurement."
    return _plain_sentence(item.get("pr_angle") or item.get("why_it_matters") or item.get("summary") or item.get("title", ""), 135)


def _watch_line(item: dict[str, Any], company: str) -> str:
    companies = [str(value).strip() for value in item.get("mentioned_companies", []) if str(value).strip()]
    if len(companies) >= 2:
        return f"Watch whether {', '.join(companies[:3])} make follow-up moves next week."
    return f"Watch whether {company} follows this move with a broader rollout or partner update next week."


def _collect_text(reports: list[dict[str, Any]], key: str) -> list[str]:
    values = []
    for report in reports:
        values.extend(str(value).strip() for value in report.get(key, []) if str(value).strip())
    return values


def _unique_text(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        text = " ".join(value.split()).strip()
        if text and text.lower() not in seen:
            seen.add(text.lower())
            result.append(text)
    return result


def _bullets(values: list[str], empty: str) -> list[str]:
    if not values:
        return [f"- {empty}"]
    return [f"- {value}" for value in values]


def _source_name(item: dict[str, Any]) -> str:
    value = str(item.get("source_label") or item.get("source") or "").strip()
    if value:
        return value
    url = str(item.get("url", ""))
    match = re.match(r"https?://([^/]+)", url)
    return match.group(1).removeprefix("www.") if match else "unknown source"


def _plain_sentence(text: str, max_chars: int) -> str:
    cleaned = " ".join(str(text).split()).strip()
    if not cleaned:
        return ""

    replacements = [
        (r"\bARPU\b", "revenue"),
        (r"\bLTV\b", "lifetime value"),
        (r"\bUA\b", "user acquisition"),
        (r"\bIVT\b", "invalid traffic"),
        (r"\bmalicious ads\b", "harmful ads"),
        (r"\bmonetisation\b", "monetization"),
        (r"\bpublisher monetization\b", "how apps make money from ads"),
        (r"\bpublisher yield\b", "app ad revenue"),
        (r"\bclean rooms\b", "privacy-safe data tools"),
    ]
    for pattern, replacement in replacements:
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)

    cleaned = re.sub(r"^Explain what\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^LinkedIn post/PR on\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^Use this as a sales or partner conversation starter with\s+", "Watch ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^BidMatrix can position as\s+", "BidMatrix can speak credibly about ", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.split(";")[0].strip()
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,;:-")

    if len(cleaned) > max_chars:
        for separator in [". ", "; ", ": ", ", while ", ", with ", ", and ", ", "]:
            head = cleaned.split(separator, 1)[0].strip()
            if 45 <= len(head) <= max_chars:
                cleaned = head
                break
        if len(cleaned) > max_chars:
            cleaned = cleaned[:max_chars].rsplit(" ", 1)[0]

    if cleaned and cleaned[-1] not in ".!?":
        cleaned += "."
    return cleaned
