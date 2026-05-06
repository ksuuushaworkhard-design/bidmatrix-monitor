from __future__ import annotations

import html
import os
import re
import smtplib
from datetime import date
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from .models import MonitorConfig


def maybe_deliver_report(config: MonitorConfig, markdown_path: Path, report_type: str) -> None:
    load_dotenv()
    if not _delivery_enabled(config, report_type):
        return

    channel = os.environ.get("BIDMATRIX_DELIVERY_CHANNEL", config.delivery.channel).strip().lower()
    subject = _subject(report_type, markdown_path)
    text = markdown_path.read_text(encoding="utf-8")

    if channel == "telegram":
        _send_telegram(subject, text, report_type)
    elif channel == "email":
        _send_email(subject, text)
    else:
        raise RuntimeError(f"Unsupported delivery channel: {channel}")


def _delivery_enabled(config: MonitorConfig, report_type: str) -> bool:
    env_value = os.environ.get("BIDMATRIX_DELIVERY_ENABLED")
    enabled = _bool(env_value) if env_value is not None else config.delivery.enabled
    if not enabled:
        return False
    if report_type == "daily":
        return config.delivery.send_daily
    if report_type == "weekly":
        return config.delivery.send_weekly
    return False


def _send_telegram(subject: str, text: str, report_type: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("Telegram delivery requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")

    message = _telegram_message(subject, text, report_type)
    data = urlencode(
        {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
            "disable_notification": "false",
        }
    ).encode("utf-8")
    request = Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data, method="POST")
    with urlopen(request, timeout=30) as response:
        response.read()


def _telegram_message(subject: str, text: str, report_type: str) -> str:
    if report_type != 'daily':
        return _telegram_weekly_message(subject, text)

    date_label = _date_from_subject(subject)
    run_date = _subject_date(subject)
    title = f'<b>BidMatrix Daily Brief — {html.escape(date_label)}</b>'
    if 'Daily brief skipped: not enough relevant market signals found today.' in text:
        return '\n'.join([title, '', 'Daily brief skipped: not enough relevant market signals found today.'])

    items = _report_items(text)
    all_top_items = [item for item in items if item.get('section') == 'top']
    adjacent_items = [item for item in items if item.get('section') == 'adjacent']
    intro_line = _daily_intro_line(text)
    lines = [title]
    top_items, top_stats = _filter_telegram_daily_items(all_top_items, run_date)
    adjacent, adjacent_stats = _filter_telegram_daily_items(adjacent_items, run_date)
    digest_items, selection_meta = _select_telegram_daily_items(top_items, adjacent, target=4, limit=4)

    if digest_items:
        core_count = sum(1 for item in digest_items if _telegram_item_counts_as_core(item))
        adjacent_count = len(digest_items) - core_count
        if _is_market_watch_intro(intro_line) or not core_count:
            if len(digest_items) == 1 and adjacent_count == 1:
                lines.extend(["", "<b>Market Watch</b>", "No strong fresh BidMatrix-core signals found today. One adjacent market signal is worth watching."])
            else:
                lines.extend(["", "<b>Market Watch</b>", "No major core BidMatrix signal dominated today, but several relevant market moves are worth tracking."])
        else:
            recent_context_count = (
                selection_meta["recent_14d_count"]
                + selection_meta["recent_30d_count"]
                + selection_meta["unknown_trusted_count"]
            )
            if not selection_meta["fresh_7d_count"] and recent_context_count:
                intro = "Fresh signals were limited, so today’s digest uses the strongest recent market context."
            elif selection_meta["fresh_7d_count"] and recent_context_count:
                intro = (
                    f"Found {selection_meta['fresh_7d_count']} fresh signal{'s' if selection_meta['fresh_7d_count'] != 1 else ''}, "
                    f"supplemented with {recent_context_count} recent market context item{'s' if recent_context_count != 1 else ''}."
                )
            elif core_count > 0 and adjacent_count > 0:
                intro = (
                    f"Found {core_count} core signal{'s' if core_count != 1 else ''}, "
                    f"supplemented with {adjacent_count} adjacent/recent market signal{'s' if adjacent_count != 1 else ''}."
                )
            elif selection_meta["fresh_7d_count"] and not selection_meta["recent_14d_count"] and not selection_meta["recent_30d_count"] and not selection_meta["unknown_trusted_count"]:
                intro = f"Found {selection_meta['fresh_7d_count']} fresh BidMatrix-relevant signal{'s' if selection_meta['fresh_7d_count'] != 1 else ''} worth attention today."
            elif selection_meta["unknown_trusted_count"]:
                intro = "Fresh dated signals were limited, so this digest includes trusted recent market context."
            elif "supplemented with" in intro_line.lower():
                intro = intro_line
            else:
                intro = f"Found {core_count} BidMatrix-relevant signal{'s' if core_count != 1 else ''} worth attention today."
            lines.extend(["", "<b>Today's useful signals</b>", html.escape(_sync_intro_count(intro, len(digest_items)))])

        section_label = "<b>Market signal to watch</b>" if len(digest_items) == 1 and adjacent_count == 1 else "<b>Top market news</b>"
        lines.extend(["", section_label])
        for index, item in enumerate(digest_items[:4], start=1):
            lines.extend(_telegram_daily_news_item(item, index))
    else:
        intro_chunks = _daily_intro_paragraphs(text)
        if any("no Exa results were available" in chunk for chunk in intro_chunks):
            lines.extend(["", "<b>Monitor error</b>", "Market brief monitor ran, but no Exa results were available. Please check EXA_API_KEY, Exa response logs, or source/query configuration."])
        else:
            lines.extend(["", "No strong fresh market signals found today. The monitor will keep watching mobile UA, measurement, fraud, CTV, AI campaign ops, and app growth."])

    return _truncate_daily('\n'.join(lines), 3800)

