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
    cutoff = date.today() - timedelta(days=days - 1)
    fresh_items = [item for item in items if _item_date(item) and _item_date(item) >= cutoff]
    background_items = [item for item in items if not _item_date(item) or _item_date(item) < cutoff]
    low_volume = len(fresh_items) < 2
    development_limit = 2 if low_volume else 3
    developments = _concrete_developments(fresh_items[:development_limit])
    background_watchlist = _concrete_developments(background_items[:2])

    return {
        "run_date": date.today().isoformat(),
        "window_days": days,
        "source_reports": [report["path"] for report in reports],
        "report_count": len(reports),
        "item_count": len(fresh_items),
        "limited_signal_volume": low_volume,
        "week_in_one_line": _week_in_one_line(developments, low_volume),
        "what_actually_happened": developments,
        "background_watchlist": background_watchlist,
        "what_this_suggests": _what_this_suggests(developments),
        "why_it_matters_for_bidmatrix": _why_it_matters_for_bidmatrix(developments),
        "best_content_angles": _best_content_angles(developments, reports),
        "best_pr_positioning_angles": _best_pr_positioning_angles(developments, reports),
        "watch_next_week": _watch_next_week(developments),
        "evidence": _evidence_block(developments),
    }


def render_weekly_markdown(digest: dict[str, Any]) -> str:
    title = "Weekly Watchlist - limited fresh signal volume" if digest.get("limited_signal_volume") else "BidMatrix Weekly Market Brief"
    lines = [f"# {title} - {digest['run_date']}", ""]

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
                        f"  Source: {item['source']}"
                        + (f" | Date: {item['date']}" if item["date"] else "")
                        + (f" | URL: {item['url']}" if item.get("url") else ""),
                    ]
                )
    else:
        lines.append("- No strong fresh weekly developments were found.")

    if digest.get("limited_signal_volume"):
        lines.extend(["", "## Background Watchlist"])
        if digest.get("background_watchlist"):
            for item in digest["background_watchlist"]:
                lines.extend(
                    [
                        f"- **{item['company']}**: Background context, not a new weekly signal. {item['event']}",
                        f"  Source: {item['source']}"
                        + (f" | Date: {item['date']}" if item["date"] else "")
                        + (f" | URL: {item['url']}" if item.get("url") else ""),
                    ]
                )
        else:
            lines.append("- No older background items were promoted to the watchlist.")

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
                    f"  URL: {item['url'] or 'unknown'}",
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
                "url": str(item.get("url") or "").strip() or None,
                "summary": _plain_sentence(item.get("what_happened") or item.get("summary") or item.get("title", ""), 190),
                "why_now": _plain_sentence(item.get("why_now") or item.get("why_it_matters") or item.get("summary") or item.get("title", ""), 170),
                "market_context": _plain_sentence(item.get("market_context") or item.get("why_it_matters") or item.get("summary") or item.get("title", ""), 170),
                "why_it_matters": _plain_sentence(item.get("why_it_matters_for_bidmatrix") or item.get("why_it_matters") or item.get("summary") or item.get("title", ""), 170),
                "content_angle": _content_angle(item, company),
                "pr_angle": _pr_angle(item, company),
                "watch": _watch_line(item, company),
            }
        )
    return developments


def _week_in_one_line(developments: list[dict[str, str]], low_volume: bool) -> str:
    if not developments:
        return "Fresh signal volume was limited this week, so this brief stays focused on the small number of developments worth tracking."
    signatures = [_development_signature(item) for item in developments]
    if "gaming_audience" in signatures and "ctv_transparency" in signatures:
        return "This week's clearest signals were about more accountable media: better audience proof in gaming and better environment proof in CTV."
    if low_volume:
        companies = ", ".join(item["company"] for item in developments[:2])
        return f"This was a light week, and the clearest developments came from {companies}."
    lead = developments[0]
    return f"The week was led by {lead['company']}, with follow-on signals that sharpened one clear market shift."


def _what_this_suggests(developments: list[dict[str, str]]) -> list[str]:
    if not developments:
        return []

    signatures = [_development_signature(item) for item in developments]
    values: list[str] = []

    if "gaming_audience" in signatures and "ctv_transparency" in signatures:
        values.append("Overwolf Ads and IAS both show a shift toward more accountable media environments: one through deterministic gamer audience data, the other through CTV transparency and verification.")
        values.append("The common thread is not more inventory, but better proof of audience quality, environment quality, and measurable outcomes.")

    for item, signature in zip(developments, signatures):
        if signature == "gaming_audience":
            values.append(f"{item['company']} shows gaming user acquisition moving beyond broad demographic targeting toward behavior-based audience quality.")
            continue
        if signature == "ctv_transparency":
            values.append(f"{item['company']} shows CTV inventory being sold with more verification, transparency, and outcome accountability.")
            continue
        if signature == "ai_content_quality":
            values.append(f"{item['company']} shows media quality controls adapting to the flood of AI-generated content in social and video.")
            continue
        if signature == "performance_ctv":
            values.append(f"{item['company']} shows app marketers now expect CTV to behave more like performance media than pure awareness inventory.")
            continue
        if signature == "ai_creative_optimization":
            values.append(f"{item['company']} shows creative intelligence moving from reporting into live media optimization and budget allocation.")
            continue
        if signature == "brand_demand_in_app":
            values.append(f"{item['company']} shows brand budgets moving deeper into mobile apps through more direct and curated demand paths.")
            continue
        values.append(_plain_sentence(item["market_context"] or item["why_now"], 150))
    return _unique_text(values)[:3]