def _telegram_weekly_message(subject: str, text: str) -> str:
    date_label = _date_from_subject(subject)
    sections = _weekly_sections(text)
    week_line = _first_bullet(
        sections.get("1. Week In One Line", []),
        "This was a light week with a small number of useful signals.",
    )
    happened = sections.get("2. What Actually Happened This Week", [])[:2]
    suggests = sections.get("3. What This Suggests", [])[:2]
    matters = sections.get("4. Why It Matters For BidMatrix", [])[:2]
    watch = sections.get("7. Watch Next Week", [])[:2]

    lines = [f"<b>BidMatrix Weekly Brief — {html.escape(date_label)}</b>"]

    if "Signal volume was light this week" in text:
        lines.extend(["", "Signal volume was light this week."])

    lines.extend(["", "<b>Week in one line</b>", html.escape(_shorten(week_line, 120))])

    lines.append("")
    lines.append("<b>What happened</b>")
    if happened:
        for item in happened:
            lines.append(f"- {html.escape(_shorten(_strip_markdown_emphasis(item), 130))}")
    else:
        lines.append("- No strong weekly developments.")

    lines.append("")
    lines.append("<b>What this suggests</b>")
    for item in suggests or ["There was not enough evidence this week to support a broader conclusion."]:
        lines.append(f"- {html.escape(_shorten(item, 120))}")

    lines.append("")
    lines.append("<b>Why it matters for BidMatrix</b>")
    for item in matters or ["The best use of this week's signals is narrow positioning rather than a broad market claim."]:
        lines.append(f"- {html.escape(_shorten(item, 120))}")

    lines.append("")
    lines.append("<b>Watch next week</b>")
    for item in watch or ["Watch for stronger follow-up moves next week."]:
        lines.append(f"- {html.escape(_shorten(item, 100))}")

    return _truncate("\n".join(lines), 1800)


def _send_email(subject: str, text: str) -> None:
    host = os.environ.get("EMAIL_SMTP_HOST")
    username = os.environ.get("EMAIL_SMTP_USERNAME")
    password = os.environ.get("EMAIL_SMTP_PASSWORD")
    sender = os.environ.get("EMAIL_FROM")
    recipient = os.environ.get("EMAIL_TO")
    port = int(os.environ.get("EMAIL_SMTP_PORT", "587"))

    missing = [
        name
        for name, value in {
            "EMAIL_SMTP_HOST": host,
            "EMAIL_SMTP_USERNAME": username,
            "EMAIL_SMTP_PASSWORD": password,
            "EMAIL_FROM": sender,
            "EMAIL_TO": recipient,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(f"Email delivery missing required env vars: {', '.join(missing)}")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content(text)

    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(username, password)
        smtp.send_message(message)


def _subject(report_type: str, markdown_path: Path) -> str:
    label = "Daily" if report_type == "daily" else "Weekly"
    match = re.search(r"(\d{4}-\d{2}-\d{2})", markdown_path.stem)
    date_label = match.group(1) if match else markdown_path.stem
    return f"BidMatrix {label} Market Brief - {date_label}"


def _report_items(text: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    section = ''

    for line in text.splitlines():
        stripped = line.strip()
        if stripped in {'## Top Signal', '## Top Signals', '## Top Market Signal', '## Top Market Signals'}:
            section = 'top'
            continue
        if stripped in {'## Adjacent Watchlist', '## Market Watch'}:
            section = 'adjacent'
            continue
        if stripped.startswith('## '):
            section = ''
        heading = re.match(r'^### (?P<rank>\d+)\.\s+(?P<title>.+)$', stripped)
        if heading:
            if current:
                items.append(current)
            current = {
                'section': section,
                'title': _clean_markdown_text(heading.group('title')),
                'url': '',
                'what_happened': '',
                'why_it_matters': '',
                'bidmatrix_angle': '',
                'content_angle': '',
                'action': '',
                'watch_next': '',
                'source': '',
                'confidence': 'medium',
            }
            continue

        if current is None:
            continue

        if stripped.startswith('- What happened:'):
            current['what_happened'] = _clean_markdown_text(stripped.removeprefix('- What happened:').strip())
        elif stripped.startswith('- Why it matters:') or stripped.startswith('- Why it may matter:'):
            current['why_it_matters'] = _clean_markdown_text(stripped.split(':', 1)[1].strip())
        elif stripped.startswith('- BidMatrix angle:') or stripped.startswith('- BidMatrix use:'):
            current['bidmatrix_angle'] = _clean_markdown_text(stripped.split(':', 1)[1].strip())
        elif stripped.startswith('- Content angle:'):
            current['content_angle'] = _clean_markdown_text(stripped.removeprefix('- Content angle:').strip())
        elif stripped.startswith('- Action:'):
            current['action'] = _clean_markdown_text(stripped.removeprefix('- Action:').strip())
        elif stripped.startswith('- Watch next:'):
            current['watch_next'] = _clean_markdown_text(stripped.removeprefix('- Watch next:').strip())
        elif stripped.startswith('- Source:'):
            current['source'] = _clean_markdown_text(stripped.removeprefix('- Source:').strip())
            url_match = re.search(r'\((https?://[^)]+)\)', stripped)
            if url_match:
                current['url'] = url_match.group(1)
            confidence_match = re.search(r'confidence:\s*(high|medium|low)', stripped, flags=re.IGNORECASE)
            if confidence_match:
                current['confidence'] = confidence_match.group(1).lower()

    if current:
        items.append(current)
    return items

def _weekly_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            current = stripped.removeprefix("## ").strip()
            sections.setdefault(current, [])
            continue
        if not current or not stripped:
            continue
        if stripped.startswith("- "):
            sections[current].append(stripped[2:].strip())
    return sections


def _first_bullet(values: list[str], fallback: str) -> str:
    return values[0] if values else fallback


def _strip_markdown_emphasis(text: str) -> str:
    return text.replace("**", "")


def _daily_intro_line(text: str) -> str:
    match = re.search(
        r"## Today's Useful Signal(?:s)?\s+(.+?)(?:\s+## Top Signal(?:s)?|\s+## Top Market Signal(?:s)?|\s+## Market Watch|\s+## Adjacent Watchlist|\s+## Strategic Context|\s+## What This Suggests|\Z)",
        text,
        flags=re.DOTALL,
    )
    if not match:
        return "Today's brief uses the best relevant market signals available."
    return _clean_markdown_text(match.group(1).strip())


def _daily_intro_paragraphs(text: str) -> list[str]:
    intro = _daily_intro_line(text)
    parts = [part.strip() for part in re.split(r"\n\s*\n", intro) if part.strip()]
    return [_shorten(part, 280) for part in parts] or ["Today's brief uses the best relevant market signals available."]


def _background_trend(text: str) -> str | None:
    lines = text.splitlines()
    start = None
    for heading in ("## Strategic Context", "## Background / Context"):
        try:
            start = lines.index(heading)
            break
        except ValueError:
            continue
    if start is None:
        return None
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if stripped.startswith("## "):
            break
        if stripped.startswith("- "):
            cleaned = _clean_markdown_text(stripped.removeprefix("- ").strip())
            if cleaned.lower().startswith("background context, not a fresh daily signal."):
                return None
            return cleaned
    return None


def _section_bullets(text: str, heading: str) -> list[str]:
    lines = text.splitlines()
    try:
        start = lines.index(heading)
    except ValueError:
        return []
    values: list[str] = []
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if stripped.startswith("## "):
            break
        if stripped.startswith("- "):
            values.append(_clean_markdown_text(stripped[2:].strip()))
    return values


def _telegram_item(item: dict[str, str], index: int) -> list[str]:
    lines = [
        f"{index}. {html.escape(_clean_trailing_fragment(_shorten(item['title'], 180)))}",
        "<b>Why it matters</b>",
        html.escape(_executive_line(item.get("why_it_matters") or item["title"], 220)),
        "<b>BidMatrix angle</b>",
        html.escape(_executive_line((item.get("bidmatrix_angle") or item.get("content_angle") or item["title"]).replace(": ", " — "), 200)),
        "<b>Action</b>",
        html.escape(_executive_line(item.get("action") or item.get("watch_next") or "Keep monitoring this signal for follow-up moves.", 180)),
        "<b>Source</b>",
        html.escape(_source_name(item)),
    ]
    if item.get("url"):
        lines.append(html.escape(item["url"]))
    lines.append("")
    return lines


def _telegram_watchlist_item(item: dict[str, str], index: int) -> list[str]:
    lines = [
        f"{index}. {html.escape(_clean_trailing_fragment(_shorten(item['title'], 180)))}",
        "<b>Why it may matter</b>",
        html.escape(_executive_line(item.get("why_it_matters") or item["title"], 220)),
        "<b>BidMatrix use</b>",
        html.escape(_executive_line(item.get("bidmatrix_angle") or "Relevance to BidMatrix is indirect; keep as watchlist only.", 200)),
        "<b>Action</b>",
        html.escape(_executive_line(item.get("action") or item.get("watch_next") or "Keep monitoring this signal for follow-up moves.", 160)),
        "<b>Source</b>",
        html.escape(_source_name(item)),
    ]
    if item.get("url"):
        lines.append(html.escape(item["url"]))
    lines.append("")
    return lines

def _shorten(text: str, max_chars: int) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return cleaned
    for separator in [". ", "; ", ": ", ", while ", ", amid ", ", with ", ", and ", ", "]:
        head = cleaned.split(separator, 1)[0].strip()
        if 35 <= len(head) <= max_chars:
            return _clean_trailing_fragment(head)
    cut = cleaned[:max_chars].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return _clean_trailing_fragment(cut)


def _sync_intro_count(intro: str, count: int) -> str:
    if "supplemented with" in intro.lower() or "fresh signals were limited" in intro.lower():
        return intro
    noun = "signal" if count == 1 else "signals"
    updated = re.sub(r"^Found\s+\d+\s+", f"Found {count} ", intro, count=1)
    updated = re.sub(r"\bsignal\(s\)\b", noun, updated)
    if count == 1:
        updated = re.sub(r"\bsignals\b", "signal", updated, count=1)
    else:
        updated = re.sub(r"\bsignal\b", "signals", updated, count=1)
    return updated


def _source_name(item: dict[str, str]) -> str:
    return item.get("source") or item.get("url") or "source"


def _telegram_daily_news_item(item: dict[str, str], index: int) -> list[str]:
    lines = [
        f"{index}. {html.escape(_clean_trailing_fragment(_shorten(item['title'], 170)))}",
        "<b>What happened</b>",
        html.escape(_executive_line(item.get("what_happened") or item["title"], 180)),
        "<b>What it affects</b>",
        html.escape(_telegram_affects_line(item)),
        "<b>Why it matters for BidMatrix</b>",
        html.escape(_telegram_bidmatrix_line(item)),
        "<b>Source</b>",
        html.escape(_source_name(item)),
    ]
    if item.get("url"):
        lines.append(html.escape(item["url"]))
    lines.append("")
    return lines


def _filter_telegram_daily_items(items: list[dict[str, str]], run_date: date | None) -> tuple[list[dict[str, str]], dict[str, int | dict[str, int]]]:
    filtered: list[dict[str, str]] = []
    stats = {
        "fresh_7d_count": 0,
        "recent_14d_count": 0,
        "recent_30d_count": 0,
        "unknown_trusted_count": 0,
        "future_date_rejected_count": 0,
        "date_quality_breakdown": {},
    }
    breakdown: dict[str, int] = {}
    for item in items:
        if _telegram_is_self_item(item):
            continue
        status = _telegram_date_status(item, run_date)
        quality = status["quality"]
        breakdown[quality] = breakdown.get(quality, 0) + 1
        if quality == "future_invalid":
            stats["future_date_rejected_count"] += 1
            continue
        if quality == "old_2025_or_earlier":
            continue
        if quality == "older_than_30d":
            continue
        if item.get("confidence") == "low":
            continue
        if quality == "unknown_trusted":
            if not _telegram_is_trusted_unknown(item):
                continue
            stats["unknown_trusted_count"] += 1
        elif quality == "fresh_7d":
            stats["fresh_7d_count"] += 1
        elif quality == "recent_14d":
            stats["recent_14d_count"] += 1
        elif quality == "recent_30d":
            stats["recent_30d_count"] += 1
        else:
            continue
        item = dict(item)
        item["_telegram_date_quality"] = quality
        filtered.append(item)
    stats["date_quality_breakdown"] = breakdown
    return filtered, stats


def _select_telegram_daily_items(
    top_items: list[dict[str, str]],
    adjacent_items: list[dict[str, str]],
    *,
    target: int = 3,
    limit: int = 4,
) -> tuple[list[dict[str, str]], dict[str, int]]:
    selected: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    seen_companies: set[str] = set()
    seen_buckets: set[str] = set()
    ranked_top = sorted(top_items, key=lambda item: (-_telegram_daily_priority(item), item.get("title", "").lower()))
    ranked_adjacent = sorted(adjacent_items, key=lambda item: (-_telegram_daily_priority(item), item.get("title", "").lower()))
    meta = {
        "fresh_7d_count": 0,
        "recent_14d_count": 0,
        "recent_30d_count": 0,
        "unknown_trusted_count": 0,
    }

    def add_candidates(candidates: list[dict[str, str]], *, unique_bucket: bool, allowed_qualities: set[str]) -> None:
        for item in candidates:
            if len(selected) >= target:
                return
            if item.get("_telegram_date_quality") not in allowed_qualities:
                continue
            url = (item.get("url") or "").strip().lower()
            title = (item.get("title") or "").strip().lower()
            company = _telegram_item_company(item).strip().lower()
            bucket = _telegram_daily_bucket(item)
            if url and url in seen_urls:
                continue
            if title and title in seen_titles:
                continue
            if company and company in seen_companies:
                continue
            if unique_bucket and bucket in seen_buckets:
                continue
            selected.append(item)
            if url:
                seen_urls.add(url)
            if title:
                seen_titles.add(title)
            if company:
                seen_companies.add(company)
            if bucket:
                seen_buckets.add(bucket)
            quality = item.get("_telegram_date_quality")
            if quality == "fresh_7d":
                meta["fresh_7d_count"] += 1
            elif quality == "recent_14d":
                meta["recent_14d_count"] += 1
            elif quality == "recent_30d":
                meta["recent_30d_count"] += 1
            elif quality == "unknown_trusted":
                meta["unknown_trusted_count"] += 1

    for allowed in (
        {"fresh_7d"},
        {"recent_14d"},
        {"unknown_trusted"},
        {"recent_30d"},
    ):
        add_candidates(ranked_top, unique_bucket=True, allowed_qualities=allowed)
        if len(selected) < target:
            add_candidates(ranked_adjacent, unique_bucket=True, allowed_qualities=allowed)
    if len(selected) < 2:
        for allowed in (
            {"fresh_7d"},
            {"recent_14d"},
            {"unknown_trusted"},
            {"recent_30d"},
        ):
            add_candidates(ranked_top, unique_bucket=False, allowed_qualities=allowed)
            if len(selected) < 2:
                add_candidates(ranked_adjacent, unique_bucket=False, allowed_qualities=allowed)
    return selected[:limit], meta


def _telegram_item_date(item: dict[str, str]) -> date | None:
    source = item.get("source", "")
    match = re.search(r"Date:\s*(\d{4}-\d{2}-\d{2})", source)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def _telegram_is_self_item(item: dict[str, str]) -> bool:
    text = " ".join([item.get("title", ""), item.get("source", ""), item.get("url", "")]).lower()
    return "bidmatrix" in text


def _telegram_date_status(item: dict[str, str], run_date: date | None) -> dict[str, str | int | None]:
    published = _telegram_item_date(item)
    if run_date is None:
        return {"quality": "missing_or_unknown_date", "age_days": None}
    if published is None:
        return {"quality": "unknown_trusted" if _telegram_is_trusted_unknown(item) else "missing_or_unknown_date", "age_days": None}
    if published.year < 2026:
        return {"quality": "old_2025_or_earlier", "age_days": None}
    age_days = (run_date - published).days
    if age_days < 0:
        return {"quality": "future_invalid", "age_days": age_days}
    if age_days <= 7:
        return {"quality": "fresh_7d", "age_days": age_days}
    if age_days <= 14:
        return {"quality": "recent_14d", "age_days": age_days}
    if age_days <= 30:
        return {"quality": "recent_30d", "age_days": age_days}
    return {"quality": "older_than_30d", "age_days": age_days}


def _telegram_is_trusted_unknown(item: dict[str, str]) -> bool:
    source = (item.get("source") or "").lower()
    title = (item.get("title") or "").lower()
    body = " ".join([item.get("what_happened", ""), item.get("why_it_matters", ""), item.get("bidmatrix_angle", "")]).lower()
    if "high-signal" not in source:
        return False
    if item.get("confidence") == "low":
        return False
    recent_markers = ("launch", "launched", "update", "updated", "announced", "report", "guidance", "privacy", "fraud", "ctv", "measurement", "attribution")
    return any(term in title or term in body for term in recent_markers)


def _telegram_item_counts_as_core(item: dict[str, str]) -> bool:
    angle = " ".join(
        [
            item.get("bidmatrix_angle", ""),
            item.get("content_angle", ""),
            item.get("why_it_matters", ""),
        ]
    ).lower()
    adjacent_markers = (
        "broad cross-screen context",
        "relevant only if",
        "indirect",
        "watchlist only",
    )
    if any(marker in angle for marker in adjacent_markers):
        return False
    return item.get("section") == "top"


def _telegram_daily_bucket(item: dict[str, str]) -> str:
    text = " ".join(
        [
            item.get("title", ""),
            item.get("what_happened", ""),
            item.get("why_it_matters", ""),
            item.get("bidmatrix_angle", ""),
            item.get("source", ""),
        ]
    ).lower()
    if any(term in text for term in ("ctv", "connected tv", "streaming", "total tv")):
        return "ctv"
    if any(term in text for term in ("agent hub", "agentic", "ai media buying", "campaign optimization", "automation")):
        return "ai_ops"
    if any(term in text for term in ("attribution", "skan", "privacy sandbox", "mmp", "measurement", "conversion rules")):
        return "measurement"
    if any(term in text for term in ("fraud", "ivt", "invalid traffic", "traffic quality", "verified traffic")):
        return "fraud"
    if any(term in text for term in ("dsp", "ssp", "programmatic", "in-app inventory", "marketplace", "supply", "bidder")):
        return "programmatic_supply"
    if any(term in text for term in ("app growth", "user acquisition", "ua ", "installs")):
        return "ua_growth"
    if any(term in text for term in ("dooh", "out-of-home", "billboards", "cross-screen")):
        return "cross_screen"
    return "general"


def _telegram_daily_priority(item: dict[str, str]) -> int:
    bucket = _telegram_daily_bucket(item)
    score = {"high": 12, "medium": 8, "low": 4}.get(item.get("confidence", "medium"), 6)
    score += {
        "measurement": 7,
        "fraud": 6,
        "ctv": 6,
        "ai_ops": 5,
        "programmatic_supply": 5,
        "ua_growth": 5,
        "cross_screen": 2,
        "general": 3,
    }.get(bucket, 3)
    text = " ".join([item.get("title", ""), item.get("what_happened", ""), item.get("source", "")]).lower()
    if any(term in text for term in ("sdk", "release notes", "ipv6", "release")):
        score -= 4
    quality = item.get("_telegram_date_quality")
    if quality == "fresh_7d":
        score += 8
    elif quality == "recent_14d":
        score += 4
    elif quality == "unknown_trusted":
        score -= 2
    elif quality == "recent_30d":
        score -= 4
    return score


def _telegram_affects_line(item: dict[str, str]) -> str:
    bucket = _telegram_daily_bucket(item)
    title = item.get("title", "").lower()
    happened = item.get("what_happened", "").lower()
    source = item.get("source", "").lower()
    text = " ".join([title, happened, source])
    if "kochava" in text and any(term in text for term in ("yahoo dsp", "stationone", "agentic dsp", "dsp workflow")):
        return "MMP-connected DSP workflows, agentic media buying, campaign optimization, and attribution-based decision support."
    if "meta" in text and any(term in text for term in ("ctv", "streaming", "tv oem", "freewheel", "magnite", "ssp")):
        return "CTV, premium video inventory, cross-screen media buying, and performance measurement."
    if any(term in text for term in ("openai", "chatgpt")) and any(term in text for term in ("conversion", "tracking", "pixel")):
        return "Ad measurement, conversion tracking, and performance accountability for AI-native ad platforms."
    if any(term in text for term in ("tiktok", "vistar", "dooh", "billboard", "out-of-home")):
        return "Cross-screen creative execution, DOOH media, and potential future app-campaign measurement."
    if any(term in text for term in ("fraud report", "state of fraud", "ivt", "invalid traffic", "fraud")):
        return "Traffic quality, fraud detection, IVT risk, channel quality, and verified acquisition sources."
    affects = {
        "measurement": "Attribution, MMP workflows, and privacy-safe measurement.",
        "fraud": "Traffic quality, fraud detection, IVT risk, channel quality, and verified acquisition sources.",
        "ctv": "CTV as performance media for app marketers and cross-screen measurement.",
        "ai_ops": "AI media buying, campaign optimization, and automated decision support.",
        "programmatic_supply": "Programmatic supply paths, in-app inventory access, and DSP or SSP infrastructure.",
        "ua_growth": "Mobile user acquisition, app growth, and performance marketing execution.",
        "cross_screen": "Cross-screen campaign execution; adjacent context unless it becomes measurable for app campaigns.",
        "general": "Mobile adtech strategy and partner or competitor positioning.",
    }.get(bucket, "Mobile adtech strategy and partner or competitor positioning.")
    if item.get("section") == "adjacent" and not affects.endswith("Adjacent context."):
        return f"{affects} Adjacent context."
    return affects


def _telegram_bidmatrix_line(item: dict[str, str]) -> str:
    title = item.get("title", "").lower()
    happened = item.get("what_happened", "").lower()
    source = item.get("source", "").lower()
    text = " ".join([title, happened, source])
    if "kochava" in text and any(term in text for term in ("yahoo dsp", "stationone", "agentic dsp", "dsp workflow")):
        return "Shows how MMP and DSP workflows are moving closer together through AI-assisted media buying. Useful for BidMatrix positioning around AI-native campaign operations, attribution-connected optimization, and measurable buying decisions."
    if "meta" in text and any(term in text for term in ("ctv", "streaming", "tv oem", "freewheel", "magnite", "ssp")):
        return "Useful broader context for BidMatrix CTV positioning: major ad platforms are exploring TV inventory as a performance and reach extension, but advertisers will still need measurable outcomes and verified environments."
    if any(term in text for term in ("openai", "chatgpt")) and any(term in text for term in ("conversion", "tracking", "pixel")):
        return "Useful as broader context: AI platforms are moving toward measurable advertising, which reinforces the need for attribution clarity and performance safeguards."
    return _executive_line(item.get("bidmatrix_angle") or item.get("content_angle") or item["title"], 170)


def _is_market_watch_intro(intro: str) -> bool:
    lowered = intro.lower()
    return (
        "no direct core bidmatrix signal dominated today" in lowered
        or "no core bidmatrix-relevant signals found today" in lowered
        or "strongest adjacent industry signals" in lowered
        or lowered.startswith("exa returned results, but no fresh bidmatrix-core items passed the filters")
    )


def _select_telegram_digest_items(items: list[dict[str, str]], limit: int = 3) -> list[dict[str, str]]:
    if not items:
        return []
    scored = [
        (_telegram_item_priority(item), item)
        for item in items
    ]
    filtered = [
        item for score, item in scored
        if score >= 8
    ] or [item for _, item in scored]
    ranked = sorted(
        filtered,
        key=lambda item: (-_telegram_item_priority(item), _telegram_item_company(item).lower(), item.get("title", "").lower()),
    )
    selected: list[dict[str, str]] = []
    seen_companies: set[str] = set()
    for item in ranked:
        company = _telegram_item_company(item).lower()
        if company and company in seen_companies:
            continue
        selected.append(item)
        if company:
            seen_companies.add(company)
        if len(selected) >= limit:
            return selected
    for item in ranked:
        if item in selected:
            continue
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def _telegram_item_company(item: dict[str, str]) -> str:
    title = item.get("title", "")
    for separator in (" — ", " – ", " - "):
        if separator in title:
            return title.split(separator, 1)[0].strip()
    return title.split(":", 1)[0].strip()


def _telegram_item_priority(item: dict[str, str]) -> int:
    text = " ".join(
        [
            item.get("title", ""),
            item.get("why_it_matters", ""),
            item.get("bidmatrix_angle", ""),
            item.get("action", ""),
            item.get("source", ""),
        ]
    ).lower()
    score = {"high": 12, "medium": 8, "low": 4}.get(item.get("confidence", "medium"), 6)
    if any(term in text for term in ("attribution", "skan", "privacy sandbox", "measurement", "mmp")):
        score += 6
    if any(term in text for term in ("fraud", "invalid traffic", "verified traffic", "traffic-quality", "traffic quality")):
        score += 5
    if any(term in text for term in ("ctv", "connected tv", "streaming inventory")):
        score += 5
    if any(term in text for term in ("ai-driven agents", "agent hub", "agentic", "optimization")):
        score += 4
    if any(term in text for term in ("dooh", "out-of-home", "billboards", "cross-screen")):
        score += 1
    if "older context" in text:
        score -= 6
    if any(term in text for term in ("android sdk", "sdk version", "release notes", "ipv6")):
        score -= 7
    return score

def _clean_trailing_fragment(text: str) -> str:
    original = text.rstrip()
    terminal = '?' if original.endswith('?') else '!' if original.endswith('!') else ''
    cleaned = text.rstrip(',;:.!?- ')
    cleaned = re.sub(r"\(\s*e\.?g\.?\s*$", "", cleaned, flags=re.IGNORECASE).rstrip(' ,;:.!?-')
    cleaned = re.sub(r"\(\s*$", "", cleaned).rstrip(' ,;:.!?-')
    cleaned = re.sub(r"\be\.?g\.?\s*$", "", cleaned, flags=re.IGNORECASE).rstrip(' ,;:.!?-')
    trailing_phrases = [
        'built on', 'based on', 'real-time', 'real time', 'using', 'allowing',
        'including', 'against', 'across', 'into', 'for', 'with', 'but', 'and',
        'to enable', 'to support', 'to help', 'such as', 'like'
    ]
    lower = cleaned.lower()
    removed_fragment = False
    for phrase in trailing_phrases:
        if lower.endswith(phrase):
            cleaned = cleaned[: -len(phrase)].rstrip(' ,;:.!?-')
            removed_fragment = True
            break
    if not cleaned:
        return ''
    if terminal and not removed_fragment:
        return cleaned + terminal
    if cleaned[-1] not in '.!?':
        cleaned += '.'
    return cleaned

def _date_from_subject(subject: str) -> str:
    match = re.search(r"(\d{4}-\d{2}-\d{2})", subject)
    return match.group(1) if match else subject


def _subject_date(subject: str) -> date | None:
    match = re.search(r"(\d{4}-\d{2}-\d{2})", subject)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def _executive_line(text: str, max_chars: int) -> str:
    cleaned = _polish_sentence(text)
    cleaned = _naturalize_sentence(cleaned)
    cleaned = _clean_trailing_fragment(cleaned)
    return _shorten(cleaned, max_chars)


def _polish_sentence(text: str) -> str:
    cleaned = " ".join(text.split()).strip()
    if not cleaned:
        return ""

    replacements = [
        (r"^[A-Z][A-Za-z0-9&' .-]+ article discusses\s+", ""),
        (r"^Explain what\s+", ""),
        (r"^Frame BidMatrix as\s+", "BidMatrix can position around "),
        (r"^Position BidMatrix as\s+", "BidMatrix can position around "),
        (r"^Use this as a sales or partner conversation starter with\s+", "Discuss with "),
        (r"^A sales or partner conversation starter with\s+", "Discuss with "),
        (r"^Share\s+", ""),
        (r"^Sponsor or attend\s+", "Attend "),
        (r"^LinkedIn post/PR on\s+", ""),
        (r"^LinkedIn posts? on\s+", ""),
        (r"^Post about\s+", ""),
        (r"^Review for\s+", "Review "),
    ]
    for pattern, replacement in replacements:
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)

    cleaned = cleaned.replace(";", " — ").strip()
    cleaned = re.sub(r"\bchanges for mobile growth teams\b", "matters for mobile growth teams", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bbrand-safe supply\b", "safer, higher-quality ad inventory", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bbrand safety\b", "ad safety", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bARPU\b", "revenue", cleaned)
    cleaned = re.sub(r"\bpublisher monetization\b", "app monetization", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(?<!in-app )\bmonetization economics\b", "in-app monetization economics", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(?<!app )\bmonetization partners\b", "app monetization partners", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(?<!app )(?<!in-app )(?<!publisher )\bmonetization\b", "app monetization", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bad inventory\b", "ad space", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bapp retention\b", "user retention", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bmalvertising\b", "harmful ads", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bintrusive ads\b", "disruptive ads", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bprogrammatic\b", "automated ad buying", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bbenchmarking\b", "ranking", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\buser experience\b", "user-friendly", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bsupply\b", "inventory", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bpublisher yield\b", "app ad revenue", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,;:-")

    if not cleaned:
        return ""

    cleaned = cleaned[0].upper() + cleaned[1:]
    if cleaned[-1] not in ".!?":
        cleaned += "."
    return cleaned


def _clean_markdown_text(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("**", "")
    return text.strip()


def _naturalize_sentence(text: str) -> str:
    cleaned = text.strip()
    rewrites = [
        (
            r"^AppHarbr.*ranking ad networks on safety, user-friendly.*$",
            "AppHarbr launched a new ranking that shows which ad networks are safer and more user-friendly.",
        ),
        (
            r"^Introduces first benchmark for in-app ad quality.*$",
            "It gives advertisers and app teams a clearer way to compare ad quality inside mobile apps.",
        ),
        (
            r"^Meta is holding exploratory meetings with SSPs like Magnite and FreeWheel, TV OEMs.*$",
            "Meta is exploring CTV expansion through talks with SSPs, TV OEMs, and streaming partners.",
        ),
    ]
    for pattern, replacement in rewrites:
        if re.match(pattern, cleaned, flags=re.IGNORECASE):
            return replacement
    return cleaned


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 80].rstrip() + "\n\n[Truncated. Open the local Markdown report for the full brief.]"

def _truncate_daily(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    marker = "<b>Source</b>"
    idx = -1
    start = 0
    for _ in range(3):
        found = text.find(marker, start)
        if found == -1:
            break
        idx = found
        start = found + len(marker)
    if idx != -1:
        next_break = text.find("\n\n", idx)
        if next_break != -1 and next_break < max_chars:
            text = text[:next_break].rstrip()
            if len(text) <= max_chars:
                return text
    return _truncate(text, max_chars)


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