def _why_it_matters_for_bidmatrix(developments: list[dict[str, str]]) -> list[str]:
    values = []
    for item in developments[:3]:
        signature = _development_signature(item)
        if signature == "ctv_transparency":
            values.append("BidMatrix can use this to talk about transparent CTV, verified environments, and performance measurement beyond impressions.")
            continue
        if signature == "ai_content_quality":
            values.append("BidMatrix can use this to make a sharper case that not every impression is equal, especially in AI-generated environments.")
            continue
        if signature == "performance_ctv":
            values.append("BidMatrix can use this to frame CTV as a measurable app-growth channel rather than a pure awareness line item.")
            continue
        if signature == "ai_creative_optimization":
            values.append("BidMatrix can connect AI-native user acquisition messaging to measurable campaign decisions, not just creative generation.")
            continue
        if signature == "gaming_audience":
            values.append("BidMatrix can use this to talk about higher-intent gamer segments and why deterministic behavior data matters more than broad demographic reach.")
            continue
        if signature == "brand_demand_in_app":
            values.append("BidMatrix can use this to reinforce its view on curated in-app supply, premium inventory quality, and brand budgets moving deeper into apps.")
            continue
        values.append(_plain_sentence(item["why_it_matters"], 145))
    return _unique_text(values)[:3]


def _best_content_angles(developments: list[dict[str, str]], reports: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for item in developments:
        signature = _development_signature(item)
        if signature == "ctv_transparency":
            values.append("Why CTV buyers now expect transparency, verification, and measurable outcomes, not just premium reach.")
            continue
        if signature == "ai_content_quality":
            values.append("Why traffic quality matters more when AI-generated content floods social and video inventory.")
            continue
        if signature == "performance_ctv":
            values.append("What it takes for CTV to work like performance media for app marketers, not just awareness media.")
            continue
        if signature == "ai_creative_optimization":
            values.append("AI in user acquisition is not just making creatives anymore. It is starting to decide which creatives deserve budget.")
            continue
        if signature == "gaming_audience":
            values.append("Why gaming user acquisition is shifting from broad reach to deterministic behavior-based segments.")
            continue
        if signature == "brand_demand_in_app":
            values.append("What more direct brand demand inside mobile apps means for inventory quality and monetization.")
            continue
        if item.get("content_angle"):
            values.append(_clean_business_line(item["content_angle"], 140))
    return _unique_text([value for value in values if value])[:3]


def _best_pr_positioning_angles(developments: list[dict[str, str]], reports: list[dict[str, Any]]) -> list[str]:
    values = []
    for item in developments:
        signature = _development_signature(item)
        if signature == "ctv_transparency":
            values.append("BidMatrix can comment on why verified CTV environments matter more as app advertisers demand measurable outcomes.")
            continue
        if signature == "ai_content_quality":
            values.append("BidMatrix can take a clear position on filtering low-quality AI-generated environments before they become performance drag.")
            continue
        if signature == "performance_ctv":
            values.append("BidMatrix can speak to the shift from awareness-first CTV to outcome-based CTV for app growth teams.")
            continue
        if signature == "ai_creative_optimization":
            values.append("BidMatrix can connect AI-native user acquisition messaging to measurable campaign decisions, not just creative generation.")
            continue
        if signature == "gaming_audience":
            values.append("BidMatrix can comment on how deterministic gamer behavior data changes audience quality and gaming user acquisition strategy.")
            continue
        if signature == "brand_demand_in_app":
            values.append("BidMatrix can comment on how direct brand demand in apps changes supply quality and monetization strategy.")
            continue
        if item.get("pr_angle"):
            values.append(_clean_business_line(item["pr_angle"], 145))
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
            "url": item.get("url"),
        }
        for item in developments
    ]


def _item_date(item: dict[str, Any]) -> date | None:
    value = str(item.get("published_date") or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _primary_company(item: dict[str, Any]) -> str:
    company_or_topic = str(item.get("company_or_topic", "")).strip()
    if company_or_topic:
        return company_or_topic
    companies = [str(value).strip() for value in item.get("mentioned_companies", []) if str(value).strip()]
    if companies:
        return companies[0]
    title = str(item.get("title", "")).strip()
    if title:
        return title.split(" ", 1)[0]
    return "Unknown"


def _event_line(item: dict[str, Any], company: str) -> str:
    what_happened = str(item.get("what_happened", "")).strip()
    if what_happened:
        return _plain_sentence(what_happened, 160)
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
    if any(term in title for term in ("daivid", "adin.ai", "creative effectiveness", "creative data")):
        return "AI in user acquisition is not just making creatives anymore. It is starting to decide which creatives deserve budget."
    return _clean_business_line(item.get("linkedin_post_angle") or item.get("summary") or item.get("why_it_matters") or item.get("title", ""), 135)


def _pr_angle(item: dict[str, Any], company: str) -> str:
    title = str(item.get("title", "")).lower()
    if "quality index" in title or "ad quality" in title:
        return "BidMatrix can speak credibly about helping teams reduce low-quality traffic and protect performance."
    if "chartboost direct" in title or "loopme" in title:
        return "BidMatrix can comment on how more brand demand in apps may change mobile growth strategy."
    if "transparency" in title or "arf" in title:
        return "BidMatrix can take a clear position on transparent, privacy-safe measurement."
    if any(term in title for term in ("daivid", "adin.ai", "creative effectiveness", "creative data")):
        return "BidMatrix can connect AI-native user acquisition messaging to measurable campaign decisions, not just creative generation."
    fallback = _clean_business_line(item.get("pr_angle") or item.get("why_it_matters") or item.get("summary") or item.get("title", ""), 135)
    if re.fullmatch(r"Announced [A-Za-z]+ \d{1,2}, \d{4}\.", fallback):
        return "BidMatrix can connect AI-native user acquisition messaging to measurable campaign decisions, not just creative generation."
    return fallback


def _watch_line(item: dict[str, Any], company: str) -> str:
    signature = _development_signature(item)
    if signature == "ctv_transparency":
        return "Watch whether CTV sellers, DSPs, or verification vendors adopt the same transparency and measurement language."
    if signature == "ai_content_quality":
        return "Watch whether social and video platforms roll out more filtering for low-quality AI-generated inventory."
    if signature == "performance_ctv":
        return "Watch whether MMPs, DSPs, or CTV networks start selling CTV with install or revenue outcomes."
    if signature == "ai_creative_optimization":
        return "Watch whether creative intelligence vendors integrate more directly with media buying, MMPs, or optimization platforms."
    if signature == "gaming_audience":
        return "Watch whether gaming ad networks or MMPs launch more deterministic audience-quality products."
    if signature == "brand_demand_in_app":
        return "Watch whether more monetization partners introduce direct brand-demand paths or curated marketplace deals."
    companies = [str(value).strip() for value in item.get("mentioned_companies", []) if str(value).strip()]
    if len(companies) >= 2:
        return f"Watch whether {', '.join(companies[:3])} make follow-up moves next week."
    return f"Watch whether {company} follows this move with a broader rollout or partner update next week."


def _development_signature(item: dict[str, Any]) -> str:
    text = " ".join(
        str(item.get(key, ""))
        for key in ("company", "event", "summary", "why_now", "market_context", "why_it_matters", "content_angle", "pr_angle")
    ).lower()
    if any(term in text for term in ("overwolf", "gamer grid", "gameplay", "hardware signals", "gamer")):
        return "gaming_audience"
    if any(term in text for term in ("ias total tv", "total tv", "connected tv", "ctv", "viewability", "device verification", "invalid traffic")):
        return "ctv_transparency"
    if any(term in text for term in ("doubleverify", "slopstopper", "ai-generated", "brand suitability", "youtube")):
        return "ai_content_quality"
    if any(term in text for term in ("moloco", "performance ctv", "mmp attribution", "roi", "installs")):
        return "performance_ctv"
    if any(term in text for term in ("daivid", "adin.ai", "creative effectiveness", "creative intelligence", "budget shifts")):
        return "ai_creative_optimization"
    if any(term in text for term in ("chartboost direct", "brand demand", "direct deals", "marketplace", "publisher")):
        return "brand_demand_in_app"
    return "other"


def _clean_business_line(text: str, max_chars: int) -> str:
    cleaned = _plain_sentence(text, max_chars)
    cleaned = re.sub(r"^Create an ", "Create a ", cleaned)
    cleaned = re.sub(r"^Run a B2B customer push to ", "", cleaned)
    cleaned = re.sub(r"^Expert in ", "", cleaned)
    cleaned = re.sub(r"^Complementary ", "", cleaned)
    cleaned = cleaned.replace("LinkedIn post", "LinkedIn angle")
    cleaned = cleaned.replace("share LinkedIn post", "publish a LinkedIn take")
    cleaned = cleaned.replace("sponsor or speak on", "consider speaking on")
    cleaned = cleaned.replace("position BidMatrix/market-intel as the place to monitor signal integrity risk", "use it to talk about signal integrity risk")
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    if cleaned and cleaned[-1] not in ".!?":
        cleaned += "."
    return cleaned


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
    cleaned = re.sub(r"(real-time|for|with|and|into|across|against)$", "", cleaned, flags=re.IGNORECASE).strip(' ,;:-')

    if cleaned and cleaned[-1] not in ".!?":
        cleaned += "."
    return cleaned
